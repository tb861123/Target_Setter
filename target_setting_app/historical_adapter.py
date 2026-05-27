"""Parser for historical GCSE / A Level results by subject.

Accepts two input layouts:

Wide format  (one row per subject × year):
    Subject | [Year] | 9 | 8 | 7 | ... | 1        (GCSE)
    Subject | [Year] | A* | A | B | C | D | E      (A Level)
    Counts or percentages.  Year column is optional.

Long format  (one row per subject × grade):
    Subject | [Year] | Grade | Count

Returns a normalised DataFrame with columns:
    Subject, Year, <grade_cols>, n, pct_<grade> ...

``aggregate_historical`` collapses all years into a single per-subject row.
``compare_targets_to_historical`` builds a side-by-side comparison table.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

GCSE_GRADES: list[str] = [str(g) for g in range(9, 0, -1)]   # ["9","8",…,"1"]
ALEVEL_GRADES: list[str] = ["A*", "A", "B", "C", "D", "E"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lower = {c.lower().strip(): c for c in df.columns}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def _add_pct_cols(row: dict, grades: list[str], total: float) -> None:
    for g in grades:
        row[f"pct_{g}"] = (row.get(g, 0) / total * 100) if total > 0 else 0.0


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
    df        DataFrame[Subject, Year, <grades>, n, pct_<grade>...]
    warnings  list of human-readable strings
    """
    warnings: list[str] = []
    grades = GCSE_GRADES if mode == "GCSE" else ALEVEL_GRADES

    try:
        file.seek(0)
    except Exception:
        pass

    try:
        df_raw = pd.read_excel(file, header=0)
    except Exception:
        try:
            file.seek(0)
            df_raw = pd.read_csv(file, encoding="utf-8")
        except Exception:
            file.seek(0)
            df_raw = pd.read_csv(file, encoding="latin-1")

    df_raw.columns = [str(c).strip() for c in df_raw.columns]
    df_raw = df_raw.dropna(how="all")

    grade_col = _find_col(df_raw, ["Grade", "grade"])
    if grade_col:
        return _parse_long(df_raw, grades, warnings)
    return _parse_wide(df_raw, grades, warnings)


# ---------------------------------------------------------------------------
# Wide parser
# ---------------------------------------------------------------------------

