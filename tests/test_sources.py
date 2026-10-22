import datetime as dt

from crawler.fetch import Page
from crawler.sources.common import clean_url, rss_entries, slug_title
from crawler.sources.listings import Elnashra, LebanonDebate
from crawler.sources.sitemaps import Lebanon24


class FakeClient:
    def __init__(self, pages: dict[str, str] | None = None, default: str = ""):
        self.pages, self.default = pages or {}, default

    def get(self, url: str) -> Page:
        for key, body in self.pages.items():
            if key in url:
                return Page(url, 200, body.encode())
        return Page(url, 200, self.default.encode())


def test_clean_url_drops_tracking_and_entities():
    url = "https://www.lebanon24.com/news/lebanon-news/1584349/lebanon24?src=rss-feeds&amp;utm_campaign=x&amp;page=2#top"
    assert clean_url(url) == "https://www.lebanon24.com/news/lebanon-news/1584349/lebanon24?page=2"


def test_headline_from_address():
    assert slug_title("https://nna-leb.gov.lb/ar/news/566164/إخماد-حريق-قرب-مدرسة-2") == "إخماد حريق قرب مدرسة"
    assert slug_title("https://today.lorientlejour.com/article/1/fire-breaks-out-in-tyre.html") == "fire breaks out in tyre"


def test_rss():
    xml = ("<rss><channel><item><title><![CDATA[حريق في تول]]></title><link>https://x.test/a?utm_source=y</link>"
           "<pubDate>Mon, 19 Oct 2026 07:12:59 GMT</pubDate></item></channel></rss>")
    assert rss_entries(xml)[0][:2] == ("https://x.test/a", "حريق في تول")


def test_lebanon_debate_listing():
    card = ('<a href="https://www.lebanondebate.com/article/891724-x" class="grid-item"><img title="حريق في عكار">'
            '<date>الخميس ٢٢ تشرين الأول ٢٠٢٦</date></a>')
    old = card.replace("891724", "1").replace("٢٢ تشرين الأول", "١ أيلول")
    items = LebanonDebate().discover(FakeClient(default=card + old), dt.date(2026, 10, 20))
    assert [(i.url, i.headline) for i in items] == [("https://www.lebanondebate.com/article/891724-x", "حريق في عكار")]


def test_elnashra_sections():
    li = ('<li class="newsfeed-main " data-timestamp="1792674834" data-id="9"> <a class="newsimg" '
          'title="إخماد حريق في الحمراء" href="https://www.elnashra.com/news/show/9/x">')
    items = Elnashra().discover(FakeClient(default=li), dt.date(2026, 10, 1))
    assert items[0].headline == "إخماد حريق في الحمراء" and items[0].published_at.year == 2026


def test_lebanon24_same_story_from_sitemap_and_feed_counted_once():
    sitemap = ("<urlset><url><loc>https://www.lebanon24.com/news/lebanon/1584349/x</loc><news:news>"
               "<news:publication_date>2026-10-19T10:12:59+03:00</news:publication_date><news:title>t</news:title>"
               "</news:news></url></urlset>")
    feed = ("<rss><item><title>t</title><link>https://www.lebanon24.com/news/lebanon-news/1584349/lebanon24?src=rss</link>"
            "<pubDate>Mon, 19 Oct 2026 07:12:59 GMT</pubDate></item></rss>")
    client = FakeClient({"newssitemap": sitemap, "Rss/News": feed})
    assert len(Lebanon24().discover(client, dt.date(2026, 10, 18))) == 1
