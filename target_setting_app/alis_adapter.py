"""ALIS Adapt percentile prediction file: parser and lookup utilities."""

from __future__ import annotations

import pandas as pd

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
    ):
        self.data = data
        self.percentile = percentile
        self.proxy_map = proxy_map if proxy_map is not None else DEFAULT_PROXY_MAP.copy()
        self._build_index()

    def _build_index(self) -> None:
        """Build a key→row dict for fast lookups."""
        self._index: dict[str, pd.Series] = {}
        df = self.data.get(self.percentile)
        if df is None:
            return
        for _, row in df.iterrows():
            key = str(row["_key"])
            self._index[key] = row

    @property
    def available_subjects(self) -> list[str]:
        df = self.data.get(self.percentile)
        if df is None:
            return []
        return [c for c in df.columns if c not in ("_key", "_name", "baseline")]

    def get_grade(self, name_key: str, subject: str) -> str | None:
        """
        Return ALIS-predicted grade letter for student (name_key = "surname|firstname")
        and subject (app name). Returns None if not found or not enrolled.
        Applies proxy mapping automatically.
        """
        # Resolve proxy if needed
        lookup_subject = subject
        if subject not in self.available_subjects:
            proxy = self.proxy_map.get(subject)
            if proxy:
                lookup_subject = proxy
            else:
                return None

        row = self._index.get(name_key)
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
        row = self._index.get(name_key)
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
        """Return student keys that have no ALIS entry."""
        return [k for k in student_keys if k not in self._index]
