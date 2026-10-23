"""Several articles, one fire (BRIEF §4.5): the reports of the same fire become one incident that
lists every source. Runs after extraction, and needs the place (the gazetteer) and the site.

Rule v1 (2026-10-23). Two reports are the same fire when all of these hold:
- they come from different articles (Claude already splits a round-up into its fires);
- their dates are at most two days apart — the fire date, or the publication date when the
  article gives none. The brief said 36 hours; two days because most articles give no fire
  date, and dumps and forests burn for days;
- their places nest at district level or finer (Saida city inside Saida district); a place found
  only at governorate level matches only the same governorate. Two places the gazetteer could not
  find match only when the headline is the same (one article published twice);
- their sites agree: a shared site category, or one not established, or both outdoors.
A report joins a group only if it matches every report already in it, so a chain of near-matches
never merges two different fires.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field

from crawler import taxonomy as tx
from crawler.derive import IN_SCOPE, WAR, scope
from crawler.extract import MAX_OTHERS, PROMPT_VERSION
from crawler.filter import fold, war_words
from crawler.geocode import Resolution, resolve
from crawler.store import Store

WINDOW_DAYS = 2
OUTDOOR = {"waste_sites", "natural_areas", "agricultural", "public_spaces"}
DAMAGES = ("deaths", "injuries", "smoke_inhalation", "buildings_burned", "vehicles_burned", "area_burned_m2", "displaced")
PRECISION = {"village": 0, "district": 1, "governorate": 2, "unknown": 3}


@dataclass
class Report:
    """One fire as one article reports it."""
    item: dict  # Claude's answer, as cleaned
    raw_ref: str
    outlet: str
    url: str
    headline: str
    published: dt.date
    date: dt.date
    date_deduced: bool  # True: the publication date, the article gives no fire date
    place: Resolution
    scope: str
    war_words: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, article: dict, item: dict, scope_: str, words: list[str]) -> Report:
        published = dt.date.fromisoformat((article.get("published_at") or article["fetched_at"])[:10])
        try:
            occurred = dt.date.fromisoformat(item["occurred_on"]) if item["occurred_on"] else None
        except ValueError:
            occurred = None
        place = resolve(item["place_text"]) if item["place_text"] else Resolution("unknown")
        return cls(item, article["raw_ref"], article["outlet"], article["url"], article["headline"], published,
                   occurred or published, occurred is None, place, scope_, words)


@dataclass
class Incident:
    reports: list[Report]  # the main report first
    record: dict           # the merged classification, with the same keys as Claude's answer
    scope: str
    date: dt.date
    date_deduced: bool
    flags: list[str]


@dataclass
class Batch:
    reports: list[Report] = field(default_factory=list)    # fires in Lebanon, in scope or war-related
    set_aside: list[dict] = field(default_factory=list)    # {article, item, scope}: not a fire, abroad…
    failed: list[dict] = field(default_factory=list)       # {article, status}: refused or failed
    stale: int = 0                                         # classified with older instructions


def load(store: Store) -> Batch:
    """Every classification made with the current instructions, sorted into fires and the rest."""
    articles = {a["raw_ref"]: a for a in store.articles()}
    batch = Batch()
    for path in sorted((store.root / "extracted").glob("*/*/*.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        article = articles.get(result["raw_ref"])
        if article is None:
            continue
        if result.get("prompt_version") != PROMPT_VERSION:
            batch.stale += 1
            continue
        if result["status"] != "ok":
            batch.failed.append({"article": article, "status": result["status"]})
            continue
        words = war_words(f"{article['headline']}\n{article['text']}")
        for item in result["items"]:
            s = scope(item)
            if s in (IN_SCOPE, WAR):
                batch.reports.append(Report.of(article, item, s, words))
            else:
                batch.set_aside.append({"article": article, "item": item, "scope": s})
    return batch


# ---------------------------------------------------------------- same fire?

def _headline(text: str) -> str:
    return re.sub(r"\W+", " ", fold(text)).strip()


def _chain(r: Resolution) -> list[str]:
    return [u["pcode"] for u in (r.admin3, r.admin2, r.admin1) if u]


def _places_nest(a: Resolution, b: Resolution) -> bool:
    if not (a.pcode and b.pcode):
        return False
    fine, coarse = sorted((a, b), key=lambda r: PRECISION[r.precision])
    if coarse.precision == "governorate":
        return coarse.precision == fine.precision and coarse.pcode == fine.pcode
    return coarse.pcode in _chain(fine)


def _sites_agree(a: dict, b: dict) -> bool:
    category = tx.site_category()
    ca = {category[s] for s in (a["site_primary"], *a["site_others"])} - {tx.NOT_ESTABLISHED}
    cb = {category[s] for s in (b["site_primary"], *b["site_others"])} - {tx.NOT_ESTABLISHED}
    if not ca or not cb or ca & cb:
        return True
    return category[a["site_primary"]] in OUTDOOR and category[b["site_primary"]] in OUTDOOR


def same_fire(a: Report, b: Report) -> bool:
    if a.raw_ref == b.raw_ref or abs((a.date - b.date).days) > WINDOW_DAYS:
        return False
    places = _places_nest(a.place, b.place) or (
        not (a.place.pcode and b.place.pcode) and _headline(a.headline) == _headline(b.headline))
    return places and _sites_agree(a.item, b.item)


def group(reports: list[Report]) -> list[list[Report]]:
    groups: list[list[Report]] = []
    for r in sorted(reports, key=lambda r: (r.date, r.published, r.url)):
        for g in groups:
            if all(same_fire(r, m) for m in g):
                g.append(r)
                break
        else:
            groups.append([r])
    return groups


# ---------------------------------------------------------------- one incident

def _filled(item: dict) -> int:
    kinds = ("site", "material", "hazard")
    return (sum(item[k] is not None for k in DAMAGES) + sum(item[f"{k}_primary"] != tx.NOT_ESTABLISHED for k in kinds)
            + sum(len(item[f"{k}_others"]) for k in kinds) + (item["occurred_on"] is not None))


def _rank(r: Report) -> tuple:
    """The main report: the most precise place, then the most detail, then the national agency."""
    return PRECISION.get(r.place.precision, 3), -_filled(r.item), r.outlet != "nna", r.published, r.url


def merge(group_: list[Report]) -> Incident:
    reports = sorted(group_, key=_rank)
    items = [r.item for r in reports]
    record = {"summary": items[0]["summary"], "place_text": items[0]["place_text"], "confidence": items[0]["confidence"]}
    flags: list[str] = []
    for kind in ("site", "material", "hazard"):  # the main report's tag, else the first source that has one
        primary = next((i[f"{kind}_primary"] for i in items if i[f"{kind}_primary"] != tx.NOT_ESTABLISHED), tx.NOT_ESTABLISHED)
        others = list(dict.fromkeys(v for i in items for v in (i[f"{kind}_primary"], *i[f"{kind}_others"])
                                    if v not in (primary, tx.NOT_ESTABLISHED)))
        record[f"{kind}_primary"], record[f"{kind}_others"] = primary, others[:MAX_OTHERS]
    origins = list(dict.fromkeys(i["origin"] for i in items if i["origin"] != "unknown"))
    record["origin"] = origins[0] if origins else "unknown"
    if len(origins) > 1:
        flags.append(f"sources disagree on the origin ({', '.join(origins)})")
    for k in DAMAGES:
        values = list(dict.fromkeys(i[k] for i in items if i[k] is not None))
        record[k] = values[0] if values else None
        if len(values) > 1:
            flags.append(f"sources disagree on {k.replace('_', ' ')} ({', '.join(map(str, values))})")
    record["responders"] = list(dict.fromkeys(x for i in items for x in i["responders"]))
    reported = sorted(r.date for r in reports if not r.date_deduced)
    date, deduced = (reported[0], False) if reported else (min(r.date for r in reports), True)
    scopes = {r.scope for r in reports}
    scope_ = WAR if WAR in scopes else IN_SCOPE
    if len(scopes) > 1:
        flags.append("only some sources say it is war-related")
    words = sorted({w for r in reports for w in r.war_words})
    if scope_ == IN_SCOPE and words:
        flags.append(f"war words in the article ({'، '.join(words)}): war-related?")
    if scope_ == IN_SCOPE and any("munitions_explosives" in i["hazard_others"] for i in items):
        flags.append("munitions named as a possible cause: war-related?")
    place = reports[0].place
    if not place.pcode:
        flags.append("place not found in the gazetteer")
    elif place.ambiguous:
        flags.append("place name shared by several places")
    elif place.conflict:
        flags.append("the article names places that do not nest")
    return Incident(reports, record, scope_, date, deduced, flags)


def incidents(reports: list[Report]) -> list[Incident]:
    """One incident per fire, the most recent first."""
    return sorted((merge(g) for g in group(reports)), key=lambda i: (i.date, i.reports[0].url), reverse=True)
