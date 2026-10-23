"""What can be deduced from what an article reports (owner, 2026-10-23), and the scope check.

Claude records only what the article states. This module adds what follows from it, from fixed
look-up tables in crawler/taxonomy.yaml: what such a site usually contains, what usually starts
fires there, the origin a hazard implies. Deduced values are kept apart from reported ones,
labelled, and never counted as reported.

Scope: war-related fires are logged with every field but not displayed (owner, 2026-10-23).
"""

from __future__ import annotations

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


def _typical(table: str, site: str) -> list[str]:
    """A look-up table's entry for a site sub-type, else for its category."""
    t = tx.lists()[table]
    return t.get(site) or t.get(tx.site_category()[site]) or []


def deduced(record: dict) -> dict:
    """What the main site and the main hazard imply, leaving out what is already reported. A count
    of burned vehicles with no vehicle among what burned implies one, of a type not stated."""
    burned = {record["material_primary"], *record["material_others"]}
    hazards = {record["hazard_primary"], *record["hazard_others"]}
    materials = _typical("typical_materials", record["site_primary"])
    if record.get("vehicles_burned") and not any(tx.material_group().get(m) == "vehicles" for m in burned):
        materials = ["vehicle_other", *materials]
    origin = None
    if record["origin"] == "unknown":
        origin = next((o for o, implied_by in tx.lists()["origin_from_hazard"].items()
                       if record["hazard_primary"] in implied_by), None)
    return {
        "materials": [m for m in dict.fromkeys(materials) if m not in burned],
        "hazards": [h for h in _typical("typical_hazards", record["site_primary"]) if h not in hazards],
        "origin": origin,
    }
