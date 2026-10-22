from crawler.bulletin import from_store, parse

# The numbers of two real bulletins (19 and 12 Oct 2026), as Civil Defense printed them.
OCT_19 = """نفذت خلال ال24 ساعة الماضية، 71 مهمة اسعاف وانقاذ توزعت كالآتي:
-اخماد حرائق: 29: كهرباء:3، منازل:4، اعشاب:8، نفايات:11، آليات متنوعة: 3.
-انقاذ:حيوانات:2
-اسعاف:22: حالات طارئة:11، نقل مرضى:3، حوادث سير:،6، نقل جثث:2
-خدمات عامة:15
-سلامة عامة:3"""
OCT_12 = """نفذت خلال ال24 ساعة الماضية، 87 مهمة اسعاف وانقاذ توزعت كالآتي:
-اخماد حرائق: 41: اشجار مثمرة:1،كهرباء:3، منازل:4، اعشاب:27، نفايات:5، آليات متنوعة: 1.
-انقاذ:1
-اسعاف:23: حالات طارئة:10، نقل مرضى:5، حوادث سير:8
-خدمات عامة:12: نقل مياه الى مراكز ايواء للنازحين:4
-سلامة عامة:10"""


def test_real_bulletins_parse_and_add_up():
    b = parse(OCT_19, "2026-10-19")
    assert b.missions_total == 71 and b.sections["fires"] == 29
    assert b.fires == {"electrical": 3, "homes": 4, "grass": 8, "rubbish": 11, "vehicles": 3}
    assert b.check == "ok"
    b = parse(OCT_12, "2026-10-12")
    assert b.fires["grass"] == 27 and b.fires["fruit_trees"] == 1 and b.sections["public_services"] == 12
    assert b.check == "ok"


def test_parts_that_do_not_add_up_are_flagged_not_fixed():
    b = parse(OCT_19.replace("كهرباء:3", "كهرباء:4"), "2026-10-19")
    assert b.fires["electrical"] == 4 and b.check == "fire types ≠ fires"


def test_an_unknown_fire_type_is_kept_and_reported():
    b = parse(OCT_19.replace("نفايات:11", "مطاعم:11"), "2026-10-19")
    assert b.fires["other"] == 11 and b.unmapped == ["مطاعم"]


def test_a_lead_only_copy_gives_the_total_and_loses_to_a_full_copy():
    lead = {"headline": "الدفاع المدني: 71 مهمة خلال ال24 ساعة الماضية", "outlet": "nna", "url": "n",
            "published_at": "2026-10-19T08:00:00+03:00", "text": "نفذت خلال ال24 ساعة الماضية، 71 مهمة اسعاف وانقاذ توزعت كالآتي: -"}
    full = dict(lead, outlet="lebanon24", url="l", text=OCT_19)
    assert from_store([lead])[0].check == "no breakdown"
    best = from_store([lead, full])
    assert len(best) == 1 and best[0].outlet == "lebanon24"
