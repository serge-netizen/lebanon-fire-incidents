"""What can be deduced from what an article reports (owner, 2026-10-23 and 2026-10-27), and the
scope check.

Claude records only what the article states. A question it leaves open is answered here when
what it did report allows, with the fixed tables in crawler/taxonomy.yaml — always from a
reported MAIN value, never from another deduction — and labelled with what it was deduced from.
The gravity of the damage is always deduced: the brief's severity scale applied to the damage.

Scope: war-related fires are logged with every field but not displayed (owner, 2026-10-23).
"""

from __future__ import annotations

from dataclasses import dataclass

from crawler import taxonomy as tx

IN_SCOPE = "in_scope"
WAR = "war_related"
ABROAD = "abroad"


def scope(item: dict) -> str:
    """in_scope, war_related, abroad, or the record type of anything that is not an incident."""
    if item["record_type"] != "incident":
        return item["record_type"]
    if not item["is_lebanon"]:
        return ABROAD
    burned = [item["material_primary"], *item["material_others"]]
    if item["origin"] == "conflict_related" or item["hazard_primary"] == "munitions_explosives" or "munitions" in burned:
        return WAR
    return IN_SCOPE  # munitions among the other hazards is only a possibility: flagged by dedupe.merge


@dataclass(frozen=True)
class Deduced:
    values: list[str]  # ids: site sub-types or categories, materials, hazards, an origin
    basis: str         # what they were deduced from, in words


def _open(record: dict, kind: str) -> bool:
    """The article states nothing for this question: no main value and no other one."""
    return record[f"{kind}_primary"] == tx.NOT_ESTABLISHED and not record[f"{kind}_others"]


def _typical(table: str, site: str) -> list[str]:
    """A look-up table's entry for a site sub-type, else for its category."""
    t = tx.lists()[table]
    return t.get(site) or t.get(tx.site_category()[site]) or []


def site_label(code: str) -> str:
    labels = tx.labels()
    return labels["site"].get(code) or labels["category"][code]


def site(record: dict) -> Deduced | None:
    if not _open(record, "site"):
        return None
    category = tx.lists()["site_from_material"].get(record["material_primary"])
    if category:
        return Deduced([category], f"from what burned ({tx.labels()['material'][record['material_primary']]})")
    return None


def materials(record: dict) -> Deduced | None:
    if not _open(record, "material"):
        return None
    if record.get("vehicles_burned"):
        return Deduced(["vehicle_other"], "from the damage (vehicles burned)")
    implied = tx.lists()["material_from_hazard"].get(record["hazard_primary"])
    if implied:
        return Deduced([implied], f"from the hazard ({tx.labels()['hazard'][record['hazard_primary']]})")
    typical = _typical("typical_materials", record["site_primary"])
    return Deduced(typical, f"from the site: usual at “{site_label(record['site_primary'])}”") if typical else None


def hazards(record: dict) -> Deduced | None:
    if not _open(record, "hazard"):
        return None
    implied = tx.lists()["hazard_from_material"].get(record["material_primary"])
    if implied:
        return Deduced([implied], f"from what burned ({tx.labels()['material'][record['material_primary']]})")
    typical = _typical("typical_hazards", record["site_primary"])
    return Deduced(typical, f"from the site: usual at “{site_label(record['site_primary'])}”") if typical else None


def origin(record: dict) -> Deduced | None:
    if record["origin"] != "unknown":
        return None
    implied = next((o for o, hazards_ in tx.lists()["origin_from_hazard"].items()
                    if record["hazard_primary"] in hazards_), None)
    if implied:
        return Deduced([implied], f"from the hazard ({tx.labels()['hazard'][record['hazard_primary']]})")
    return None


def gravity(record: dict) -> int | None:
    """The brief's severity scale (taxonomy `gravity`): the highest level the damage reaches."""
    def n(field: str) -> float:
        return record.get(field) or 0

    if n("deaths") > 0 or n("buildings_burned") >= 2:
        return 4
    if n("injuries") > 0 or n("smoke_inhalation") > 0 or n("displaced") > 0:
        return 3
    if (record.get("property_damage") == "damaged" or n("buildings_burned") == 1 or n("vehicles_burned") > 0
            or n("area_burned_m2") > 0):
        return 2
    return 1 if record.get("property_damage") == "none" else None
