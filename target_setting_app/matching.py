"""
Student and subject name matching across multiple data sources.

Student matching handles: exact matches, normalised matches (hyphens/apostrophes/
accents stripped), surname-only tiebreaking, forename abbreviation (Tom ↔ Thomas),
and fuzzy scoring.

Subject matching handles: exact, case-insensitive, common abbreviations (Maths →
Mathematics, Eng Lit → English Literature, etc.), and fuzzy sequence scoring.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------

def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def normalise_part(name: str) -> str:
    """
    Normalise a single name part (surname or forename):
    lowercase, strip accents, remove hyphens/apostrophes/dots/spaces.
    """
    name = name.lower().strip()
    name = _strip_accents(name)
    name = re.sub(r"[-'’.`\s]", "", name)
    return name


def normalise_key(key: str) -> str:
    """Return a fully normalised 'surname|forename' key."""
    parts = key.split("|", 1)
    if len(parts) == 2:
        return f"{normalise_part(parts[0])}|{normalise_part(parts[1])}"
    return normalise_part(key)


def display_name(key: str) -> str:
    parts = key.split("|", 1)
    if len(parts) == 2:
        return f"{parts[0].title()} {parts[1].title()}"
    return key.title()


# ---------------------------------------------------------------------------
# Fuzzy scoring
# ---------------------------------------------------------------------------

# Common forename abbreviations / variants (lowercase, no spaces)
_FORENAME_ALIASES: dict[str, list[str]] = {
    "thomas": ["tom", "tommy"],
    "elizabeth": ["beth", "liz", "eliza", "lizzie", "ellie", "betty"],
    "william": ["will", "bill", "billy", "willy"],
    "james": ["jim", "jimmy", "jamie"],
    "robert": ["rob", "bob", "bobby"],
    "richard": ["rick", "rich", "dick"],
    "charles": ["charlie", "chuck"],
    "alexander": ["alex", "alec", "sandy"],
    "nicholas": ["nick", "nicky"],
    "christopher": ["chris"],
    "matthew": ["matt"],
    "michael": ["mike", "micky"],
    "jonathan": ["jon", "jonny"],
    "benjamin": ["ben", "benny"],
    "theodore": ["theo", "ted"],
    "anthony": ["tony"],
    "samantha": ["sam"],
    "catherine": ["cathy", "kate", "katie"],
    "katherine": ["kathy", "kate", "katie", "kat"],
    "josephine": ["josie", "jo"],
    "josephina": ["josie", "jo"],
    "eleanor": ["ellie", "nell"],
    "margaret": ["meg", "maggie", "peggy"],
    "victoria": ["vicky", "tori"],
    "jessica": ["jess"],
    "jennifer": ["jen", "jenny"],
    "rebecca": ["becca", "becky"],
    "rosemary": ["rosie"],
    "arabella": ["bella"],
    "georgina": ["georgie"],
    "francesca": ["frankie"],
    "harriet": ["hattie"],
    "frederica": ["freddie"],
    "frederik": ["freddie", "fred"],
    "frederic": ["freddie", "fred"],
}

# Build reverse map: alias -> canonical
_ALIAS_CANONICAL: dict[str, str] = {}
for canonical, aliases in _FORENAME_ALIASES.items():
    for alias in aliases:
        _ALIAS_CANONICAL[alias] = canonical


def _canonical_forename(fn: str) -> str:
    """Map a forename to its canonical form for comparison."""
    n = normalise_part(fn)
    return _ALIAS_CANONICAL.get(n, n)


def _forename_score(fn1: str, fn2: str) -> float:
    """Score similarity of two forenames (0–1), handling abbreviations and aliases."""
    n1 = normalise_part(fn1)
    n2 = normalise_part(fn2)
    if n1 == n2:
        return 1.0
    # Canonical alias match
    if _canonical_forename(n1) == _canonical_forename(n2):
        return 0.95
    # One is a prefix of the other (Tom → Thomas, Ben → Benjamin)
    short, long = (n1, n2) if len(n1) <= len(n2) else (n2, n1)
    if len(short) >= 2 and long.startswith(short):
        return 0.90
    # First initial match
    if n1 and n2 and n1[0] == n2[0]:
        seq = difflib.SequenceMatcher(None, n1, n2).ratio()
        return max(seq, 0.55)
    return difflib.SequenceMatcher(None, n1, n2).ratio()


def fuzzy_score(key1: str, key2: str) -> float:
    """
    Overall similarity between two 'surname|forename' keys.
    Returns 0.0–1.0.  Surnames are weighted more heavily (65/35).
    """
    p1 = key1.split("|", 1)
    p2 = key2.split("|", 1)
    if len(p1) != 2 or len(p2) != 2:
        return difflib.SequenceMatcher(None, normalise_part(key1), normalise_part(key2)).ratio()
    sn1, fn1 = p1
    sn2, fn2 = p2
    sn_score = difflib.SequenceMatcher(
        None, normalise_part(sn1), normalise_part(sn2)
    ).ratio()
    fn_score = _forename_score(fn1, fn2)
    return 0.65 * sn_score + 0.35 * fn_score


# ---------------------------------------------------------------------------
# Match finder
# ---------------------------------------------------------------------------

EXACT_THRESHOLD = 1.0
FUZZY_THRESHOLD = 0.80    # suggest but don't auto-confirm
POSSIBLE_THRESHOLD = 0.60  # show as "possible" low-confidence suggestion


def find_best_match(
    key: str,
    candidates: list[str],
    threshold: float = FUZZY_THRESHOLD,
) -> tuple[str, float, str] | None:
    """
    Find the best match for key in candidates.
    Returns (matched_key, score, match_type) or None.
    match_type: "exact" | "normalised" | "fuzzy" | "possible"
    """
    if not candidates:
        return None

    # 1. Exact key match
    if key in candidates:
        return (key, 1.0, "exact")

    # 2. Normalised match (strips hyphens, apostrophes, accents)
    norm_key = normalise_key(key)
    norm_map = {normalise_key(c): c for c in candidates}
    if norm_key in norm_map:
        return (norm_map[norm_key], 0.98, "normalised")

    # 3. Surname-exact match — find candidates with same normalised surname
    key_sn = norm_key.split("|")[0]
    same_surname = [c for c in candidates if normalise_key(c).split("|")[0] == key_sn]
    if len(same_surname) == 1:
        score = fuzzy_score(key, same_surname[0])
        if score >= POSSIBLE_THRESHOLD:
            mtype = "fuzzy" if score >= threshold else "possible"
            return (same_surname[0], score, mtype)

    # 4. Full fuzzy
    scored = [(c, fuzzy_score(key, c)) for c in candidates]
    best_c, best_s = max(scored, key=lambda x: x[1])
    if best_s >= threshold:
        return (best_c, best_s, "fuzzy")
    if best_s >= POSSIBLE_THRESHOLD:
        return (best_c, best_s, "possible")

    return None


# ---------------------------------------------------------------------------
# Cross-source matching report
# ---------------------------------------------------------------------------

STATUS_ICON = {
    "exact":      "✅",
    "normalised": "✅",   # treated as exact in practice
    "fuzzy":      "⚠️",
    "possible":   "⚠️",
    "manual":     "🔧",
    "unmatched":  "❌",
    "n/a":        "—",    # source not uploaded
}


def match_sources(
    master_keys: list[str],
    source_keys: dict[str, list[str]],
    manual_overrides: dict[str, str] | None = None,
    threshold: float = FUZZY_THRESHOLD,
) -> pd.DataFrame:
    """
    For each master key (from the subject list), determine its match status
    in each uploaded data source.

    Args:
        master_keys:      list of 'surname|forename' keys (subject list)
        source_keys:      {'Source Name': [keys...]}
        manual_overrides: {'Source Name::master_key': 'confirmed_target_key'}
        threshold:        fuzzy match confidence floor

    Returns DataFrame with columns:
        master_key | display_name | <src>_status | <src>_matched | <src>_suggestion | <src>_score | ...
    """
    overrides = manual_overrides or {}
    rows = []

    for mkey in master_keys:
        row: dict = {"master_key": mkey, "display_name": display_name(mkey)}

        for src, s_keys in source_keys.items():
            override_key = f"{src}::{mkey}"

            if override_key in overrides:
                row[f"{src}_status"]     = "manual"
                row[f"{src}_matched"]    = overrides[override_key]
                row[f"{src}_suggestion"] = None
                row[f"{src}_score"]      = 1.0
                continue

            result = find_best_match(mkey, s_keys, threshold=threshold)

            if result is None:
                row[f"{src}_status"]     = "unmatched"
                row[f"{src}_matched"]    = None
                row[f"{src}_suggestion"] = None
                row[f"{src}_score"]      = 0.0
            elif result[2] in ("exact", "normalised"):
                row[f"{src}_status"]     = result[2]
                row[f"{src}_matched"]    = result[0]
                row[f"{src}_suggestion"] = None
                row[f"{src}_score"]      = result[1]
            elif result[2] == "fuzzy":
                row[f"{src}_status"]     = "fuzzy"
                row[f"{src}_matched"]    = None
                row[f"{src}_suggestion"] = result[0]
                row[f"{src}_score"]      = result[1]
            else:  # possible
                row[f"{src}_status"]     = "possible"
                row[f"{src}_matched"]    = None
                row[f"{src}_suggestion"] = result[0]
                row[f"{src}_score"]      = result[1]

        rows.append(row)

    return pd.DataFrame(rows)


def issues_only(report: pd.DataFrame, sources: list[str]) -> pd.DataFrame:
    """Return rows where at least one source has a non-exact match."""
    bad_statuses = {"fuzzy", "possible", "unmatched"}
    mask = report[[f"{s}_status" for s in sources if f"{s}_status" in report.columns]].isin(bad_statuses).any(axis=1)
    return report[mask].reset_index(drop=True)


def summary_counts(report: pd.DataFrame, sources: list[str]) -> dict[str, dict[str, int]]:
    """Return {source: {status: count}} counts."""
    result = {}
    for src in sources:
        col = f"{src}_status"
        if col not in report.columns:
            continue
        counts = report[col].value_counts().to_dict()
        result[src] = counts
    return result


def apply_overrides_to_key(
    key: str,
    source: str,
    report: pd.DataFrame,
    manual_overrides: dict[str, str],
) -> str:
    """
    Given a master key and source, return the resolved key to use for lookups.
    Falls back to the key itself if no override and exact/normalised matched.
    """
    override_key = f"{source}::{key}"
    if override_key in manual_overrides:
        return manual_overrides[override_key]

    col_status    = f"{source}_status"
    col_matched   = f"{source}_matched"
    col_suggestion = f"{source}_suggestion"

    row = report[report["master_key"] == key]
    if row.empty:
        return key

    status = row.iloc[0].get(col_status, "unmatched")
    if status in ("exact", "normalised", "manual"):
        return row.iloc[0].get(col_matched) or key
    if status == "fuzzy":
        # auto-use suggestion only if it's the only candidate — otherwise need manual confirm
        return row.iloc[0].get(col_suggestion) or key
    return key


# ---------------------------------------------------------------------------
# Subject name matching
# ---------------------------------------------------------------------------

# Lowercase → canonical subject name.  Only the most common abbreviations;
# the canonical names mirror the subject_profiles.py constants exactly.
_SUBJECT_ALIASES: dict[str, str] = {
    "maths": "Mathematics",
    "math": "Mathematics",
    "further maths": "Further Mathematics",
    "further math": "Further Mathematics",
    "f/maths": "Further Mathematics",
    "further maths (as)": "Further Mathematics",
    "eng lang": "English Language",
    "english lang": "English Language",
    "eng lit": "English Literature",
    "english lit": "English Literature",
    "english lang & lit": "English Language",
    "bio": "Biology",
    "chem": "Chemistry",
    "phys": "Physics",
    "hist": "History",
    "geo": "Geography",
    "geog": "Geography",
    "econ": "Economics",
    "computer science": "Computing",
    "i.t.": "Computing",
    "it": "Computing",
    "information technology": "Computing",
    "pe": "Physical Education",
    "p.e.": "Physical Education",
    "sport": "Physical Education",
    "sports": "Physical Education",
    "d&t": "Design Technology",
    "design & technology": "Design Technology",
    "design and technology": "Design Technology",
    "dt": "Design Technology",
    "re": "Religion Philosophy And Ethics",
    "rs": "Religion Philosophy And Ethics",
    "religious studies": "Religion Philosophy And Ethics",
    "religion philosophy and ethics": "Religion Philosophy And Ethics",
    "religion, philosophy and ethics": "Religion Philosophy And Ethics",
    "rpe": "Religion Philosophy And Ethics",
    "philosophy and ethics": "Religion Philosophy And Ethics",
    "ethics": "Religion Philosophy And Ethics",
    "classical civ": "Classical Civilisation",
    "classics": "Classical Civilisation",
    "psych": "Psychology",
    "business": "Business Studies",
    "business studies": "Business Studies",
    "business & management": "Business Studies",
    "art & design": "Art",
    "art and design": "Art",
    "fine art": "Art",
    "media": "Media Studies",
    "film": "Film Studies",
    "politics": "Politics",
    "gov & politics": "Politics",
    "government & politics": "Politics",
    "government and politics": "Politics",
    "phil": "Philosophy",
    "sociology": "Sociology",
    "soc": "Sociology",
    "spanish": "Spanish",
    "french": "French",
    "german": "German",
    "latin": "Latin",
    "drama": "Drama",
    "music": "Music",
}


def normalise_subject(name: str) -> str:
    """Strip, collapse whitespace, and resolve common abbreviations."""
    s = name.strip()
    lower = re.sub(r"\s+", " ", s.lower().rstrip("."))
    return _SUBJECT_ALIASES.get(lower, s)


def match_subjects(
    source_subjects: list[str],
    canonical_subjects: list[str],
    threshold: float = 0.82,
) -> dict[str, tuple[str, float, str]]:
    """
    Match each source subject name to the closest canonical name.

    Returns
    -------
    {source_name: (canonical_name, score, match_type)}
    match_type: "exact" | "alias" | "fuzzy" | "possible" | "unmatched"
    """
    if not canonical_subjects:
        return {s: (s, 0.0, "unmatched") for s in source_subjects}

    canonical_lower = {c.lower().strip(): c for c in canonical_subjects}
    result: dict[str, tuple[str, float, str]] = {}

    for src in source_subjects:
        src_clean = src.strip()

        # 1. Exact
        if src_clean in canonical_subjects:
            result[src_clean] = (src_clean, 1.0, "exact")
            continue

        # 2. Case-insensitive exact
        src_lower = src_clean.lower().strip()
        if src_lower in canonical_lower:
            result[src_clean] = (canonical_lower[src_lower], 0.99, "exact")
            continue

        # 3. Alias
        aliased = normalise_subject(src_clean)
        if aliased in canonical_subjects:
            result[src_clean] = (aliased, 0.95, "alias")
            continue

        # 4. Fuzzy sequence similarity
        scored = [
            (c, difflib.SequenceMatcher(None, src_lower, c.lower()).ratio())
            for c in canonical_subjects
        ]
        best_c, best_s = max(scored, key=lambda x: x[1])
        if best_s >= threshold:
            result[src_clean] = (best_c, round(best_s, 3), "fuzzy")
        elif best_s >= 0.55:
            result[src_clean] = (best_c, round(best_s, 3), "possible")
        else:
            result[src_clean] = (best_c, round(best_s, 3), "unmatched")

    return result


def build_subject_map(
    subject_matches: dict[str, tuple[str, float, str]],
    manual_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """
    Build a final {source_name: canonical_name} map from match results and
    any user-confirmed overrides.  Auto-accepts exact and alias matches.
    """
    overrides = manual_overrides or {}
    mapping: dict[str, str] = {}
    for src, (canon, _score, mtype) in subject_matches.items():
        if src in overrides:
            mapping[src] = overrides[src]
        elif mtype in ("exact", "alias"):
            mapping[src] = canon
        # fuzzy / possible / unmatched — only accepted if user confirmed via override
    return mapping


def resolve_student_keys(
    df: pd.DataFrame,
    surname_col: str,
    forename_col: str,
    manual_remap: dict[str, str] | None = None,
) -> pd.Series:
    """
    Return a Series of resolved canonical keys for each row.

    manual_remap maps canonical_key → source_key (output of _extract_remap).
    This function inverts it and also applies normalised key matching as a
    fallback, so apostrophes, hyphens, and accents are handled automatically.
    """
    remap = manual_remap or {}
    # Invert: source_key → canonical_key
    inv_remap = {v: k for k, v in remap.items()}
    # Normalised version of the same inversion
    norm_inv = {normalise_key(v): k for k, v in remap.items()}

    raw = (
        df[surname_col].astype(str).str.strip().str.lower()
        + "|"
        + df[forename_col].astype(str).str.strip().str.lower()
    )

    def _resolve(key: str) -> str:
        if key in inv_remap:
            return inv_remap[key]
        nk = normalise_key(key)
        if nk in norm_inv:
            return norm_inv[nk]
        # Normalised self — e.g. "o'brien|alice" → "obrien|alice"
        return nk

    return raw.map(_resolve)
