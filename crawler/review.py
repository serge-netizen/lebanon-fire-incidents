"""Review (BRIEF §4.7). For now, the owner's review workbook — the task 4 feedback loop: one row
per fire (articles about the same fire share a row), what the articles report kept apart from
what is deduced, and two columns for the owner's verdict and correction. Private: it quotes the
articles, so it is written to the private store, never to this repo. Task 5 adds the review
sheet and reads decisions back.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from crawler import taxonomy as tx
from crawler.dedupe import DAMAGES, Incident, incidents, load
from crawler.derive import WAR, deduced
from crawler.geocode import Resolution
from crawler.store import Store

HEADER_FILL = PatternFill("solid", fgColor="2F3B4C")
REVIEW_FILL = PatternFill("solid", fgColor="FFF4D6")
WRAP = Alignment(wrap_text=True, vertical="top")
LINK = Font(color="1F5FAF", underline="single")
LOW_CONFIDENCE = 0.7  # below this, the brief sends a record to a second pass (BRIEF §4.4)

FIRE_COLUMNS = [  # (title, width)
    ("#", 5), ("Fire date", 12), ("Articles", 14), ("Headline (main article)", 44), ("Summary (Claude)", 44),
    ("Place as written", 24), ("Location found", 26), ("Site — main", 28), ("Site — others", 26),
    ("What burned — reported (main first)", 28), ("What burned — deduced, NOT reported", 28),
    ("Hazard — reported (main first)", 24), ("Hazard — deduced, NOT reported", 24), ("Origin", 16),
    ("Damage (reported)", 22), ("Responders", 16), ("Checks", 32), ("Confidence", 10),
    ("YOUR VERDICT (OK / wrong)", 14), ("YOUR CORRECTION", 40),
]
ARTICLE_COLUMNS = [("Fire", 6), ("Outlet", 11), ("Published", 11), ("Headline", 50), ("Summary (Claude)", 50),
                   ("Evidence: Claude's quotes from the article", 70)]
SET_ASIDE_COLUMNS = [("#", 5), ("Published", 11), ("Outlet", 11), ("Headline", 60), ("Set aside as", 14),
                     ("Summary (Claude)", 60), ("Confidence", 10)]
SET_ASIDE_AS = {"aggregate_report": "totals", "background": "background", "not_a_fire": "not a fire", "abroad": "abroad"}
DAMAGE_TEXT = {  # (one, several)
    "deaths": ("dead", "dead"), "injuries": ("injured", "injured"),
    "smoke_inhalation": ("treated for smoke", "treated for smoke"),
    "buildings_burned": ("building burned", "buildings burned"), "vehicles_burned": ("vehicle burned", "vehicles burned"),
    "area_burned_m2": ("m² burned", "m² burned"), "displaced": ("displaced", "displaced"),
}


# ---------------------------------------------------------------- cell text

def _site(code: str) -> str:
    labels = tx.labels()
    if code == tx.NOT_ESTABLISHED:
        return "not established"
    return f"{labels['site'][code]} ({labels['category'][tx.site_category()[code]]})"


def _reported(record: dict, kind: str, label_kind: str) -> str:
    codes = [c for c in (record[f"{kind}_primary"], *record[f"{kind}_others"]) if c != tx.NOT_ESTABLISHED]
    return "; ".join(tx.labels()[label_kind][c] for c in codes) or "not established"


def _location(r: Resolution) -> str:
    parts = [u["name_en"] for u in (r.admin3, r.admin2, r.admin1) if u]
    return f"{' · '.join(parts)} ({r.precision})" if parts else "not found"


def _origin(record: dict, implied: str | None) -> str:
    labels = tx.labels()["origin"]
    if record["origin"] != "unknown" or not implied:
        return labels[record["origin"]]
    return f"{labels[implied]} (deduced from the hazard)"


def _damage(record: dict) -> str:
    parts = [f"{record[k]:,.0f} {DAMAGE_TEXT[k][record[k] != 1]}" for k in DAMAGES if record[k] is not None]
    return "; ".join(parts) or "none stated"


def _outlets(i: Incident) -> str:
    return ", ".join(f"{o} ×{n}" if n > 1 else o for o, n in Counter(r.outlet for r in i.reports).items())


def fire_row(n: int, i: Incident) -> list:
    rec, d, main = i.record, deduced(i.record), i.reports[0]
    labels = tx.labels()
    checks = [*i.flags] + ([f"confidence below {LOW_CONFIDENCE}"] if rec["confidence"] < LOW_CONFIDENCE else [])
    return [
        n, i.date.isoformat() + (" (publication date)" if i.date_deduced else ""), _outlets(i),
        (main.headline, main.url), rec["summary"], rec["place_text"] or "", _location(main.place),
        _site(rec["site_primary"]), "; ".join(_site(s) for s in rec["site_others"]),
        _reported(rec, "material", "material"), "; ".join(labels["material"][m] for m in d["materials"]),
        _reported(rec, "hazard", "hazard"), "; ".join(labels["hazard"][h] for h in d["hazards"]),
        _origin(rec, d["origin"]), _damage(rec), ", ".join(rec["responders"]), "\n".join(checks),
        round(rec["confidence"], 2), "", "",
    ]


# ---------------------------------------------------------------- the workbook

def _sheet(wb: Workbook, title: str, header: list[tuple[str, int]], rows: list[list], review_cols: int = 0) -> None:
    ws = wb.create_sheet(title)
    ws.sheet_view.showGridLines = False
    ws.append([h for h, _ in header])
    for col, (_, width) in enumerate(header, start=1):
        cell = ws.cell(row=1, column=col)
        cell.font, cell.fill, cell.alignment = Font(bold=True, color="FFFFFF"), HEADER_FILL, WRAP
        ws.column_dimensions[get_column_letter(col)].width = width
    for r, row in enumerate(rows, start=2):
        ws.append([v[0] if isinstance(v, tuple) else v for v in row])
        for col, v in enumerate(row, start=1):
            cell = ws.cell(row=r, column=col)
            cell.alignment = WRAP
            if isinstance(v, tuple):  # (text, url)
                cell.hyperlink, cell.font = v[1], LINK
            if col > len(header) - review_cols:
                cell.fill = REVIEW_FILL
    ws.freeze_panes = "E2"
    ws.auto_filter.ref = ws.dimensions


def _evidence(item: dict) -> str:
    return "\n".join(f"{e['field']}: «{e['quote']}»" for e in item["evidence"])


def write(path: Path, store: Store | None = None) -> dict:
    batch = load(store or Store())
    fires = incidents(batch.reports)
    in_scope = [i for i in fires if i.scope != WAR]
    war = [i for i in fires if i.scope == WAR]
    articles = []
    for prefix, group in (("F", in_scope), ("W", war)):
        for n, i in enumerate(group, start=1):
            articles += [[f"{prefix}{n}", r.outlet, r.published.isoformat(), (r.headline, r.url), r.item["summary"],
                          _evidence(r.item)] for r in i.reports]
    set_aside = sorted(([(x["article"].get("published_at") or "")[:10], x["article"]["outlet"],
                         (x["article"]["headline"], x["article"]["url"]), SET_ASIDE_AS.get(x["scope"], x["scope"]),
                         x["item"]["summary"], round(x["item"]["confidence"], 2)] for x in batch.set_aside),
                       key=lambda row: row[0], reverse=True)
    failed = [[(a["article"].get("published_at") or "")[:10], a["article"]["outlet"],
               (a["article"]["headline"], a["article"]["url"]), a["status"]] for a in batch.failed]

    wb = Workbook()
    readme = wb.active
    readme.title = "Read me"
    readme.sheet_view.showGridLines = False
    merged = len(batch.reports) - len(fires)
    lines = [
        ("Fire incidents in Lebanon — second classification, for review", True),
        ("", False),
        ((f"{len(batch.reports)} reports of fires in Lebanon became {len(fires)} fires once articles about the same fire "
         f"were merged ({merged} merged). {len(in_scope)} are on 'Fires in Lebanon'; {len(war)} war-related fires are "
         f"logged on their own sheet and will not be shown. Set aside: {len(set_aside)} (not a fire, abroad, background, "
         f"totals). Not classified: {len(failed)}."), False),
        ("", False),
        (("How to review: one row per fire. Write OK or wrong in the yellow 'YOUR VERDICT' column and what it should be "
         "in 'YOUR CORRECTION'. The sheet 'Articles' lists every article behind each fire (F3 = row 3 of 'Fires in "
         "Lebanon', W2 = row 2 of 'War-related') with the quotes Claude based its answer on. 'Set aside' shows what "
         "Claude did not count — say if a real Lebanese fire is hiding there."), False),
        ("", False),
        (("Each row answers separate questions. WHERE: the place as written, and the place found in the official table "
         "(OCHA/CDR). SITE: the facility or place that witnessed the fire (a school, a house, a road, a forest). WHAT "
         "BURNED: the objects and materials. HAZARD: what started or fed the fire. ORIGIN: accident, deliberate, war or "
         "unknown. DAMAGE: as reported."), False),
        (("REPORTED means Claude read it in the article. DEDUCED means the computer looked it up in a fixed table — what "
         "such a site usually contains, what usually starts fires there, the origin a hazard implies, the publication "
         "date when the article gives no fire date. Deduced values are labelled and never counted as reported."), False),
        (("War-related fires (strikes, shelling, munitions, fires set by an army) are kept but not shown. Claude marks "
         "them; a second check puts 'war words in the article' in 'Checks' for any other fire whose article uses them."),
         False),
        (("Same fire: two articles are merged when their places match (same village, or a village inside the same "
         "district), their dates are at most two days apart, and their sites agree. 'Articles' says how many and from "
         "which outlets."), False),
    ]
    if batch.stale:
        lines.append((f"{batch.stale} classifications made with older instructions are not shown.", False))
    for text, bold in lines:
        readme.append([text])
        cell = readme.cell(row=readme.max_row, column=1)
        cell.font, cell.alignment = Font(bold=bold, size=14 if bold else 11), WRAP
    readme.column_dimensions["A"].width = 120
    _sheet(wb, "Fires in Lebanon", FIRE_COLUMNS, [fire_row(n, i) for n, i in enumerate(in_scope, start=1)], review_cols=2)
    _sheet(wb, "War-related (not shown)", FIRE_COLUMNS, [fire_row(n, i) for n, i in enumerate(war, start=1)], review_cols=2)
    _sheet(wb, "Articles", ARTICLE_COLUMNS, articles)
    _sheet(wb, "Set aside", SET_ASIDE_COLUMNS, [[n, *row] for n, row in enumerate(set_aside, start=1)])
    if failed:
        _sheet(wb, "Not classified", [("#", 5), ("Published", 11), ("Outlet", 11), ("Headline", 60), ("Why", 30)],
               [[n, *row] for n, row in enumerate(failed, start=1)])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return {"reports": len(batch.reports), "fires": len(in_scope), "war_related": len(war), "merged": merged,
            "set_aside": len(set_aside), "failed": len(failed), "stale": batch.stale, "path": str(path)}
