"""Helpers every source adapter shares: Beirut dates, sitemap and RSS readers, clean addresses,
article text."""

from __future__ import annotations

import datetime as dt
import html
import re
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import lxml.html
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


BLOCKS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "tr", "section", "article"}
# Inside an article body: code, forms, embeds and advertisement blocks (Lebanon24 puts one mid-text).
NOISE = (".//script | .//style | .//noscript | .//input | .//iframe | .//form | .//button"
         " | .//*[contains(@class, 'Banner')]")


def body_text(page_html: str, xpath: str) -> str:
    """The text of the elements `xpath` selects — an outlet's article body, read without the menus,
    log-in boxes and lists of other headlines a generic reader picks up. Empty when the page has
    no body: a breaking-news flash, which is its headline only."""
    lines: list[str] = []
    for el in lxml.html.fromstring(page_html).xpath(xpath):
        for junk in el.xpath(NOISE):
            junk.drop_tree()
        for node in el.iter():
            if not isinstance(node.tag, str):  # a comment
                continue
            node.text = node.text and re.sub(r"\s+", " ", node.text)
            node.tail = node.tail and re.sub(r"\s+", " ", node.tail)
            if node.tag in BLOCKS:
                node.text = "\n" + (node.text or "")
            if node.tag in BLOCKS or node.tag == "br":
                node.tail = "\n" + (node.tail or "")
        lines += (line.strip() for line in el.text_content().split("\n"))
    return "\n".join(line for line in lines if line)


def same_words(a: str, b: str) -> bool:
    """Equal once punctuation and spacing are ignored: a body that only repeats the headline."""
    def words(t: str) -> str:
        return " ".join(re.findall(r"\w+", t))
    return words(a) == words(b)


def meta_description(page_html: str) -> str:
    """The page's own summary. Tags are removed: NNA sometimes cuts one in half ("<span s")."""
    m = re.search(r'<meta[^>]+(?:property|name)="(?:og:)?description"[^>]+content="([^"]*)"', page_html)
    return clean_title(re.sub(r"<[^>]*(?:>|$)", " ", html.unescape(m.group(1)))) if m else ""
