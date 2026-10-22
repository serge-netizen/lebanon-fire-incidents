"""Source census (task 3, step A): how many fire stories does each outlet actually carry?

Counts headlines with fire words, per source, over a recent window. Meant to run on GitHub's
servers (`census.yml`), because sites treat data-centre addresses differently from a home line.
Headlines are written to the private store; only counts are printed, since job logs are public.

Two kinds of source:
- **archives** reachable by date (NNA daily sitemaps, Lebanon24 section feeds, Janoubia's site
  search, the Civil Defense listing): counted over the whole window;
- **rolling news sitemaps** that only hold the last days (LBCI, Al Jadeed, MTV, Annahar,
  Lebanon24, Tayyar): counted over the days they cover, so their per-day rate is the comparable
  figure. Re-running the census on later days lengthens their window.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
from dataclasses import asdict, dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo

from crawler import config
from crawler.fetch import Page, PoliteClient
from crawler.filter import census_kind

BEIRUT = ZoneInfo(config.TIMEZONE)

NNA_CATEGORIES = (1, 2, 3, 4, 5, 6, 7, 9, 10, 12)  # the ones that publish (2026-10-20); 8, 11, 13–19 were empty
NEWS_SITEMAPS = {
    "lbci": "https://www.lbcgroup.tv/newssitemap.xml",
    "aljadeed": "https://www.aljadeed.tv/newssitemap.xml",
    "mtv": "https://sitemaps.mtv.com.lb/fresh/sitemap-news.xml.gz",
    "annahar": "https://www.annahar.com/sitemap/sitemap-news.xml",
    "lebanon24": "https://www.lebanon24.com/newssitemap.xml",
    "tayyar": "https://www.tayyar.org/sitemap.xml",
}
LEBANON24_FEEDS = ("1/لبنان", "7/متفرقات", "23/أخبار-عاجلة")
ELNASHRA_PAGES = ("news/tag/حريق", "category/show/news/37/قضاء-وأمن", "category/show/news/20/متفرقات")
STATUS_ONLY = {
    "lebanonfiles": "https://www.lebanonfiles.com/",
    "kataeb": "https://www.kataeb.org/category/" + quote("متفرقات"),
}
LEBANON_DEBATE = "https://www.lebanondebate.com/category/134-" + quote("المحلية")
# Levantine month names as Lebanese sites print them.
AR_MONTHS = {"كانون الثاني": 1, "شباط": 2, "آذار": 3, "نيسان": 4, "أيار": 5, "حزيران": 6, "تموز": 7,
             "آب": 8, "أيلول": 9, "تشرين الأول": 10, "تشرين الثاني": 11, "كانون الأول": 12}
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


@dataclass
class Item:
    day: str        # YYYY-MM-DD, Beirut time
    title: str
    url: str
    kind: str | None  # fire | fire_conflict | tally | None


@dataclass
class Result:
    source: str
    method: str
    status: str = "ok"
    first_day: str | None = None  # oldest day the listing reached, inside or outside the window
    last_day: str | None = None
    items: list[Item] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def see(self, day: dt.date) -> None:
        d = day.isoformat()
        self.first_day = min(self.first_day or d, d)
        self.last_day = max(self.last_day or d, d)

    def fail(self, page: Page, what: str) -> Result:
        self.status = page.blocked or f"HTTP {page.status}"
        self.notes.append(f"{what}: {self.status}")
        return self


class Window:
    def __init__(self, days: int, today: dt.date | None = None):
        self.end = (today or dt.datetime.now(BEIRUT).date()) - dt.timedelta(days=1)
        self.start = self.end - dt.timedelta(days=days - 1)

    def __contains__(self, day: dt.date) -> bool:
        return self.start <= day <= self.end

    def days(self) -> list[dt.date]:
        return [self.start + dt.timedelta(days=i) for i in range((self.end - self.start).days + 1)]


def _add(result: Result, window: Window, day: dt.date, title: str, url: str) -> None:
    result.see(day)
    if day in window:
        title = html.unescape(re.sub(r"\s+", " ", title)).strip()
        result.items.append(Item(day.isoformat(), title, url, census_kind(title)))


def _beirut_day(stamp: str) -> dt.date | None:
    try:
        when = dt.datetime.fromisoformat(stamp.strip())
    except ValueError:
        try:
            when = parsedate_to_datetime(stamp.strip())
        except (TypeError, ValueError):
            return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=BEIRUT)
    return when.astimezone(BEIRUT).date()


# ---------------------------------------------------------------- probes

def nna(c: PoliteClient, w: Window) -> Result:
    """NNA publishes one sitemap per category per day; the headline is in each address."""
    r = Result("nna", "daily category sitemaps")
    for day in w.days():
        for cat in NNA_CATEGORIES:
            page = c.get(f"https://nna-leb.gov.lb/ar/sitemap/n/{cat}?date={day.isoformat()}")
            if not page.ok:
                r.notes.append(f"{day} cat {cat}: {page.blocked or page.status}")
                continue
            for loc in re.findall(r"<loc>(.*?)</loc>", page.text):
                slug = unquote(loc).split("/news/", 1)[-1].split("/", 1)[-1]
                _add(r, w, day, re.sub(r"-\d+$", "", slug).replace("-", " "), loc)
    if not r.items and r.notes:
        r.status = "no data"
    return r


def news_sitemap(name: str, url: str, c: PoliteClient, w: Window) -> Result:
    r = Result(name, "news sitemap")
    page = c.get(url)
    if not page.ok:
        return r.fail(page, url)
    for block in re.findall(r"<url>(.*?)</url>", page.text, flags=re.DOTALL):
        loc = re.search(r"<loc>(.*?)</loc>", block, flags=re.DOTALL)
        title = re.search(r"<(?:news:)?title>(.*?)</(?:news:)?title>", block, flags=re.DOTALL)
        stamp = re.search(r"<(?:news:)?publication_date>(.*?)</", block) or re.search(r"<lastmod>(.*?)</", block)
        day = _beirut_day(stamp.group(1)) if stamp else None
        if loc and day:
            text = title.group(1) if title else unquote(loc.group(1)).rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
            _add(r, w, day, re.sub(r"<!\[CDATA\[|\]\]>", "", text), loc.group(1).strip())
    return r


def lebanon24_feeds(c: PoliteClient, w: Window) -> Result:
    r = Result("lebanon24_rss", "RSS, three sections")
    for feed in LEBANON24_FEEDS:
        number, name = feed.split("/")
        page = c.get(f"https://www.lebanon24.com/Rss/News/{number}/{quote(name)}")
        if not page.ok:
            r.fail(page, feed)
            continue
        for block in re.findall(r"<item>(.*?)</item>", page.text, flags=re.DOTALL):
            title = re.search(r"<title>(.*?)</title>", block, flags=re.DOTALL)
            link = re.search(r"<link>(.*?)</link>", block, flags=re.DOTALL)
            stamp = re.search(r"<pubDate>(.*?)</pubDate>", block)
            day = _beirut_day(stamp.group(1)) if stamp else None
            if title and link and day:
                _add(r, w, day, re.sub(r"<!\[CDATA\[|\]\]>", "", title.group(1)), link.group(1).strip())
    seen: set[str] = set()
    r.items = [i for i in r.items if not (i.url in seen or seen.add(i.url))]  # one story, several feeds
    return r


def janoubia(c: PoliteClient, w: Window) -> Result:
    """WordPress site search API: every post published inside the window."""
    r = Result("janoubia", "WordPress posts API")
    for number in range(1, 60):
        page = c.get("https://janoubia.com/wp-json/wp/v2/posts?per_page=100&_fields=date,link,title"
                     f"&after={w.start.isoformat()}T00:00:00&before={(w.end + dt.timedelta(days=1)).isoformat()}T00:00:00"
                     f"&page={number}")
        if page.status == 400:  # past the last page
            break
        if not page.ok:
            return r.fail(page, f"page {number}")
        posts = json.loads(page.text)
        for p in posts:
            day = _beirut_day(p["date"])
            if day:
                _add(r, w, day, p["title"]["rendered"], p["link"])
        if len(posts) < 100:
            break
    return r


def elnashra(c: PoliteClient, w: Window) -> Result:
    r = Result("elnashra", "tag and section pages (first page each)")
    for path in ELNASHRA_PAGES:
        page = c.get("https://www.elnashra.com/" + "/".join(quote(p) for p in path.split("/")))
        if not page.ok:
            r.fail(page, path)
            continue
        found = re.findall(r'data-timestamp="(\d+)" data-id="\d+">\s*<a class="newsimg" title="([^"]*)" href="([^"]+)"',
                           page.text)
        days = [dt.datetime.fromtimestamp(int(t), BEIRUT).date() for t, _, _ in found]
        if days:
            r.notes.append(f"{path}: {len(found)} items, newest {max(days)}, oldest {min(days)}")
        for (stamp, title, href), day in zip(found, days):
            _add(r, w, day, title, href)
    seen: set[str] = set()
    r.items = [i for i in r.items if not (i.title in seen or seen.add(i.title))]
    return r


def arabic_date(text: str) -> dt.date | None:
    """'الخميس ٢٢ تشرين الأول ٢٠٢٦' → 2026-10-22."""
    t = text.translate(AR_DIGITS)
    for name, month in AR_MONTHS.items():
        m = re.search(rf"(\d{{1,2}})\s+{name}\s+(\d{{4}})", t)
        if m:
            return dt.date(int(m.group(2)), month, int(m.group(1)))
    return None


def lebanon_debate(c: PoliteClient, w: Window, max_pages: int = 150) -> Result:
    r = Result("lebanondebate", "local-news pages, 24 per page")
    for number in range(1, max_pages + 1):
        page = c.get(LEBANON_DEBATE + (f"?pagination={number}" if number > 1 else ""))
        if not page.ok:
            return r.fail(page, f"page {number}")
        cards = re.findall(r'<a href="([^"]+/article/\d+[^"]*)" class="grid-item">.*?title="([^"]*)".*?<date>(.*?)</date>',
                           page.text, flags=re.DOTALL)
        days = [arabic_date(d) for _, _, d in cards]
        for (href, title, _), day in zip(cards, days):
            if day:
                _add(r, w, day, title, href)
        known = [d for d in days if d]
        if not known or min(known) < w.start:
            break
    return r


def lorient_today(c: PoliteClient, w: Window) -> Result:
    """English. The newest article sitemap; the headline is the address's slug."""
    r = Result("lorient_today", "article sitemap (English)")
    index = c.get("https://today.lorientlejour.com/sitemap_index.xml")
    if not index.ok:
        return r.fail(index, "sitemap index")
    numbered = sorted((int(n), u) for u, n in re.findall(r"<loc>(\S*?article-sitemap(\d+)\.xml)</loc>", index.text))
    for _, url in numbered[-2:]:  # the two newest files cover the window
        page = c.get(url)
        if not page.ok:
            r.fail(page, url)
            continue
        for loc, stamp in re.findall(r"<loc>(.*?)</loc>\s*<lastmod>(.*?)</lastmod>", page.text):
            day = _beirut_day(stamp)
            slug = loc.rstrip("/").rsplit("/", 1)[-1].removesuffix(".html")
            if day:
                _add(r, w, day, slug.replace("-", " "), loc)
    return r


