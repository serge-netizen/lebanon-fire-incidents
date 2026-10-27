import datetime as dt

from crawler.fetch import Page
from crawler.sources.base import DiscoveredItem
from crawler.sources.common import clean_url, rss_entries, slug_title
from crawler.sources.listings import NNA, Elnashra, LebanonDebate
from crawler.sources.sitemaps import LBCI, MTV, Lebanon24, Tayyar


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


# Synthetic pages in each outlet's layout (no real article text in this repo).
LEBANON24 = ('<html><body><nav>بحث تصفّح بدون إعلانات</nav><div itemprop="articleBody"><div><strong>'
             'اندلع حريق في <a class="entities-links">عكار</a> مساء اليوم.<br>'
             '<div class="MainControlDiv BannersControl_FullMainDiv"><div>Advertisement</div></div>'
             '</strong>وعملت فرق الدفاع المدني على إخماده.</div></div><div>مواضيع ذات صلة</div></body></html>')
FLASH = '<html><body><nav>بحث</nav><div itemprop="articleBody"><div class="MainControlDiv Banners">Advertisement</div></div></body></html>'
LBCI_PAGE = ('<html><body><div itemprop="articleBody" class="article_details_body"><div>0<sup>min</sup></div>'
        '<span class="d-none">حريق في صور</span><div class="ShortDesc"><h2>شب حريق في محل في صور.</h2></div>'
        '<div class="LongDesc"><div>ولم يفد عن إصابات.</div></div><div class="ltrDisclaimerDiv">*حفاظاً على حقوق الملكية</div>'
        '<div class="article_details_next">التالي خبر آخر</div></div></body></html>')


def _fetch(source, page: str, headline: str):
    return source.fetch(FakeClient(default=page), DiscoveredItem("https://x.test/news/a/1584349/x", headline, None, source.slug))


def test_an_outlet_body_is_read_without_menus_or_advertisements():
    article = _fetch(Lebanon24(), LEBANON24, "حريق في عكار")
    assert article.method == "full text"
    assert article.text == "اندلع حريق في عكار مساء اليوم.\nوعملت فرق الدفاع المدني على إخماده."
    lbci = _fetch(LBCI(), LBCI_PAGE, "حريق في صور")
    assert lbci.text == "شب حريق في محل في صور.\nولم يفد عن إصابات."  # no reading time, notice or next story


def test_a_flash_with_no_body_is_kept_as_its_headline():
    for source, page in ((Lebanon24(), FLASH), (LBCI(), LBCI_PAGE.replace("ShortDesc", "x").replace("LongDesc", "y")),
                         (MTV(), "<html><body><div class='articles-wrapper'>invalid {{ loginErrorMessage }}</div></body></html>"),
                         (Tayyar(), "<html><body><nav>FPM Writers</nav><div class='text '></div></body></html>")):
        article = _fetch(source, page, "حريق في عكار")
        assert (article.method, article.text) == ("headline only", "حريق في عكار"), source.slug


def test_nna_summary_cut_in_half_gives_the_headline():
    page = '<meta property="og:title" content="إخماد حريق في تول"><meta property="og:description" content="&lt;span s">'
    article = _fetch(NNA(), page, "x")
    assert (article.method, article.text) == ("headline only", "إخماد حريق في تول")
    whole = page.replace("&lt;span s", "وطنية - أخمد الدفاع المدني حريقاً في تول")
    assert _fetch(NNA(), whole, "x").text == "وطنية - أخمد الدفاع المدني حريقاً في تول"


def test_lebanon24_key_is_the_article_number():
    assert Lebanon24().key("https://www.lebanon24.com/news/lebanon-news/1584349/lebanon24?src=rss") == "1584349"
    assert LBCI().key("https://x.test/a") == "https://x.test/a"
