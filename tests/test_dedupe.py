import datetime as dt
import json

from crawler import dedupe
from crawler import taxonomy as tx
from crawler.dedupe import Report
from crawler.extract import PROMPT_VERSION
from crawler.geocode import Resolution
from crawler.store import Store

ITEM = {
    "record_type": "incident", "is_lebanon": True, "summary": "A fire.", "occurred_on": None,
    "date_precision": "unknown", "place_text": "x", "site_primary": "dump", "site_others": [],
    "material_primary": "household_rubbish", "material_others": [], "hazard_primary": "not_established",
    "hazard_others": [], "origin": "unknown", "deaths": None, "injuries": None, "smoke_inhalation": None,
    "buildings_burned": None, "vehicles_burned": None, "area_burned_m2": None, "displaced": None,
    "responders": [], "evidence": [], "confidence": 0.9,
}
SOUTH, SAIDA, SAIDA_CITY, MIEH = ("LB6",), ("LB6", "LB61"), ("LB6", "LB61", "LB61001"), ("LB6", "LB61", "LB61002")


def place(pcodes: tuple[str, ...]) -> Resolution:
    if not pcodes:
        return Resolution("unknown")
    units = {f"admin{n}": {"pcode": p, "name_en": p} for n, p in enumerate(pcodes, start=1)}
    return Resolution({1: "governorate", 2: "district", 3: "village"}[len(pcodes)], **units)


def report(ref: str, where: tuple[str, ...] = SAIDA, day: int = 7, outlet: str = "nna", headline: str = "",
           scope: str = "in_scope", words: tuple[str, ...] = (), **item) -> Report:
    date = dt.date(2026, 10, day)
    return Report(ITEM | item, ref, outlet, f"https://x.test/{ref}", headline or f"headline {ref}", date, date, True,
                  place(where), scope, list(words))


def merged(*reports: Report) -> list[list[str]]:
    return sorted(sorted(r.raw_ref for r in g) for g in dedupe.group(list(reports)))


def test_one_fire_from_three_outlets_is_one_incident():
    reports = [report("a", SAIDA, 7, "janoubia"), report("b", SAIDA_CITY, 7), report("c", SAIDA, 6, site_primary="not_established")]
    [incident] = dedupe.incidents(reports)
    assert len(incident.reports) == 3 and incident.reports[0].raw_ref == "b"  # the most precise place leads


def test_what_must_match():
    assert merged(report("a"), report("a")) == [["a"], ["a"]]  # two fires in one article stay two
    assert merged(report("a", SAIDA_CITY), report("b", MIEH)) == [["a"], ["b"]]  # neighbouring villages
    assert merged(report("a", SOUTH), report("b", SAIDA_CITY)) == [["a"], ["b"]]  # governorate only: too vague
    assert merged(report("a", day=1), report("b", day=4)) == [["a"], ["b"]]  # three days apart
    assert merged(report("a", site_primary="house"), report("b", site_primary="forest")) == [["a"], ["b"]]
    assert merged(report("a", site_primary="orchard"), report("b", site_primary="forest")) == [["a", "b"]]  # both outdoors


def test_a_factory_whose_product_is_not_stated_is_any_factory():
    assert merged(report("a", site_primary="factory_unspecified"), report("b", site_primary="recycling")) == [["a", "b"]]
    assert merged(report("a", site_primary="chemicals_plastics"),
                  report("b", site_primary="house", site_others=["factory_unspecified"])) == [["a", "b"]]
    assert merged(report("a", site_primary="factory_unspecified"), report("b", site_primary="quarry")) == [["a"], ["b"]]
    assert merged(report("a", site_primary="factory_unspecified"), report("b", site_primary="warehouse")) == [["a"], ["b"]]
    assert merged(report("a", site_primary="recycling"), report("b", site_primary="food_processing")) == [["a"], ["b"]]
    assert dedupe.FACTORIES <= set(tx.site_ids())


