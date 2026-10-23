import pytest

from crawler import derive
from crawler.filter import war_words

FIRE = {
    "record_type": "incident", "is_lebanon": True, "origin": "unknown",
    "site_primary": "house", "site_others": [], "material_primary": "furniture_upholstery", "material_others": [],
    "hazard_primary": "not_established", "hazard_others": [],
}


@pytest.mark.parametrize("change,expected", [
    ({}, "in_scope"),
    ({"origin": "conflict_related"}, "war_related"),
    ({"hazard_primary": "munitions_explosives"}, "war_related"),
    ({"hazard_others": ["munitions_explosives"]}, "in_scope"),  # only a possibility: flagged, not excluded
    ({"material_primary": "munitions"}, "war_related"),
    ({"hazard_primary": "fireworks"}, "in_scope"),  # celebrations are civil fires
    ({"hazard_primary": "gas"}, "in_scope"),        # so is a gas cylinder explosion
    ({"is_lebanon": False}, "abroad"),
    ({"record_type": "background"}, "background"),
])
def test_scope(change, expected):
    assert derive.scope(FIRE | change) == expected


def test_deduced_leaves_out_what_is_reported():
    d = derive.deduced(FIRE)
    assert "furniture_upholstery" not in d["materials"] and "mattresses_bedding" in d["materials"]
    assert d["hazards"][0] == "electrical_installation" and d["origin"] is None


def test_a_sub_type_entry_replaces_its_category():
    bakery = derive.deduced(FIRE | {"site_primary": "bakery", "material_primary": "not_established"})
    restaurant = derive.deduced(FIRE | {"site_primary": "restaurant", "material_primary": "not_established"})
    assert "diesel_fuel_oil" in bakery["materials"] and "cooking_oil_fat" in restaurant["materials"]


def test_nothing_is_deduced_from_an_unknown_site():
    d = derive.deduced(FIRE | {"site_primary": "not_established"})
    assert d["materials"] == [] and d["hazards"] == []


def test_origin_is_deduced_only_when_not_reported():
    assert derive.deduced(FIRE | {"hazard_primary": "electrical_installation"})["origin"] == "accidental"
    assert derive.deduced(FIRE | {"hazard_primary": "open_burning"})["origin"] is None  # fits any origin
    reported = FIRE | {"hazard_primary": "electrical_installation", "origin": "deliberate"}
    assert derive.deduced(reported)["origin"] is None


@pytest.mark.parametrize("text,found", [
    ("غارة إسرائيلية تشعل حريقاً في وادي الخنازير", True),
    ("وبالغارات المعادية احترقت الأحراج", True),
    ("العدو يشعل حرائق في الخيام", True),
    ("حريق في تبنين تزامن مع تفجير للجيش", True),
    ("Israeli shelling sets fields ablaze", True),
    ("حريق في مغارة جعيتا", False),        # a cave, not an air strike
    ("انتشار العدوى في المخيم", False),     # infection, not the enemy
    ("انفجار قارورة غاز في منزل", False),   # a civil explosion
    ("workers strike outside the port", False),
])
def test_war_words(text, found):
    assert bool(war_words(text)) is found
