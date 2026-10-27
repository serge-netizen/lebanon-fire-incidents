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

# LBCI and Al Jadeed share a publishing system: the lead and the rest of the text in two blocks.
SHORT_AND_LONG = ('//div[@itemprop="articleBody"]'
                  '//div[contains(@class, "ShortDesc") or contains(@class, "LongDesc")]')


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
    body = SHORT_AND_LONG


class AlJadeed(NewsSitemapSource):
    slug = "aljadeed"
    sitemap = "https://www.aljadeed.tv/newssitemap.xml"
    body = SHORT_AND_LONG


class MTV(NewsSitemapSource):
    slug = "mtv"
    sitemap = "https://sitemaps.mtv.com.lb/fresh/sitemap-news.xml.gz"
    body = '//div[contains(@class, "articles-report")]'


class Annahar(NewsSitemapSource):
    slug = "annahar"
    sitemap = "https://www.annahar.com/sitemap/sitemap-news.xml"
    # The lead and the article column; not the "most read" column beside it (2026-10-27).
    body = ('//div[contains(@class, "newsSection")]//div[contains(@class, "description")]'
            ' | //div[contains(@class, "newsSection")]//div[contains(@class, "firstColumn")]')

    def archive(self, client: PoliteClient, first: dt.date, last: dt.date) -> list[DiscoveredItem]:
        """One sitemap per month, headlines included, back to 2019."""
        items: list[DiscoveredItem] = []
        month = first.replace(day=1)
        while month <= last:
            page = client.get(f"https://www.annahar.com/sitemap/sitemap-{month:%Y-%m}.xml")
            if not page.ok:
                raise RuntimeError(f"sitemap {month:%Y-%m}: {page.blocked or page.status}")
            items += [DiscoveredItem(url, title, when, self.slug) for url, title, when in news_sitemap_entries(page.text)
                      if first <= when.date() <= last]
            month = (month + dt.timedelta(days=32)).replace(day=1)
        return items


class Tayyar(NewsSitemapSource):
    slug = "tayyar"
    sitemap = "https://www.tayyar.org/sitemap.xml"
    body = '//div[contains(concat(" ", normalize-space(@class), " "), " text ")]'


class Lebanon24(NewsSitemapSource):
    """News sitemap (two to three days, every section) plus three section feeds (five weeks). The
    two give one article two addresses; its number identifies it."""

    slug = "lebanon24"
    sitemap = "https://www.lebanon24.com/newssitemap.xml"
    feeds = ("1/لبنان", "7/متفرقات", "23/أخبار-عاجلة")
    body = '//div[@itemprop="articleBody"]'

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

    def key(self, url: str) -> str:
        return self._id(url)

    @staticmethod
    def _id(url: str) -> str:
        m = re.search(r"/news/[^/]+/(\d+)", url)
        return m.group(1) if m else url
