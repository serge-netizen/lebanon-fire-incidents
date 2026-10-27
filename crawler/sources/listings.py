"""Outlets read through listing pages or a site API."""

from __future__ import annotations

import datetime as dt
import json
import re
from urllib.parse import quote, unquote

from crawler.fetch import PoliteClient
from crawler.sources.base import DiscoveredItem, FetchedArticle, Source
from crawler.sources.common import (
    BEIRUT,
    arabic_date,
    clean_title,
    clean_url,
    meta_description,
    parse_when,
    same_words,
    slug_title,
)


class LebanonDebate(Source):
    """Local-news pages, 24 dated articles each. Reachable from GitHub."""

    slug = "lebanondebate"
    listing = "https://www.lebanondebate.com/category/134-" + quote("المحلية")
    max_pages = 40

    def discover(self, client: PoliteClient, since: dt.date) -> list[DiscoveredItem]:
        items: dict[str, DiscoveredItem] = {}
        for number in range(1, self.max_pages + 1):
            page = client.get(self.listing + (f"?pagination={number}" if number > 1 else ""))
            if not page.ok:
                raise RuntimeError(f"page {number}: {page.blocked or page.status}")
            cards = re.findall(r'<a href="([^"]+/article/\d+[^"]*)" class="grid-item">.*?title="([^"]*)".*?<date>(.*?)</date>',
                               page.text, flags=re.DOTALL)
            days = [arabic_date(d) for _, _, d in cards]
            for (href, title, _), day in zip(cards, days, strict=True):
                if day and day >= since:
                    when = dt.datetime.combine(day, dt.time(12), BEIRUT)  # the listing gives the day only
                    items.setdefault(clean_url(href), DiscoveredItem(clean_url(href), clean_title(title), when, self.slug))
            known = [d for d in days if d]
            if not known or min(known) < since:
                break
        return list(items.values())


class NNA(Source):
    """National News Agency: one sitemap per category per day, headline in each address.

    Article text loads in the browser from NNA's /api/, which its robots.txt forbids: we read the
    lead paragraph the page itself carries (its description) and nothing more. Most NNA items are
    republished in full by other outlets, which the pipeline also reads.
    """

    slug = "nna"
    where = "home"
    is_upstream = True
    categories = (1, 2, 3, 4, 5, 6, 7, 9, 10, 12)

    def discover(self, client: PoliteClient, since: dt.date) -> list[DiscoveredItem]:
        return self.archive(client, since, dt.datetime.now(BEIRUT).date())

    def archive(self, client: PoliteClient, first: dt.date, last: dt.date) -> list[DiscoveredItem]:
        """The daily sitemaps reach back about two years."""
        items: dict[str, DiscoveredItem] = {}
        day = first
        while day <= last:
            for cat in self.categories:
                page = client.get(f"https://nna-leb.gov.lb/ar/sitemap/n/{cat}?date={day.isoformat()}")
                if page.blocked == "bot_check":
                    raise RuntimeError("bot check")
                if not page.ok:
                    continue
                for loc in re.findall(r"<loc>(.*?)</loc>", page.text):
                    url = clean_url(loc)
                    when = dt.datetime.combine(day, dt.time(12), BEIRUT)
                    items.setdefault(url, DiscoveredItem(url, slug_title(url), when, self.slug))
            day += dt.timedelta(days=1)
        return list(items.values())

    def fetch(self, client: PoliteClient, item: DiscoveredItem) -> FetchedArticle | None:
        page = client.get(item.url)
        if not page.ok:
            return None
        title = re.search(r'<meta property="og:title" content="([^"]*)"', page.text)
        headline = clean_title(title.group(1)) if title else item.headline
        lead = meta_description(page.text)
        if not lead or same_words(lead, headline):  # NNA's own summary is sometimes broken HTML
            return FetchedArticle(item.url, self.slug, headline, item.published_at, headline, method="headline only")
        return FetchedArticle(item.url, self.slug, headline, item.published_at, lead, method="lead only")