def civil_defense(c: PoliteClient, w: Window) -> Result:
    """Statement titles are generic ('…البيان الآتي'): only the count and freshness are measured."""
    r = Result("civil_defense", "statements listing")
    page = c.get("http://civildefense.gov.lb/index.php?page=dailyacts")
    if not page.ok:
        return r.fail(page, "listing")
    for stamp in re.findall(r'class="NewsSummaryPostdate">\s*([^<]+?)\s*<', page.text):
        try:
            day = dt.datetime.strptime(stamp.strip(), "%b %d, %Y").date()
        except ValueError:
            continue
        _add(r, w, day, "statement", "http://civildefense.gov.lb/index.php?page=dailyacts")
    r.notes.append(f"newest statement listed: {r.last_day}")
    return r


def status_only(name: str, url: str, c: PoliteClient) -> Result:
    page = c.get(url)
    r = Result(name, "reachability only")
    if not page.ok:
        return r.fail(page, url)
    links = len(set(re.findall(r'href="[^"]*/(?:news|article|articles)/\d+', page.text)))
    r.notes.append(f"HTTP 200, {len(page.body)} bytes, {links} article links in the HTML"
                   + (" — built in the browser: needs Playwright" if links == 0 else ""))
    if links == 0:
        r.status = "needs browser"
    return r


