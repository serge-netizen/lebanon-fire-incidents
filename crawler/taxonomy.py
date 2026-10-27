"""The classification lists (crawler/taxonomy.yaml), read once, with the look-ups that extraction,
deduction, duplicate detection and review share.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

PATH = Path(__file__).with_name("taxonomy.yaml")
NOT_ESTABLISHED = "not_established"


@lru_cache(maxsize=1)
def lists() -> dict:
    return yaml.safe_load(PATH.read_text(encoding="utf-8"))


def _parents(section: str, child: str) -> dict[str, str]:
    """Leaf id → the id of the group it belongs to."""
    return {leaf: group for group, v in lists()[section].items() for leaf in v.get(child) or {}}


@lru_cache(maxsize=1)
def site_category() -> dict[str, str]:
    """Site sub-type → its category; `not_established` maps to itself."""
    return _parents("site_types", "subtypes") | {NOT_ESTABLISHED: NOT_ESTABLISHED}


@lru_cache(maxsize=1)
def material_group() -> dict[str, str]:
    return _parents("materials", "items")


def site_ids() -> list[str]:
    return list(site_category())


def material_ids() -> list[str]:
    return list(material_group())


def hazard_ids() -> list[str]:
    return list(lists()["hazards"])


def origin_ids() -> list[str]:
    return list(lists()["origins"])


def responder_ids() -> list[str]:
    return list(lists()["responders"])


def property_damage_ids() -> list[str]:
    return list(lists()["property_damage"])


@lru_cache(maxsize=1)
def labels() -> dict[str, dict[str, str]]:
    """Plain-English label of every id, by kind: site, category, material, hazard, origin,
    responder, property_damage, gravity."""
    t = lists()
    out: dict[str, dict[str, str]] = {"site": {}, "category": {}, "material": {}}
    for category, v in t["site_types"].items():
        out["category"][category] = v["label"]
        out["site"].update({k: s["label"] for k, s in (v.get("subtypes") or {}).items()})
    out["site"][NOT_ESTABLISHED] = t["site_types"][NOT_ESTABLISHED]["label"]
    for v in t["materials"].values():
        out["material"].update({k: m["label"] for k, m in v["items"].items()})
    out["material"][NOT_ESTABLISHED] = "Not established"
    out["hazard"] = {k: v["label"] for k, v in t["hazards"].items()}
    out["origin"] = {k: v["label"] for k, v in t["origins"].items()}
    out["responder"] = {k: v["label"] for k, v in t["responders"].items()}
    out["property_damage"] = {k: v["label"] for k, v in t["property_damage"].items()}
    out["gravity"] = {k: v["label"] for k, v in t["gravity"].items()}
    return out
