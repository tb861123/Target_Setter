"""File parsing logic for Yellis GCSE, Yellis A Level, GCSE grades, and subject lists."""

from __future__ import annotations

import io
import pandas as pd


# ---------------------------------------------------------------------------
# Yellis GCSE (Year 10)
# ---------------------------------------------------------------------------

def parse_yellis_gcse(file) -> tuple[pd.DataFrame, list[str]]:
    """
    Parse the Yellis GCSE baseline Excel file.
    Returns (dataframe, list_of_warnings).
    """
    warnings: list[str] = []
    raw = pd.read_excel(file, sheet_name="Sheet1", header=None)

    if raw.shape[1] < 13:
        # Try to accommodate files with slightly different column counts
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
    # Pad if fewer columns
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

    # Warn about missing sub-scores
    for col in ["vocab_score", "maths_score", "patterns_score"]:
        if col in df.columns and df[col].isna().all():
            warnings.append(f"Sub-score column '{col}' is entirely empty — will use overall score only.")

    return df, warnings


# ---------------------------------------------------------------------------
# Yellis A Level (Year 12)
# ---------------------------------------------------------------------------

def parse_yellis_alevel(file) -> tuple[pd.DataFrame, list[str]]:
    """
    Parse the Yellis A Level (ALIS) baseline Excel file.
    Returns (dataframe, list_of_warnings).
    """
    warnings: list[str] = []
    raw = pd.read_excel(file, sheet_name="Data", header=None)

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

def parse_gcse_grades(file) -> tuple[pd.DataFrame, list[str]]:
    """
    Parse the iSams GCSE grades import file.
    Returns (wide-format dataframe, list_of_warnings).
    Columns: Surname, Forename, <subject1>, <subject2>, ...
    """
    warnings: list[str] = []

    raw = pd.read_excel(file, sheet_name="iSams import", header=1)
    needed = ["Surname", "Forename", "Subject", "Grade"]
    missing = [c for c in needed if c not in raw.columns]
    if missing:
        raise ValueError(f"GCSE grades file missing columns: {missing}")

    df = raw[["Surname", "Forename", "Subject", "Grade"]].copy()
    df["Surname"] = df["Surname"].ffill()
    df["Forename"] = df["Forename"].ffill()
    df = df.dropna(subset=["Subject", "Grade"])
    df["Subject"] = df["Subject"].astype(str).str.strip().str.title()
    df["Grade"] = pd.to_numeric(df["Grade"], errors="coerce")
    df = df.dropna(subset=["Grade"])
    df["Grade"] = df["Grade"].astype(int)

    # Warn about unexpected subjects
    known = {
        "Art", "Biology", "Chemistry", "Classical Civilisation", "Computing",
        "Design Technology", "Double Science 1", "Double Science 2", "Drama",
        "Economics", "English Language", "English Literature", "French",
        "Further Mathematics", "Geography", "German", "History", "Latin",
        "Mathematics", "Music", "Physical Education", "Physics",
        "Religion Philosophy And Ethics", "Spanish",
    }
    found = set(df["Subject"].unique())
    unknown = found - known
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

def parse_subject_list(file) -> tuple[pd.DataFrame, str, list[str]]:
    """
    Parse student subject list file (CSV or Excel).
    Auto-detects format: long (comma-separated subjects in one column)
    or wide (binary columns per subject).
    Returns (dataframe with columns [surname, forename, subjects_list], format_detected, warnings).
    'subjects_list' is a list of subject strings per student row.
    """
    warnings: list[str] = []

    fname = getattr(file, "name", "")
    if fname.lower().endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    df.columns = [c.strip() for c in df.columns]

    # Normalise name columns
    surname_col = _find_col(df, ["Surname", "surname", "Last Name", "last_name"])
    forename_col = _find_col(df, ["Forename", "forename", "First Name", "firstname", "first_name", "Firstname"])
    student_name_col = _find_col(df, ["Student Name", "student_name", "Name", "name"])

    if surname_col and forename_col:
        df = df.rename(columns={surname_col: "surname", forename_col: "forename"})
    elif student_name_col:
        # Split "Last, First" or "First Last"
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
            "Cannot find name columns. Expected 'Surname'+'Forename' or 'Student Name'."
        )

    non_name_cols = [c for c in df.columns if c not in ("surname", "forename")]

    # Detect format
    format_detected = _detect_subject_format(df, non_name_cols)

    if format_detected == "long":
        # Single subject-list column
        subj_col = _find_col(df, non_name_cols)
        df["subjects"] = df[subj_col].apply(
            lambda v: [s.strip() for s in str(v).split(",") if s.strip()] if pd.notna(v) else []
        )
    else:
        # Wide binary format
        binary_cols = non_name_cols
        df["subjects"] = df[binary_cols].apply(
            lambda row: [
                col
                for col in binary_cols
                if _is_truthy(row[col])
            ],
            axis=1,
        )

    return df[["surname", "forename", "subjects"]], format_detected, warnings


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


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
        # Likely long format — single subjects column
        col = non_name_cols[0]
        sample = df[col].dropna().head(5)
        if sample.apply(lambda v: "," in str(v)).any():
            return "long"
    # Check if columns look like subject names (wide format)
    # Heuristic: if values are mostly 0/1/Y/N then wide
    sample_col = non_name_cols[0]
    sample_vals = df[sample_col].dropna().head(20).astype(str).str.upper()
    binary_like = sample_vals.isin(["0", "1", "Y", "N", "YES", "NO", "TRUE", "FALSE", "X", ""]).mean()
    if binary_like > 0.7:
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
    """
    Left-join source onto target on normalised name.
    Returns merged df and list of unmatched source students.
    """
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
    # Drop duplicate cols from right side
    dup_cols = [c for c in merged.columns if c.endswith("_y")]
    merged = merged.drop(columns=dup_cols)

    return merged, unmatched