# ---------------------------------------------------------------- archive depth (owner, 2026-10-22: up to 10 years)

def depth(c: PoliteClient) -> list[dict]:
    """One or two requests per source: does its archive reach back, and with headlines?"""
    checks = []

    def check(source: str, what: str, url: str, count) -> None:
        page = c.get(url)
        checks.append({"source": source, "what": what, "status": page.blocked or page.status,
                       "result": count(page) if page.ok else None})

    for day in ("2016-10-20", "2020-10-20", "2023-10-20", "2024-10-20"):
        check("nna", f"local news sitemap for {day}", f"https://nna-leb.gov.lb/ar/sitemap/n/1?date={day}",
              lambda p: f"{p.text.count('<loc>')} addresses (headline in address)")
    check("mtv", "monthly sitemap Oct 2016", "https://sitemaps.mtv.com.lb/archives/2016/sitemap-2016-m10.xml.gz",
          lambda p: f"{p.text.count('<loc>')} addresses, no headlines")
    for month in ("2019-10", "2022-10"):
        check("annahar", f"monthly sitemap {month}", f"https://www.annahar.com/sitemap/sitemap-{month}.xml",
              lambda p: f"{p.text.count('<url>')} addresses, headlines: {'<news:title>' in p.text}")
    check("janoubia", "oldest post", "https://janoubia.com/wp-json/wp/v2/posts?per_page=1&order=asc&_fields=date",
          lambda p: f"oldest post {json.loads(p.text)[0]['date'][:10]}")
    check("lorient_today", "first article sitemap", "https://today.lorientlejour.com/article-sitemap1.xml",
          lambda p: f"oldest lastmod {min(re.findall(r'<lastmod>(.{10})', p.text) or ['-'])}")
    for site in ("elnashra.com/news/show/*", "lebanon24.com/news/*", "lbcgroup.tv/news/*"):
        check("wayback", f"{site} captured in 2016",
              f"https://web.archive.org/cdx/search/cdx?url={site}&from=2016&to=2016&output=json&limit=2000"
              "&fl=original&filter=statuscode:200&collapse=urlkey",
              lambda p: f"{max(len(json.loads(p.text or '[]')) - 1, 0)} distinct addresses (capped at 2,000)")
    return checks