def test_places_not_found_merge_on_the_same_headline_or_a_name_one_contains():
    same = merged(report("a", (), headline="حريق سيارة في الجنوب"), report("b", (), headline="حريق سيارة في الجنوب!"))
    assert same == [["a", "b"]]
    assert merged(report("a", (), place_text="وادي الخنازير"), report("b", (), place_text="منطقة الحوش")) == [["a"], ["b"]]
    hawsh = report("a", (), place_text="منطقة الحوش", site_primary="not_established")
    inside = report("b", ("LB7", "LB72", "LB72005"), place_text="منطقة الحوش بين برج الملوك وسهل مرجعيون")
    assert merged(hawsh, inside) == [["a", "b"]]
    assert merged(hawsh, report("c", SAIDA_CITY, place_text="مكب النفايات في صيدا")) == [["a"], ["c"]]
    south = report("d", (), place_text="في الجنوب")
    south.place.matched.append("جنوب")  # a name the map knows, but two governorates: too broad to merge on
    assert merged(south, report("e", SAIDA_CITY, place_text="صيدا في الجنوب")) == [["d"], ["e"]]
    assert "place too broad to map" in dedupe.merge([south]).flags
    assert "place not found in the gazetteer" in dedupe.merge([hawsh]).flags


def test_a_chain_of_near_matches_never_merges_two_fires():
    # Saida district matches both villages, but the villages do not match each other.
    assert merged(report("a", SAIDA, 6), report("b", SAIDA_CITY, 7), report("c", MIEH, 7)) == [["a", "b"], ["c"]]


def test_merge_fills_gaps_and_flags_disagreements():
    main = report("a", SAIDA_CITY, injuries=2, property_damage="none")
    other = report("b", SAIDA, injuries=3, hazard_primary="electrical_installation", origin="accidental",
                   scope="war_related", property_damage="damaged")
    incident = dedupe.merge([other, main])
    rec = incident.record
    assert incident.reports[0] is main and rec["injuries"] == 2
    assert rec["hazard_primary"] == "electrical_installation" and rec["origin"] == "accidental"
    assert incident.scope == "war_related" and rec["property_damage"] == "damaged"
    assert any("injuries" in f for f in incident.flags) and any("war-related" in f for f in incident.flags)
    assert any("on the damage" in f for f in incident.flags)


def test_war_words_are_flagged_on_a_fire_in_scope():
    incident = dedupe.merge([report("a", words=("قصف",))])
    assert incident.scope == "in_scope" and any("war words" in f for f in incident.flags)
    possible = dedupe.merge([report("a", hazard_others=["munitions_explosives", "vehicle_fault"])])
    assert possible.scope == "in_scope" and any("possible cause" in f for f in possible.flags)


def test_load_keeps_current_classifications_and_sorts_them(tmp_path):
    store = Store(tmp_path)
    article = {"url": "https://x.test/1", "outlet": "nna", "headline": "إخماد حريق في بورة للخردة في تول",
               "published_at": "2026-09-28T12:00:00+03:00", "text": "إخماد حريق في بورة للخردة والكسر في تول"}
    fire = ITEM | {"place_text": "تول - قضاء النبطية", "site_primary": "scrap_yard", "occurred_on": "2026-09-27"}
    for key, version, items in (("a", PROMPT_VERSION, [fire, ITEM | {"is_lebanon": False}]), ("b", "1", [fire])):
        (tmp_path / "raw/nna/2026-09").mkdir(parents=True, exist_ok=True)
        (tmp_path / "extracted/nna/2026-09").mkdir(parents=True, exist_ok=True)
        (tmp_path / f"raw/nna/2026-09/{key}.json").write_text(json.dumps(article, ensure_ascii=False), encoding="utf-8")
        result = {"raw_ref": f"raw/nna/2026-09/{key}.json", "prompt_version": version, "status": "ok", "items": items}
        (tmp_path / f"extracted/nna/2026-09/{key}.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    batch = dedupe.load(store)
    assert (len(batch.reports), len(batch.set_aside), batch.stale) == (1, 1, 1)
    r = batch.reports[0]
    assert r.date == dt.date(2026, 9, 27) and not r.date_deduced and r.place.precision == "village"
