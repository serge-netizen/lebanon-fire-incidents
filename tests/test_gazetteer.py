import csv

from crawler import config
from crawler.gazetteer import units
from crawler.geocode import gazetteer


def test_counts_match_ochas_published_structure():
    levels = [u.level for u in units().values()]
    assert (levels.count(1), levels.count(2), levels.count(3)) == (8, 26, 1610)


def test_every_unit_nests_in_existing_parents():
    u = units()
    for unit in u.values():
        assert unit.adm1_pcode in u and u[unit.adm1_pcode].level == 1
        if unit.level == 3:
            assert u[unit.adm2_pcode].level == 2
            assert u[unit.adm2_pcode].adm1_pcode == unit.adm1_pcode


def test_every_place_has_an_arabic_name_and_lies_in_lebanon():
    for unit in units().values():
        if unit.is_place:
            assert unit.name_ar, unit.pcode
        assert 33.0 < unit.lat < 34.8 and 35.0 < unit.lon < 36.7, unit.pcode


def test_disputed_strips_are_never_matched():
    assert sum(1 for u in units().values() if not u.is_place) == 65
    assert "litige" not in gazetteer().index


def test_alias_and_guard_files_are_well_formed():
    gazetteer()  # raises on an alias pointing at an unknown P-code
    with (config.GAZETTEER_DIR / "aliases.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            assert row["status"] in {"verified", "proposed"}, row
            assert row["basis"].strip(), row
            assert row["level"] in {"1", "2", "3", "region"}, row
    with (config.GAZETTEER_DIR / "common_words.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            assert row["guard"] in {"cue", "article", "needs_article"}, row
