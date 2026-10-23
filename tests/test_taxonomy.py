from crawler import taxonomy as tx
from crawler.dedupe import OUTDOOR

ENTRY_KEYS = {"label", "nfirs", "cues", "rule", "fire_class", "note", "definition"}


def test_inline_entries_have_no_stray_keys():
    # In YAML's inline {…} form a comma ends a value: an unquoted "Hotel, guesthouse or…" label
    # becomes "Hotel" plus a stray key. Draft 0.2 lost half its labels that way.
    t = tx.lists()
    for section, child in (("site_types", "subtypes"), ("materials", "items")):
        for group in t[section].values():
            for key, entry in (group.get(child) or {}).items():
                assert set(entry) <= ENTRY_KEYS, (key, set(entry) - ENTRY_KEYS)
                assert entry["label"].strip(), key


def test_ids_are_unique_within_each_list():
    t = tx.lists()
    sites = [k for g in t["site_types"].values() for k in g.get("subtypes") or {}]
    materials = [k for g in t["materials"].values() for k in g["items"]]
    assert len(sites) == len(set(sites)) and len(materials) == len(set(materials))
    assert not set(sites) & set(t["site_types"])  # a sub-type never shares its name with a category


def test_lookup_tables_use_known_ids():
    t = tx.lists()
    sites, categories = set(tx.site_ids()), set(t["site_types"])
    for table, known in (("typical_materials", set(tx.material_ids())), ("typical_hazards", set(tx.hazard_ids()))):
        for key, values in t[table].items():
            assert key in sites | categories, (table, key)
            assert set(values) <= known, (table, key, set(values) - known)
    for origin, hazards in t["origin_from_hazard"].items():
        assert origin in tx.origin_ids() and set(hazards) <= set(tx.hazard_ids())
    assert OUTDOOR <= categories


def test_every_id_has_a_label():
    labels = tx.labels()
    assert set(tx.site_ids()) <= set(labels["site"]) and set(tx.material_ids()) <= set(labels["material"])
    assert labels["material"]["plastics_nylon"] == "Plastics and nylon"
    assert labels["site"]["hotel"] == "Hotel, guesthouse or furnished apartments"
