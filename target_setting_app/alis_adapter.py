"""ALIS Adapt percentile prediction file: parser and lookup utilities."""

from __future__ import annotations

import re
import unicodedata

import pandas as pd


def _norm_key(key: str) -> str:
    """Normalise a surname|forename key: lowercase, strip accents/hyphens/apostrophes."""
    key = key.lower().strip()
    key = "".join(
        c for c in unicodedata.normalize("NFD", key)
        if unicodedata.category(c) != "Mn"
    )
    parts = key.split("|", 1)
    normed = [re.sub(r"[-''.`\s]", "", p) for p in parts]
    return "|".join(normed)

# ---------------------------------------------------------------------------
# Percentile sheet labels (as they appear in the file)
# ---------------------------------------------------------------------------
PERCENTILE_SHEETS = [
    "50th Percentile",
    "75th Percentile",
    "90th Percentile",
    "97th Percentile",
    "99th Percentile",
]

PERCENTILE_LABELS = ["50th", "75th", "90th", "97th", "99th"]

# ---------------------------------------------------------------------------
# Mapping from ALIS column names → app subject names
# ---------------------------------------------------------------------------
ALIS_TO_APP: dict[str, str] = {
    "A2-Art and Design - Fine Art": "Art",
    "A2-Art and Design (Photo.)": "Photography",
    "A2-Biology": "Biology",
    "A2-Business Studies: Single": "Business",
    "A2-Chemistry": "Chemistry",
    "A2-Classical Civilisation": "Classical Civilisation",
    "A2-Computing": "Computing",
    "A2-Drama And Theatre Studies": "Drama",
    "A2-DT Product Design": "Design Technology",
    "A2-Economics": "Economics",
    "A2-English Literature": "English Literature",
    "A2-French": "French",
    "A2-Geography": "Geography",
    "A2-Government And Politics": "Politics",
    "A2-History": "History",
    "A2-Latin": "Latin",
    "A2-Mathematics (Further)": "Further Mathematics",
    "A2-Mathematics": "Mathematics",
    "A2-Music": "Music",
    "A2-Physical Education": "PE",
    "A2-Physics": "Physics",
    "A2-Psychology": "Psychology",
    "A2-Religious Studies": "RPE",
    "A2-Spanish": "Spanish",
}

# Inverse map for lookups
APP_TO_ALIS: dict[str, str] = {v: k for k, v in ALIS_TO_APP.items()}

# ---------------------------------------------------------------------------
# Default proxy subjects for A Level subjects NOT present in the ALIS file.
# Key = app subject name, value = app subject name to use as proxy.
# ---------------------------------------------------------------------------
DEFAULT_PROXY_MAP: dict[str, str] = {
    "Film Studies": "English Literature",
    "German": "French",  # closest available MFL
    # Photography is in the file but rarely populated; proxy to Art if absent
    "Photography": "Art",
}

