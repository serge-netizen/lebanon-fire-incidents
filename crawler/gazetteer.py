"""Build and load the offline gazetteer (BRIEF §4.6, task 2).

Source: OCHA / Council for Development and Reconstruction (CDR) common operational dataset of
administrative boundaries for Lebanon (COD-AB), published on HDX as `cod-ab-lbn`, licence
CC BY-IGO. We use its tabular file only: names (English and Arabic), P-codes and the centre
point of every unit. No boundary shapes are stored here.

`build()` needs the optional `gazetteer` dependencies (pandas, openpyxl) and is run by hand when
OCHA publishes a new version. Everything else reads the committed parquet with pyarrow.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from crawler import config

SOURCE_DATASET = "cod-ab-lbn"
SOURCE_URL = (
    "https://data.humdata.org/dataset/569beba7-bad7-4951-a19d-468a035461cd/resource/"
    "83dae3aa-1047-4019-9ca2-a5709810ad21/download/lbn_admin_boundaries.xlsx"
)
PARQUET_PATH = config.GAZETTEER_DIR / "lebanon.parquet"
# Governorates created after OCHA's table, applied over it at load time (the parquet stays OCHA's).
GOVERNORATES_PATH = config.GAZETTEER_DIR / "governorates.csv"

# OCHA marks disputed boundary strips between cadastral areas as "Litige" (French: dispute).
# They are polygons, not places: kept in the table, never matched by name.
NOT_A_PLACE = {"Litige"}

SCHEMA = pa.schema([
    ("level", pa.int8()),          # 1 governorate, 2 district (caza), 3 cadastral area
    ("pcode", pa.string()),
    ("name_en", pa.string()),
    ("name_ar", pa.string()),
    ("adm1_pcode", pa.string()),
    ("adm2_pcode", pa.string()),   # null for level 1
    ("lat", pa.float64()),         # centre point published by OCHA, not a measured location
    ("lon", pa.float64()),
    ("area_sqkm", pa.float64()),
    ("is_place", pa.bool_()),
])


@dataclass(frozen=True)
class Unit:
    level: int
    pcode: str
    name_en: str
    name_ar: str | None
    adm1_pcode: str
    adm2_pcode: str | None
    lat: float
    lon: float
    area_sqkm: float
    is_place: bool
    ocha_adm1_pcode: str | None = None  # the governorate in OCHA's own table; None for one OCHA lacks


def build(xlsx: Path | None = None, out: Path = PARQUET_PATH) -> dict:
    """Download (or read) the OCHA spreadsheet and write the gazetteer parquet. Returns a summary."""
    import pandas as pd  # optional dependency group "gazetteer"

    raw = xlsx.read_bytes() if xlsx else httpx.get(
        SOURCE_URL, headers={"User-Agent": config.USER_AGENT}, timeout=120, follow_redirects=True
    ).raise_for_status().content
    sha256 = hashlib.sha256(raw).hexdigest()
    book = io.BytesIO(raw)

    rows: list[dict] = []
    a1 = pd.read_excel(book, "lbn_admin1")
    for r in a1.itertuples():
        rows.append(_row(1, r.adm1_pcode, r.adm1_name, r.adm1_name1, r.adm1_pcode, None, r))
    a2 = pd.read_excel(book, "lbn_admin2")
    for r in a2.itertuples():
        rows.append(_row(2, r.adm2_pcode, r.adm2_name, r.adm2_name1, r.adm1_pcode, r.adm2_pcode, r))
    a3 = pd.read_excel(book, "lbn_admin3")
    conflict_rows = 0
    for r in a3.itertuples():
        if str(r.adm3_pcode) == "0":  # areas OCHA labels "Conflict": no name, no P-code
            conflict_rows += 1
            continue
        rows.append(_row(3, r.adm3_pcode, r.adm3_name, r.adm3_name1, r.adm1_pcode, r.adm2_pcode, r))

    table = pa.Table.from_pylist(rows, schema=SCHEMA)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out)
    levels = {lvl: sum(1 for x in rows if x["level"] == lvl) for lvl in (1, 2, 3)}
    return {
        "sha256": sha256,
        "rows": len(rows),
        "levels": levels,
        "not_places": sum(1 for x in rows if not x["is_place"]),
        "conflict_rows_dropped": conflict_rows,
        "version": str(a3.version.iloc[0]),
        "valid_on": str(a3.valid_on.iloc[0])[:10],
    }


def _row(level, pcode, name_en, name_ar, adm1, adm2, r) -> dict:
    name_en = str(name_en).strip()
    name_ar = str(name_ar).strip() if isinstance(name_ar, str) and name_ar.strip() else None
    return {
        "level": level,
        "pcode": str(pcode),
        "name_en": name_en,
        "name_ar": name_ar,
        "adm1_pcode": str(adm1),
        "adm2_pcode": None if adm2 is None else str(adm2),
        "lat": round(float(r.center_lat), 5),
        "lon": round(float(r.center_lon), 5),
        "area_sqkm": round(float(r.area_sqkm), 3),
        "is_place": name_en not in NOT_A_PLACE,
    }


@lru_cache(maxsize=1)
def units() -> dict[str, Unit]:
    """Every unit, keyed by P-code: OCHA's table with today's governorates applied over it."""
    table = pq.read_table(PARQUET_PATH)
    u = {r["pcode"]: Unit(**r, ocha_adm1_pcode=r["adm1_pcode"]) for r in table.to_pylist()}
    with GOVERNORATES_PATH.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            _apply_governorate(u, row)
    return u


def _apply_governorate(u: dict[str, Unit], row: dict) -> None:
    """Move whole districts into a governorate OCHA does not have, and re-centre the one they left.

    Centre points of the new and the shrunk governorate are computed, not published by OCHA: the
    area-weighted mean of their districts' centre points.
    """
    districts = row["districts"].split("|")
    left = {u[d].adm1_pcode for d in districts}
    members = [u[d] for d in districts]
    u[row["pcode"]] = Unit(
        level=1, pcode=row["pcode"], name_en=row["name_en"], name_ar=row["name_ar"],
        adm1_pcode=row["pcode"], adm2_pcode=None, lat=_centre(members, "lat"), lon=_centre(members, "lon"),
        area_sqkm=round(sum(m.area_sqkm for m in members), 3), is_place=True, ocha_adm1_pcode=None,
    )
    for code, unit in list(u.items()):
        if unit.adm2_pcode in districts:  # the districts themselves and every cadastral area in them
            u[code] = replace(unit, adm1_pcode=row["pcode"])
    for gov in left:
        rest = [x for x in u.values() if x.level == 2 and x.adm1_pcode == gov]
        u[gov] = replace(u[gov], lat=_centre(rest, "lat"), lon=_centre(rest, "lon"),
                         area_sqkm=round(sum(x.area_sqkm for x in rest), 3))


def _centre(units_: list[Unit], axis: str) -> float:
    total = sum(x.area_sqkm for x in units_)
    return round(sum(getattr(x, axis) * x.area_sqkm for x in units_) / total, 5)
