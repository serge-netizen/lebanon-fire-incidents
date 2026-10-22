import datetime as dt

from crawler.census import Window, arabic_date, news_sitemap, nna
from crawler.fetch import Page
from crawler.filter import census_kind

TODAY = dt.date(2026, 10, 22)

NAMESPACED = """<urlset xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"><url>
<loc>https://example.test/news/1</loc><news:news><news:publication_date>2026-10-21T08:00:00+00:00</news:publication_date>
<news:title>إخماد حريق في معمل في بلدة تول</news:title></news:news></url><url>
<loc>https://example.test/news/2</loc><news:news><news:publication_date>2026-10-01T08:00:00+00:00</news:publication_date>
<news:title>خبر قديم</news:title></news:news></url></urlset>"""

PLAIN = """<urlset><url><loc>https://example.test/news/3</loc><news><publication_date>2026-10-21T17:52:40+03:00</publication_date>
<title>الدفاع المدني: 92 مهمة خلال الـ24 ساعة الماضية</title></news></url></urlset>"""

NNA_DAY = "<urlset><url><loc>https://nna-leb.gov.lb/ar/news/566164/إخماد-حريق-قرب-مدرسة-برج-رحال-2</loc></url></urlset>"


class FakeClient:
    def __init__(self, body: str):
        self.body = body.encode()

    def get(self, url: str) -> Page:
        return Page(url, 200, self.body)


def test_window_is_the_days_before_today():
    w = Window(2, today=TODAY)
    assert (w.start, w.end) == (dt.date(2026, 10, 20), dt.date(2026, 10, 21))
    assert TODAY not in w


def test_news_sitemaps_with_and_without_namespace():
    w = Window(7, today=TODAY)
    r = news_sitemap("x", "https://example.test/sitemap.xml", FakeClient(NAMESPACED), w)
    assert [i.kind for i in r.items] == ["fire"]          # the 1 Oct story falls outside the window
    assert r.first_day == "2026-10-01"                     # but still shows how far the listing reaches
    r = news_sitemap("y", "https://example.test/sitemap.xml", FakeClient(PLAIN), w)
    assert [i.kind for i in r.items] == ["tally"]


def test_nna_headline_comes_from_the_address():
    r = nna(FakeClient(NNA_DAY), Window(1, today=TODAY))
    assert r.items[0].title == "إخماد حريق قرب مدرسة برج رحال"
    assert r.items[0].kind == "fire"


def test_levantine_dates():
    assert arabic_date("الخميس ٢٢ تشرين الأول ٢٠٢٦") == dt.date(2026, 10, 22)
    assert arabic_date("3 آب 2019") == dt.date(2019, 8, 3)
    assert arabic_date("بلا تاريخ") is None


def test_ceasefire_is_not_a_fire():
    assert census_kind("Ceasefire talks resume") is None
    assert census_kind("حريق سيارة تزامن مع قصف") == "fire_conflict"