# All app subjects covered directly or via proxy
ALIS_COVERED_SUBJECTS = set(ALIS_TO_APP.values()) | set(DEFAULT_PROXY_MAP.keys())


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_alis_adapt(file) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """
    Parse an ALIS Adapt XLS file.

    Returns:
        (data_by_percentile, warnings)
        data_by_percentile: {percentile_label: DataFrame}
            Each DataFrame has columns:
                _key         - normalised "surname|firstname" for joining
                _name        - original StudentName
                baseline     - ALIS score (float)
                <subject>... - predicted grade (str A*/A/B/C/D/E or NaN)
            Subject columns use APP subject names (not ALIS column names).

    warnings: list of warning strings.
    """
    warnings: list[str] = []

    # Support both .xls and .xlsx
    fname = getattr(file, "name", str(file))
    engine = "xlrd" if str(fname).lower().endswith(".xls") else "openpyxl"

    try:
        xl = pd.ExcelFile(file, engine=engine)
    except Exception:
        # Fallback
        xl = pd.ExcelFile(file)

    found_sheets = [s for s in PERCENTILE_SHEETS if s in xl.sheet_names]
    if not found_sheets:
        raise ValueError(
            f"ALIS Adapt file does not contain expected sheets. "
            f"Expected one of: {PERCENTILE_SHEETS}. "
            f"Found: {xl.sheet_names}"
        )

    if len(found_sheets) < len(PERCENTILE_SHEETS):
        missing = set(PERCENTILE_SHEETS) - set(found_sheets)
        warnings.append(f"Some percentile sheets not found: {sorted(missing)}")

    data: dict[str, pd.DataFrame] = {}

    for sheet in found_sheets:
        raw = pd.read_excel(file, sheet_name=sheet, header=0, engine=engine)

        # Drop the redundant first data row if it's a repeated header
        if len(raw) > 0 and str(raw.iloc[0, 0]).strip().upper() in ("UID", ""):
            raw = raw.iloc[1:].reset_index(drop=True)

        raw = raw.dropna(subset=["StudentName"])
        raw = raw[raw["StudentName"].astype(str).str.strip() != ""]

        # Parse student name: "Surname, Firstname"
        names = raw["StudentName"].astype(str).str.strip()
        split = names.str.split(",", n=1, expand=True)
        surnames = split[0].str.strip().str.lower()
        firstnames = split[1].str.strip().str.lower() if split.shape[1] > 1 else pd.Series("", index=raw.index)

        df = pd.DataFrame()
        df["_key"] = surnames + "|" + firstnames
        df["_name"] = names
        df["baseline"] = pd.to_numeric(raw["baseline"], errors="coerce")

        # Map ALIS subject columns → app names
        for alis_col, app_name in ALIS_TO_APP.items():
            if alis_col in raw.columns:
                col_data = raw[alis_col].astype(str).str.strip()
                col_data = col_data.replace({"nan": None, "": None, "NaN": None})
                df[app_name] = col_data
            else:
                warnings.append(f"Sheet '{sheet}': ALIS column '{alis_col}' not found.")
                df[app_name] = None

        # Deduplicate on _key: keep row with highest (non-NaN) baseline
        df = df.sort_values("baseline", ascending=False, na_position="last")
        df = df.drop_duplicates(subset=["_key"], keep="first")

        # Short label for the percentile (e.g. "75th")
        label = sheet.replace(" Percentile", "")
        data[label] = df.reset_index(drop=True)

    return data, warnings


# ---------------------------------------------------------------------------
# Lookup helper
# ---------------------------------------------------------------------------

class ALISLookup:
    """
    Provides grade lookups from parsed ALIS Adapt data.

    Usage:
        lookup = ALISLookup(data_by_percentile, percentile="75th", proxy_map=...)
        grade = lookup.get_grade("smith|alice", "Mathematics")  # → "A" or None
    """

    def __init__(
        self,
        data: dict[str, pd.DataFrame],
        percentile: str = "75th",
        proxy_map: dict[str, str] | None = None,
        key_remap: dict[str, str] | None = None,
    ):
        self.data = data
        self.percentile = percentile
        self.proxy_map = proxy_map if proxy_map is not None else DEFAULT_PROXY_MAP.copy()
        self.key_remap = key_remap or {}
        self._build_index()

    def _build_index(self) -> None:
        """Build key→row and normalised-key→row dicts for fast lookups."""
        self._index: dict[str, pd.Series] = {}
        self._norm_index: dict[str, pd.Series] = {}
        df = self.data.get(self.percentile)
        if df is None:
            return
        for _, row in df.iterrows():
            key = str(row["_key"])
            self._index[key] = row
            norm = _norm_key(key)
            if norm not in self._norm_index:
                self._norm_index[norm] = row

    @property
    def available_subjects(self) -> list[str]:
        df = self.data.get(self.percentile)
        if df is None:
            return []
        return [c for c in df.columns if c not in ("_key", "_name", "baseline")]

    def _resolve_row(self, name_key: str) -> pd.Series | None:
        """Look up a student row by key, with remap and normalised fallback."""
        lookup_key = self.key_remap.get(name_key, name_key)
        row = self._index.get(lookup_key)
        if row is None:
            row = self._norm_index.get(_norm_key(lookup_key))
        return row

    def get_grade(self, name_key: str, subject: str) -> str | None:
        """
        Return ALIS-predicted grade letter for student (name_key = "surname|firstname")
        and subject (app name). Returns None if not found or not enrolled.
        Applies proxy mapping and normalised key fallback automatically.
        """
        # Resolve proxy if needed
        lookup_subject = subject
        if subject not in self.available_subjects:
            proxy = self.proxy_map.get(subject)
            if proxy:
                lookup_subject = proxy
            else:
                return None

        row = self._resolve_row(name_key)
        if row is None:
            return None

        val = row.get(lookup_subject)
        if val is None or str(val).lower() in ("nan", "none", ""):
            # Also try proxy for this student even if subject is in ALIS
            proxy = self.proxy_map.get(subject)
            if proxy and proxy != subject:
                val = row.get(proxy)
                if val is None or str(val).lower() in ("nan", "none", ""):
                    return None
            else:
                return None

        return str(val).strip()

    def get_baseline(self, name_key: str) -> float | None:
        row = self._resolve_row(name_key)
        if row is None:
            return None
        v = row.get("baseline")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def all_keys(self) -> list[str]:
        return list(self._index.keys())

    def unmatched_keys(self, student_keys: list[str]) -> list[str]:
        """Return student keys that have no ALIS entry (including normalised fallback)."""
        return [k for k in student_keys if self._resolve_row(k) is None]


