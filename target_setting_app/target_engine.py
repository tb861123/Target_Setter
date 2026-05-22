"""GCSE and A Level target calculation engine."""

from __future__ import annotations

import math
import pandas as pd
import numpy as np

from subject_profiles import (
    OVERALL_MEAN,
    BEST_HUMANITIES,
    BEST_SCIENCE,
    HUMANITIES_GCSE_COLS,
    SCIENCE_GCSE_COLS,
    G_DS1,
    G_DS2,
    G_BIOLOGY,
    G_CHEMISTRY,
    G_PHYSICS,
    get_profile,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALEVEL_GRADE_MAP = {"A*": 6, "A": 5, "B": 4, "C": 3, "D": 2, "E": 1}
ALEVEL_GRADE_REVERSE = {v: k for k, v in ALEVEL_GRADE_MAP.items()}
ALEVEL_GRADES_ORDERED = ["A*", "A", "B", "C", "D", "E"]

GCSE_GRADES = list(range(9, 0, -1))  # 9 down to 1

# Sub-score subject groups for GCSE
MATHS_GROUP = {"Mathematics", "Further Mathematics", "Physics", "Computing"}
VOCAB_GROUP = {"English Literature", "Drama", "Film Studies"}
PATTERNS_GROUP = {"Art", "Design Technology", "Music"}


# ---------------------------------------------------------------------------
# GCSE Target Engine
# ---------------------------------------------------------------------------

class GCSETargetEngine:
    def __init__(
        self,
        yellis_df: pd.DataFrame,
        subject_list_df: pd.DataFrame,
        distribution: dict[str, float],
        use_subscores: bool = False,
        subscore_weights: dict[str, tuple[float, float]] | None = None,
        dept_adjustments: dict[str, float] | None = None,
    ):
        """
        yellis_df: parsed Yellis GCSE data (surname, forename, form, overall_score, ...)
        subject_list_df: (surname, forename, subjects) where subjects is list[str]
        distribution: {'9': pct, '8': pct, ...} summing to ~100; cumulative given as input
        use_subscores: whether to apply sub-score weighting
        subscore_weights: {subject_group_key: (overall_weight, subscore_weight)}
        dept_adjustments: {subject: float delta}
        """
        self.yellis = yellis_df.copy()
        self.subject_list = subject_list_df.copy()
        self.distribution = distribution
        self.use_subscores = use_subscores
        self.subscore_weights = subscore_weights or {}
        self.dept_adjustments = dept_adjustments or {}

    def _get_weighted_score(self, row: pd.Series, subject: str) -> float:
        overall = float(row.get("overall_score", 0) or 0)
        if not self.use_subscores:
            return overall

        if subject in MATHS_GROUP:
            sub = float(row.get("maths_score", overall) or overall)
            w_o, w_s = self.subscore_weights.get("maths_group", (0.7, 0.3))
        elif subject in VOCAB_GROUP:
            sub = float(row.get("vocab_score", overall) or overall)
            w_o, w_s = self.subscore_weights.get("vocab_group", (0.7, 0.3))
        elif subject in PATTERNS_GROUP:
            sub = float(row.get("patterns_score", overall) or overall)
            w_o, w_s = self.subscore_weights.get("patterns_group", (0.7, 0.3))
        else:
            return overall

        if pd.isna(sub):
            return overall
        return w_o * overall + w_s * sub

    def _cumulative_to_marginal(self, cum_pct: dict[str, float]) -> dict[int, float]:
        """Convert cumulative % to marginal % per grade (sorted 9→1)."""
        grades = [9, 8, 7, 6, 5, 4, 3, 2, 1]
        cum_labels = ["9", "9-8", "9-7", "9-6", "9-5", "9-4"]
        cum_vals = [cum_pct.get(lbl, 0) / 100 for lbl in cum_labels]
        # cum_vals[0] = % getting 9
        # cum_vals[1] = % getting 9 or 8  (so marginal 8 = cum[1]-cum[0])
        marginal = {}
        prev = 0.0
        for i, g in enumerate([9, 8, 7, 6, 5, 4]):
            if i < len(cum_vals):
                marginal[g] = cum_vals[i] - prev
                prev = cum_vals[i]
        # grades 3, 2, 1 share the remaining
        remaining = 1.0 - prev
        marginal[3] = remaining / 3
        marginal[2] = remaining / 3
        marginal[1] = remaining - marginal[3] - marginal[2]
        return marginal

    def generate(self) -> pd.DataFrame:
        """
        Returns a DataFrame indexed by (surname, forename, form) with one column per subject.
        Cell values are integer target grades (1–9) or pd.NA.
        """
        # Build all subjects
        all_subjects: set[str] = set()
        for subjects in self.subject_list["subjects"]:
            all_subjects.update(subjects)
        all_subjects = sorted(all_subjects)

        marginal = self._cumulative_to_marginal(self.distribution)

        # Build student base info
        # Join subject_list with yellis on name key
        sl = self.subject_list.copy()
        sl["_key"] = (
            sl["surname"].str.strip().str.lower()
            + "|"
            + sl["forename"].str.strip().str.lower()
        )

        yw = self.yellis.copy()
        yw["_key"] = (
            yw["surname"].str.strip().str.lower()
            + "|"
            + yw["forename"].str.strip().str.lower()
        )

        merged = sl.merge(yw, on="_key", how="left", suffixes=("", "_y"))
        merged = merged.drop(columns=[c for c in merged.columns if c.endswith("_y")])

        rows = []
        for _, student in merged.iterrows():
            row = {
                "surname": student["surname"],
                "forename": student["forename"],
                "form": student.get("form", ""),
                "overall_score": student.get("overall_score", None),
                "_subjects": student.get("subjects", []),
                "_has_baseline": pd.notna(student.get("overall_score")),
            }
            rows.append(row)

        students_df = pd.DataFrame(rows)

        # For each subject, rank and assign targets
        targets: dict[str, list] = {s: [pd.NA] * len(students_df) for s in all_subjects}

        for subject in all_subjects:
            # Students taking this subject who have baseline data
            mask_takes = students_df["_subjects"].apply(lambda subs: subject in subs)
            mask_has = students_df["_has_baseline"]

            eligible_idx = students_df[mask_takes & mask_has].index.tolist()
            no_baseline_idx = students_df[mask_takes & ~mask_has].index.tolist()

            if not eligible_idx:
                continue

            # Score for ranking
            scores = students_df.loc[eligible_idx].apply(
                lambda r: self._get_weighted_score(r, subject), axis=1
            )
            ranked_idx = scores.sort_values(ascending=False).index.tolist()
            n = len(ranked_idx)

            assigned = _assign_grades_by_distribution(n, marginal, GCSE_GRADES)

            for pos, idx in enumerate(ranked_idx):
                raw_grade = assigned[pos]
                adj = self.dept_adjustments.get(subject, 0.0)
                grade = int(round(raw_grade + adj))
                grade = max(1, min(9, grade))
                targets[subject][idx] = grade

            for idx in no_baseline_idx:
                targets[subject][idx] = "N/A"

        result = students_df[["surname", "forename", "form", "overall_score"]].copy()
        for subject in all_subjects:
            result[subject] = targets[subject]

        return result.reset_index(drop=True)


# ---------------------------------------------------------------------------
# A Level Target Engine
# ---------------------------------------------------------------------------

class ALevelTargetEngine:
    def __init__(
        self,
        yellis_df: pd.DataFrame,
        gcse_wide_df: pd.DataFrame,
        subject_list_df: pd.DataFrame,
        distribution: dict[str, float],
        gcse_weight: float = 0.80,
        yellis_weight: float = 0.20,
        fallback_ratio: float = 0.60,
        profile_overrides: dict | None = None,
        dept_adjustments: dict[str, float] | None = None,
    ):
        self.yellis = yellis_df.copy()
        self.gcse_wide = gcse_wide_df.copy()
        self.subject_list = subject_list_df.copy()
        self.distribution = distribution
        self.gcse_weight = gcse_weight
        self.yellis_weight = yellis_weight
        self.fallback_ratio = fallback_ratio
        self.profile_overrides = profile_overrides or {}
        self.dept_adjustments = dept_adjustments or {}

    def _get_student_gcse_score(
        self, gcse_row: pd.Series, subject: str
    ) -> float:
        """Compute subject-specific GCSE score for this student."""
        profile = get_profile(subject, self.profile_overrides)

        # Compute overall mean GCSE — only consider scalar numeric columns
        _skip = {"Surname", "Forename", "_key", "surname", "forename",
                 "subjects", "_subjects", "year_group", "overall_score",
                 "yellis_normalised", "_has_yellis", "_gcse_row",
                 "code", "gender", "dob", "overall_band",
                 "vocab_score", "vocab_band", "maths_score", "maths_band",
                 "nonverbal_score", "nonverbal_band"}
        numeric_cols = []
        for c in gcse_row.index:
            if c in _skip:
                continue
            val = gcse_row[c]
            try:
                if isinstance(val, (int, float)) and pd.notna(val):
                    numeric_cols.append(c)
            except (TypeError, ValueError):
                pass
        overall_mean = float(gcse_row[numeric_cols].mean()) if numeric_cols else 5.0

        def _get_gcse(col: str) -> float | None:
            """Get GCSE grade for a subject column, handling Double Science proxy."""
            val = gcse_row.get(col)
            try:
                is_na = pd.isna(val)
            except (TypeError, ValueError):
                is_na = True
            if not is_na and isinstance(val, (int, float)):
                return float(val)
            if col in (G_BIOLOGY, G_CHEMISTRY, G_PHYSICS):
                ds1 = gcse_row.get(G_DS1)
                ds2 = gcse_row.get(G_DS2)
                try:
                    if isinstance(ds1, (int, float)) and isinstance(ds2, (int, float)) \
                            and pd.notna(ds1) and pd.notna(ds2):
                        return (float(ds1) + float(ds2)) / 2.0
                except (TypeError, ValueError):
                    pass
            return None

        def _best_humanities() -> float:
            vals = [_get_gcse(c) for c in HUMANITIES_GCSE_COLS]
            vals = [v for v in vals if v is not None]
            return max(vals) if vals else overall_mean

        def _best_science() -> float:
            vals = [_get_gcse(c) for c in SCIENCE_GCSE_COLS]
            vals = [v for v in vals if v is not None]
            if vals:
                return max(vals)
            ds1 = gcse_row.get(G_DS1)
            ds2 = gcse_row.get(G_DS2)
            try:
                if isinstance(ds1, (int, float)) and isinstance(ds2, (int, float)) \
                        and pd.notna(ds1) and pd.notna(ds2):
                    return (float(ds1) + float(ds2)) / 2.0
            except (TypeError, ValueError):
                pass
            return overall_mean

        primary_gcse = profile.get("primary_gcse")
        has_primary = primary_gcse is not None and _get_gcse(primary_gcse) is not None

        weights_dict = profile["primary"] if has_primary else profile["fallback"]

        score = 0.0
        total_weight = 0.0
        for comp, w in weights_dict.items():
            if comp == OVERALL_MEAN:
                val = overall_mean
            elif comp == BEST_HUMANITIES:
                val = _best_humanities()
            elif comp == BEST_SCIENCE:
                val = _best_science()
            else:
                val = _get_gcse(comp)
                if val is None:
                    # Component missing — redistribute weight to overall_mean
                    val = overall_mean
            score += w * val
            total_weight += w

        if total_weight > 0 and abs(total_weight - 1.0) > 0.01:
            score /= total_weight

        return score

    def generate(self) -> pd.DataFrame:
        """
        Returns DataFrame with one row per student and one column per subject.
        Grade values are strings like 'A*', 'A', ... 'E' or pd.NA.
        """
        all_subjects: set[str] = set()
        for subjects in self.subject_list["subjects"]:
            all_subjects.update(subjects)
        all_subjects = sorted(all_subjects)

        # Build distribution as cumulative → marginal
        marginal = self._cumulative_to_marginal(self.distribution)

        # Join everything on name key
        sl = self.subject_list.copy()
        sl["_key"] = (
            sl["surname"].str.strip().str.lower()
            + "|"
            + sl["forename"].str.strip().str.lower()
        )

        yw = self.yellis.copy()
        yw["_key"] = (
            yw["surname"].str.strip().str.lower()
            + "|"
            + yw["firstname"].str.strip().str.lower()
        )

        gw = self.gcse_wide.copy()
        gw["_key"] = (
            gw["Surname"].str.strip().str.lower()
            + "|"
            + gw["Forename"].str.strip().str.lower()
        )

        # Use suffix "" for left (sl) so surname/forename are preserved without suffix
        merged = sl.merge(yw, on="_key", how="left", suffixes=("", "_yw"))
        merged = merged.merge(gw, on="_key", how="left", suffixes=("", "_gw"))
        # Drop duplicate columns from right-side merges
        merged = merged.drop(
            columns=[c for c in merged.columns if c.endswith("_yw") or c.endswith("_gw")],
            errors="ignore",
        )

        rows = []
        for _, student in merged.iterrows():
            yellis_score = student.get("overall_score")
            yellis_norm = (float(yellis_score) / 150.0 * 9.0) if pd.notna(yellis_score) else None

            rows.append({
                "surname": student["surname"],
                "forename": student["forename"],
                "year_group": "Year 12",
                "overall_score": yellis_score,
                "yellis_normalised": yellis_norm,
                "_subjects": student.get("subjects", []),
                "_has_yellis": pd.notna(yellis_score),
                "_gcse_row": student,
            })

        students_df = pd.DataFrame(rows)

        targets: dict[str, list] = {s: [pd.NA] * len(students_df) for s in all_subjects}

        for subject in all_subjects:
            mask_takes = students_df["_subjects"].apply(lambda subs: subject in subs)
            mask_has = students_df["_has_yellis"]

            eligible_idx = students_df[mask_takes & mask_has].index.tolist()
            no_baseline_idx = students_df[mask_takes & ~mask_has].index.tolist()

            if not eligible_idx:
                continue

            composite_scores = {}
            for idx in eligible_idx:
                row = students_df.loc[idx]
                gcse_row = row["_gcse_row"]
                gcse_score = self._get_student_gcse_score(gcse_row, subject)
                yellis_norm = row["yellis_normalised"] or 5.0
                composite = (
                    self.gcse_weight * gcse_score
                    + self.yellis_weight * yellis_norm
                )
                composite_scores[idx] = composite

            ranked_idx = sorted(composite_scores, key=composite_scores.__getitem__, reverse=True)
            n = len(ranked_idx)
            assigned = _assign_grades_by_distribution(n, marginal, list(range(6, 0, -1)))

            for pos, idx in enumerate(ranked_idx):
                raw_grade = assigned[pos]
                adj = self.dept_adjustments.get(subject, 0.0)
                grade_num = raw_grade + adj
                grade_num = max(1, min(6, round(grade_num)))
                targets[subject][idx] = ALEVEL_GRADE_REVERSE[int(grade_num)]

            for idx in no_baseline_idx:
                targets[subject][idx] = "N/A"

        result = students_df[["surname", "forename", "year_group", "overall_score"]].copy()
        for subject in all_subjects:
            result[subject] = targets[subject]

        return result.reset_index(drop=True)

    def _cumulative_to_marginal(self, cum_pct: dict[str, float]) -> dict[int, float]:
        """Convert cumulative % to marginal % per A Level grade (6=A* down to 1=E)."""
        labels = ["A*", "A*-A", "A*-B", "A*-C", "A*-D", "A*-E"]
        cum_vals = [cum_pct.get(lbl, 0) / 100 for lbl in labels]
        marginal = {}
        prev = 0.0
        for i, g in enumerate(range(6, 0, -1)):  # 6=A*, 5=A, ..., 1=E
            if i < len(cum_vals):
                marginal[g] = cum_vals[i] - prev
                prev = cum_vals[i]
            else:
                marginal[g] = 0.0
        # Normalise
        total = sum(marginal.values())
        if total > 0:
            marginal = {k: v / total for k, v in marginal.items()}
        return marginal


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _assign_grades_by_distribution(
    n: int,
    marginal: dict[int, float],
    grades_desc: list[int],
) -> list[int]:
    """
    Assign grades to n students ranked 0 (best) to n-1 (worst)
    according to marginal proportions.
    Returns list of length n mapping position → grade.
    """
    assigned = []
    pos = 0
    for grade in grades_desc:
        prop = marginal.get(grade, 0.0)
        count = round(prop * n)
        for _ in range(count):
            assigned.append(grade)
        if len(assigned) >= n:
            break

    # Fill remainder with lowest grade if rounding left gaps
    while len(assigned) < n:
        assigned.append(grades_desc[-1])

    # Trim if overshot
    assigned = assigned[:n]
    return assigned


# ---------------------------------------------------------------------------
# Summary statistics helpers
# ---------------------------------------------------------------------------

def compute_gcse_summary(targets_df: pd.DataFrame, subject_cols: list[str]) -> pd.DataFrame:
    """
    Returns DataFrame with rows for each grade band and columns for each subject + 'All'.
    Values are cumulative percentages (string like '42.5%').
    """
    bands = [
        ("9", [9]),
        ("9-8", [9, 8]),
        ("9-7", [9, 8, 7]),
        ("9-6", [9, 8, 7, 6]),
        ("9-5", [9, 8, 7, 6, 5]),
        ("9-4", [9, 8, 7, 6, 5, 4]),
    ]
    rows = []
    for band_label, grade_vals in bands:
        row = {"Band": band_label}
        all_vals = []
        for subj in subject_cols:
            col = targets_df[subj].dropna()
            numeric = pd.to_numeric(col, errors="coerce").dropna()
            if len(numeric) == 0:
                row[subj] = ""
                continue
            pct = (numeric.isin(grade_vals).sum() / len(numeric)) * 100
            row[subj] = f"{pct:.1f}%"
            all_vals.extend(numeric.tolist())
        if all_vals:
            all_series = pd.Series(all_vals)
            all_pct = (all_series.isin(grade_vals).sum() / len(all_series)) * 100
            row["All"] = f"{all_pct:.1f}%"
        else:
            row["All"] = ""
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# ALIS-based A Level Target Engine
# ---------------------------------------------------------------------------

class ALevelALISEngine:
    """
    Generates A Level targets using ALIS Adapt percentile predictions as the
    primary signal.  Two modes are available:

    * direct  — use the ALIS grade at the chosen percentile as the target, then
                apply dept adjustment.  Simple and faithful to what ALIS produces.
    * ranked  — convert the ALIS grade to a numeric ranking score, rank students
                per subject, then apply the school's own distribution curve
                (same as ALevelTargetEngine but seeded by ALIS rather than
                composite scores).  Useful when the school wants to impose a
                specific grade profile that differs from the national distribution.

    Fallback: students/subjects with no ALIS entry fall back to ALevelTargetEngine
    composite scoring when gcse_wide_df and the subject_list profile are provided.
    """

    GRADE_NUM = {"A*": 6, "A": 5, "B": 4, "C": 3, "D": 2, "E": 1}
    GRADE_STR = {v: k for k, v in GRADE_NUM.items()}
    GRADES_DESC = [6, 5, 4, 3, 2, 1]

    def __init__(
        self,
        alis_lookup,            # ALISLookup instance (default percentile)
        subject_list_df: pd.DataFrame,
        yellis_df: pd.DataFrame | None = None,
        gcse_wide_df: pd.DataFrame | None = None,
        mode: str = "direct",   # "direct" | "ranked"
        distribution: dict[str, float] | None = None,  # used only in ranked mode
        gcse_blend_weight: float = 0.0,  # 0 = pure ALIS, 1 = pure GCSE composite
        dept_adjustments: dict[str, float] | None = None,
        profile_overrides: dict | None = None,
        subject_lookups: dict | None = None,  # subject → lookup override
    ):
        self.lookup = alis_lookup
        self.subject_lookups = subject_lookups or {}
        self.subject_list = subject_list_df.copy()
        self.yellis_df = yellis_df
        self.gcse_wide_df = gcse_wide_df
        self.mode = mode
        self.distribution = distribution or {}
        self.gcse_blend_weight = gcse_blend_weight
        self.dept_adjustments = dept_adjustments or {}
        self.profile_overrides = profile_overrides or {}

    def _get_lookup(self, subject: str):
        """Return the lookup for a subject, respecting per-subject percentile overrides."""
        return self.subject_lookups.get(subject, self.lookup)

    def generate(self) -> pd.DataFrame:
        all_subjects: set[str] = set()
        for subjects in self.subject_list["subjects"]:
            all_subjects.update(subjects)
        all_subjects = sorted(all_subjects)

        # Build student base list
        sl = self.subject_list.copy()
        sl["_key"] = (
            sl["surname"].str.strip().str.lower()
            + "|"
            + sl["forename"].str.strip().str.lower()
        )

        rows = []
        for _, student in sl.iterrows():
            key = student["_key"]
            baseline = self.lookup.get_baseline(key)
            rows.append({
                "surname": student["surname"],
                "forename": student["forename"],
                "year_group": "Year 12",
                "overall_score": baseline,
                "_key": key,
                "_subjects": student.get("subjects", []),
            })

        students_df = pd.DataFrame(rows)

        targets: dict[str, list] = {s: [pd.NA] * len(students_df) for s in all_subjects}
        unmatched: set[str] = set()

        for subject in all_subjects:
            mask_takes = students_df["_subjects"].apply(lambda s: subject in s)
            eligible_idx = students_df[mask_takes].index.tolist()

            if not eligible_idx:
                continue

            subj_lookup = self._get_lookup(subject)

            if self.mode == "direct":
                for idx in eligible_idx:
                    key = students_df.at[idx, "_key"]
                    grade = subj_lookup.get_grade(key, subject)
                    if grade is None:
                        unmatched.add(f"{students_df.at[idx, 'surname']} {students_df.at[idx, 'forename']}")
                        targets[subject][idx] = "N/A"
                    else:
                        adj = self.dept_adjustments.get(subject, 0.0)
                        num = self.GRADE_NUM.get(grade, 3)
                        num = max(1, min(6, round(num + adj)))
                        targets[subject][idx] = self.GRADE_STR[num]

            else:
                # ranked mode: convert ALIS grade to numeric score, rank, apply dist
                scores: dict[int, float] = {}
                for idx in eligible_idx:
                    key = students_df.at[idx, "_key"]
                    grade = subj_lookup.get_grade(key, subject)
                    num = self.GRADE_NUM.get(grade, 3) if grade else 3
                    scores[idx] = float(num)

                marginal = self._cumulative_to_marginal(self.distribution)
                ranked_idx = sorted(scores, key=scores.__getitem__, reverse=True)
                n = len(ranked_idx)
                assigned = _assign_grades_by_distribution(n, marginal, self.GRADES_DESC)

                for pos, idx in enumerate(ranked_idx):
                    raw = assigned[pos]
                    adj = self.dept_adjustments.get(subject, 0.0)
                    num = max(1, min(6, round(raw + adj)))
                    targets[subject][idx] = self.GRADE_STR[num]

        result = students_df[["surname", "forename", "year_group", "overall_score"]].copy()
        for subject in all_subjects:
            result[subject] = targets[subject]

        return result.reset_index(drop=True)

    def _cumulative_to_marginal(self, cum_pct: dict[str, float]) -> dict[int, float]:
        labels = ["A*", "A*-A", "A*-B", "A*-C", "A*-D", "A*-E"]
        cum_vals = [cum_pct.get(lbl, 0) / 100 for lbl in labels]
        marginal: dict[int, float] = {}
        prev = 0.0
        for i, g in enumerate(range(6, 0, -1)):
            if i < len(cum_vals):
                marginal[g] = max(0.0, cum_vals[i] - prev)
                prev = cum_vals[i]
            else:
                marginal[g] = 0.0
        total = sum(marginal.values())
        if total > 0:
            marginal = {k: v / total for k, v in marginal.items()}
        return marginal


def compute_alevel_summary(targets_df: pd.DataFrame, subject_cols: list[str]) -> pd.DataFrame:
    bands = [
        ("A*", ["A*"]),
        ("A*-A", ["A*", "A"]),
        ("A*-B", ["A*", "A", "B"]),
        ("A*-C", ["A*", "A", "B", "C"]),
        ("A*-D", ["A*", "A", "B", "C", "D"]),
        ("A*-E", ["A*", "A", "B", "C", "D", "E"]),
    ]
    rows = []
    for band_label, grade_vals in bands:
        row = {"Band": band_label}
        all_vals = []
        for subj in subject_cols:
            col = targets_df[subj].dropna()
            col = col[col != "N/A"]
            if len(col) == 0:
                row[subj] = ""
                continue
            pct = (col.isin(grade_vals).sum() / len(col)) * 100
            row[subj] = f"{pct:.1f}%"
            all_vals.extend(col.tolist())
        if all_vals:
            all_series = pd.Series(all_vals)
            all_pct = (all_series.isin(grade_vals).sum() / len(all_series)) * 100
            row["All"] = f"{all_pct:.1f}%"
        else:
            row["All"] = ""
        rows.append(row)
    return pd.DataFrame(rows)