class Elnashra(Source):
    """Security and miscellaneous sections. From outside a browser only the first page shows (one
    to two days), and the bot check comes and goes."""

    slug = "elnashra"
    where = "home"
    body = '//div[contains(@class, "articleBody")]'
    pages = ("category/show/news/37/قضاء-وأمن", "category/show/news/20/متفرقات")

    def discover(self, client: PoliteClient, since: dt.date) -> list[DiscoveredItem]:
        items: dict[str, DiscoveredItem] = {}
        for path in self.pages:
            page = client.get("https://www.elnashra.com/" + "/".join(quote(p) for p in path.split("/")))
            if page.blocked == "bot_check":
                raise RuntimeError("bot check")
            if not page.ok:
                continue
            for stamp, title, href in re.findall(
                    r'data-timestamp="(\d+)" data-id="\d+">\s*<a class="newsimg" title="([^"]*)" href="([^"]+)"', page.text):
                when = dt.datetime.fromtimestamp(int(stamp), BEIRUT)
                if when.date() >= since:
                    url = clean_url(href)
                    items.setdefault(url, DiscoveredItem(url, clean_title(title), when, self.slug))
        return list(items.values())


class Janoubia(Source):
    """WordPress: the posts API lists every article by date."""

    slug = "janoubia"
    where = "home"  # the generic reader is right here; its body block also holds share buttons

    def discover(self, client: PoliteClient, since: dt.date) -> list[DiscoveredItem]:
        return self._posts(client, f"&after={since.isoformat()}T00:00:00")

    def archive(self, client: PoliteClient, first: dt.date, last: dt.date) -> list[DiscoveredItem]:
        """The archive reaches 2011."""
        return self._posts(client, f"&after={first.isoformat()}T00:00:00"
                                   f"&before={(last + dt.timedelta(days=1)).isoformat()}T00:00:00")

    def _posts(self, client: PoliteClient, dates: str) -> list[DiscoveredItem]:
        items = []
        for number in range(1, 30):
            page = client.get("https://janoubia.com/wp-json/wp/v2/posts?per_page=100&_fields=date,link,title"
                              f"{dates}&page={number}")
            if page.status == 400:  # past the last page
                break
            if page.blocked == "bot_check" or not page.ok:
                raise RuntimeError(f"page {number}: {page.blocked or page.status}")
            posts = json.loads(page.text)
            for p in posts:
                when = parse_when(p["date"])
                items.append(DiscoveredItem(clean_url(unquote(p["link"])), clean_title(p["title"]["rendered"]), when, self.slug))
            if len(posts) < 100:
                break
        return items


class LOrientToday(Source):
    """English. The newest article sitemaps; the headline is the address. Some articles are behind
    a paywall: then only the part the page shows is kept."""

    slug = "lorient_today"
    where = "home"

    def __init__(self) -> None:
        self._sitemaps: list[list[tuple[str, dt.datetime]]] | None = None  # every file, read once a run

    def discover(self, client: PoliteClient, since: dt.date) -> list[DiscoveredItem]:
        return self._items(self._files(client, newest=2), since, dt.date.max)

    def archive(self, client: PoliteClient, first: dt.date, last: dt.date) -> list[DiscoveredItem]:
        """About 25 sitemaps of 2,000 articles each, back to about 2018; dated by last change."""
        if self._sitemaps is None:
            self._sitemaps = self._files(client)
        return self._items(self._sitemaps, first, last)

    def _files(self, client: PoliteClient, newest: int | None = None) -> list[list[tuple[str, dt.datetime]]]:
        index = client.get("https://today.lorientlejour.com/sitemap_index.xml")
        if not index.ok:
            raise RuntimeError(f"sitemap index: {index.blocked or index.status}")
        files = sorted((int(n), u) for u, n in re.findall(r"<loc>(\S*?article-sitemap(\d+)\.xml)</loc>", index.text))
        out = []
        for _, url in files[-newest:] if newest else files:
            page = client.get(url)
            if page.ok:
                out.append([(clean_url(loc), when) for loc, stamp in
                            re.findall(r"<loc>(.*?)</loc>\s*<lastmod>(.*?)</lastmod>", page.text)
                            if (when := parse_when(stamp))])
        return out

    def _items(self, files: list[list[tuple[str, dt.datetime]]], first: dt.date, last: dt.date) -> list[DiscoveredItem]:
        items: dict[str, DiscoveredItem] = {}
        for url, when in (entry for f in files for entry in f):
            if first <= when.date() <= last:
                items.setdefault(url, DiscoveredItem(url, slug_title(url), when, self.slug))
        return list(items.values())
