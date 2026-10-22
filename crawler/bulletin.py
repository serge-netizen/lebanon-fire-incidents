"""The Civil Defense daily bulletin → one row of numbers per day (BRIEF §7, amendment 7).

The bulletin is published most mornings by NNA and republished in full by other outlets:

    نفذت خلال ال24 ساعة الماضية، 71 مهمة اسعاف وانقاذ توزعت كالآتي:
    -اخماد حرائق: 29: كهرباء:3، منازل:4، اعشاب:8، نفايات:11، آليات متنوعة: 3.
    -انقاذ:حيوانات:2
    -اسعاف:22: حالات طارئة:11، نقل مرضى:3، حوادث سير:،6، نقل جثث:2

Its format is fixed, so a parser reads it: no language model, no cost. Each row covers the
24 hours before publication. Parts that do not add up are flagged, never corrected.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from crawler import config
from crawler.filter import census_kind, fold

MAPPING_PATH = config.OFFICIAL_DIR / "mapping" / "civil_defense_bulletin.yaml"
CSV_PATH = config.OFFICIAL_DIR / "daily_tallies.csv"
FIRE_COLUMNS = ("electrical", "homes", "grass", "forest", "trees", "fruit_trees", "farmland", "rubbish",
                "vehicles", "shops", "businesses", "factories", "warehouses", "generators", "other")
SECTIONS = ("fires", "rescue", "ambulance", "public_services", "public_safety")
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


@lru_cache(maxsize=1)
def _mapping() -> tuple[dict[str, str], dict[str, str]]:
    raw = yaml.safe_load(MAPPING_PATH.read_text(encoding="utf-8"))
    return ({fold(k): v for k, v in raw["sections"].items()}, {fold(k): v for k, v in raw["fire_types"].items()})


@dataclass
class Bulletin:
    published_on: str
    missions_total: int | None = None
    sections: dict[str, int] = field(default_factory=dict)
    fires: dict[str, int] = field(default_factory=dict)
    unmapped: list[str] = field(default_factory=list)
    outlet: str = ""
    url: str = ""

    @property
    def check(self) -> str:
        """'ok' when the parts add up, 'no breakdown' when only the total was published."""
        if not self.sections:
            return "no breakdown"
        problems = []
        if self.missions_total is not None and sum(self.sections.values()) != self.missions_total:
            problems.append("sections ≠ total")
        if self.fires and "fires" in self.sections and sum(self.fires.values()) != self.sections["fires"]:
            problems.append("fire types ≠ fires")
        return "; ".join(problems) or "ok"


def parse(text: str, published_on: str, outlet: str = "", url: str = "") -> Bulletin | None:
    t = fold(text).translate(DIGITS)
    total = re.search(r"(\d+)\s*مهم", t)
    if not total:
        return None
    b = Bulletin(published_on, int(total.group(1)), outlet=outlet, url=url)
    section_names, fire_names = _mapping()
    for line in re.findall(r"^\s*-\s*(.+)$", t, flags=re.MULTILINE):
        name, _, rest = line.partition(":")
        key = section_names.get(name.strip())
        if not key:
            continue
        head = re.match(r"\s*(\d+)\s*(?::|$)", rest)
        parts = [(n.strip(" ،,."), int(v)) for n, v in re.findall(r"([^\d:،,.]+?)\s*:\s*،?\s*(\d+)", rest)]
        b.sections[key] = int(head.group(1)) if head else sum(v for _, v in parts)
        if key == "fires":
            for n, v in parts:
                column = fire_names.get(n)
                if not column:
                    b.unmapped.append(n)
                    column = "other"
                b.fires[column] = b.fires.get(column, 0) + v
    return b


def from_store(articles) -> list[Bulletin]:
    """Every bulletin in the private store; one per day, the most complete copy kept."""
    best: dict[str, Bulletin] = {}
    for a in articles:
        if census_kind(a.get("headline", "")) != "tally":
            continue
        day = (a.get("published_at") or a["fetched_at"])[:10]
        b = parse(a["text"], day, a["outlet"], a["url"])
        if not b:
            continue
        rank = (b.check == "ok", bool(b.sections), b.missions_total is not None)
        if day not in best or rank > (best[day].check == "ok", bool(best[day].sections), best[day].missions_total is not None):
            best[day] = b
    return [best[d] for d in sorted(best)]


def write_csv(bulletins: list[Bulletin], path: Path = CSV_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = (["published_on", "missions_total"] + [s for s in SECTIONS] + [f"fires_{c}" for c in FIRE_COLUMNS]
               + ["check", "outlet", "source_url"])
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for b in bulletins:
            w.writerow([b.published_on, b.missions_total] + [b.sections.get(s) for s in SECTIONS]
                       + [b.fires.get(c) if b.fires else None for c in FIRE_COLUMNS] + [b.check, b.outlet, b.url])
