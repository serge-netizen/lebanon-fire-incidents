"""The contract every outlet adapter fulfils (BRIEF §4.1).

One class per outlet in crawler/sources/{slug}.py, registered in SOURCES, with a
saved HTML page under crawler/sources/fixtures/{slug}/ so parser tests run offline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Literal


@dataclass(frozen=True)
class DiscoveredItem:
    url: str
    headline: str
    published_at: datetime | None
    outlet: str


@dataclass(frozen=True)
class FetchedArticle:
    url: str
    outlet: str
    headline: str
    published_at: datetime | None
    text: str  # Stored only in the private store, never published.
    fetched_at: datetime


class Source(ABC):
    slug: ClassVar[str]
    source_type: ClassVar[Literal["media", "official"]] = "media"
    is_upstream: ClassVar[bool] = False
    needs_browser: ClassVar[bool] = False  # True only for JavaScript-rendered sites (NNA, OTV).

    @abstractmethod
    def discover(self) -> Iterable[DiscoveredItem]:
        """List candidate articles from feeds, sitemaps or listing pages."""

    @abstractmethod
    def fetch(self, url: str) -> FetchedArticle:
        """Download one article and extract its main text."""
