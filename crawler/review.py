"""Review (BRIEF §4.7). For now, the owner's review workbook — the task 4 feedback loop: one row
per item Claude extracted, in plain labels, with two columns for the owner's verdict and
correction. Private: it quotes the articles, so it is written to the private store, never to this
repo. Task 5 adds the review sheet and reads decisions back.
"""

from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from crawler.extract import taxonomy
from crawler.geocode import resolve
from crawler.store import Store

HEADER_FILL = PatternFill("solid", fgColor="2F3B4C")
REVIEW_FILL = PatternFill("solid", fgColor="FFF4D6")
WRAP = Alignment(wrap_text=True, vertical="top")

COLUMNS = [  # (title, width)
    ("#", 5), ("Published", 11), ("Outlet", 12), ("Headline", 46), ("Summary (Claude)", 46),
    ("Fire date", 11), ("Place as written", 26), ("Location found", 30), ("Location precision", 11),
    ("Site category", 22), ("Site (primary)", 26), ("Site (others)", 26), ("Hazard (primary)", 24),
    ("Hazard (others)", 24), ("Materials reported", 26), ("Fire class of reported materials", 12),
    ("Typical materials for this site — NOT reported", 30), ("Origin", 14), ("Deaths", 8),
    ("Injuries", 8), ("Smoke inhalation", 9), ("Buildings burned", 9), ("Vehicles burned", 9),
    ("Area burned (m²)", 10), ("Displaced", 9), ("Responders", 18), ("Confidence", 10),
    ("Evidence (quotes)", 60), ("YOUR VERDICT (OK / wrong)", 14), ("YOUR CORRECTION", 40),
]


def _labels() -> tuple[dict, dict, dict, dict]:
    t = taxonomy()
    sites, categories = {"not_established": "Not established"}, {"not_established": "Not established"}
    for cat, v in t["site_types"].items():
        categories[cat] = v["label"]
        for sub, s in (v.get("subtypes") or {}).items():
            sites[sub] = s["label"]
    hazards = {k: v["label"] for k, v in t["hazards"].items()}
    materials = {k: v for k, v in t["materials"].items()}
    return sites, categories, hazards, materials


def _location(place_text: str | None) -> tuple[str, str]:
    if not place_text:
        return "", "unknown"
    r = resolve(place_text)
    parts = [u["name_en"] for u in (r.admin3, r.admin2, r.admin1) if u]
    flags = [f for f, on in (("ambiguous", r.ambiguous), ("conflict", r.conflict)) if on]
    return (" · ".join(parts) or "not resolved") + (f" ({', '.join(flags)})" if flags else ""), r.precision