def _parse_wide(
    df: pd.DataFrame,
    grades: list[str],
    warnings: list[str],
) -> tuple[pd.DataFrame, list[str]]:
    subj_col = _find_col(df, ["Subject", "subject", "SubjectName", "Subject Name", "Qualification"])
    year_col = _find_col(df, ["Year", "year", "AcademicYear", "Academic Year", "Cohort", "Session"])

    if subj_col is None:
        warnings.append("Could not find a Subject column in the historical results file.")
        return pd.DataFrame(), warnings

    grade_cols_present = [c for c in df.columns if c.strip() in grades]
    if not grade_cols_present:
        warnings.append(
            f"No grade columns found (expected headers like {', '.join(grades[:4])}…). "
            "Make sure the column headers match exactly."
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
        total = 0.0
        for g in grades:
            col = _find_col(df, [g])
            try:
                v = float(raw_row[col]) if col else 0.0
                v = 0.0 if pd.isna(v) else v
            except (TypeError, ValueError):
                v = 0.0
            out[g] = v
            total += v

        # Heuristic: treat as percentages only if the row sum is close to 100
        non_zero = [out[g] for g in grades if out[g] > 0]
        row_sum = sum(non_zero)
        if non_zero and abs(row_sum - 100) <= 5:
            out["n"] = 100
            for g in grades:
                out[f"pct_{g}"] = out[g]
        else:
            out["n"] = int(round(total)) if total > 0 else 0
            _add_pct_cols(out, grades, total)

        rows.append(out)

    if not rows:
        warnings.append("No data rows found in historical results file.")
        return pd.DataFrame(), warnings

    result = pd.DataFrame(rows)
    warnings.insert(0, f"Loaded {len(result)} subject-year rows from historical results.")
    return result, warnings


# ---------------------------------------------------------------------------
# Long parser
# ---------------------------------------------------------------------------

def _parse_long(
    df: pd.DataFrame,
    grades: list[str],
    warnings: list[str],
) -> tuple[pd.DataFrame, list[str]]:
    subj_col  = _find_col(df, ["Subject", "subject", "SubjectName"])
    grade_col = _find_col(df, ["Grade", "grade"])
    count_col = _find_col(df, ["Count", "count", "N", "n", "Total", "Number", "Students"])
    year_col  = _find_col(df, ["Year", "year", "AcademicYear", "Academic Year", "Cohort"])

    if not (subj_col and grade_col and count_col):
        warnings.append(
            "Long format needs Subject, Grade, and Count columns. "
            f"Found: {list(df.columns[:8])}"
        )
        return pd.DataFrame(), warnings

    df_w = df.copy()
    df_w["_subj"]  = df_w[subj_col].astype(str).str.strip()
    df_w["_grade"] = df_w[grade_col].astype(str).str.strip()
    df_w["_count"] = pd.to_numeric(df_w[count_col], errors="coerce").fillna(0)
    df_w["_year"]  = df_w[year_col].astype(str).str.strip() if year_col else "Historical"

    rows: list[dict] = []
    for (subj, year), grp in df_w.groupby(["_subj", "_year"]):
        grade_counts = dict(zip(grp["_grade"], grp["_count"]))
        total = float(sum(grade_counts.values()))
        out: dict = {"Subject": subj, "Year": year}
        for g in grades:
            out[g] = float(grade_counts.get(g, 0))
        out["n"] = int(round(total))
        _add_pct_cols(out, grades, total)
        rows.append(out)

    if not rows:
        warnings.append("No data rows found in historical results file.")
        return pd.DataFrame(), warnings

    result = pd.DataFrame(rows)
    warnings.insert(0, f"Loaded {len(result)} subject-year rows from historical results.")
    return result, warnings


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_historical(df: pd.DataFrame, mode: str = "GCSE") -> pd.DataFrame:
    """
    Collapse all years into a single per-subject aggregate row.
    Returns a DataFrame indexed by Subject with grade count + pct columns.
    """
    grades = GCSE_GRADES if mode == "GCSE" else ALEVEL_GRADES
    if df.empty:
        return df

    agg_rows: list[dict] = []
    for subj, grp in df.groupby("Subject"):
        total = float(grp["n"].sum())
        out: dict = {"Subject": subj}
        for g in grades:
            col = g
            if col in grp.columns:
                out[g] = float(grp[col].sum())
            else:
                out[g] = 0.0
        out["n"] = int(round(total))
        _add_pct_cols(out, grades, total)
        agg_rows.append(out)

    return pd.DataFrame(agg_rows).set_index("Subject")


# ---------------------------------------------------------------------------
# Comparison helper
# ---------------------------------------------------------------------------

def compare_targets_to_historical(
    targets_df: pd.DataFrame,
    historical_agg: pd.DataFrame,
    mode: str = "GCSE",
) -> pd.DataFrame:
    """
    Build a comparison table: for each subject in targets_df that also appears
    in historical_agg, compute the current target grade distribution and compare
    with the historical grade distribution.

    Returns DataFrame with columns:
        Subject | n_students |
        <grade>_target_pct | <grade>_hist_pct | <grade>_delta |
        avg_target | avg_hist | avg_delta
    """
    grades = GCSE_GRADES if mode == "GCSE" else ALEVEL_GRADES

    meta_cols = {"surname", "forename", "form", "year_group", "overall_score", "avg_gcse"}
    subj_cols = [c for c in targets_df.columns if c not in meta_cols]

    rows: list[dict] = []
    for subj in sorted(subj_cols):
        if subj not in historical_agg.index:
            continue

        col = targets_df[subj].dropna()
        col = col[col.astype(str).str.strip().str.upper() != "N/A"]
        if col.empty:
            continue

        n_students = len(col)
        out: dict = {"Subject": subj, "n_students": n_students}

        # Compute target distribution
        target_counts: dict[str, int] = {}
        for val in col:
            try:
                g = str(int(round(float(val)))) if mode == "GCSE" else str(val)
            except (ValueError, TypeError):
                g = str(val)
            target_counts[g] = target_counts.get(g, 0) + 1

        for g in grades:
            t_pct = (target_counts.get(g, 0) / n_students * 100) if n_students > 0 else 0.0
            h_pct = float(historical_agg.loc[subj, f"pct_{g}"] if f"pct_{g}" in historical_agg.columns else 0)
            out[f"{g}_target%"] = round(t_pct, 1)
            out[f"{g}_hist%"] = round(h_pct, 1)
            out[f"{g}_Δ"] = round(t_pct - h_pct, 1)

        # Average grade numerics
        if mode == "GCSE":
            try:
                t_avg = sum(int(round(float(v))) for v in col if str(v).replace(".", "").isdigit()) / n_students
            except Exception:
                t_avg = None
            try:
                h_avg = sum(
                    float(historical_agg.loc[subj, f"pct_{g}"]) / 100 * int(g) * historical_agg.loc[subj, "n"]
                    for g in grades if f"pct_{g}" in historical_agg.columns
                ) / float(historical_agg.loc[subj, "n"]) if float(historical_agg.loc[subj, "n"]) > 0 else None
            except Exception:
                h_avg = None
            out["avg_target"] = round(t_avg, 2) if t_avg is not None else ""
            out["avg_hist"]   = round(h_avg, 2) if h_avg is not None else ""
            out["avg_Δ"]      = round(t_avg - h_avg, 2) if t_avg is not None and h_avg is not None else ""
        else:
            from target_engine import ALEVEL_GRADE_MAP
            grade_vals = ALEVEL_GRADE_MAP
            try:
                t_nums = [grade_vals[str(v)] for v in col if str(v) in grade_vals]
                t_avg = sum(t_nums) / len(t_nums) if t_nums else None
            except Exception:
                t_avg = None
            try:
                h_n = float(historical_agg.loc[subj, "n"])
                h_avg = (
                    sum(
                        float(historical_agg.loc[subj, f"pct_{g}"]) / 100 * grade_vals[g] * h_n
                        for g in grades if f"pct_{g}" in historical_agg.columns and g in grade_vals
                    ) / h_n
                    if h_n > 0 else None
                )
            except Exception:
                h_avg = None
            out["avg_target"] = round(t_avg, 2) if t_avg is not None else ""
            out["avg_hist"]   = round(h_avg, 2) if h_avg is not None else ""
            out["avg_Δ"]      = round(t_avg - h_avg, 2) if t_avg is not None and h_avg is not None else ""

        rows.append(out)

    return pd.DataFrame(rows) if rows else pd.DataFrame()
