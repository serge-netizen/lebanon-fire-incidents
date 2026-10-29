"""Offline place resolution: place text → OCHA administrative units (BRIEF §4.6, task 2).

Rules, in the order they bite:

1. **Exact names only.** Text and names are normalised the same way (diacritics, letter
   variants, the article "ال", "كفر" spacing) and must then match whole. No fuzzy matching:
   distinct Lebanese villages differ by one letter.
2. **Common-word names need a place cue.** A cadastral area called "المزرعة" (the farm) only
   matches after "بلدة", "منطقة", "حي"… — never in "حريق في مزرعة دواجن".
3. **A district name beats a same-named cadastral area.** "جبيل" is the Jbeil district unless
   something finer is said; picking one cadastral area would be a guess downward.
4. **A name shared by a governorate and a district** resolves to the governorate unless the text
   says "قضاء"/"مدينة", or the governorate has a single district (Akkar, Beirut).
5. **Infer upward only.** Several candidates (homonyms, several villages, a village and a district
   that does not contain it) resolve to their lowest common unit; nothing is ever pushed down.
6. **A blank is an answer.** No known name → precision "unknown", never a guess.
7. **A direction is not a place** (2026-10-27). What follows "باتجاه" or "نحو" is where a road
   leads: "نفق حامات باتجاه طرابلس" is the Hamat tunnel, not Tripoli.
8. **The district or governorate a text names holds its places** (2026-10-28). A village named
   outside it is left out when another named village lies inside it: in "محلة العين … بلدة عندقت
   – عكار", "العين" is a quarter of Andaqt, not the village Aain in Baalbek. When no named village
   lies inside and the text says "قضاء"/"محافظة", that district or governorate is the answer:
   "بلدة عين الناصرة - قضاء صيدا" is in Saida, whatever "عين" alone matches. Both are flagged.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

from crawler import config
from crawler.gazetteer import Unit, units

MAX_NGRAM = 6

# ---------------------------------------------------------------- normalisation

_AR_MARKS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")  # harakat, shadda, tatweel
_AR_LETTERS = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ٲ": "ا", "ٳ": "ا", "ى": "ي", "ی": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي", "ک": "ك",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
})
_ARABIC = re.compile(r"[\u0600-\u06FF]")
# Article/particle prefixes on Arabic words: "وال", "بال", "فال", "كال", "لل", "ال".
_AR_ARTICLE = re.compile(r"^(?:[وبفك]?ال|لل)(?=\w{2,})")
# French-style transliteration articles OCHA uses ("Saida El-Qadimeh", "Aain Ez-Zeit").
_LATIN_ARTICLES = {"el", "al", "ech", "ej", "ed", "en", "er", "es", "et", "ez", "ad", "ash", "as", "az", "an", "at"}


def _tokens(text: str) -> list[tuple[str, bool]]:
    """Normalised words, each with whether an Arabic article ("ال", "بال", "لل"…) was removed."""
    t = unicodedata.normalize("NFKC", text)
    t = _AR_MARKS.sub("", t).translate(_AR_LETTERS)
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    t = re.sub(r"[^\w\s]|_", " ", t.lower())
    out: list[tuple[str, bool]] = []
    for w in t.split():
        article = False
        if _ARABIC.search(w):
            bare = _AR_ARTICLE.sub("", w)
            article, w = bare != w, bare
        elif w in _LATIN_ARTICLES:
            continue
        else:
            # Transliteration habits only, never sounds: Chouf/Shouf, Bourj/Burj, Aakkar/Akkar.
            w = re.sub(r"(.)\1+", r"\1", w.replace("ch", "sh").replace("ou", "u"))
        if out and out[-1][0] == "كفر" and _ARABIC.search(w):
            # "كفر رمان" and "كفررمان" are the same village; OCHA itself writes both forms.
            out[-1] = ("كفر" + w, out[-1][1])
            continue
        out.append((w, article))
    return out


def normalise(text: str) -> str:
    """The one form both the text and every gazetteer name are reduced to before matching."""
    return " ".join(w for w, _ in _tokens(text))


def _strip_clitic(word: str) -> str | None:
    """'بسن' → 'سن', 'وكفرحيم' → 'كفرحيم'. Tried only after the word failed as written."""
    if len(word) >= 3 and word[0] in "وبلف" and _ARABIC.match(word):
        return word[1:]
    return None


# ---------------------------------------------------------------- index

CUES_TOWN = {"بلده", "قريه", "منطقه", "حي", "محله", "خراج", "احراج", "مدينه", "ضيعه",
             "village", "town", "city", "area", "neighbourhood", "neighborhood"}
CUES_DISTRICT = {"قضاء", "caza", "kaza", "qada", "district"}
CUES_GOVERNORATE = {"محافظه", "governorate", "mohafaza", "muhafaza"}
CUE_UNION = ("اتحاد", "بلديات")  # "اتحاد بلديات X": a union of municipalities, never one village
DIRECTION = {"باتجاه", "اتجاه", "نحو", "towards", "toward", "vers"}  # rule 7: the rest is not the place


@dataclass(frozen=True)
class Entry:
    pcodes: tuple[str, ...]  # one unit, or several for a region alias
    level: int               # 1, 2, 3; 0 for a region (resolved through the common unit)
    kind: str                # official | part | alias
    needs_cue: bool = False
    alias_status: str | None = None


@dataclass
class Gazetteer:
    index: dict[str, list[Entry]]
    by_pcode: dict[str, Unit]
    article_guard: set[str]  # "صور" is Tyre, but "الصور"/"بالصور" means "the photos"
    needs_article: set[str]  # "الحدث" is Hadath, but bare "حدث" means "happened"


def _add(index: dict[str, list[Entry]], name: str | None, entry: Entry) -> None:
    if not name:
        return
    key = normalise(name)
    if key and entry not in index.setdefault(key, []):
        index[key].append(entry)


def _compound_parts(name_ar: str) -> list[str]:
    """'أدما والدفنه' → ['أدما', 'الدفنه']. Only the 'X والY' form, where both halves are names."""
    parts = re.split(r"\s+و(?=ال)", name_ar)
    return parts if len(parts) > 1 else []


@lru_cache(maxsize=1)
def gazetteer() -> Gazetteer:
    by_pcode = units()
    guards = _read_common_words()
    common = {k for k, guard in guards.items() if guard == "cue"}
    index: dict[str, list[Entry]] = {}
    for u in by_pcode.values():
        if not u.is_place:
            continue
        for name in (u.name_ar, u.name_en):
            key = normalise(name) if name else ""
            _add(index, name, Entry((u.pcode,), u.level, "official", needs_cue=key in common))
        if u.level == 3 and u.name_ar:
            for part in _compound_parts(u.name_ar):
                key = normalise(part)
                if len(key.replace(" ", "")) >= 3:
                    _add(index, part, Entry((u.pcode,), 3, "part", needs_cue=key in common))
    for row in _read_aliases():
        pcodes = tuple(row["pcode"].split("|"))
        unknown = [p for p in pcodes if p not in by_pcode]
        if unknown:
            raise ValueError(f"aliases.csv: unknown P-code {unknown} for {row['alias']!r}")
        level = 0 if row["level"] == "region" else int(row["level"])
        _add(index, row["alias"], Entry(pcodes, level, "alias", alias_status=row["status"]))
    article_guard = {k for k, guard in guards.items() if guard == "article"}
    needs_article = {k for k, guard in guards.items() if guard == "needs_article"}
    return Gazetteer(index=index, by_pcode=by_pcode, article_guard=article_guard,
                     needs_article=needs_article)


def _read_aliases() -> list[dict]:
    with (config.GAZETTEER_DIR / "aliases.csv").open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["alias"].strip()]


def _read_common_words() -> dict[str, str]:
    """Normalised word → guard: 'cue' (needs بلدة/منطقة…), 'article' (never matches as 'الX')
    or 'needs_article' (only matches as 'الX')."""
    with (config.GAZETTEER_DIR / "common_words.csv").open(encoding="utf-8") as f:
        return {normalise(r["word"]): r["guard"] for r in csv.DictReader(f) if r["word"].strip()}


# ---------------------------------------------------------------- resolution

@dataclass
class Match:
    text: str
    key: str
    entries: list[Entry]
    cue: str | None


@dataclass
class Resolution:
    precision: str  # village | district | governorate | unknown
    admin1: dict | None = None
    admin2: dict | None = None
    admin3: dict | None = None
    lat: float | None = None
    lon: float | None = None
    matched: list[str] = field(default_factory=list)
    ambiguous: bool = False  # several possible places, resolved to what they share
    conflict: bool = False   # the text names places that do not nest (worth a human look)
    notes: list[str] = field(default_factory=list)

    @property
    def pcode(self) -> str | None:
        unit = self.admin3 or self.admin2 or self.admin1
        return unit["pcode"] if unit else None

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()} | {"pcode": self.pcode}


def _find_matches(text: str, g: Gazetteer) -> list[Match]:
    tokens = _tokens(text)
    tokens = tokens[:next((i for i, (w, _) in enumerate(tokens) if w in DIRECTION), len(tokens))]
    words = [w for w, _ in tokens]
    matches, i = [], 0
    while i < len(words):
        found = None
        for n in range(min(MAX_NGRAM, len(words) - i), 0, -1):
            span = words[i:i + n]
            candidates = [" ".join(span)]
            stripped = _strip_clitic(span[0])
            if stripped:
                candidates.append(" ".join([stripped, *span[1:]]))
            for key in candidates:
                if key not in g.index:
                    continue
                if n == 1 and tokens[i][1] and key in g.article_guard:
                    continue  # written with "ال": the common word, not the place
                if n == 1 and not tokens[i][1] and key in g.needs_article:
                    continue  # written without "ال": the common word, not the place
                found = (n, key)
                break
            if found:
                break
        if not found:
            i += 1
            continue
        n, key = found
        matches.append(Match(" ".join(words[i:i + n]), key, list(g.index[key]), _cue(words, i, n)))
        i += n
    return matches


def _cue(words: list[str], i: int, n: int) -> str | None:
    before = [_strip_clitic(w) or w for w in words[max(0, i - 2):i]]
    prev = words[i - 1] if i else ""
    prev_bare = _strip_clitic(prev) or prev
    after = words[i + n] if i + n < len(words) else ""
    if tuple(words[max(0, i - 2):i]) == CUE_UNION:
        return "union"
    if prev in CUES_DISTRICT or prev_bare in CUES_DISTRICT or after in CUES_DISTRICT:
        return "district"
    if prev in CUES_GOVERNORATE or prev_bare in CUES_GOVERNORATE or after in CUES_GOVERNORATE:
        return "governorate"
    if prev in CUES_TOWN or prev_bare in CUES_TOWN or (prev == "of" and before and before[0] in CUES_TOWN):
        return "town"
    return None


def _choose(m: Match, g: Gazetteer, notes: list[str]) -> list[Entry]:
    """Apply rules 2–4 to one matched name; returns the entries that survive."""
    entries = [e for e in m.entries if not e.needs_cue or m.cue == "town"]
    if len(entries) < len(m.entries):
        notes.append(f"'{m.text}' is also a common word: ignored without a cue such as بلدة/منطقة")
    if not entries:
        return []
    if m.cue == "district":
        entries = [e for e in entries if e.level == 2] or entries
    elif m.cue == "governorate":
        entries = [e for e in entries if e.level == 1] or entries
    elif any(e.level == 0 for e in entries):
        # A region alias ("الجنوب", "البقاع") carries the colloquial meaning of a bare region word,
        # which is wider than the governorate of the same name.
        entries = [e for e in entries if e.level == 0]
    levels = {e.level for e in entries}
    if 3 in levels and levels & {1, 2}:  # rule 3: a coarser unit of the same name wins
        entries = [e for e in entries if e.level != 3]
        levels = {e.level for e in entries}
    if 1 in levels and 2 in levels:  # rule 4
        gov = next(e for e in entries if e.level == 1).pcodes[0]
        single = sum(1 for u in g.by_pcode.values() if u.level == 2 and u.adm1_pcode == gov) == 1
        keep = 2 if (m.cue in {"district", "town"} or single) else 1
        entries = [e for e in entries if e.level == keep]
    if m.cue == "union":  # "اتحاد بلديات X" spans several municipalities: district at most
        entries = [Entry((g.by_pcode[p].adm2_pcode,), 2, e.kind) if e.level == 3 else e
                   for e in entries for p in e.pcodes]
    return entries


def _ancestors(u: Unit) -> tuple[str, str | None, str | None]:
    if u.level == 1:
        return (u.pcode, None, None)
    if u.level == 2:
        return (u.adm1_pcode, u.pcode, None)
    return (u.adm1_pcode, u.adm2_pcode, u.pcode)


def _common(pcodes: set[str], g: Gazetteer) -> tuple[str | None, str | None, str | None]:
    """Lowest common unit of a set of units (rule 5)."""
    chains = [_ancestors(g.by_pcode[p]) for p in pcodes]
    out = []
    for depth in range(3):
        values = {c[depth] for c in chains}
        if len(values) != 1 or None in values:
            break
        out.append(values.pop())
    return tuple(out + [None] * (3 - len(out)))  # type: ignore[return-value]


def _expand(e: Entry) -> set[str]:
    return set(e.pcodes)


def resolve(text: str) -> Resolution:
    g = gazetteer()
    notes: list[str] = []
    matches = _find_matches(text, g)
    villages: list[set[str]] = []
    districts: set[str] = set()
    governorates: set[str] = set()
    regions: set[str] = set()
    explicit: set[str] = set()  # districts and governorates named with "قضاء" or "محافظة"
    used: list[str] = []
    for m in matches:
        entries = _choose(m, g, notes)
        if not entries:
            continue
        used.append(m.text)
        if m.cue in ("district", "governorate"):
            explicit |= {p for e in entries if e.level in (1, 2) for p in e.pcodes}
        for e in entries:
            if e.kind == "alias" and e.alias_status != "verified":
                notes.append(f"'{m.text}' resolved through a proposed alias (not yet verified)")
        if all(e.level == 3 for e in entries):
            villages.append(set().union(*map(_expand, entries)))
        else:
            for e in entries:
                if e.level == 2:
                    districts |= _expand(e)
                elif e.level == 1:
                    governorates |= _expand(e)
                elif e.level == 0:
                    regions |= _expand(e)
                else:
                    villages.append(_expand(e))

    ambiguous = conflict = left_out = False
    # Rule 8: a village outside the district or governorate the text names is left out.
    if villages and (districts or governorates):
        kept = [group for group in villages if any(g.by_pcode[p].adm2_pcode in districts
                                                   or g.by_pcode[p].adm1_pcode in governorates for p in group)]
        if kept and len(kept) < len(villages):
            left_out = True
            notes.append("a place outside the district or governorate the text names was left out")
            villages = kept
        elif not kept and explicit:
            left_out = True
            notes.append("no place named lies in the district or governorate the text names: that one is kept")
            villages = []
    # Homonyms: keep the candidates that sit in a district or governorate the text names.
    narrowed = []
    for group in villages:
        if len(group) > 1:
            inside = {p for p in group if g.by_pcode[p].adm2_pcode in districts
                      or g.by_pcode[p].adm1_pcode in governorates}
            if inside:
                group = inside
            if len(group) > 1:
                ambiguous = True
                notes.append(f"{len(group)} places share this name: resolved to what they have in common")
        narrowed.append(group)
    pool: set[str] = set().union(*narrowed) if narrowed else set()
    if len(narrowed) > 1 and len(pool) > 1:
        ambiguous = True
        notes.append("several places named: resolved to what they have in common")

    if pool:
        for d in districts:
            if not any(g.by_pcode[p].adm2_pcode == d for p in pool):
                conflict = True
                pool.add(d)
        for gov in governorates:
            if not any(g.by_pcode[p].adm1_pcode == gov for p in pool):
                conflict = True
                pool.add(gov)
    elif districts:
        pool = set(districts)
        for gov in governorates:
            if not any(g.by_pcode[d].adm1_pcode == gov for d in districts):
                conflict = True
                pool.add(gov)
        if len(districts) > 1:
            ambiguous = True
    elif governorates:
        pool = set(governorates)
        ambiguous = len(governorates) > 1
    elif regions:
        pool = set(regions)
        ambiguous = len(regions) > 1
    if conflict:
        notes.append("the places named do not nest inside each other: resolved to what they share")
    conflict = conflict or left_out  # worth a human look either way

    if not pool:
        return Resolution("unknown", matched=used, notes=notes or ["no known place name"])
    adm1, adm2, adm3 = _common(pool, g)
    finest = adm3 or adm2 or adm1
    if not finest:
        return Resolution("unknown", matched=used, ambiguous=ambiguous, conflict=conflict,
                          notes=notes + ["the places named share no governorate"])
    unit = g.by_pcode[finest]
    return Resolution(
        precision={1: "governorate", 2: "district", 3: "village"}[unit.level],
        admin1=_describe(g, adm1), admin2=_describe(g, adm2), admin3=_describe(g, adm3),
        lat=unit.lat, lon=unit.lon, matched=used, ambiguous=ambiguous, conflict=conflict, notes=notes,
    )


def _describe(g: Gazetteer, pcode: str | None) -> dict | None:
    if not pcode:
        return None
    u = g.by_pcode[pcode]
    return {"pcode": u.pcode, "name_en": u.name_en, "name_ar": u.name_ar, "name_fr": None}
