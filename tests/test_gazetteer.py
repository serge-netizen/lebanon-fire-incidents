import csv

from crawler import config
from crawler.gazetteer import units
from crawler.geocode import gazetteer


def test_counts_match_ochas_published_structure_plus_one_governorate():
    u = units()
    levels = [x.level for x in u.values()]
    assert (levels.count(1), levels.count(2), levels.count(3)) == (9, 26, 1610)
    assert {x.ocha_adm1_pcode for x in u.values() if x.level == 1} - {None} == {f"LB{i}" for i in range(1, 9)}


def _districts_of(gov: str) -> list[str]:
    return sorted(p for p, x in units().items() if x.level == 2 and x.adm1_pcode == gov)


def test_keserwan_jbeil_is_two_districts_carved_out_of_mount_lebanon():
    u = units()
    assert _districts_of("LBKJ") == ["LB34", "LB35"]
    assert _districts_of("LB3") == ["LB31", "LB32", "LB33", "LB36"]
    assert u["26277"].adm1_pcode == "LBKJ" and u["26277"].ocha_adm1_pcode == "LB3"
    assert abs(u["LB3"].area_sqkm + u["LBKJ"].area_sqkm - 1971.13) < 1  # nothing lost in the move


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
