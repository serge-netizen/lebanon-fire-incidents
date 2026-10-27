"""Task 4: Claude reads each fire article and fills in the classification (crawler/taxonomy.yaml).

Model: Claude Haiku 5.5, the model the brief names (amendment 2, corrected 2026-10-23). Structured
outputs hold the answer to a JSON schema built from the taxonomy, so every tag is one of the
listed ids. Claude records only what the article reports; what can be deduced from it is added
by crawler/derive.py. Article text and evidence quotes stay in the private store; job logs show
counts only.

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

from crawler import config
from crawler import taxonomy as tx
from crawler.filter import census_kind, fold
from crawler.store import Store

# The instructions, as UTF-8 text (BRIEF §11); the lists are filled in from the taxonomy.
PROMPT_PATH = Path(__file__).parent / "prompts" / "extract.md"
PROMPT_VERSION = "5"  # bump whenever the instructions or the lists change; stored with every result
EFFORT = "medium"     # Haiku 5.5's default; chosen, to be tuned on the owner's corrections
MAX_OTHERS = 4        # owner, 2026-10-22: one main tag and up to four more (site, burned, hazard)
MAX_TEXT_CHARS = 20_000
# $ per million tokens (input, output) for prompts up to 100K tokens; from the claude-api
# reference cached 2026-10-06 — re-check before quoting a budget.
PRICE = {"claude-haiku-5-5": (0.10, 0.50)}
FIRE_WORDS = re.compile(fold(r"حريق|حرائق|إخماد|أخمد|تخمد|النيران|نيران|اشتعال|احتراق|التهمت|تلتهم"
                             r"|\bfires?\b|\bblazes?\b|wildfires?|\bincendies?\b"))
RECORD_TYPES = ["incident", "aggregate_report", "background", "not_a_fire"]


# ---------------------------------------------------------------- what the model must return

def _nullable(kind: str) -> dict:
    return {"type": [kind, "null"]}


def schema() -> dict:
    sites, materials, hazards = tx.site_ids(), tx.material_ids(), tx.hazard_ids()
    item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "record_type": {"enum": RECORD_TYPES},
            "is_lebanon": {"type": "boolean"},
            "summary": {"type": "string"},
            "occurred_on": _nullable("string"),
            "date_precision": {"enum": ["exact", "day", "week", "unknown"]},
            "place_text": _nullable("string"),
            "site_primary": {"enum": sites},
            "site_others": {"type": "array", "items": {"enum": sites}},
            "material_primary": {"enum": [*materials, tx.NOT_ESTABLISHED]},
            "material_others": {"type": "array", "items": {"enum": materials}},
            "hazard_primary": {"enum": hazards},
            "hazard_others": {"type": "array", "items": {"enum": hazards}},
            "origin": {"enum": tx.origin_ids()},
            "deaths": _nullable("integer"),
            "injuries": _nullable("integer"),
            "smoke_inhalation": _nullable("integer"),
            "buildings_burned": _nullable("integer"),
            "vehicles_burned": _nullable("integer"),
            "area_burned_m2": _nullable("number"),
            "displaced": _nullable("integer"),
            "property_damage": {"enum": tx.property_damage_ids()},
            "responders": {"type": "array", "items": {"enum": tx.responder_ids()}},
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


def _groups(section: dict, child: str) -> list[str]:
    """A two-level list: each group's label as a heading, then its ids."""
    lines = []
    for v in section.values():
        if child not in v:
            continue
        head = v["label"] + (f" — {v['definition']}" if v.get("definition") else "")
        lines.append(head + (f" Rule: {v['rule']}" if v.get("rule") else ""))
        lines += [_entry(k, s) for k, s in v[child].items()]
    return lines


@lru_cache(maxsize=1)
def system_prompt() -> str:
    t = tx.lists()
    sites = [*_groups(t["site_types"], "subtypes"), f"  {tx.NOT_ESTABLISHED}: {t['site_types'][tx.NOT_ESTABLISHED]['definition']}"]
    materials = [*_groups(t["materials"], "items"), f"  {tx.NOT_ESTABLISHED}: the article does not say what burned."]
    hazards = [_entry(k, v) for k, v in t["hazards"].items()]
    origins = [f"   {k}: {v['definition']}" for k, v in t["origins"].items()]
    property_damage = [f"   {k}: {v['definition']}" for k, v in t["property_damage"].items()]
    responders = [f"   {k}: {v['label']} (words such as: {'، '.join(v['cues'])})" for k, v in t["responders"].items()]
    damages = [f"  {k}: {v}" for k, v in t["damages"].items()]
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(sites="\n".join(sites), materials="\n".join(materials), hazards="\n".join(hazards),
                           origins="\n".join(origins), property_damage="\n".join(property_damage),
                           responders="\n".join(responders), damages="\n".join(damages), max_others=MAX_OTHERS)


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
    """Enforce what the schema cannot say: list lengths, no main tag repeated, sane numbers."""
    for kind in ("site", "material", "hazard"):
        primary, seen = item[f"{kind}_primary"], []
        for v in item[f"{kind}_others"]:
            if v not in (primary, tx.NOT_ESTABLISHED) and v not in seen:
                seen.append(v)
        item[f"{kind}_others"] = seen[:MAX_OTHERS]
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


def is_done(store: Store, article: dict) -> bool:
    """Classified with the current instructions; older results are done again."""
    path = result_path(store, article)
    return path.exists() and json.loads(path.read_text(encoding="utf-8")).get("prompt_version") == PROMPT_VERSION


def run(limit: int | None = None, force: bool = False, workers: int = 4, store: Store | None = None,
        client: anthropic.Anthropic | None = None) -> dict:
    store = store or Store()
    client = client or anthropic.Anthropic()
    todo = [a for a in store.articles() if is_candidate(a) and (force or not is_done(store, a))]
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
