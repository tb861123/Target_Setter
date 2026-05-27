"""Parser for historical GCSE / A Level results by subject.

Accepts two input layouts:

**Cumulative % format** (preferred — matches the downloadable template):
    GCSE:    Subject | [Year] | 9 | 8+ | 7+ | 6+ | 5+ | 4+ | 3+ | n
    A Level: Subject | [Year] | A* | A*-A | A*-B | A*-C | A*-D | A*-E | n
    Values are percentages of students at or above each threshold.

**Raw counts/% format** (legacy):
    GCSE:    Subject | [Year] | 9 | 8 | 7 | … | 1       (counts or %)
    A Level: Subject | [Year] | A* | A | B | C | D | E   (counts or %)

**Long format** (one row per subject × grade):
    Subject | [Year] | Grade | Count

All formats are normalised to a DataFrame with columns:
    Subject, Year, cum_pct_<threshold>..., n

``aggregate_historical`` collapses all years into a single per-subject row.
``compare_targets_to_historical`` builds a cumulative % comparison table.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

GCSE_GRADES: list[str] = [str(g) for g in range(9, 0, -1)]  # ["9","8",…,"1"]
ALEVEL_GRADES: list[str] = ["A*", "A", "B", "C", "D", "E"]

# Cumulative threshold labels
GCSE_CUM_LABELS: list[str] = [str(9)] + [f"{g}+" for g in range(8, 1, -1)]
ALEVEL_CUM_LABELS: list[str] = ["A*", "A*-A", "A*-B", "A*-C", "A*-D", "A*-E"]

# Which raw grades count toward each cumulative threshold
GCSE_CUM_SETS: dict[str, set] = {
    str(9): {9},
    **{f"{g}+": set(range(g, 10)) for g in range(8, 1, -1)},
}
ALEVEL_CUM_SETS: dict[str, set] = {
    "A*":   {"A*"},
    "A*-A": {"A*", "A"},
    "A*-B": {"A*", "A", "B"},
    "A*-C": {"A*", "A", "B", "C"},
    "A*-D": {"A*", "A", "B", "C", "D"},
    "A*-E": {"A*", "A", "B", "C", "D", "E"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lower = {c.lower().strip(): c for c in df.columns}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def _cum_labels_for(mode: str) -> list[str]:
    return GCSE_CUM_LABELS if mode == "GCSE" else ALEVEL_CUM_LABELS


def _cum_sets_for(mode: str) -> dict[str, set]:
    return GCSE_CUM_SETS if mode == "GCSE" else ALEVEL_CUM_SETS


def _is_cumulative_headers(df: pd.DataFrame, mode: str) -> bool:
    """Return True if the DataFrame columns contain cumulative threshold labels.

    Only checks labels containing "+" or "-" to avoid false-positive detection
    on raw grade columns like "9" which also appears in GCSE_CUM_LABELS.
    """
    cum_only = [l for l in _cum_labels_for(mode) if "+" in l or "-" in l]
    return bool(set(cum_only) & set(df.columns))


# ---------------------------------------------------------------------------
# Public parser
# ---------------------------------------------------------------------------

def parse_historical_results(
    file: Any,
    mode: str = "GCSE",
) -> tuple[pd.DataFrame, list[str]]:
    """
    Parse a historical results Excel/CSV file.

    Returns
    -------
    df        DataFrame[Subject, Year, cum_pct_<threshold>..., n]
    warnings  list of human-readable strings
    """
    warnings: list[str] = []

    try:
        file.seek(0)
    except Exception:
        pass

    # Try Excel first, auto-detecting preamble rows (templates have title+notes before headers)
    df_raw = None
    for skip in (0, 1, 2, 3):
        try:
            try:
                file.seek(0)
            except Exception:
                pass
            candidate = pd.read_excel(file, header=skip)
            candidate.columns = [str(c).strip() for c in candidate.columns]
            candidate = candidate.dropna(how="all")
            if _find_col(candidate, ["Subject", "subject", "SubjectName", "Subject Name", "Qualification"]) is not None:
                df_raw = candidate
                break
        except Exception:
            continue

    if df_raw is None:
        # Fall back to CSV
        for enc in ("utf-8", "latin-1"):
            try:
                try:
                    file.seek(0)
                except Exception:
                    pass
                df_raw = pd.read_csv(file, encoding=enc)
                df_raw.columns = [str(c).strip() for c in df_raw.columns]
                df_raw = df_raw.dropna(how="all")
                if _find_col(df_raw, ["Subject", "subject"]) is not None:
                    break
            except Exception:
                continue

    if df_raw is None or df_raw.empty:
        warnings.append("Could not read file or find a Subject column in any header row.")
        return pd.DataFrame(), warnings

    grade_col = _find_col(df_raw, ["Grade", "grade"])
    if grade_col:
        return _parse_long(df_raw, mode, warnings)

    if _is_cumulative_headers(df_raw, mode):
        return _parse_cumulative_wide(df_raw, mode, warnings)

    return _parse_raw_wide(df_raw, mode, warnings)


# ---------------------------------------------------------------------------
# Cumulative-% wide parser  (primary: template format)
# ---------------------------------------------------------------------------

def _parse_cumulative_wide(
    df: pd.DataFrame,
    mode: str,
    warnings: list[str],
) -> tuple[pd.DataFrame, list[str]]:
    """Parse a file where grade columns are cumulative threshold labels (8+, A*-A, etc.)."""
    cum_labels = _cum_labels_for(mode)
    subj_col = _find_col(df, ["Subject", "subject", "SubjectName", "Subject Name", "Qualification"])
    year_col = _find_col(df, ["Year", "year", "AcademicYear", "Academic Year", "Cohort"])
    n_col    = _find_col(df, ["n", "N", "Total", "Students", "total"])

    if subj_col is None:
        warnings.append("Could not find a Subject column.")
        return pd.DataFrame(), warnings

    rows: list[dict] = []
    for _, raw_row in df.iterrows():
        subj = str(raw_row[subj_col]).strip()
        if not subj or subj.lower() in ("nan", "subject", ""):
            continue
        year_val = str(raw_row[year_col]).strip() if year_col else "Historical"
        if year_val.lower() == "nan":
            year_val = "Historical"

        out: dict = {"Subject": subj, "Year": year_val}
        for label in cum_labels:
            col = _find_col(df, [label])
            try:
                v = float(raw_row[col]) if col else 0.0
                v = 0.0 if pd.isna(v) else v
            except (TypeError, ValueError):
                v = 0.0
            out[f"cum_pct_{label}"] = v

        try:
            n = float(raw_row[n_col]) if n_col else 0
            out["n"] = int(round(n)) if not pd.isna(n) else 0
        except (TypeError, ValueError):
            out["n"] = 0

        rows.append(out)

    if not rows:
        warnings.append("No data rows found.")
        return pd.DataFrame(), warnings

    result = pd.DataFrame(rows)
    warnings.insert(0, f"Loaded {len(result)} subject-year rows (cumulative % format).")
    return result, warnings


# ---------------------------------------------------------------------------
# Raw-count/% wide parser  (legacy)
# ---------------------------------------------------------------------------

def _parse_raw_wide(
    df: pd.DataFrame,
    mode: str,
    warnings: list[str],
) -> tuple[pd.DataFrame, list[str]]:
    """Parse raw grade count or % columns; convert to cumulative %."""
    grades = GCSE_GRADES if mode == "GCSE" else ALEVEL_GRADES
    cum_labels = _cum_labels_for(mode)
    cum_sets   = _cum_sets_for(mode)

    subj_col = _find_col(df, ["Subject", "subject", "SubjectName", "Subject Name", "Qualification"])
    year_col = _find_col(df, ["Year", "year", "AcademicYear", "Academic Year", "Cohort"])

    if subj_col is None:
        warnings.append("Could not find a Subject column.")
        return pd.DataFrame(), warnings

    grade_cols_present = [c for c in df.columns if c.strip() in set(grades)]
    if not grade_cols_present:
        warnings.append(
            f"No grade columns found (expected {', '.join(grades[:4])}… or {', '.join(cum_labels[:3])}…)."
        )
        return pd.DataFrame(), warnings

    rows: list[dict] = []
    for _, raw_row in df.iterrows():
        subj = str(raw_row[subj_col]).strip()
        if not subj or subj.lower() in ("nan", "subject", ""):
            continue
        year_val = str(raw_row[year_col]).strip() if year_col else "Historical"
        if year_val.lower() == "nan":
            year_val = "Historical"

        out: dict = {"Subject": subj, "Year": year_val}
        raw: dict = {}
        total = 0.0
        for g in grades:
            col = _find_col(df, [g])
            try:
                v = float(raw_row[col]) if col else 0.0
                v = 0.0 if pd.isna(v) else v
            except (TypeError, ValueError):
                v = 0.0
            raw[g] = v
            total += v

        # Heuristic: if sum ≈ 100, treat as per-grade %; else treat as counts
        non_zero = [raw[g] for g in grades if raw[g] > 0]
        row_sum = sum(non_zero)
        is_pct = bool(non_zero) and abs(row_sum - 100) <= 5

        if is_pct:
            out["n"] = 100
            pct = raw
        else:
            out["n"] = int(round(total)) if total > 0 else 0
            pct = {g: (raw[g] / total * 100) if total > 0 else 0.0 for g in grades}

        # Convert per-grade % to cumulative %
        if mode == "GCSE":
            grade_int_map = {g: int(g) for g in grades}
            for label in cum_labels:
                gs = cum_sets[label]
                out[f"cum_pct_{label}"] = sum(pct.get(g, 0.0) for g in grades if grade_int_map.get(g) in gs)
        else:
            for label in cum_labels:
                gs = cum_sets[label]
                out[f"cum_pct_{label}"] = sum(pct.get(g, 0.0) for g in grades if g in gs)

        rows.append(out)

    if not rows:
        warnings.append("No data rows found.")
        return pd.DataFrame(), warnings

    result = pd.DataFrame(rows)
    warnings.insert(0, f"Loaded {len(result)} subject-year rows (raw count format, converted to cumulative %).")
    return result, warnings


# ---------------------------------------------------------------------------
# Long parser
# ---------------------------------------------------------------------------

def _parse_long(
    df: pd.DataFrame,
    mode: str,
    warnings: list[str],
) -> tuple[pd.DataFrame, list[str]]:
    """Parse long format: Subject | [Year] | Grade | Count → cumulative %."""
    grades     = GCSE_GRADES if mode == "GCSE" else ALEVEL_GRADES
    cum_labels = _cum_labels_for(mode)
    cum_sets   = _cum_sets_for(mode)

    subj_col  = _find_col(df, ["Subject", "subject", "SubjectName"])
    grade_col = _find_col(df, ["Grade", "grade"])
    count_col = _find_col(df, ["Count", "count", "N", "n", "Total", "Number", "Students"])
    year_col  = _find_col(df, ["Year", "year", "AcademicYear", "Academic Year", "Cohort"])

    if not (subj_col and grade_col and count_col):
        warnings.append(
            f"Long format needs Subject, Grade, Count. Found: {list(df.columns[:8])}"
        )
        return pd.DataFrame(), warnings

    df_w = df.copy()
    df_w["_subj"]  = df_w[subj_col].astype(str).str.strip()
    df_w["_grade"] = df_w[grade_col].astype(str).str.strip()
    df_w["_count"] = pd.to_numeric(df_w[count_col], errors="coerce").fillna(0)
    df_w["_year"]  = df_w[year_col].astype(str).str.strip() if year_col else "Historical"

    rows: list[dict] = []
    for (subj, year), grp in df_w.groupby(["_subj", "_year"]):
        raw = dict(zip(grp["_grade"], grp["_count"]))
        total = float(sum(raw.values()))
        out: dict = {"Subject": subj, "Year": year, "n": int(round(total))}
        pct = {g: (raw.get(g, 0) / total * 100) if total > 0 else 0.0 for g in grades}

        if mode == "GCSE":
            grade_int_map = {g: int(g) for g in grades}
            for label in cum_labels:
                gs = cum_sets[label]
                out[f"cum_pct_{label}"] = sum(pct.get(g, 0.0) for g in grades if grade_int_map.get(g) in gs)
        else:
            for label in cum_labels:
                gs = cum_sets[label]
                out[f"cum_pct_{label}"] = sum(pct.get(g, 0.0) for g in grades if g in gs)

        rows.append(out)

    if not rows:
        warnings.append("No data rows found.")
        return pd.DataFrame(), warnings

    result = pd.DataFrame(rows)
    warnings.insert(0, f"Loaded {len(result)} subject-year rows (long format).")
    return result, warnings


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_historical(df: pd.DataFrame, mode: str = "GCSE") -> pd.DataFrame:
    """
    Collapse all years into a single per-subject aggregate weighted by n.
    Returns a DataFrame indexed by Subject with cum_pct_* columns.
    """
    cum_labels = _cum_labels_for(mode)
    cum_cols   = [f"cum_pct_{l}" for l in cum_labels]

    if df.empty:
        return df

    agg_rows: list[dict] = []
    for subj, grp in df.groupby("Subject"):
        total_n = float(grp["n"].sum())
        out: dict = {"Subject": subj, "n": int(round(total_n))}
        for col in cum_cols:
            if col in grp.columns and total_n > 0:
                # Weighted average of cumulative percentages
                out[col] = float((grp[col] * grp["n"]).sum() / total_n)
            else:
                out[col] = 0.0
        agg_rows.append(out)

    return pd.DataFrame(agg_rows).set_index("Subject")


# ---------------------------------------------------------------------------
# Comparison helper
# ---------------------------------------------------------------------------

def _targets_to_cumulative(
    targets_df: pd.DataFrame,
    mode: str,
) -> pd.DataFrame:
    """
    Compute cumulative % from a targets DataFrame.
    Returns DataFrame indexed by Subject with cum_pct_* columns and n.
    """
    cum_labels = _cum_labels_for(mode)
    cum_sets   = _cum_sets_for(mode)
    meta_cols  = {"surname", "forename", "form", "year_group", "overall_score", "avg_gcse"}
    subj_cols  = [c for c in targets_df.columns if c not in meta_cols]

    rows: list[dict] = []
    for subj in sorted(subj_cols):
        col = targets_df[subj].dropna()
        col_cleaned: list = []
        for v in col:
            s = str(v).strip()
            if s.lower() in ("nan", "n/a", ""):
                continue
            if mode == "GCSE":
                try:
                    col_cleaned.append(int(round(float(s))))
                except (ValueError, TypeError):
                    pass
            else:
                col_cleaned.append(s)

        n = len(col_cleaned)
        if n == 0:
            continue

        out: dict = {"Subject": subj, "n": n}
        for label in cum_labels:
            gs = cum_sets[label]
            count = sum(1 for v in col_cleaned if v in gs)
            out[f"cum_pct_{label}"] = count / n * 100

        rows.append(out)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("Subject")


def compare_targets_to_historical(
    targets_df: pd.DataFrame,
    historical_agg: pd.DataFrame,
    mode: str = "GCSE",
) -> pd.DataFrame:
    """
    Build a comparison table of current target cumulative % vs historical.

    Returns DataFrame with columns:
        Subject | n_students |
        <label>_target% | <label>_hist% | <label>_Δ   (for each cumulative label)
    """
    cum_labels = _cum_labels_for(mode)
    targets_cum = _targets_to_cumulative(targets_df, mode)

    if targets_cum.empty or historical_agg.empty:
        return pd.DataFrame()

    rows: list[dict] = []
    for subj in targets_cum.index:
        if subj not in historical_agg.index:
            continue

        out: dict = {"Subject": subj, "n_students": int(targets_cum.loc[subj, "n"])}
        for label in cum_labels:
            col = f"cum_pct_{label}"
            t_pct = float(targets_cum.loc[subj, col]) if col in targets_cum.columns else 0.0
            h_pct = float(historical_agg.loc[subj, col]) if col in historical_agg.columns else 0.0
            out[f"{label}_target%"] = round(t_pct, 1)
            out[f"{label}_hist%"]   = round(h_pct, 1)
            out[f"{label}_Δ"]       = round(t_pct - h_pct, 1)

        rows.append(out)

    return pd.DataFrame(rows) if rows else pd.DataFrame()