def rows(store: Store) -> tuple[list[list], list[list], list[list]]:
    sites, categories, hazards, materials = _labels()
    typical = taxonomy()["typical_materials"]
    articles = {a["raw_ref"]: a for a in store.articles()}
    fires, other, failed = [], [], []
    for path in sorted((store.root / "extracted").glob("*/*/*.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        a = articles.get(result["raw_ref"], {})
        base = [(a.get("published_at") or "")[:10], result["outlet"], (a.get("headline", ""), result["url"])]
        if result["status"] != "ok":
            failed.append(base + [result["status"]])
            continue
        for i in result["items"]:
            if i["record_type"] != "incident" or not i["is_lebanon"]:
                kind = "abroad" if not i["is_lebanon"] and i["record_type"] == "incident" else i["record_type"]
                other.append(base + [kind, i["summary"], i["confidence"]])
                continue
            location, precision = _location(i["place_text"])
            reported = [materials[m] for m in i["materials"]]
            fires.append(base + [
                i["summary"], i["occurred_on"] or "", i["place_text"] or "", location, precision,
                categories[i["site_category"]], sites[i["site_primary"]], "; ".join(sites[s] for s in i["site_others"]),
                hazards[i["hazard_primary"]], "; ".join(hazards[h] for h in i["hazard_others"]),
                "; ".join(m["label"] for m in reported), " ".join(sorted({str(m["fire_class"]) for m in reported})),
                "; ".join(materials[m]["label"] for m in typical.get(i["site_category"], [])),
                i["origin"], i["deaths"], i["injuries"], i["smoke_inhalation"], i["buildings_burned"],
                i["vehicles_burned"], i["area_burned_m2"], i["displaced"], ", ".join(i["responders"]),
                round(i["confidence"], 2), "\n".join(f"{e['field']}: «{e['quote']}»" for e in i["evidence"]), "", "",
            ])
    key = lambda r: r[0]
    return sorted(fires, key=key, reverse=True), sorted(other, key=key, reverse=True), failed


def _sheet(wb: Workbook, title: str, header: list[tuple[str, int]], data: list[list], review_cols: int = 0) -> None:
    ws = wb.create_sheet(title)
    ws.sheet_view.showGridLines = False
    ws.append([h for h, _ in header])
    for col, (_, width) in enumerate(header, start=1):
        cell = ws.cell(row=1, column=col)
        cell.font, cell.fill, cell.alignment = Font(bold=True, color="FFFFFF"), HEADER_FILL, WRAP
        ws.column_dimensions[get_column_letter(col)].width = width
    for n, row in enumerate(data, start=1):
        headline, url = row[2]
        ws.append([n, row[0], row[1], headline, *row[3:]])
        link = ws.cell(row=n + 1, column=4)
        link.hyperlink, link.font = url, Font(color="1F5FAF", underline="single")
        for col in range(1, len(header) + 1):
            ws.cell(row=n + 1, column=col).alignment = WRAP
        for col in range(len(header) - review_cols + 1, len(header) + 1):
            ws.cell(row=n + 1, column=col).fill = REVIEW_FILL
    ws.freeze_panes = "E2"
    ws.auto_filter.ref = ws.dimensions


def write(path: Path, store: Store | None = None) -> dict:
    store = store or Store()
    fires, other, failed = rows(store)
    wb = Workbook()
    readme = wb.active
    readme.title = "Read me"
    readme.sheet_view.showGridLines = False
    counts = (f"Fires in Lebanon: {len(fires)} items. Other items (not a fire, abroad, daily totals): "
              f"{len(other)}. Not classified (refused or failed): {len(failed)}.")
    how = ("How to review: on the sheet 'Fires in Lebanon', write OK or wrong in the yellow 'YOUR VERDICT' "
           "column, and what it should be in 'YOUR CORRECTION'. The sheet 'Other items' shows what Claude "
           "set aside — say if a real Lebanese fire is hiding there.")
    words = ("Site = what kind of place burned. Location = where on the map. Hazard = what started or fed "
             "the fire. Materials = what was burning, only when the article says so.")
    typical_note = ("'Typical materials for this site' is NOT a finding: it is what such a place usually "
                    "contains, shown so you can judge whether to use it. It is never counted as reported.")
    location_note = ("Location found comes from the official place table (OCHA/CDR); 'ambiguous' means two "
                     "places share the name, 'conflict' means the article names places that do not nest.")
    classes = ("Fire classes follow NFPA 10: A ordinary solids, B flammable liquids and gases, C live "
               "electrical, D combustible metals, K cooking oil.")
    lines = [("Fire incidents in Lebanon — first classification, for review", True), ("", False),
             (counts, False), ("", False), (how, False), ("", False), (words, False),
             (typical_note, False), (location_note, False), (classes, False)]
    for text, bold in lines:
        readme.append([text])
        readme.cell(row=readme.max_row, column=1).font = Font(bold=bold, size=14 if bold else 11)
        readme.cell(row=readme.max_row, column=1).alignment = Alignment(wrap_text=True, vertical="top")
    readme.column_dimensions["A"].width = 120
    _sheet(wb, "Fires in Lebanon", COLUMNS, fires, review_cols=2)
    _sheet(wb, "Other items", [("#", 5), ("Published", 11), ("Outlet", 12), ("Headline", 60), ("Set aside as", 16),
                               ("Summary (Claude)", 60), ("Confidence", 10)], other)
    if failed:
        _sheet(wb, "Not classified", [("#", 5), ("Published", 11), ("Outlet", 12), ("Headline", 60), ("Why", 30)], failed)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return {"fires": len(fires), "other": len(other), "failed": len(failed), "path": str(path)}
