"""Task 4: Claude reads each fire article and fills in the classification (crawler/taxonomy.yaml).

Model: Claude Haiku 5.5, the model the brief names (amendment 2, corrected 2026-10-23). Structured
outputs hold the answer to a JSON schema built from the taxonomy, so every tag is one of the
listed ids. Article text and evidence quotes stay in the private store; job logs show counts only.

A free first check decides what reaches the model: fire words in the headline or the opening
300 characters. Civil Defense daily bulletins are read by crawler/bulletin.py instead.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import re
from functools import lru_cache
from pathlib import Path

import anthropic
import yaml

from crawler import config
from crawler.filter import census_kind, fold
from crawler.store import Store

TAXONOMY_PATH = Path(__file__).with_name("taxonomy.yaml")
# The instructions, as UTF-8 text (BRIEF §11); the lists are filled in from the taxonomy.
PROMPT_PATH = Path(__file__).parent / "prompts" / "extract.md"
PROMPT_VERSION = "1"  # bump whenever the instructions change; stored with every result
EFFORT = "medium"     # Haiku 5.5's default; chosen, to be tuned on the owner's corrections
MAX_OTHERS = 4        # owner, 2026-10-22: one primary tag and up to four more
MAX_MATERIALS = 5
MAX_TEXT_CHARS = 20_000
# $ per million tokens (input, output) for prompts up to 100K tokens; from the claude-api
# reference cached 2026-10-06 — re-check before quoting a budget.
PRICE = {"claude-haiku-5-5": (0.10, 0.50)}
FIRE_WORDS = re.compile(fold(r"حريق|حرائق|إخماد|أخمد|تخمد|النيران|نيران|اشتعال|احتراق|التهمت|تلتهم"
                             r"|\bfires?\b|\bblazes?\b|wildfires?|\bincendies?\b"))
RESPONDERS = ["civil_defense", "beirut_fire_brigade", "army", "red_cross", "municipality", "other"]
ORIGINS = ["accidental", "deliberate", "conflict_related", "unknown"]


# ---------------------------------------------------------------- the lists

@lru_cache(maxsize=1)
def taxonomy() -> dict:
    return yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8"))


def site_category() -> dict[str, str]:
    """Sub-type id → its category id."""
    out = {"not_established": "not_established"}
    for category, v in taxonomy()["site_types"].items():
        for sub in v.get("subtypes") or {}:
            out[sub] = category
    return out


def hazard_ids() -> list[str]:
    return list(taxonomy()["hazards"])


def material_ids() -> list[str]:
    return [m for m in taxonomy()["materials"] if m != "not_established"]


# ---------------------------------------------------------------- what the model must return

def _nullable(kind: str) -> dict:
    return {"type": [kind, "null"]}


def schema() -> dict:
    sites = list(site_category())
    item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "record_type": {"enum": ["incident", "aggregate_report", "not_a_fire"]},
            "is_lebanon": {"type": "boolean"},
            "summary": {"type": "string"},
            "occurred_on": _nullable("string"),
            "date_precision": {"enum": ["exact", "day", "week", "unknown"]},
            "place_text": _nullable("string"),
            "site_primary": {"enum": sites},
            "site_others": {"type": "array", "items": {"enum": sites}},
            "hazard_primary": {"enum": hazard_ids()},
            "hazard_others": {"type": "array", "items": {"enum": hazard_ids()}},
            "materials": {"type": "array", "items": {"enum": material_ids()}},
            "origin": {"enum": ORIGINS},
            "deaths": _nullable("integer"),
            "injuries": _nullable("integer"),
            "smoke_inhalation": _nullable("integer"),
            "buildings_burned": _nullable("integer"),
            "vehicles_burned": _nullable("integer"),
            "area_burned_m2": _nullable("number"),
            "displaced": _nullable("integer"),
            "responders": {"type": "array", "items": {"enum": RESPONDERS}},
            "evidence": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "properties": {"field": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["field", "quote"]}},
            "confidence": {"type": "number"},
        },
    }
    item["required"] = list(item["properties"])
    return {"type": "object", "additionalProperties": False, "required": ["items"],
            "properties": {"items": {"type": "array", "items": item}}}


def _entry(key: str, v: dict) -> str:
    text = f"  {key}: {v['label']}"
    if v.get("definition"):
        text += f" — {v['definition']}"
    if v.get("rule"):
        text += f" Rule: {v['rule']}"
    if v.get("cues"):
        text += f" (words such as: {'، '.join(v['cues'])})"
    return text


@lru_cache(maxsize=1)
def system_prompt() -> str:
    t = taxonomy()
    sites = []
    for category, v in t["site_types"].items():
        if category == "not_established":
            continue
        head = f"{v['label']} — {v['definition']}" + (f" Rule: {v['rule']}" if v.get("rule") else "")
        sites.append(head)
        sites += [_entry(k, s) for k, s in v["subtypes"].items()]
    sites.append("  not_established: the article does not say what kind of place burned.")
    hazards = [_entry(k, v) for k, v in t["hazards"].items()]
    materials = [_entry(k, v) for k, v in t["materials"].items() if k != "not_established"]
    damages = [f"  {k}: {v}" for k, v in t["damages"].items()]
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(sites="\n".join(sites), hazards="\n".join(hazards), materials="\n".join(materials),
                           damages="\n".join(damages), max_others=MAX_OTHERS, max_materials=MAX_MATERIALS)


def user_message(article: dict) -> str:
    text = article["text"]
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + f"\n[text cut at {MAX_TEXT_CHARS:,} characters]"
    return (f"Outlet: {article['outlet']}\nPublished: {(article.get('published_at') or '')[:10]}\n"
            f"Headline: {article['headline']}\n\nText:\n{text}")


# ---------------------------------------------------------------- one article

def is_candidate(article: dict) -> bool:
    """The free first check: a fire story, not a daily bulletin."""
    if census_kind(article["headline"]) == "tally":
        return False
    return bool(FIRE_WORDS.search(fold(article["headline"])) or FIRE_WORDS.search(fold(article["text"][:300])))


def clean_item(item: dict) -> dict:
    """Enforce what the schema cannot say: list lengths, no primary repeated, sane numbers."""
    def others(primary: str, values: list[str], limit: int) -> list[str]:
        seen = []
        for v in values:
            if v != primary and v != "not_established" and v not in seen:
                seen.append(v)
        return seen[:limit]

    item["site_others"] = others(item["site_primary"], item["site_others"], MAX_OTHERS)
    item["hazard_others"] = others(item["hazard_primary"], item["hazard_others"], MAX_OTHERS)
    item["materials"] = others("", item["materials"], MAX_MATERIALS)
    categories = site_category()
    item["site_category"] = categories[item["site_primary"]]
    item["site_categories_other"] = others(item["site_category"], [categories[s] for s in item["site_others"]], MAX_OTHERS)
    for k in ("deaths", "injuries", "smoke_inhalation", "buildings_burned", "vehicles_burned", "displaced", "area_burned_m2"):
        if item[k] is not None and item[k] < 0:
            item[k] = None
    item["confidence"] = min(max(float(item["confidence"]), 0.0), 1.0)
    return item


def extract_one(client: anthropic.Anthropic, article: dict) -> dict:
    result = {"raw_ref": article["raw_ref"], "url": article["url"], "outlet": article["outlet"],
              "model": config.EXTRACT_MODEL, "prompt_version": PROMPT_VERSION, "effort": EFFORT,
              "status": "ok", "items": [], "usage": {"input_tokens": 0, "output_tokens": 0}}
    try:
        response = client.messages.create(
            model=config.EXTRACT_MODEL,
            max_tokens=8000,
            system=system_prompt(),
            messages=[{"role": "user", "content": user_message(article)}],
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": schema()}},
        )
    except anthropic.BadRequestError as e:
        return result | {"status": f"bad request: {e.message}"[:300]}
    except anthropic.APIStatusError as e:  # the SDK has already retried 429 and 5xx twice
        return result | {"status": f"API error {e.status_code}"}
    except anthropic.APIConnectionError:
        return result | {"status": "network error"}
    result["usage"] = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    result["request_id"] = response._request_id
    if response.stop_reason in ("refusal", "max_tokens"):
        return result | {"status": response.stop_reason}  # Haiku 5.5 has no server-side fallback
    text = next((b.text for b in response.content if b.type == "text"), "")
    result["items"] = [clean_item(i) for i in json.loads(text)["items"]]
    return result


# ---------------------------------------------------------------- a run

def result_path(store: Store, article: dict) -> Path:
    return store.root / article["raw_ref"].replace("raw/", "extracted/", 1)


def run(limit: int | None = None, force: bool = False, workers: int = 4, store: Store | None = None,
        client: anthropic.Anthropic | None = None) -> dict:
    store = store or Store()
    client = client or anthropic.Anthropic()
    todo = [a for a in store.articles() if is_candidate(a) and (force or not result_path(store, a).exists())]
    todo = todo[:limit] if limit else todo
    totals = {"articles": len(todo), "ok": 0, "not_ok": 0, "items": 0, "incidents_in_lebanon": 0,
              "input_tokens": 0, "output_tokens": 0}
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for article, result in zip(todo, pool.map(lambda a: extract_one(client, a), todo), strict=True):
            path = result_path(store, article)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
            totals["ok" if result["status"] == "ok" else "not_ok"] += 1
            totals["items"] += len(result["items"])
            totals["incidents_in_lebanon"] += sum(1 for i in result["items"]
                                                  if i["record_type"] == "incident" and i["is_lebanon"])
            totals["input_tokens"] += result["usage"]["input_tokens"]
            totals["output_tokens"] += result["usage"]["output_tokens"]
    price_in, price_out = PRICE.get(config.EXTRACT_MODEL, (0.0, 0.0))
    totals["cost_usd"] = round((totals["input_tokens"] * price_in + totals["output_tokens"] * price_out) / 1e6, 4)
    return totals
