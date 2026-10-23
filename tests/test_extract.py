import json
from types import SimpleNamespace

import anthropic

from crawler import extract
from crawler import taxonomy as tx
from crawler.store import Store

ITEM = {
    "record_type": "incident", "is_lebanon": True, "summary": "Fire in a scrap yard in Toul.",
    "occurred_on": "2026-09-28", "date_precision": "day", "place_text": "تول - قضاء النبطية",
    "site_primary": "scrap_yard", "site_others": ["scrap_yard", "warehouse", "house", "road", "parking", "forest"],
    "material_primary": "scrap", "material_others": ["scrap", "rubber_tyres", "rubber_tyres", "not_established"],
    "hazard_primary": "not_established", "hazard_others": ["not_established"],
    "origin": "unknown", "deaths": 0, "injuries": 0, "smoke_inhalation": None, "buildings_burned": None,
    "vehicles_burned": None, "area_burned_m2": -5, "displaced": None, "responders": ["civil_defense"],
    "evidence": [{"field": "place_text", "quote": "في تول"}], "confidence": 1.4,
}
ARTICLE = {"raw_ref": "raw/nna/2026-09/abc.json", "url": "https://x.test/1", "outlet": "nna",
           "headline": "إخماد حريق في بورة للخردة في تول", "published_at": "2026-09-28T12:00:00+03:00",
           "text": "إخماد حريق في بورة للخردة والكسر في تول - قضاء النبطية"}


class FakeMessages:
    def __init__(self, stop_reason="end_turn", error=None):
        self.stop_reason, self.error, self.calls = stop_reason, error, 0

    def create(self, **kw):
        self.calls += 1
        if self.error:
            raise self.error
        assert "temperature" not in kw  # Haiku 5.5 refuses sampling parameters
        content = [SimpleNamespace(type="thinking", thinking=""),
                   SimpleNamespace(type="text", text=json.dumps({"items": [dict(ITEM)]}))]
        return SimpleNamespace(stop_reason=self.stop_reason, content=content, _request_id="req_1",
                               usage=SimpleNamespace(input_tokens=3000, output_tokens=700))


def fake_client(**kw):
    return SimpleNamespace(messages=FakeMessages(**kw))


def test_schema_and_prompt_cover_every_id():
    s = extract.schema()["properties"]["items"]["items"]
    assert s["required"] == list(s["properties"])
    prompt = extract.system_prompt()
    assert "{" not in prompt  # every placeholder filled
    for site in tx.site_ids():
        assert site in s["properties"]["site_primary"]["enum"] and f"{site}:" in prompt
    for m in tx.material_ids():
        assert m in s["properties"]["material_others"]["items"]["enum"] and f"  {m}:" in prompt
    assert tx.NOT_ESTABLISHED in s["properties"]["material_primary"]["enum"]
    for h in tx.hazard_ids() + tx.origin_ids():
        assert f"{h}:" in prompt


def test_free_first_check():
    assert extract.is_candidate(ARTICLE)
    assert not extract.is_candidate(dict(ARTICLE, headline="الدفاع المدني: 92 مهمة خلال ال24 ساعة الماضية"))
    assert not extract.is_candidate(dict(ARTICLE, headline="زيارة رسمية", text="لقاء في السراي"))


def test_answer_is_cleaned():
    item = extract.clean_item(dict(ITEM))
    assert item["site_others"] == ["warehouse", "house", "road", "parking"]  # main tag dropped, four kept
    assert item["material_others"] == ["rubber_tyres"] and item["hazard_others"] == []
    assert item["area_burned_m2"] is None and item["confidence"] == 1.0


def test_thinking_block_first_and_refusal_kept_for_review():
    ok = extract.extract_one(fake_client(), ARTICLE)
    assert ok["status"] == "ok" and ok["items"][0]["site_primary"] == "scrap_yard"
    refused = extract.extract_one(fake_client(stop_reason="refusal"), ARTICLE)
    assert refused["status"] == "refusal" and refused["items"] == []


def test_network_failure_is_recorded_not_raised():
    error = anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
    assert extract.extract_one(fake_client(error=error), ARTICLE)["status"] == "network error"


def test_run_saves_results_and_skips_them_next_time(tmp_path):
    store = Store(tmp_path)
    (tmp_path / "raw" / "nna" / "2026-09").mkdir(parents=True)
    (tmp_path / "raw" / "nna" / "2026-09" / "abc.json").write_text(json.dumps(ARTICLE, ensure_ascii=False), encoding="utf-8")
    client = fake_client()
    totals = extract.run(store=store, client=client)
    assert (totals["articles"], totals["incidents_in_lebanon"]) == (1, 1)
    assert (tmp_path / "extracted" / "nna" / "2026-09" / "abc.json").exists()
    assert totals["cost_usd"] == round((3000 * 0.10 + 700 * 0.50) / 1e6, 4)
    assert extract.run(store=store, client=client)["articles"] == 0 and client.messages.calls == 1
    saved = tmp_path / "extracted" / "nna" / "2026-09" / "abc.json"
    saved.write_text(json.dumps(json.loads(saved.read_text()) | {"prompt_version": "0"}), encoding="utf-8")
    assert extract.run(store=store, client=client)["articles"] == 1  # older instructions: classified again
