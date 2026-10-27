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


def test_nothing_is_deduced_when_the_article_answers():
    assert derive.materials(FIRE) is None and derive.site(FIRE) is None
    assert derive.hazards(FIRE | {"hazard_others": ["gas"]}) is None  # a possible cause is an answer too


def test_what_burned_from_the_damage_then_the_hazard_then_the_site():
    unknown = FIRE | {"material_primary": "not_established"}
    assert derive.materials(unknown | {"vehicles_burned": 1}).values == ["vehicle_other"]
    gas = derive.materials(unknown | {"hazard_primary": "gas"})
    assert gas.values == ["lpg_cylinders"] and gas.basis == "from the hazard (Gas)"
    house = derive.materials(unknown)
    assert "mattresses_bedding" in house.values and house.basis == "from the site: usual at “House or villa”"
    # a sub-type's entry replaces its category's
    assert "diesel_fuel_oil" in derive.materials(unknown | {"site_primary": "bakery"}).values
    assert "cooking_oil_fat" in derive.materials(unknown | {"site_primary": "restaurant"}).values
    assert derive.materials(unknown | {"site_primary": "not_established"}) is None


def test_hazard_from_what_burned_then_the_site():
    assert derive.hazards(FIRE | {"material_primary": "cooking_oil_fat"}).values == ["cooking"]
    assert derive.hazards(FIRE).values[0] == "electrical_installation"  # usual in a house


def test_site_from_what_burned():
    grass = FIRE | {"site_primary": "not_established", "material_primary": "dry_grass_weeds"}
    assert derive.site(grass).values == ["natural_areas"] and derive.site_label("natural_areas") == "Natural areas"
    assert derive.site(FIRE | {"site_primary": "not_established", "material_primary": "car"}) is None


def test_origin_from_a_reported_hazard_only():
    assert derive.origin(FIRE | {"hazard_primary": "electrical_installation"}).values == ["accidental"]
    assert derive.origin(FIRE | {"hazard_primary": "open_burning"}) is None  # fits any origin
    assert derive.origin(FIRE | {"hazard_primary": "electrical_installation", "origin": "deliberate"}) is None


@pytest.mark.parametrize("damage,level", [
    ({"deaths": 1}, 4), ({"buildings_burned": 2}, 4), ({"injuries": 2}, 3), ({"smoke_inhalation": 1}, 3),
    ({"buildings_burned": 1}, 2), ({"area_burned_m2": 5000.0}, 2), ({"property_damage": "damaged"}, 2),
    ({"property_damage": "none"}, 1), ({"deaths": 0, "injuries": 0}, None), ({}, None),
])
def test_gravity_of_the_damage(damage, level):
    assert derive.gravity(damage) == level


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
