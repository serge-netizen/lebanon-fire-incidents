"""Outlets read through their own news sitemap (and, for Lebanon24, its section feeds).
All reachable from GitHub's servers (census 2026-10-22)."""

from __future__ import annotations

import datetime as dt
import re
from typing import ClassVar
from urllib.parse import quote

from crawler.fetch import PoliteClient
from crawler.sources.base import DiscoveredItem, Source
from crawler.sources.common import news_sitemap_entries, rss_entries


class NewsSitemapSource(Source):
    sitemap: ClassVar[str]

    def discover(self, client: PoliteClient, since: dt.date) -> list[DiscoveredItem]:
        page = client.get(self.sitemap)
        if not page.ok:
            raise RuntimeError(f"{self.sitemap}: {page.blocked or page.status}")
        return [DiscoveredItem(url, title, when, self.slug)
                for url, title, when in news_sitemap_entries(page.text) if when.date() >= since]


class LBCI(NewsSitemapSource):
    slug = "lbci"
    sitemap = "https://www.lbcgroup.tv/newssitemap.xml"


class AlJadeed(NewsSitemapSource):
    slug = "aljadeed"
    sitemap = "https://www.aljadeed.tv/newssitemap.xml"


class MTV(NewsSitemapSource):
    slug = "mtv"
    sitemap = "https://sitemaps.mtv.com.lb/fresh/sitemap-news.xml.gz"


class Annahar(NewsSitemapSource):
    slug = "annahar"
    sitemap = "https://www.annahar.com/sitemap/sitemap-news.xml"


class Tayyar(NewsSitemapSource):
    slug = "tayyar"
    sitemap = "https://www.tayyar.org/sitemap.xml"


class Lebanon24(NewsSitemapSource):
    """News sitemap (two to three days, every section) plus three section feeds (five weeks)."""

    slug = "lebanon24"
    sitemap = "https://www.lebanon24.com/newssitemap.xml"
    feeds = ("1/لبنان", "7/متفرقات", "23/أخبار-عاجلة")

    def discover(self, client: PoliteClient, since: dt.date) -> list[DiscoveredItem]:
        items = {self._id(i.url): i for i in super().discover(client, since)}
        for feed in self.feeds:
            number, name = feed.split("/")
            page = client.get(f"https://www.lebanon24.com/Rss/News/{number}/{quote(name)}")
            if not page.ok:
                continue
            for url, title, when in rss_entries(page.text):
                if when.date() >= since:
                    items.setdefault(self._id(url), DiscoveredItem(url, title, when, self.slug))
        return list(items.values())

    @staticmethod
    def _id(url: str) -> str:
        m = re.search(r"/news/[^/]+/(\d+)", url)
        return m.group(1) if m else url
