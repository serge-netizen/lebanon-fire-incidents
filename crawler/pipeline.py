"""One crawl run (task 3): for each source this machine can read — discover, filter, fetch the
new candidates, save their text to the private store. Extraction is task 4."""

from __future__ import annotations

import datetime as dt

from crawler.fetch import PoliteClient
from crawler.filter import census_kind, check
from crawler.sources import sources_for
from crawler.sources.common import BEIRUT
from crawler.store import Store

# Chosen, not measured: after this many days off, older days are left to the backfill (task 6).
CATCH_UP_LIMIT_DAYS = 60


def since_for(store: Store, slug: str, days: int, today: dt.date) -> dt.date:
    """The last `days` days — or back to the last successful run (one day of overlap) after time off."""
    start = today - dt.timedelta(days=days - 1)
    last = store.last_success(slug)
    if last:
        start = min(start, last.date() - dt.timedelta(days=1))
    pending = store.resume_from(slug)
    if pending:
        start = min(start, pending)
    return max(start, today - dt.timedelta(days=CATCH_UP_LIMIT_DAYS - 1))


def is_candidate(headline: str) -> bool:
    """Worth fetching: the brief's keyword filter, or a Civil Defense daily bulletin."""
    return check(headline).passes or census_kind(headline) == "tally"


def run(where: str, days: int = 3, max_fetch: int = 150, store: Store | None = None,
        client: PoliteClient | None = None) -> list[dict]:
    store = store or Store()
    client = client or PoliteClient()
    today = dt.datetime.now(BEIRUT).date()
    reports = []
    for source in sources_for(where):
        since = since_for(store, source.slug, days, today)
        report = {"source": source.slug, "since": since.isoformat(), "discovered": 0, "candidates": 0,
                  "already_saved": 0, "fetched": 0, "failed": 0, "left_for_next_run": 0, "error": None}
        try:
            items = source.discover(client, since)
        except Exception as e:  # noqa: BLE001 — one blocked or changed site must not stop the others; recorded below
            report["error"] = f"{type(e).__name__}: {e}"[:200]
            store.record_run(source.slug, report, success=False)
            reports.append(report)
            continue
        candidates = [i for i in items if is_candidate(i.headline)]
        todo = sorted((i for i in candidates if i.url not in store.fetched(source.slug)),
                      key=lambda i: i.published_at or dt.datetime.max.replace(tzinfo=BEIRUT))
        report.update(discovered=len(items), candidates=len(candidates), already_saved=len(candidates) - len(todo))
        for item in todo[:max_fetch]:
            article = source.fetch(client, item)
            if article is None:
                report["failed"] += 1  # not marked: tried again next run
                continue
            store.save(article)
            store.mark_fetched(source.slug, item.url)
            report["fetched"] += 1
        left = todo[max_fetch:]
        report["left_for_next_run"] = len(left)
        resume = min((i.published_at.date() for i in left if i.published_at), default=None)
        store.record_run(source.slug, report, success=True, resume_from=resume)
        reports.append(report)
    return reports


def print_reports(reports: list[dict]) -> None:
    """Counts only: GitHub job logs are public."""
    print(f"{'source':14} {'since':10} {'found':>6} {'cand.':>5} {'saved':>5} {'new':>4} {'fail':>4} {'left':>4}  error")
    for r in reports:
        print(f"{r['source']:14} {r['since']:10} {r['discovered']:>6} {r['candidates']:>5} {r['already_saved']:>5} "
              f"{r['fetched']:>4} {r['failed']:>4} {r['left_for_next_run']:>4}  {r['error'] or ''}")
