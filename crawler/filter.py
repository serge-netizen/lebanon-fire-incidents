"""Keyword filter over headline + first 300 characters (BRIEF §3).

Patterns live in `filter_patterns.yaml` (UTF-8 data, never strings in code — BRIEF §11).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

PATTERNS_PATH = Path(__file__).with_name("filter_patterns.yaml")
_MARKS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي"})


def fold(text: str) -> str:
    """Remove Arabic diacritics and tatweel, unify alef forms, lower-case Latin."""
    return _MARKS.sub("", unicodedata.normalize("NFKC", text)).translate(_FOLD).lower()


@dataclass(frozen=True)
class Verdict:
    passes: bool        # goes on to extraction
    borderline: bool    # passed on because of a borderline word only
    excluded_hint: bool  # military/figurative wording present: the model decides


@lru_cache(maxsize=1)
def _patterns() -> dict:
    raw = yaml.safe_load(PATTERNS_PATH.read_text(encoding="utf-8"))
    compile_ = lambda items: re.compile("|".join(f"(?:{fold(p)})" for p in items))
    return {
        "match": compile_(raw["match"]),
        "borderline": compile_(raw["borderline"]),
        "exclude": compile_(raw["exclude"]),
        "census_fire": re.compile(fold(raw["census"]["fire"])),
        "census_tally": re.compile(fold(raw["census"]["tally"])),
    }


def check(headline: str, lead: str = "") -> Verdict:
    text = fold(f"{headline} {lead[:300]}")
    p = _patterns()
    matched = bool(p["match"].search(text))
    borderline = not matched and bool(p["borderline"].search(text))
    return Verdict(passes=matched or borderline, borderline=borderline, excluded_hint=bool(p["exclude"].search(text)))


def census_kind(headline: str) -> str | None:
    """'tally' (a daily mission count), 'fire', 'fire_conflict' (fire words beside military
    wording — kept apart, never dropped: BRIEF §11), or None."""
    text = fold(headline)
    p = _patterns()
    if p["census_tally"].search(text):
        return "tally"
    if p["census_fire"].search(text):
        return "fire_conflict" if p["exclude"].search(text) else "fire"
    return None
