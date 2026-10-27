import datetime as dt
import json
from typing import ClassVar

from crawler import backfill
from crawler.sources.base import DiscoveredItem, FetchedArticle, Source
from crawler.sources.common import BEIRUT
from crawler.store import Store

TODAY = dt.date(2026, 10, 27)


class Archive(Source):
    """One fire story a day, and one other article."""
    slug = "archive"
    fail: ClassVar[set[str]] = set()
    calls: ClassVar[list[tuple[dt.date, dt.date]]] = []

    def discover(self, client, since):
        return []

    def archive(self, client, first, last):
        Archive.calls.append((first, last))
        days = [first + dt.timedelta(days=n) for n in range((last - first).days + 1)]
        return [DiscoveredItem(f"https://x.test/{d}/{kind}", headline, dt.datetime.combine(d, dt.time(12), BEIRUT), self.slug)
                for d in days for kind, headline in (("fire", "إخماد حريق في تول"), ("visit", "زيارة رسمية"))]

    def fetch(self, client, item):
        if item.url in self.fail:
            return None
        return FetchedArticle(item.url, self.slug, item.headline, item.published_at, "نص المقال")


class Clock:
    """Each call is one second later."""
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 1
        return self.t


def _store(tmp_path) -> Store:
    """The daily crawl began on 20 October: the history ends the day before."""
    (tmp_path / "raw" / "archive" / "2026-10").mkdir(parents=True)
    (tmp_path / "raw" / "archive" / "2026-10" / "a.json").write_text(json.dumps(
        {"url": "https://x.test/daily", "outlet": "archive", "headline": "h", "published_at": "2026-10-20T09:00:00+03:00",
         "fetched_at": "2026-10-20T10:00:00+03:00", "text": "t", "method": "full text"}), encoding="utf-8")
    return Store(tmp_path)


def _run(store, monkeypatch, minutes=60.0, days=60):
    monkeypatch.setattr(backfill, "sources_for", lambda where: [Archive()])
    return backfill.run("home", minutes, days=days, store=store, client=object(), today=TODAY, clock=Clock())[0]


def test_stretches_newest_first_end_where_the_daily_crawl_began(tmp_path):
    progress = backfill.Progress(_store(tmp_path), "archive")
    assert progress.data["until"] == "2026-10-20"
    assert progress.stretches(TODAY, 60, 31) == [(dt.date(2026, 9, 19), dt.date(2026, 10, 19)),
                                                 (dt.date(2026, 8, 28), dt.date(2026, 9, 18))]
    assert progress.stretches(TODAY, 60, 7)[:2] == [(dt.date(2026, 10, 13), dt.date(2026, 10, 19)),
                                                    (dt.date(2026, 10, 6), dt.date(2026, 10, 12))]


def test_the_history_is_collected_once_and_resumes_when_time_runs_out(tmp_path, monkeypatch):
    store = _store(tmp_path)
    first = _run(store, monkeypatch, minutes=0.25)  # 15 "seconds": part of the newest stretch only
    assert first["done"] == 0 and 0 < first["fetched"] < 31 and first["candidates"] == 31
    second = _run(store, monkeypatch)
    assert second["done"] == 2 and first["fetched"] + second["fetched"] == 31 + 22
    saved = [a for a in store.articles() if a["url"] != "https://x.test/daily"]
    assert len(saved) == 53 and all("fire" in a["url"] for a in saved)  # candidates only
    assert not (tmp_path / "state" / "fetched" / "archive.txt").exists()  # the daily crawl's list is untouched
    Archive.calls.clear()
    assert _run(store, monkeypatch)["fetched"] == 0 and Archive.calls == []  # nothing left to read
    longer = _run(store, monkeypatch, days=70)  # a longer history: only the days not yet read
    assert Archive.calls == [(dt.date(2026, 8, 19), dt.date(2026, 9, 18)), (dt.date(2026, 8, 18), dt.date(2026, 8, 18))]
    assert longer["fetched"] == 10  # the days not read before; the others are in its list


def test_an_article_the_daily_crawl_saved_is_not_fetched_again(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.mark_fetched("archive", "https://x.test/2026-10-19/fire")
    report = _run(store, monkeypatch, days=8)  # the history is the 19th only
    assert (report["candidates"], report["fetched"], report["done"]) == (1, 0, 1)


def test_a_failed_fetch_is_tried_again_then_given_up(tmp_path, monkeypatch):
    store = _store(tmp_path)
    Archive.fail = {"https://x.test/2026-10-19/fire"}
    assert _run(store, monkeypatch, days=8)["failed"] == 1
    assert _run(store, monkeypatch, days=8)["failed"] == 1  # tried again
    assert _run(store, monkeypatch, days=8)["failed"] == 1  # third try, then given up
    assert _run(store, monkeypatch, days=8)["failed"] == 0
    Archive.fail = set()
