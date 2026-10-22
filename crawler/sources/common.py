"""Helpers every source adapter shares: Beirut dates, sitemap and RSS readers, clean addresses,
article text."""

from __future__ import annotations

import datetime as dt
import html
import re
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import trafilatura

from crawler import config

BEIRUT = ZoneInfo(config.TIMEZONE)
# Levantine month names as Lebanese sites print them.
AR_MONTHS = {"كانون الثاني": 1, "شباط": 2, "آذار": 3, "نيسان": 4, "أيار": 5, "حزيران": 6, "تموز": 7,
             "آب": 8, "أيلول": 9, "تشرين الأول": 10, "تشرين الثاني": 11, "كانون الأول": 12}
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
TRACKING = re.compile(r"^(utm_|src$|fbclid$|gclid$|ref$)")


def parse_when(stamp: str) -> dt.datetime | None:
    """ISO 8601 or RFC 822 → an aware datetime in Beirut time."""
    stamp = stamp.strip()
    try:
        when = dt.datetime.fromisoformat(stamp)
    except ValueError:
        try:
            when = parsedate_to_datetime(stamp)
        except (TypeError, ValueError):
            return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=BEIRUT)
    return when.astimezone(BEIRUT)


def arabic_date(text: str) -> dt.date | None:
    """'الخميس ٢٢ تشرين الأول ٢٠٢٦' → 2026-10-22."""
    t = text.translate(AR_DIGITS)
    for name, month in AR_MONTHS.items():
        m = re.search(rf"(\d{{1,2}})\s+{name}\s+(\d{{4}})", t)
        if m:
            return dt.date(int(m.group(2)), month, int(m.group(1)))
    return None


def clean_url(url: str) -> str:
    """Unescape, drop tracking parameters and fragments: one address per article."""
    parts = urlsplit(html.unescape(url.strip()))
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING.match(k)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def clean_title(text: str) -> str:
    text = re.sub(r"<!\[CDATA\[|\]\]>", "", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def slug_title(url: str) -> str:
    """The headline written into an address: '/news/123/إخماد-حريق-في-تول-2' → 'إخماد حريق في تول'."""
    last = unquote(url).rstrip("/").rsplit("/", 1)[-1].removesuffix(".html")
    return re.sub(r"-\d+$", "", last).replace("-", " ").strip()


def news_sitemap_entries(xml: str) -> list[tuple[str, str, dt.datetime]]:
    """(address, headline, published) from a news sitemap, with or without the news: prefix."""
    out = []
    for block in re.findall(r"<url>(.*?)</url>", xml, flags=re.DOTALL):
        loc = re.search(r"<loc>(.*?)</loc>", block, flags=re.DOTALL)
        title = re.search(r"<(?:news:)?title>(.*?)</(?:news:)?title>", block, flags=re.DOTALL)
        stamp = re.search(r"<(?:news:)?publication_date>(.*?)</", block) or re.search(r"<lastmod>(.*?)</", block)
        when = parse_when(stamp.group(1)) if stamp else None
        if loc and when:
            url = clean_url(loc.group(1))
            out.append((url, clean_title(title.group(1)) if title else slug_title(url), when))
    return out


def rss_entries(xml: str) -> list[tuple[str, str, dt.datetime]]:
    out = []
    for block in re.findall(r"<item>(.*?)</item>", xml, flags=re.DOTALL):
        title = re.search(r"<title>(.*?)</title>", block, flags=re.DOTALL)
        link = re.search(r"<link>(.*?)</link>", block, flags=re.DOTALL)
        stamp = re.search(r"<pubDate>(.*?)</pubDate>", block)
        when = parse_when(stamp.group(1)) if stamp else None
        if title and link and when:
            out.append((clean_url(link.group(1)), clean_title(title.group(1)), when))
    return out


def article_text(page_html: str) -> str:
    """Main text of an article page; recall over precision, so short list lines survive."""
    return trafilatura.extract(page_html, include_comments=False, include_tables=True, favor_recall=True) or ""


def meta_description(page_html: str) -> str:
    m = re.search(r'<meta[^>]+(?:property|name)="(?:og:)?description"[^>]+content="([^"]*)"', page_html)
    return clean_title(m.group(1)) if m else ""
