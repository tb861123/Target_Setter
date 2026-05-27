"""Parser and lookup for Yellis GCSE per-student predictions file.

The CEM file has 4 sheets:
  Standard Score   — 50th-percentile decimal predictions (e.g. 7.1, 8.3)
  Standard Grade   — 50th-percentile grade boundaries (e.g. 7, 7/8, 8/9)
  Top 25% Score    — 75th-percentile decimal predictions
  Top 25% Grade    — 75th-percentile grade boundaries

``parse_yellis_gcse_predictions`` reads the file and returns per-percentile
DataFrames.  ``YellisGCSELookup`` wraps them with a name×subject look-up API
compatible with how the rest of the app uses ALISLookup.
"""

from __future__ import annotations

import pandas as pd

from data_ingestion import _available_sheets, _find_col

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Non-subject columns that appear in all/some sheets
_META_COLS_LOWER: frozenset[str] = frozenset({
    "student", "surname", "forename", "sex", "dob", "form",
    "cem id", "cust", "reading score", "maths score", "science score",
    "yellis score", "yellis band", "attainment 8", "ebacc aps",
})

# Map from our internal subject names (lower-case) → predictions file column names (lower-case)
_SUBJECT_ALIASES: dict[str, str] = {
    "art": "art & design",
    "computing": "computer science",
    "design technology": "design & technology",
    "english language": "english",
    "religion philosophy and ethics": "religious studies",
    "double science 1": "combined science (double award)",
    "double science 2": "combined science (double award)",
}

