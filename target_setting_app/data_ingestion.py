"""File parsing logic for Yellis GCSE, Yellis A Level, GCSE grades, subject lists, and ALIS Adapt."""

from __future__ import annotations

import pandas as pd


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _available_sheets(file) -> list[str]:
    """Return sheet names from an Excel file, resetting file position afterwards."""
    try:
        xl = pd.ExcelFile(file)
        sheets = xl.sheet_names
        try:
            file.seek(0)
        except Exception:
            pass
        return sheets
    except Exception:
        return []


def _resolve_sheet(file, expected: str) -> str:
    """
    Return `expected` if it exists in the file.
    Falls back to a case-insensitive match.
    Raises ValueError listing available sheets if nothing matches.
    """
    sheets = _available_sheets(file)
    if not sheets:
        return expected  # let the downstream read fail naturally
    if expected in sheets:
        return expected
    lower_map = {s.lower(): s for s in sheets}
    if expected.lower() in lower_map:
        return lower_map[expected.lower()]
    raise ValueError(
        f"Sheet '{expected}' not found. Available sheets: {sheets}"
    )


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Case-insensitive column search across a list of candidate names."""
    lower_map = {c.lower(): c for c in df.columns}
    for name in candidates:
        if name in df.columns:
            return name
        if name.lower() in lower_map:
            return lower_map[name.lower()]
    return None


# ---------------------------------------------------------------------------
# Yellis GCSE (Year 10)
# ---------------------------------------------------------------------------

def parse_yellis_gcse(
    file,
    sheet_name: str = "Sheet1",
) -> tuple[pd.DataFrame, list[str]]:
    """
    Parse the Yellis GCSE baseline Excel file.
    Returns (dataframe, list_of_warnings).

    Args:
        sheet_name: Sheet to read (default 'Sheet1'). Pass an alternative name
                    if the CEM export uses a different sheet.
    """
    warnings: list[str] = []
    sheet = _resolve_sheet(file, sheet_name)
    try:
        file.seek(0)
    except Exception:
        pass

    raw = pd.read_excel(file, sheet_name=sheet, header=None)

    if raw.shape[1] < 13:
        warnings.append(
            f"Expected at least 13 columns in Yellis GCSE file, found {raw.shape[1]}. "
            "Results may be incomplete."
        )

    cols = [
        "surname", "forename", "form", "sex",
        "overall_score", "overall_band",
        "vocab_score", "vocab_band",
        "maths_score", "maths_band",
        "patterns_score", "patterns_band",
        "range",
    ]
    actual_cols = cols[: raw.shape[1]]
    raw = raw.iloc[3:].reset_index(drop=True)
    raw.columns = range(raw.shape[1])
    df = raw.iloc[:, : len(actual_cols)].copy()
    df.columns = actual_cols

    numeric_cols = ["overall_score", "vocab_score", "maths_score", "patterns_score", "range"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["surname", "forename"])
    df["surname"] = df["surname"].astype(str).str.strip()
    df["forename"] = df["forename"].astype(str).str.strip()
    df = df[df["surname"].str.lower() != "nan"]
    df = df.reset_index(drop=True)

    for col in ["vocab_score", "maths_score", "patterns_score"]:
        if col in df.columns and df[col].isna().all():
            warnings.append(f"Sub-score column '{col}' is entirely empty — will use overall score only.")

    return df, warnings


# ---------------------------------------------------------------------------
# Yellis A Level (Year 12)
# ---------------------------------------------------------------------------

def parse_yellis_alevel(
    file,
    sheet_name: str = "Data",
) -> tuple[pd.DataFrame, list[str]]:
    """
    Parse the Yellis A Level (ALIS) baseline Excel file.
    Returns (dataframe, list_of_warnings).

    Args:
        sheet_name: Sheet to read (default 'Data'). Pass an alternative name if needed.
    """
    warnings: list[str] = []
    sheet = _resolve_sheet(file, sheet_name)
    try:
        file.seek(0)
    except Exception:
        pass

    raw = pd.read_excel(file, sheet_name=sheet, header=None)

    cols = [
        "code", "surname", "firstname", "gender", "dob",
        "overall_score", "overall_band",
        "vocab_score", "vocab_band",
        "maths_score", "maths_band",
        "nonverbal_score", "nonverbal_band",
    ]
    actual_cols = cols[: raw.shape[1]]
    raw = raw.iloc[3:].reset_index(drop=True)
    raw.columns = range(raw.shape[1])
    df = raw.iloc[:, : len(actual_cols)].copy()
    df.columns = actual_cols

    numeric_cols = ["overall_score", "vocab_score", "maths_score", "nonverbal_score"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["surname", "firstname"])
    df["surname"] = df["surname"].astype(str).str.strip()
    df["firstname"] = df["firstname"].astype(str).str.strip()
    df = df[df["surname"].str.lower() != "nan"]
    df = df.reset_index(drop=True)

    return df, warnings


# ---------------------------------------------------------------------------
# GCSE Grades (iSams import — A Level mode)
# ---------------------------------------------------------------------------

# Accepted column-name synonyms searched in order (case-insensitive)
_GCSE_GRADE_COL_SYNONYMS: dict[str, list[str]] = {
    "Surname":  ["Surname", "Last Name", "LastName", "Family Name", "FamilyName",
                 "Pupil Surname", "Student Surname", "Last"],
    "Forename": ["Forename", "First Name", "FirstName", "Given Name", "GivenName",
                 "Pupil Forename", "Student Forename", "Preferred Name", "First", "Firstname"],
    "Subject":  ["Subject", "Course", "Module", "SubjectName", "Subject Name"],
    "Grade":    ["Grade", "Mark", "Score", "Result", "Grade Value", "GradeValue"],
}


def parse_gcse_grades(
    file,
    sheet_name: str = "iSams import",
    col_map: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Parse the iSams GCSE grades import file.
    Returns (wide-format dataframe, list_of_warnings).
    Columns: Surname, Forename, <subject1>, <subject2>, ...

    Args:
        sheet_name: Sheet to read (default 'iSams import').
        col_map:    Explicit {standard_name: actual_col_name} overrides.
                    Keys: 'Surname', 'Forename', 'Subject', 'Grade'.
    """
    warnings: list[str] = []
    sheet = _resolve_sheet(file, sheet_name)
    try:
        file.seek(0)
    except Exception:
        pass

    # Try header=1 (row 2 is the header, common iSams layout)
    raw = pd.read_excel(file, sheet_name=sheet, header=1)

    # If key columns not found, retry with header=0 (row 1 is the header)
    def _col_score(df: pd.DataFrame) -> int:
        return sum(
            1 for syns in _GCSE_GRADE_COL_SYNONYMS.values()
            if any(s.lower() in [c.lower() for c in df.columns] for s in syns)
        )

    if _col_score(raw) < 3:
        try:
            file.seek(0)
        except Exception:
            pass
        raw2 = pd.read_excel(file, sheet_name=sheet, header=0)
        if _col_score(raw2) > _col_score(raw):
            raw = raw2

    # Resolve column names
    resolved: dict[str, str] = dict(col_map or {})
    for std_name, synonyms in _GCSE_GRADE_COL_SYNONYMS.items():
        if std_name not in resolved:
            found = _find_col(raw, synonyms)
            if found:
                resolved[std_name] = found

    missing = [s for s in ["Surname", "Forename", "Subject", "Grade"] if s not in resolved]
    if missing:
        raise ValueError(
            f"GCSE grades file: could not find columns {missing}. "
            f"Columns in file: {raw.columns.tolist()}. "
            f"Use the column-mapping option to specify the correct names."
        )

    df = raw[[resolved[s] for s in ["Surname", "Forename", "Subject", "Grade"]]].copy()
    df.columns = ["Surname", "Forename", "Subject", "Grade"]

    df["Surname"] = df["Surname"].ffill()
    df["Forename"] = df["Forename"].ffill()
    df = df.dropna(subset=["Subject", "Grade"])
    df["Subject"] = df["Subject"].astype(str).str.strip().str.title()
    df["Grade"] = pd.to_numeric(df["Grade"], errors="coerce")
    df = df.dropna(subset=["Grade"])
    df["Grade"] = df["Grade"].astype(int)

    known = {
        "Art", "Biology", "Chemistry", "Classical Civilisation", "Computing",
        "Design Technology", "Double Science 1", "Double Science 2", "Drama",
        "Economics", "English Language", "English Literature", "French",
        "Further Mathematics", "Geography", "German", "History", "Latin",
        "Mathematics", "Music", "Physical Education", "Physics",
        "Religion Philosophy And Ethics", "Spanish",
    }
    found_subjects = set(df["Subject"].unique())
    unknown = found_subjects - known
    if unknown:
        warnings.append(f"Unrecognised GCSE subjects (will be included as-is): {sorted(unknown)}")

    gcse_wide = (
        df.pivot_table(
            index=["Surname", "Forename"],
            columns="Subject",
            values="Grade",
            aggfunc="first",
        )
        .reset_index()
    )
    gcse_wide.columns.name = None
    return gcse_wide, warnings