# ---------------------------------------------------------------------------
# Blended lookup: merges ALIS-test predictions with GCSE-baseline predictions
# ---------------------------------------------------------------------------

_GRADE_NUM = {"A*": 6, "A": 5, "B": 4, "C": 3, "D": 2, "E": 1}
_GRADE_STR = {v: k for k, v in _GRADE_NUM.items()}


class ALISBlendedLookup:
    """
    Blends per-student grade predictions from two ALISLookup instances:
      • alis_lookup  — predictions based on ALIS aptitude test score
      • gcse_lookup  — predictions based on mean GCSE score

    For each student × subject, both numeric predictions are combined:
        blended = alis_weight × alis_num + gcse_weight × gcse_num

    When only one source has a prediction, that source is used alone.
    This object satisfies the same interface as ALISLookup so it is a
    drop-in replacement inside ALevelALISEngine.
    """

    def __init__(
        self,
        alis_lookup: ALISLookup,
        gcse_lookup: ALISLookup,
        alis_weight: float = 0.5,
        gcse_weight: float = 0.5,
    ):
        self.alis_lookup = alis_lookup
        self.gcse_lookup = gcse_lookup
        self.alis_weight = alis_weight
        self.gcse_weight = gcse_weight
        # Normalise weights
        total = alis_weight + gcse_weight
        if total > 0:
            self.alis_weight = alis_weight / total
            self.gcse_weight = gcse_weight / total

    @property
    def available_subjects(self) -> list[str]:
        a = set(self.alis_lookup.available_subjects)
        g = set(self.gcse_lookup.available_subjects)
        return sorted(a | g)

    def get_grade(self, name_key: str, subject: str) -> str | None:
        ag = self.alis_lookup.get_grade(name_key, subject)
        gg = self.gcse_lookup.get_grade(name_key, subject)

        if ag is None and gg is None:
            return None
        if ag is None:
            return gg
        if gg is None:
            return ag

        an = _GRADE_NUM.get(ag, 3)
        gn = _GRADE_NUM.get(gg, 3)
        blended = self.alis_weight * an + self.gcse_weight * gn
        return _GRADE_STR[max(1, min(6, round(blended)))]

    def get_baseline(self, name_key: str) -> float | None:
        """Return ALIS test score as the primary baseline (for display/sorting)."""
        return self.alis_lookup.get_baseline(name_key)

    def all_keys(self) -> list[str]:
        a = set(self.alis_lookup.all_keys())
        g = set(self.gcse_lookup.all_keys())
        return list(a | g)

    def unmatched_keys(self, student_keys: list[str]) -> list[str]:
        all_known = set(self.all_keys())
        return [k for k in student_keys if k not in all_known]
