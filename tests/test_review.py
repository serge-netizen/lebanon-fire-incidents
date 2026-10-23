import json

from openpyxl import load_workbook

from crawler import review
from crawler.extract import PROMPT_VERSION
from crawler.store import Store

ITEM = {
    "record_type": "incident", "is_lebanon": True, "summary": "A fire.", "occurred_on": None,
    "date_precision": "unknown", "place_text": None, "site_primary": "dump", "site_others": [],
    "material_primary": "household_rubbish", "material_others": [], "hazard_primary": "not_established",
    "hazard_others": [], "origin": "unknown", "deaths": None, "injuries": None, "smoke_inhalation": None,
    "buildings_burned": None, "vehicles_burned": None, "area_burned_m2": None, "displaced": None,
    "responders": [], "evidence": [], "confidence": 0.9,
}
DUMP = ITEM | {"place_text": "صيدا - جبل النفايات", "evidence": [{"field": "site_primary", "quote": "جبل النفايات"}]}
ARTICLES = {  # key: (outlet, headline, items)
    "a": ("nna", "حريق جبل النفايات في صيدا", [DUMP]),
    "b": ("janoubia", "حرائق النفايات في صيدا", [DUMP | {"site_primary": "not_established", "injuries": 1}]),
    "c": ("nna", "غارة تشعل حريقاً في الخيام", [ITEM | {"place_text": "الخيام", "site_primary": "orchard",
                                                       "origin": "conflict_related"}]),
    "d": ("nna", "حريق في كنيسة في مصر", [ITEM | {"is_lebanon": False}]),
}


def test_workbook_has_one_row_per_fire(tmp_path):
    for key, (outlet, headline, items) in ARTICLES.items():
        (tmp_path / "raw" / outlet / "2026-10").mkdir(parents=True, exist_ok=True)
        (tmp_path / "extracted" / outlet / "2026-10").mkdir(parents=True, exist_ok=True)
        article = {"url": f"https://x.test/{key}", "outlet": outlet, "headline": headline,
                   "published_at": "2026-10-07T12:00:00+03:00", "text": headline}
        (tmp_path / f"raw/{outlet}/2026-10/{key}.json").write_text(json.dumps(article, ensure_ascii=False), encoding="utf-8")
        result = {"raw_ref": f"raw/{outlet}/2026-10/{key}.json", "prompt_version": PROMPT_VERSION, "status": "ok",
                  "items": items}
        (tmp_path / f"extracted/{outlet}/2026-10/{key}.json").write_text(json.dumps(result, ensure_ascii=False),
                                                                          encoding="utf-8")
    out = tmp_path / "review.xlsx"
    counts = review.write(out, Store(tmp_path))
    assert (counts["fires"], counts["war_related"], counts["merged"], counts["set_aside"]) == (1, 1, 1, 1)
    wb = load_workbook(out)
    assert wb.sheetnames == ["Read me", "Fires in Lebanon", "War-related (not shown)", "Articles", "Set aside"]
    header = [c.value for c in wb["Fires in Lebanon"][1]]
    row = dict(zip(header, [c.value for c in wb["Fires in Lebanon"][2]], strict=True))
    assert row["Articles"] == "nna, janoubia" and row["Fire date"] == "2026-10-07 (publication date)"
    assert row["Site — main"] == "Dump or landfill (Waste sites)" and row["What burned — reported (main first)"] == "Household rubbish"
    assert "Household rubbish" not in row["What burned — deduced, NOT reported"]
    assert row["Damage (reported)"] == "1 injured"
    possible = {"hazard_primary": "not_established", "hazard_others": ["munitions_explosives"]}
    assert review._reported(possible, "hazard", "hazard") == "not established (also named: Munitions and explosives)"
    assert [c.value for c in wb["Articles"]["A"]][1:] == ["F1", "F1", "W1"]