# Canonical sheet name sets (lower-cased for matching)
_SHEET_KEYS: dict[str, list[str]] = {
    "standard_score": ["standard score", "standard scores"],
    "top25_score":    ["top 25% score", "top 25% scores"],
    "standard_grade": ["standard grade", "standard grades"],
    "top25_grade":    ["top 25% grade", "top 25% grades"],
}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_yellis_gcse_predictions(
    file,
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """
    Parse the Yellis GCSE predictions Excel file.

    Returns
    -------
    data : dict with keys 'standard_score', 'top25_score', 'standard_grade',
           'top25_grade'.  Each value is a DataFrame with columns
           [Surname, Forename, Yellis_Score, <subject>, ...].
           Missing sheets are absent from the dict.
    warnings : list of warning strings.
    """
    warnings: list[str] = []

    sheets = _available_sheets(file)
    lower_sheets: dict[str, str] = {s.lower(): s for s in sheets}

    def _find_sheet(candidates: list[str]) -> str | None:
        for c in candidates:
            if c in lower_sheets:
                return lower_sheets[c]
        return None

    data: dict[str, pd.DataFrame] = {}

    for key, candidates in _SHEET_KEYS.items():
        sheet = _find_sheet(candidates)
        if sheet is None:
            warnings.append(f"Sheet not found (expected: '{candidates[0]}') — skipped.")
            continue

        try:
            file.seek(0)
        except Exception:
            pass

        df = pd.read_excel(file, sheet_name=sheet, header=1)
        df.columns = [str(c).strip() for c in df.columns]

        surname_col = _find_col(df, ["Surname", "surname"])
        forename_col = _find_col(df, ["Forename", "Firstname", "forename"])
        yellis_col = _find_col(df, ["Yellis Score", "Yellis score"])

        if not surname_col or not forename_col:
            warnings.append(f"Could not find Surname/Forename columns in sheet '{sheet}' — skipped.")
            continue

        # Subject columns = everything not metadata and not Unnamed
        subj_cols = [
            c for c in df.columns
            if c.lower().strip() not in _META_COLS_LOWER
            and not c.startswith("Unnamed")
        ]

        keep_cols = [surname_col, forename_col]
        rename_map = {surname_col: "Surname", forename_col: "Forename"}
        if yellis_col:
            keep_cols.append(yellis_col)
            rename_map[yellis_col] = "Yellis_Score"
        keep_cols.extend(subj_cols)

        df = df[keep_cols].copy().rename(columns=rename_map)

        df["Surname"] = df["Surname"].astype(str).str.strip()
        df["Forename"] = df["Forename"].astype(str).str.strip()
        df = df[
            (df["Surname"].str.lower() != "nan")
            & (df["Forename"].str.lower() != "nan")
            & (df["Surname"] != "")
        ]

        # Numeric conversion for score sheets only (grade sheets stay as strings)
        if key.endswith("_score"):
            for col in subj_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            if "Yellis_Score" in df.columns:
                df["Yellis_Score"] = pd.to_numeric(df["Yellis_Score"], errors="coerce")
        else:
            # Grade sheets: keep as string for boundary parsing
            for col in subj_cols:
                if col in df.columns:
                    df[col] = df[col].astype(str).str.strip().replace("nan", pd.NA)

        df = df.reset_index(drop=True)
        data[key] = df

    found = list(data.keys())
    if found:
        warnings.insert(0, f"Loaded Yellis GCSE predictions: {', '.join(found)}.")

    return data, warnings


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def _norm_name_key(surname: str, forename: str) -> str:
    return surname.strip().lower() + "|" + forename.strip().lower()


def _parse_grade_boundary(val: str | float, bound: str = "lower") -> int | None:
    """
    Parse a grade boundary string like '7', '7/8', '8/9'.
    bound='lower' returns the first number, 'upper' returns the second.
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return None
    if "/" in s:
        parts = s.split("/")
        try:
            nums = [int(p.strip()) for p in parts if p.strip().isdigit()]
        except ValueError:
            return None
        if not nums:
            return None
        return min(nums) if bound == "lower" else max(nums)
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


class YellisGCSELookup:
    """
    Per-student, per-subject GCSE grade look-up from Yellis predictions.

    Parameters
    ----------
    data : dict returned by parse_yellis_gcse_predictions
    percentile : 'standard' (50th) or 'top25' (75th percentile)
    source : 'score' (decimal, rounded) or 'grade' (grade boundary strings)
    grade_bound : 'lower' or 'upper' — used when source='grade' to resolve
                  boundary strings like '7/8'.  Default 'lower' (conservative).
    """

    def __init__(
        self,
        data: dict[str, pd.DataFrame],
        percentile: str = "standard",
        source: str = "score",
        grade_bound: str = "lower",
        key_remap: dict[str, str] | None = None,
    ):
        self.percentile = percentile
        self.source = source
        self.grade_bound = grade_bound
        self.key_remap = key_remap or {}

        sheet_key = f"{percentile}_{source}"
        if sheet_key not in data:
            # Fallback: try the other source
            alt = f"{percentile}_{'grade' if source == 'score' else 'score'}"
            if alt in data:
                sheet_key = alt
                self.source = "grade" if source == "score" else "score"
            else:
                self._df = None
                self._index: dict[str, int] = {}
                self._subj_norm: dict[str, str] = {}
                return

        self._df = data[sheet_key].copy()
        self._build_index()

    def _build_index(self) -> None:
        self._index = {}
        for i, row in self._df.iterrows():
            key = _norm_name_key(row["Surname"], row["Forename"])
            self._index[key] = int(i)

        # Subject column → normalised name lookup
        meta = {"surname", "forename", "yellis_score"}
        self._subj_norm = {
            col.lower().strip(): col
            for col in self._df.columns
            if col.lower() not in meta
        }

    def _resolve_name(self, name_key: str) -> int | None:
        """Returns row index for a name key, respecting key_remap."""
        effective = self.key_remap.get(name_key, name_key)
        return self._index.get(effective)

    def _resolve_subject(self, subject: str) -> str | None:
        """Return the actual column name for a subject (case-insensitive + aliases)."""
        norm = subject.lower().strip()
        if norm in self._subj_norm:
            return self._subj_norm[norm]
        alias = _SUBJECT_ALIASES.get(norm)
        if alias and alias in self._subj_norm:
            return self._subj_norm[alias]
        return None

    def get_grade(self, name_key: str, subject: str) -> int | None:
        """Return predicted GCSE grade (1-9) for a student × subject, or None."""
        if self._df is None:
            return None
        row_idx = self._resolve_name(name_key)
        if row_idx is None:
            return None
        col = self._resolve_subject(subject)
        if col is None:
            return None
        val = self._df.at[row_idx, col]
        if self.source == "score":
            try:
                f = float(val)
                if pd.isna(f):
                    return None
                return max(1, min(9, int(round(f))))
            except (TypeError, ValueError):
                return None
        else:
            return _parse_grade_boundary(val, self.grade_bound)

    def get_baseline(self, name_key: str) -> float | None:
        """Return Yellis Score for a student, or None."""
        if self._df is None or "Yellis_Score" not in self._df.columns:
            return None
        row_idx = self._resolve_name(name_key)
        if row_idx is None:
            return None
        val = self._df.at[row_idx, "Yellis_Score"]
        try:
            f = float(val)
            return None if pd.isna(f) else f
        except (TypeError, ValueError):
            return None

    def unmatched_keys(self, keys: list[str]) -> list[str]:
        """Return names from keys that are not in the predictions file."""
        if self._df is None:
            return list(keys)
        return [k for k in keys if self._resolve_name(k) is None]

    @property
    def available_subjects(self) -> list[str]:
        """Subject column names as they appear in the predictions file."""
        if self._df is None:
            return []
        meta = {"surname", "forename", "yellis_score"}
        return [c for c in self._df.columns if c.lower() not in meta]

    @property
    def student_count(self) -> int:
        return 0 if self._df is None else len(self._df)
