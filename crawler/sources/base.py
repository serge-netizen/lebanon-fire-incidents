"""The contract every outlet adapter fulfils (BRIEF §4.1).

One class per outlet in crawler/sources/, registered in SOURCES. Parser tests use small synthetic
pages: real article text never enters this public repo (BRIEF §11).
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Literal

from crawler.fetch import PoliteClient
from crawler.sources.common import BEIRUT, article_text, body_text, same_words


@dataclass(frozen=True)
class DiscoveredItem:
    url: str
    headline: str
    published_at: dt.datetime | None
    outlet: str


@dataclass
class FetchedArticle:
    url: str
    outlet: str
    headline: str
    published_at: dt.datetime | None
    text: str  # private store only, never published
    # or "lead only" when the site gives no more without a browser, "headline only" for a flash
    method: str = "full text"
    fetched_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(BEIRUT))


class Source(ABC):
    slug: ClassVar[str]
    # Where the source can be read from: GitHub's servers, or only a Lebanese connection
    # (four sites answer GitHub with a bot check — docs/BUILD_PLAN.md §9).
    where: ClassVar[Literal["github", "home"]] = "github"
    source_type: ClassVar[Literal["media", "official"]] = "media"
    is_upstream: ClassVar[bool] = False
    # Where the article text is on the outlet's pages (an XPath). Without one, a generic reader
    # finds it — which, on some outlets, also took the menus and the lists of other headlines.
    body: ClassVar[str | None] = None
    # How many days of the archive the 12-month history reads at a time (crawler/backfill.py).
    archive_days: ClassVar[int] = 31

    @abstractmethod
    def discover(self, client: PoliteClient, since: dt.date) -> list[DiscoveredItem]:
        """Articles published on or after `since`, from feeds, sitemaps or listing pages."""

    def archive(self, client: PoliteClient, first: dt.date, last: dt.date) -> list[DiscoveredItem]:
        """Articles published from `first` to `last`, both included, read from the outlet's archive
        (the 12-month history, crawler/backfill.py). An outlet without a readable archive keeps
        this default."""
        raise NotImplementedError

    @classmethod
    def has_archive(cls) -> bool:
        return cls.archive is not Source.archive

    def key(self, url: str) -> str:
        """What the fetched list records for an article: its address, unless the outlet serves
        one article under several addresses."""
        return url

    def fetch(self, client: PoliteClient, item: DiscoveredItem) -> FetchedArticle | None:
        """Download one article. None when the site refuses or the page has no text. A page with
        no article body (a breaking-news flash) is kept as its headline."""
        page = client.get(item.url)
        if not page.ok:
            return None
        if self.body:
            text = body_text(page.text, self.body)
            if not text or same_words(text, item.headline):
                return FetchedArticle(item.url, self.slug, item.headline, item.published_at, item.headline,
                                      method="headline only")
            return FetchedArticle(item.url, self.slug, item.headline, item.published_at, text)
        text = article_text(page.text)
        if not text:
            return None
        return FetchedArticle(item.url, self.slug, item.headline, item.published_at, text)