# ---------------------------------------------------------------------------
# Subject list
# ---------------------------------------------------------------------------

_SURNAME_CANDIDATES = [
    "Surname", "surname", "Last Name", "last_name", "LastName",
    "Family Name", "FamilyName", "Pupil Surname", "Student Surname",
]
_FORENAME_CANDIDATES = [
    "Forename", "forename", "First Name", "firstname", "first_name",
    "Firstname", "Given Name", "GivenName", "Pupil Forename",
    "Student Forename", "Preferred Name", "PreferredName",
]
_STUDENT_NAME_CANDIDATES = [
    "Student Name", "student_name", "Name", "name",
    "Pupil Name", "PupilName", "Full Name", "FullName",
]


def parse_subject_list(file) -> tuple[pd.DataFrame, str, list[str]]:
    """
    Parse student subject list file (CSV or Excel).
    Auto-detects long (comma-separated subjects) or wide (binary columns) format.
    Returns (dataframe[surname, forename, subjects], format_detected, warnings).
    """
    warnings: list[str] = []

    fname = getattr(file, "name", "")
    if fname.lower().endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    df.columns = [str(c).strip() for c in df.columns]

    surname_col = _find_col(df, _SURNAME_CANDIDATES)
    forename_col = _find_col(df, _FORENAME_CANDIDATES)
    student_name_col = _find_col(df, _STUDENT_NAME_CANDIDATES)

    if surname_col and forename_col:
        df = df.rename(columns={surname_col: "surname", forename_col: "forename"})
    elif student_name_col:
        name_parts = df[student_name_col].str.split(",", expand=True)
        if name_parts.shape[1] >= 2:
            df["surname"] = name_parts[0].str.strip()
            df["forename"] = name_parts[1].str.strip()
        else:
            name_parts2 = df[student_name_col].str.split(" ", expand=True)
            df["forename"] = name_parts2[0].str.strip()
            df["surname"] = name_parts2.iloc[:, 1:].apply(
                lambda r: " ".join(r.dropna().astype(str)), axis=1
            )
        df = df.drop(columns=[student_name_col])
        warnings.append("Split 'Student Name' column into surname and forename — please verify.")
    else:
        raise ValueError(
            "Cannot find name columns. Expected 'Surname' + 'Forename' (or variants such as "
            "'Last Name'/'First Name', 'Pupil Surname'/'Pupil Forename') or a single "
            "'Student Name' / 'Name' column."
        )

    non_name_cols = [c for c in df.columns if c not in ("surname", "forename")]
    format_detected = _detect_subject_format(df, non_name_cols)

    if format_detected == "long":
        subj_col = _find_col(df, non_name_cols) or non_name_cols[0]
        df["subjects"] = df[subj_col].apply(
            lambda v: [s.strip() for s in str(v).split(",") if s.strip()] if pd.notna(v) else []
        )
    else:
        binary_cols = non_name_cols
        df["subjects"] = df[binary_cols].apply(
            lambda row: [col for col in binary_cols if _is_truthy(row[col])],
            axis=1,
        )

    df = df[["surname", "forename", "subjects"]].copy()
    df["surname"] = df["surname"].astype(str).str.strip()
    df["forename"] = df["forename"].astype(str).str.strip()
    df = df[(df["surname"].str.lower() != "nan") & df["surname"].notna()]
    df = df.reset_index(drop=True)

    return df, format_detected, warnings


