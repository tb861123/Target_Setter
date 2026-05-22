"""Reusable Streamlit UI components for Target Setting Tool."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from target_engine import compute_gcse_summary, compute_alevel_summary

YELLIS_BAND_COLOURS = {
    "A": "#C6EFCE",
    "B": "#FFEB9C",
    "C": "#FFD580",
    "D": "#FFC7CE",
}

ALEVEL_GRADE_COLOURS = {
    "A*": "#00B050",
    "A": "#70AD47",
    "B": "#FFC000",
    "C": "#FF7F00",
    "D": "#FF0000",
    "E": "#C00000",
}


def render_distribution_inputs(
    mode: str,
    existing: dict | None = None,
) -> dict[str, float]:
    """
    Render cumulative % inputs for target distribution.
    Returns dict of {band_label: cumulative_pct}.
    """
    if mode == "GCSE":
        bands = ["9", "9-8", "9-7", "9-6", "9-5", "9-4"]
        defaults = [40.0, 65.0, 82.0, 92.0, 98.0, 100.0]
    else:
        bands = ["A*", "A*-A", "A*-B", "A*-C", "A*-D", "A*-E"]
        defaults = [20.0, 50.0, 80.0, 95.0, 99.0, 100.0]

    existing = existing or {}
    result = {}
    prev = 0.0

    st.markdown("**Cumulative target distribution (%)**")
    cols = st.columns(len(bands))
    for i, (band, default) in enumerate(zip(bands, defaults)):
        with cols[i]:
            val = st.number_input(
                band,
                min_value=prev,
                max_value=100.0,
                value=float(existing.get(band, default)),
                step=1.0,
                key=f"dist_{mode}_{band}",
            )
        result[band] = val
        prev = val

    # Validate
    vals = list(result.values())
    errors = []
    for i in range(1, len(vals)):
        if vals[i] < vals[i - 1]:
            errors.append(f"Band '{bands[i]}' ({vals[i]:.1f}%) must be ≥ '{bands[i-1]}' ({vals[i-1]:.1f}%).")
    if errors:
        for err in errors:
            st.error(err)

    return result


def render_dept_adjustments(
    subjects: list[str],
    existing: dict | None = None,
    key_prefix: str = "",
) -> dict[str, float]:
    """Render per-subject department adjustment sliders. Returns {subject: delta}."""
    existing = existing or {}
    result = {}
    with st.expander("Department Adjustments", expanded=False):
        st.caption(
            "Historical performance adjustment: positive raises targets for consistently "
            "strong departments; negative lowers them for departments facing challenges."
        )
        cols = st.columns(min(3, len(subjects)))
        for i, subj in enumerate(subjects):
            with cols[i % len(cols)]:
                val = st.slider(
                    subj,
                    min_value=-0.5,
                    max_value=0.5,
                    value=float(existing.get(subj, 0.0)),
                    step=0.1,
                    format="%.1f",
                    key=f"{key_prefix}dept_{subj}",
                    help="Shift all targets in this subject up/down by this amount (grade points).",
                )
                result[subj] = val
    return result


def render_gcse_matrix(
    targets_df: pd.DataFrame,
    overrides: dict,
    dept_adjustments: dict,
) -> tuple[pd.DataFrame, dict]:
    """
    Display editable GCSE target matrix.
    Returns (updated_targets_df, updated_overrides).
    """
    subject_cols = [
        c for c in targets_df.columns
        if c not in ("surname", "forename", "form", "overall_score")
    ]
    subject_cols = sorted(subject_cols)

    df_display = targets_df.copy()

    # Apply department adjustments on top of targets (but not overrides)
    for subj in subject_cols:
        adj = dept_adjustments.get(subj, 0.0)
        if adj != 0.0 and subj in df_display.columns:
            def _apply_adj(val, adj=adj):
                if pd.isna(val) or val in ("N/A", ""):
                    return val
                try:
                    new_val = int(round(float(val) + adj))
                    return max(1, min(9, new_val))
                except (TypeError, ValueError):
                    return val
            df_display[subj] = df_display[subj].apply(_apply_adj)

    # Apply manual overrides
    for student_key, subj_overrides in overrides.items():
        surname, forename = student_key.split("|", 1)
        mask = (
            (df_display["surname"].str.lower() == surname.lower())
            & (df_display["forename"].str.lower() == forename.lower())
        )
        idx_list = df_display[mask].index.tolist()
        for idx in idx_list:
            for subj, grade in subj_overrides.items():
                df_display.at[idx, subj] = grade

    st.markdown("### Target Grade Matrix")
    st.caption(
        "Amber cells = manually overridden. Click 'Edit Overrides' below to modify individual targets."
    )

    # Display as static table with colour hints
    display_rows = []
    for _, row in df_display.sort_values("overall_score", ascending=False, na_position="last").iterrows():
        r = {
            "Surname": row["surname"],
            "Forename": row["forename"],
            "Form": row.get("form", ""),
            "Yellis": f"{row['overall_score']:.0f}" if pd.notna(row.get("overall_score")) else "",
        }
        for subj in subject_cols:
            val = row.get(subj)
            r[subj] = val if pd.notna(val) and val not in ("", None) else ""
        display_rows.append(r)

    display_df = pd.DataFrame(display_rows)

    def _style_cell(val):
        if val == "":
            return ""
        return "text-align: center;"

    st.dataframe(display_df, use_container_width=True, height=400)

    # Override editor
    with st.expander("Edit Individual Target Overrides"):
        st.info("Select a student and subject below to override their target.")
        student_options = [
            f"{r['Surname']}, {r['Forename']}" for r in display_rows
        ]
        sel_student = st.selectbox("Student", student_options, key="override_student_gcse")
        sel_subject = st.selectbox("Subject", subject_cols, key="override_subject_gcse")
        sel_grade = st.selectbox(
            "New Target Grade", list(range(9, 0, -1)), key="override_grade_gcse"
        )
        if st.button("Apply Override", key="apply_override_gcse"):
            if sel_student and sel_subject:
                surname, forename = sel_student.split(", ", 1)
                student_key = f"{surname}|{forename}"
                if student_key not in overrides:
                    overrides[student_key] = {}
                overrides[student_key][sel_subject] = sel_grade
                st.success(f"Override set: {sel_student} — {sel_subject} → {sel_grade}")
                st.rerun()

        if overrides:
            st.markdown("**Current overrides:**")
            override_rows = []
            for sk, subj_dict in overrides.items():
                sn, fn = sk.split("|", 1)
                for subj, grade in subj_dict.items():
                    override_rows.append({"Student": f"{sn}, {fn}", "Subject": subj, "Grade": grade})
            st.dataframe(pd.DataFrame(override_rows), use_container_width=True)
            if st.button("Clear All Overrides", key="clear_overrides_gcse"):
                overrides.clear()
                st.rerun()

    # Summary footer
    st.markdown("### Grade Distribution Summary")
    summary = compute_gcse_summary(df_display, subject_cols)
    st.dataframe(summary.set_index("Band"), use_container_width=True)

    return df_display, overrides


def render_alevel_matrix(
    targets_df: pd.DataFrame,
    overrides: dict,
    dept_adjustments: dict,
) -> tuple[pd.DataFrame, dict]:
    """Display editable A Level target matrix. Returns (updated_df, updated_overrides)."""
    from target_engine import ALEVEL_GRADES_ORDERED, ALEVEL_GRADE_MAP, ALEVEL_GRADE_REVERSE

    subject_cols = [
        c for c in targets_df.columns
        if c not in ("surname", "forename", "year_group", "overall_score")
    ]
    subject_cols = sorted(subject_cols)

    df_display = targets_df.copy()

    # Apply dept adjustments
    for subj in subject_cols:
        adj = dept_adjustments.get(subj, 0.0)
        if adj != 0.0 and subj in df_display.columns:
            def _apply_adj_al(val, adj=adj):
                if pd.isna(val) or val in ("N/A", ""):
                    return val
                num = ALEVEL_GRADE_MAP.get(val)
                if num is None:
                    return val
                new_num = int(round(num + adj))
                new_num = max(1, min(6, new_num))
                return ALEVEL_GRADE_REVERSE[new_num]
            df_display[subj] = df_display[subj].apply(_apply_adj_al)

    # Apply manual overrides
    for student_key, subj_overrides in overrides.items():
        surname, forename = student_key.split("|", 1)
        mask = (
            (df_display["surname"].str.lower() == surname.lower())
            & (df_display["forename"].str.lower() == forename.lower())
        )
        for idx in df_display[mask].index:
            for subj, grade in subj_overrides.items():
                df_display.at[idx, subj] = grade

    st.markdown("### Target Grade Matrix")
    st.caption("Amber cells = manually overridden.")

    display_rows = []
    for _, row in df_display.sort_values("overall_score", ascending=False, na_position="last").iterrows():
        r = {
            "Surname": row["surname"],
            "Forename": row["forename"],
            "Yellis": f"{row['overall_score']:.1f}" if pd.notna(row.get("overall_score")) else "",
        }
        for subj in subject_cols:
            val = row.get(subj)
            r[subj] = val if pd.notna(val) and val not in ("", None) else ""
        display_rows.append(r)

    display_df = pd.DataFrame(display_rows)
    st.dataframe(display_df, use_container_width=True, height=400)

    # Override editor
    with st.expander("Edit Individual Target Overrides"):
        student_options = [f"{r['Surname']}, {r['Forename']}" for r in display_rows]
        sel_student = st.selectbox("Student", student_options, key="override_student_al")
        sel_subject = st.selectbox("Subject", subject_cols, key="override_subject_al")
        sel_grade = st.selectbox(
            "New Target Grade", ALEVEL_GRADES_ORDERED, key="override_grade_al"
        )
        if st.button("Apply Override", key="apply_override_al"):
            if sel_student and sel_subject:
                surname, forename = sel_student.split(", ", 1)
                student_key = f"{surname}|{forename}"
                if student_key not in overrides:
                    overrides[student_key] = {}
                overrides[student_key][sel_subject] = sel_grade
                st.success(f"Override set: {sel_student} — {sel_subject} → {sel_grade}")
                st.rerun()

        if overrides:
            st.markdown("**Current overrides:**")
            override_rows = []
            for sk, subj_dict in overrides.items():
                sn, fn = sk.split("|", 1)
                for subj, grade in subj_dict.items():
                    override_rows.append({"Student": f"{sn}, {fn}", "Subject": subj, "Grade": grade})
            st.dataframe(pd.DataFrame(override_rows), use_container_width=True)
            if st.button("Clear All Overrides", key="clear_overrides_al"):
                overrides.clear()
                st.rerun()

    st.markdown("### Grade Distribution Summary")
    summary = compute_alevel_summary(df_display, subject_cols)
    st.dataframe(summary.set_index("Band"), use_container_width=True)

    return df_display, overrides


def render_validation_warnings(warnings: list[str], missing_students: list[str]) -> None:
    if warnings:
        with st.expander(f"Warnings ({len(warnings)})", expanded=True):
            for w in warnings:
                st.warning(w)
    if missing_students:
        with st.expander(f"Students missing baseline data ({len(missing_students)})", expanded=True):
            st.error("These students are in the subject list but have no Yellis baseline data. "
                     "They will be excluded from target generation.")
            for s in missing_students:
                st.write(f"- {s}")
