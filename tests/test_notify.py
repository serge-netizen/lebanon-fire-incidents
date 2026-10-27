import datetime as dt
import json
from typing import ClassVar

import pytest

from crawler import dedupe, notify
from crawler.dedupe import Report
from crawler.extract import PROMPT_VERSION
from crawler.geocode import Resolution
from crawler.store import Store

ITEM = {
    "record_type": "incident", "is_lebanon": True, "summary": "A fire at a dump.", "occurred_on": None,
    "date_precision": "unknown", "place_text": "صيدا", "site_primary": "dump", "site_others": [],
    "material_primary": "household_rubbish", "material_others": [], "hazard_primary": "not_established",
    "hazard_others": [], "origin": "unknown", "deaths": None, "injuries": 1, "smoke_inhalation": None,
    "buildings_burned": None, "vehicles_burned": None, "area_burned_m2": None, "displaced": None,
    "responders": ["civil_defense"], "evidence": [], "confidence": 0.9,
}


def report(ref: str, day: int, **item) -> Report:
    date = dt.date(2026, 10, day)
    saida = Resolution("district", admin1={"pcode": "LB6", "name_en": "South"}, admin2={"pcode": "LB61", "name_en": "Saida"})
    return Report(ITEM | item, f"raw/{ref}.json", "nna", f"https://x.test/{ref}", f"headline {ref}", date, date, True,
                  saida, "in_scope")


def test_a_fire_keeps_its_number():
    a, b = report("a", day=5), report("b", day=6, site_primary="house", place_text="y")
    registry: dict = {}
    first = dedupe.incidents([a, b])
    assert sorted(notify.number(registry, first)) == [1, 2]
    joined = dedupe.incidents([a, b, report("c", day=6, site_primary="house", place_text="y")])  # a new article
    numbers = dict(zip((i.reports[0].raw_ref for i in joined), notify.number(registry, joined), strict=True))
    assert numbers["raw/a.json"] == 1 and set(numbers.values()) == {1, 2} and registry["next"] == 3


def _store(tmp_path, items_by_key: dict[str, list[dict]], published: str = "2026-10-26") -> Store:
    for key, items in items_by_key.items():
        for top in ("raw", "extracted"):
            (tmp_path / top / "nna" / "2026-10").mkdir(parents=True, exist_ok=True)
        article = {"url": f"https://x.test/{key}", "outlet": "nna", "headline": f"حريق {key}",
                   "published_at": f"{published}T12:00:00+03:00", "text": "نص"}
        (tmp_path / f"raw/nna/2026-10/{key}.json").write_text(json.dumps(article, ensure_ascii=False), encoding="utf-8")
        result = {"raw_ref": f"raw/nna/2026-10/{key}.json", "prompt_version": PROMPT_VERSION, "status": "ok",
                  "items": items}
        (tmp_path / f"extracted/nna/2026-10/{key}.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return Store(tmp_path)


class FakeSMTP:
    sent: ClassVar[list] = []

    def __init__(self, host, port, timeout):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        assert (user, password) == ("sender@x.test", "app-password")

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def test_one_email_per_new_fire_in_scope_and_only_once(tmp_path, monkeypatch):
    store = _store(tmp_path, {"dump": [ITEM], "war": [ITEM | {"place_text": "الخيام", "origin": "conflict_related"}]})
    today = dt.date(2026, 10, 27)
    for k in ("MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_TO"):
        monkeypatch.delenv(k, raising=False)
    assert notify.run(store, today) == {"fires": 2, "due": 1, "sent": 0, "mail": "not configured: nothing sent"}
    assert (tmp_path / "state" / "fires.json").exists() and not (tmp_path / "state" / "notified.txt").exists()

    monkeypatch.setenv("MAIL_USERNAME", "sender@x.test")
    monkeypatch.setenv("MAIL_PASSWORD", "app-password")
    monkeypatch.setenv("MAIL_TO", "review@x.test")
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", FakeSMTP)
    FakeSMTP.sent = []
    assert notify.run(store, today)["sent"] == 1  # the war-related fire is logged, not e-mailed
    [msg] = FakeSMTP.sent
    assert msg["To"] == "review@x.test" and msg["Subject"].startswith("New fire F-") and "Dump or landfill" in msg["Subject"]
    html_part = msg.get_body(("html",)).get_content()
    assert "Reply OK" in html_part and "1 injured" in html_part and "— reported" in html_part
    assert notify.run(store, today)["due"] == 0 and len(FakeSMTP.sent) == 1  # never twice
    assert notify.run(store, today + dt.timedelta(days=30))["due"] == 0


@pytest.mark.parametrize("days_ago,due", [(0, 1), (6, 1), (7, 0), (200, 0)])
def test_history_is_not_emailed(tmp_path, monkeypatch, days_ago, due):
    for k in ("MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_TO"):
        monkeypatch.delenv(k, raising=False)
    store = _store(tmp_path, {"dump": [ITEM]})
    assert notify.run(store, dt.date(2026, 10, 26) + dt.timedelta(days=days_ago))["due"] == due
