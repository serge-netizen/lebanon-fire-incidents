import datetime as dt
from typing import ClassVar

from crawler import pipeline
from crawler.sources.base import DiscoveredItem, FetchedArticle, Source
from crawler.sources.common import BEIRUT
from crawler.store import Store

NOW = dt.datetime.now(BEIRUT)


class FakeSource(Source):
    slug = "fake"
    fail: ClassVar[set[str]] = set()

    def discover(self, client, since):
        return [DiscoveredItem(f"https://x.test/{n}", h, NOW, self.slug)
                for n, h in ((1, "إخماد حريق في تول"), (2, "زيارة رسمية"), (3, "حريق سيارة في صور"))]

    def fetch(self, client, item):
        if item.url in self.fail:
            return None
        return FetchedArticle(item.url, self.slug, item.headline, item.published_at, "نص المقال")


def _run(tmp_path, monkeypatch, **kw):
    monkeypatch.setattr(pipeline, "sources_for", lambda where: [FakeSource()])
    return pipeline.run("github", store=Store(tmp_path), client=object(), **kw)[0]


def test_second_run_fetches_nothing_new(tmp_path, monkeypatch):
    first = _run(tmp_path, monkeypatch)
    assert (first["candidates"], first["fetched"]) == (2, 2)  # the official visit is not a candidate
    second = _run(tmp_path, monkeypatch)
    assert (second["already_saved"], second["fetched"]) == (2, 0)
    assert len(list(Store(tmp_path).articles())) == 2


def test_a_failed_fetch_is_tried_again(tmp_path, monkeypatch):
    FakeSource.fail = {"https://x.test/3"}
    assert _run(tmp_path, monkeypatch)["failed"] == 1
    FakeSource.fail = set()
    assert _run(tmp_path, monkeypatch)["fetched"] == 1


def test_fetch_limit_leaves_the_rest_for_next_run(tmp_path, monkeypatch):
    report = _run(tmp_path, monkeypatch, max_fetch=1)
    assert report["left_for_next_run"] == 1
    assert Store(tmp_path).resume_from("fake") == NOW.date()


def test_catch_up_after_days_off(tmp_path):
    store = Store(tmp_path)
    today = dt.date(2026, 10, 22)
    assert pipeline.since_for(store, "fake", 3, today) == dt.date(2026, 10, 20)
    (tmp_path / "state" / "runs").mkdir(parents=True)
    (tmp_path / "state" / "runs" / "fake.json").write_text('{"last_success": "2026-10-10T08:00:00+03:00"}')
    assert pipeline.since_for(store, "fake", 3, today) == dt.date(2026, 10, 9)
