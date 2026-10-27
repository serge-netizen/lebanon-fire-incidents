"""The last 12 months (task 6; owner's decision 2026-10-22), read from each outlet's archive.

Month by month, newest first, for each source with a readable archive (`Source.archive`): read
the month's list of articles, keep the candidates (the daily crawl's keyword check), fetch and
save the new ones. Resumable: a run stops when its time is up, shared between the sources, and
the next run carries on from the first month not done. A fetch that fails is tried again on the
next run.

It never edits the daily crawl's files: what it fetched is listed under state/backfill/, and the
history ends where the daily crawl began for that source (the oldest article the store held when
the backfill first ran), so the two never fetch the same article.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Callable

from crawler.fetch import PoliteClient
from crawler.pipeline import is_candidate, is_saved
from crawler.sources import sources_for
from crawler.sources.base import DiscoveredItem, Source
from crawler.sources.common import BEIRUT
from crawler.store import Store

DAYS = 365  # owner, 2026-10-22: the last 12 months
TRIES = 3   # chosen: a page that fails three runs in a row is given up


class Progress:
    """state/backfill/<source>.json (where the history ends, the months done, the fetches to try
    again) and state/backfill/<source>.txt (what the backfill fetched)."""

    def __init__(self, store: Store, slug: str):
        self.path = store.root / "state" / "backfill" / f"{slug}.json"
        self.fetched_path = self.path.with_suffix(".txt")
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.data.setdefault("done", [])
        self.data.setdefault("retry", [])
        self.fetched = (set(self.fetched_path.read_text(encoding="utf-8").splitlines())
                        if self.fetched_path.exists() else set())
        if "until" not in self.data:  # fixed on the first run, so it never moves
            dates = [(a.get("published_at") or a["fetched_at"])[:10] for a in store.articles() if a["outlet"] == slug]
            self.data["until"] = min(dates) if dates else dt.datetime.now(BEIRUT).date().isoformat()

    def months(self, today: dt.date, days: int) -> list[tuple[dt.date, dt.date]]:
        """(first, last) day of each month of the history, newest first."""
        start, end = today - dt.timedelta(days=days), dt.date.fromisoformat(self.data["until"]) - dt.timedelta(days=1)
        out = []
        month = end.replace(day=1)
        while end >= start:
            out.append((max(month, start), end))
            end = month - dt.timedelta(days=1)
            month = end.replace(day=1)
        return out

    def mark(self, key: str) -> None:
        self.fetched_path.parent.mkdir(parents=True, exist_ok=True)
        with self.fetched_path.open("a", encoding="utf-8") as f:
            f.write(key + "\n")
        self.fetched.add(key)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")


def _item(d: dict) -> DiscoveredItem:
    return DiscoveredItem(d["url"], d["headline"], dt.datetime.fromisoformat(d["published_at"]) if d["published_at"] else None,
                          d["outlet"])


def _fetch(source: Source, client: PoliteClient, store: Store, progress: Progress, item: DiscoveredItem,
           report: dict, tries: int = 0) -> None:
    article = source.fetch(client, item)
    if article is None:
        report["failed"] += 1
        if tries + 1 < TRIES:
            progress.data["retry"].append({"url": item.url, "headline": item.headline, "outlet": item.outlet,
                                           "published_at": item.published_at.isoformat() if item.published_at else None,
                                           "tries": tries + 1})
        return
    store.save(article)
    progress.mark(source.key(item.url))
    report["fetched"] += 1
    report["headline_only"] += article.method == "headline only"


def backfill_source(source: Source, progress: Progress, client: PoliteClient, store: Store, today: dt.date,
                    days: int, deadline: float, clock: Callable[[], float]) -> dict:
    months = progress.months(today, days)
    report = {"source": source.slug, "until": progress.data["until"], "months": len(months), "done": 0,
              "discovered": 0, "candidates": 0, "fetched": 0, "headline_only": 0, "failed": 0, "error": None}
    retry, progress.data["retry"] = progress.data["retry"], []
    for d in retry:
        _fetch(source, client, store, progress, _item(d), report, d.get("tries", 0))
    try:
        for first, last in months:
            if first.strftime("%Y-%m") in progress.data["done"]:
                continue
            if clock() > deadline:
                break
            items = source.archive(client, first, last)
            candidates = [i for i in items if is_candidate(i.headline)]
            report["discovered"] += len(items)
            report["candidates"] += len(candidates)
            todo = [i for i in candidates if not is_saved(store, source, i.url) and source.key(i.url) not in progress.fetched]
            for item in todo:
                if clock() > deadline:
                    break
                _fetch(source, client, store, progress, item, report)
            else:
                progress.data["done"].append(first.strftime("%Y-%m"))
                continue
            break  # out of time inside the month: it is read again next run, its fetched articles skipped
    except Exception as e:  # noqa: BLE001 — a blocked or changed archive must not stop the other sources
        report["error"] = f"{type(e).__name__}: {e}"[:200]
    progress.save()
    report["done"] = sum(first.strftime("%Y-%m") in progress.data["done"] for first, _ in months)
    return report


def run(where: str, minutes: float, days: int = DAYS, store: Store | None = None, client: PoliteClient | None = None,
        today: dt.date | None = None, clock: Callable[[], float] = time.monotonic) -> list[dict]:
    """Each source with an archive gets an equal share of the time left, the one with the fewest
    months to go first, so time a finished source does not need goes to the others."""
    store, client = store or Store(), client or PoliteClient()
    today = today or dt.datetime.now(BEIRUT).date()
    end = clock() + minutes * 60
    todo = [(s, Progress(store, s.slug)) for s in sources_for(where) if s.has_archive()]
    todo.sort(key=lambda sp: sum(f.strftime("%Y-%m") not in sp[1].data["done"] for f, _ in sp[1].months(today, days)))
    reports = []
    for n, (source, progress) in enumerate(todo):
        share = (end - clock()) / (len(todo) - n)
        reports.append(backfill_source(source, progress, client, store, today, days, clock() + share, clock))
    return reports


def print_reports(reports: list[dict]) -> None:
    """Counts only: GitHub job logs are public."""
    print(f"{'source':14} {'until':10} {'months':>6} {'done':>4} {'found':>6} {'cand.':>5} {'new':>4} {'flash':>5} "
          f"{'fail':>4}  error")
    for r in reports:
        print(f"{r['source']:14} {r['until']:10} {r['months']:>6} {r['done']:>4} {r['discovered']:>6} {r['candidates']:>5} "
              f"{r['fetched']:>4} {r['headline_only']:>5} {r['failed']:>4}  {r['error'] or ''}")