def _is_truthy(val) -> bool:
    if pd.isna(val):
        return False
    if isinstance(val, (int, float)):
        return bool(val)
    return str(val).strip().upper() in ("1", "Y", "YES", "TRUE", "X", "✓")


def _detect_subject_format(df: pd.DataFrame, non_name_cols: list[str]) -> str:
    """Return 'long' or 'wide'."""
    if len(non_name_cols) == 0:
        return "wide"
    if len(non_name_cols) == 1:
        col = non_name_cols[0]
        sample = df[col].dropna().head(5)
        if sample.apply(lambda v: "," in str(v)).any():
            return "long"

    _BINARY_STRINGS = {"0", "1", "Y", "N", "YES", "NO", "TRUE", "FALSE", "X", ""}

    def _is_binary_val(v) -> bool:
        if pd.isna(v):
            return True
        if isinstance(v, (int, float)):
            return v in (0, 1, 0.0, 1.0)
        return str(v).strip().upper() in _BINARY_STRINGS

    # Score binary-ness across up to 5 subject columns for robustness
    cols_to_check = non_name_cols[:min(5, len(non_name_cols))]
    scores = []
    for col in cols_to_check:
        vals = df[col].head(20)
        if len(vals) == 0:
            continue
        scores.append(vals.apply(_is_binary_val).mean())

    if scores and (sum(scores) / len(scores)) > 0.6:
        return "wide"
    return "long"


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

def match_students(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
    source_surname: str = "surname",
    source_forename: str = "forename",
    target_surname: str = "surname",
    target_forename: str = "forename",
) -> tuple[pd.DataFrame, list[str]]:
    """Left-join source onto target on normalised name key."""
    s = source_df.copy()
    t = target_df.copy()

    s["_key"] = (
        s[source_surname].str.strip().str.lower()
        + "|"
        + s[source_forename].str.strip().str.lower()
    )
    t["_key"] = (
        t[target_surname].str.strip().str.lower()
        + "|"
        + t[target_forename].str.strip().str.lower()
    )

    merged = s.merge(t, on="_key", how="left", suffixes=("", "_y"))
    unmatched = merged[merged.isnull().any(axis=1)][source_surname].tolist()
    merged = merged.drop(columns=["_key"])
    merged = merged.drop(columns=[c for c in merged.columns if c.endswith("_y")])

    return merged, unmatched


# ---------------------------------------------------------------------------
# ALIS Adapt file (re-exported convenience wrapper)
# ---------------------------------------------------------------------------

def parse_alis_adapt(file):
    """Parse ALIS Adapt XLS/XLSX percentile file. Returns (data_by_percentile, warnings)."""
    from alis_adapter import parse_alis_adapt as _parse
    return _parse(file)