# ---------------------------------------------------------------- run

def run(days: int, out: Path) -> list[dict]:
    w = Window(days)
    c = PoliteClient()
    results = [nna(c, w), lebanon24_feeds(c, w), janoubia(c, w), lebanon_debate(c, w), elnashra(c, w),
               lorient_today(c, w), civil_defense(c, w)]
    results += [news_sitemap(n, u, c, w) for n, u in NEWS_SITEMAPS.items()]
    results += [status_only(n, u, c) for n, u in STATUS_ONLY.items()]

    stamp = dt.datetime.now(BEIRUT).strftime("%Y-%m-%d")
    folder = out / stamp
    (folder / "items").mkdir(parents=True, exist_ok=True)
    summary = []
    for r in results:
        (folder / "items" / f"{r.source}.json").write_text(
            json.dumps(asdict(r), ensure_ascii=False, indent=1), encoding="utf-8")
        summary.append(_summarise(r, w))
    archive = depth(c)
    (folder / "summary.json").write_text(json.dumps(
        {"window": [w.start.isoformat(), w.end.isoformat()], "requests": c.requests, "sources": summary,
         "depth": archive}, ensure_ascii=False, indent=1), encoding="utf-8")
    for d in archive:
        print(f"depth  {d['source']:14} {d['what']:34} {d['status']!s:9} {d['result']}")
    return summary


def _summarise(r: Result, w: Window) -> dict:
    covered = 0
    if r.first_day and r.last_day:
        lo = max(dt.date.fromisoformat(r.first_day), w.start)
        hi = min(dt.date.fromisoformat(r.last_day), w.end)
        covered = max((hi - lo).days + 1, 0)
    count = lambda kind: sum(1 for i in r.items if i.kind == kind)
    fire = count("fire") + count("fire_conflict")
    return {
        "source": r.source, "method": r.method, "status": r.status, "days_covered": covered,
        "items": len(r.items), "fire": count("fire"), "fire_conflict": count("fire_conflict"),
        "tally": count("tally"), "fire_per_day": round(fire / covered, 2) if covered else None,
        "notes": r.notes[:6],
    }


def print_table(summary: list[dict]) -> None:
    print(f"{'source':15} {'status':16} {'days':>4} {'items':>6} {'fire':>5} {'confl':>5} {'tally':>5} {'fire/day':>8}")
    for s in summary:
        print(f"{s['source']:15} {s['status'][:16]:16} {s['days_covered']:>4} {s['items']:>6} {s['fire']:>5} "
              f"{s['fire_conflict']:>5} {s['tally']:>5} {s['fire_per_day']!s:>8}")
