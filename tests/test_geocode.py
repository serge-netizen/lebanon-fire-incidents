from pathlib import Path

import pytest
import yaml

from crawler.geocode import normalise, resolve

CASES = yaml.safe_load((Path(__file__).parent / "fixtures" / "geocode_cases.yaml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- the task 2 "done" test

@pytest.mark.parametrize("case", CASES, ids=[c["source"] for c in CASES])
def test_real_place_strings(case):
    r, want = resolve(case["text"]), case["expect"]
    assert r.precision == want["precision"], r.as_dict()
    if "pcode" in want:
        assert r.pcode == want["pcode"], r.as_dict()
    for flag in ("ambiguous", "conflict"):
        if flag in want:
            assert getattr(r, flag) is want[flag], r.as_dict()


def test_there_are_at_least_30_real_cases():
    assert len(CASES) >= 30


# ---------------------------------------------------------------- normalisation

@pytest.mark.parametrize("a,b", [
    ("سنّ الفيل", "سن الفيل"),            # shadda
    ("إهدن", "اهدن"),                      # hamza under alef
    ("ٲبو الٲسود", "أبو الأسود"),          # wavy hamza (NNA 2026-05-16)
    ("زحلة", "زحله"),                      # taa marbuta
    ("النبطية الفوقا", "نبطية الفوقا"),    # article dropped by OCHA
    ("كفررمان", "كفر رمان"),               # كفر spacing
    ("Zahlé", "zahle"),                    # accents
    ("Shouf", "Chouf"),                    # ch / sh
    ("Burj Hammoud", "Bourj Hamoud"),      # ou / u, doubled letters
    ("Saida El-Qadimeh", "Saida Qadimeh"), # transliteration articles
])
def test_spelling_variants_meet(a, b):
    assert normalise(a) == normalise(b)


def test_distinct_names_stay_distinct():
    assert normalise("عرايا") != normalise("فاريا")


# ---------------------------------------------------------------- the rules (synthetic strings)

def test_common_word_needs_a_place_cue():
    assert resolve("حريق في مزرعة دواجن").precision == "unknown"
    assert resolve("حريق في منطقة المزرعة في بيروت").pcode == "10310"


def test_forest_fire_is_not_a_village():
    assert resolve("حرائق الغابات في عكار").pcode == "LB51"


def test_photos_are_not_tyre():
    assert resolve("بالصور: حريق في سيارة").precision == "unknown"
    assert resolve("حريق في صور").pcode == "LB63"


def test_hadath_needs_its_article():
    assert resolve("حريق في الحدث").precision == "village"
    assert resolve("وهذا ما حدث").precision == "unknown"


def test_mina_needs_its_article():
    assert resolve("حريق في مبنى بالميناء").pcode == "31181"  # Mina, Tripoli
    assert resolve("حريق في ميناء صيدا").pcode == "LB61"  # Saida's port, not Mina


def test_district_name_beats_same_named_village():
    assert resolve("حريق في بعلبك").pcode == "LB21"


def test_governorate_and_district_sharing_a_name():
    assert resolve("حريق في النبطية").pcode == "LB4"        # several districts: only the governorate is certain
    assert resolve("حريق في قضاء النبطية").pcode == "LB44"
    assert resolve("حريق في عكار").pcode == "LB51"          # one-district governorate: same area either way


def test_homonyms_need_a_district_to_be_told_apart():
    r = resolve("حريق في كفر الفتوح")                       # two cadastral areas: Jbeil and Akkar
    assert r.precision == "unknown" and r.ambiguous
    assert resolve("حريق في كفر الفتوح - قضاء جبيل").pcode == "26273"


def test_two_villages_resolve_upward_never_down():
    r = resolve("حريق بين دميت وبعقلين")
    assert (r.precision, r.pcode, r.ambiguous) == ("district", "LB33", True)


def test_region_words_are_not_governorates():
    assert resolve("حريق في الجنوب").precision == "unknown"
    assert resolve("حريق في محافظة الجنوب").pcode == "LB6"


def test_nine_governorates():
    assert resolve("حريق في جونية").admin1["pcode"] == "LBKJ"
    assert resolve("حريق في محافظة كسروان جبيل").pcode == "LBKJ"
    assert resolve("حريق في محافظة جبل لبنان").pcode == "LB3"
    assert resolve("حريق في جبل لبنان").precision == "unknown"  # in everyday use it still includes Kesrouan


def test_english_and_french():
    assert resolve("Fire breaks out in Ashrafieh, Beirut").pcode == "10650"
    assert resolve("Blaze in the Chouf district").pcode == "LB33"
    assert resolve("Fire near Sidon").pcode == "LB61"
    assert resolve("Incendie à Tyr").pcode == "LB63"
    assert resolve("A fire north of the city").precision == "unknown"


def test_no_place_is_an_answer():
    r = resolve("الدفاع المدني: 92 مهمة خلال الـ24 ساعة الماضية")
    assert r.precision == "unknown" and r.pcode is None and r.lat is None


def test_a_village_carries_its_parents_and_centre():
    r = resolve("في بلدة زبود – قضاء بعلبك")
    assert r.admin3["pcode"] == "53237" and r.admin2["pcode"] == "LB21" and r.admin1["pcode"] == "LB8"
    assert 33 < r.lat < 35 and 35 < r.lon < 37


def test_a_bare_name_ocha_writes_with_its_district_is_shared():
    """OCHA writes "الخرائب صيدا" and "الخرائب" (Hermel); the press writes the bare name."""
    assert resolve("بلدة الخرايب").ambiguous and resolve("بلدة الخرايب").precision == "unknown"
    assert resolve("الخرايب - قضاء صيدا").pcode == "61419"
    assert resolve("بلدة يحمر الشقيف").pcode == "71394"  # its region tells it apart
    assert resolve("برمانا").pcode == "22611"  # a name only OCHA's form carried


def test_the_district_a_text_names_holds_its_places():
    """Rule 8: a village outside it is left out, and an explicit district beats a stray match."""
    r = resolve("حريق في محلة العين قرب بلدة عندقت – عكار")
    assert (r.pcode, r.conflict) == ("35498", True)
    assert resolve("بلدة عين الناصرة - قضاء صيدا").pcode == "LB61"  # Ain al-Nasra is not in OCHA's table
    r = resolve("حريق في بلدة دميت قرب صيدا")  # without "قضاء", Saida is a landmark: rule 5 as before
    assert (r.precision, r.conflict) == ("unknown", True)
