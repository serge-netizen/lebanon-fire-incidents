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
from crawler.sources.common import BEIRUT, article_text


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
    method: str = "full text"  # or "lead only" when the site gives no more without a browser
    fetched_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(BEIRUT))


class Source(ABC):
    slug: ClassVar[str]
    # Where the source can be read from: GitHub's servers, or only a Lebanese connection
    # (four sites answer GitHub with a bot check — docs/BUILD_PLAN.md §9).
    where: ClassVar[Literal["github", "home"]] = "github"
    source_type: ClassVar[Literal["media", "official"]] = "media"
    is_upstream: ClassVar[bool] = False

    @abstractmethod
    def discover(self, client: PoliteClient, since: dt.date) -> list[DiscoveredItem]:
        """Articles published on or after `since`, from feeds, sitemaps or listing pages."""

    def fetch(self, client: PoliteClient, item: DiscoveredItem) -> FetchedArticle | None:
        """Download one article. None when the site refuses or the page has no text."""
        page = client.get(item.url)
        if not page.ok:
            return None
        text = article_text(page.text)
        if not text:
            return None
        return FetchedArticle(item.url, self.slug, item.headline, item.published_at, text)
