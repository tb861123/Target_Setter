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
                value=max(prev, float(existing.get(band, default))),
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
    with st.expander("Edit Individual Student Targets"):
        overrides = render_student_editor(
            df_display, overrides, subject_cols,
            mode="GCSE", key_prefix="sted_gcse_",
        )
        if overrides:
            st.divider()
            st.markdown("**All active overrides:**")
            override_rows = []
            for sk, subj_dict in overrides.items():
                sn, fn = sk.split("|", 1)
                for subj, grade in subj_dict.items():
                    override_rows.append({"Student": f"{sn.title()}, {fn.title()}", "Subject": subj, "Grade": grade})
            st.dataframe(pd.DataFrame(override_rows), use_container_width=True, hide_index=True)
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
        if c not in ("surname", "forename", "year_group", "overall_score", "avg_gcse")
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
            "ALIS score": f"{row['overall_score']:.1f}" if pd.notna(row.get("overall_score")) else "",
        }
        if "avg_gcse" in row.index:
            avg = row.get("avg_gcse")
            r["Avg GCSE"] = f"{avg:.1f}" if pd.notna(avg) else ""
        for subj in subject_cols:
            val = row.get(subj)
            r[subj] = val if pd.notna(val) and val not in ("", None) else ""
        display_rows.append(r)

    display_df = pd.DataFrame(display_rows)
    st.dataframe(display_df, use_container_width=True, height=400)

    # Override editor
    with st.expander("Edit Individual Student Targets"):
        overrides = render_student_editor(
            df_display, overrides, subject_cols,
            mode="AL", key_prefix="sted_al_",
        )
        if overrides:
            st.divider()
            st.markdown("**All active overrides:**")
            override_rows = []
            for sk, subj_dict in overrides.items():
                sn, fn = sk.split("|", 1)
                for subj, grade in subj_dict.items():
                    override_rows.append({"Student": f"{sn.title()}, {fn.title()}", "Subject": subj, "Grade": grade})
            st.dataframe(pd.DataFrame(override_rows), use_container_width=True, hide_index=True)
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


def render_matching_dashboard(
    master_keys: list[str],
    source_keys: dict[str, list[str]],
    ss_key: str = "match_overrides",
    key_prefix: str = "md_",
    deleted_ss_key: str = "gcse_deleted_students",
) -> None:
    """
    Display cross-source student matching status and correction controls.
    Reads and writes match overrides via st.session_state[ss_key].
    Deleted student keys are stored as a set in st.session_state[deleted_ss_key].

    Args:
        master_keys:     list of 'surname|forename' keys from the subject list (source of truth)
        source_keys:     {'Source Name': [keys...]} for each uploaded data source
        ss_key:          session_state key for overrides dict
        key_prefix:      prefix for all widget keys (avoids collisions between GCSE/A Level)
        deleted_ss_key:  session_state key for set of deleted student keys
    """
    from matching import match_sources, issues_only, summary_counts, STATUS_ICON

    if not master_keys or not source_keys:
        return

    current_overrides: dict[str, str] = st.session_state.get(ss_key, {})
    sources = list(source_keys.keys())

    report = match_sources(master_keys, source_keys, manual_overrides=current_overrides)
    counts = summary_counts(report, sources)

    st.markdown("#### Student Matching Status")

    # Per-source summary metrics
    metric_cols = st.columns(len(sources))
    for i, src in enumerate(sources):
        c = counts.get(src, {})
        n_ok = c.get("exact", 0) + c.get("normalised", 0) + c.get("manual", 0)
        n_warn = c.get("fuzzy", 0) + c.get("possible", 0)
        n_bad = c.get("unmatched", 0)
        total = len(master_keys)
        with metric_cols[i]:
            if n_warn + n_bad == 0:
                st.metric(src, f"{n_ok}/{total}", delta="All matched", delta_color="off")
            else:
                st.metric(
                    src,
                    f"{n_ok}/{total} matched",
                    delta=f"{n_warn + n_bad} issue(s)",
                    delta_color="inverse",
                )

    issues = issues_only(report, sources)

    if issues.empty:
        st.success("All students matched across all sources.")
        return

    st.warning(f"{len(issues)} student(s) have potential matching issues.")

    # Bulk-approve button — auto-confirms all high-confidence fuzzy suggestions
    n_confirmable = sum(
        1
        for _, row in issues.iterrows()
        for src in sources
        if row.get(f"{src}_status") in ("fuzzy", "possible")
        and row.get(f"{src}_suggestion")
        and row.get(f"{src}_score", 0) >= 0.85
    )
    if n_confirmable > 0:
        c1, c2 = st.columns([2, 5])
        with c1:
            if st.button(
                f"Auto-confirm {n_confirmable} suggestion(s)",
                key=f"{key_prefix}bulk",
                help="Accepts all suggested matches with ≥85% confidence. "
                     "You can still override individual decisions below.",
            ):
                bulk = dict(current_overrides)
                for _, row in issues.iterrows():
                    mkey = row["master_key"]
                    for src in sources:
                        if row.get(f"{src}_status") not in ("fuzzy", "possible"):
                            continue
                        suggestion = row.get(f"{src}_suggestion")
                        score = row.get(f"{src}_score", 0)
                        if suggestion and score >= 0.85:
                            bulk[f"{src}::{mkey}"] = suggestion
                st.session_state[ss_key] = bulk
                st.success(f"Confirmed {n_confirmable} match(es).")
                st.rerun()
        with c2:
            st.caption(
                "Or expand **Fix Matching Issues** below to review each one individually."
            )

    # Dedup: if the same master_key appears twice (duplicate student in upload),
    # only show one row to avoid duplicate widget keys.
    issues = issues.drop_duplicates(subset="master_key", keep="first")

    # Issues summary table
    tbl_rows = []
    for _, row in issues.iterrows():
        r: dict = {"Student": row["display_name"]}
        for src in sources:
            status = row.get(f"{src}_status", "n/a")
            icon = STATUS_ICON.get(status, "?")
            suggestion = row.get(f"{src}_suggestion")
            score = row.get(f"{src}_score", 0.0)
            if status in ("exact", "normalised", "manual"):
                r[src] = f"{icon}"
            elif status in ("fuzzy", "possible") and suggestion:
                r[src] = f"{icon} {suggestion} ({score:.0%})"
            elif status == "unmatched":
                r[src] = "❌ not found"
            else:
                r[src] = icon
        tbl_rows.append(r)

    st.dataframe(pd.DataFrame(tbl_rows), use_container_width=True, hide_index=True)

    # Correction controls
    with st.expander("Fix Matching Issues", expanded=True):
        st.caption(
            "For each issue, select the correct student from the source data, "
            "or mark as unmatched to exclude from lookups."
        )

        for _, row in issues.iterrows():
            mkey = row["master_key"]
            student_name = row["display_name"]

            issue_srcs = [
                s for s in sources
                if row.get(f"{s}_status") in ("fuzzy", "possible", "unmatched")
            ]
            if not issue_srcs:
                continue

            st.markdown(f"**{student_name}**")
            fix_cols = st.columns(len(issue_srcs))

            for ci, src in enumerate(issue_srcs):
                status = row.get(f"{src}_status")
                suggestion = row.get(f"{src}_suggestion")
                s_keys = sorted(source_keys.get(src, []))
                override_key = f"{src}::{mkey}"
                wkey = f"{key_prefix}{src}_{mkey}"

                options = [
                    "(no change)",
                    "(delete student)",
                    "(ignore issue)",
                ] + s_keys + ["(mark as unmatched)"]

                # Determine pre-fill value
                saved = current_overrides.get(override_key)
                deleted_set = st.session_state.get(deleted_ss_key, set())
                if mkey in deleted_set or saved == "__DELETED__":
                    default = "(delete student)"
                elif saved == "__IGNORED__":
                    default = "(ignore issue)"
                elif saved == "__UNMATCHED__":
                    default = "(mark as unmatched)"
                elif saved and saved in s_keys:
                    default = saved
                elif suggestion and suggestion in s_keys:
                    default = suggestion
                else:
                    default = "(no change)"

                if wkey not in st.session_state:
                    st.session_state[wkey] = default

                with fix_cols[ci]:
                    st.selectbox(
                        f"{src}",
                        options,
                        key=wkey,
                        help=(
                            f"Status: {status}"
                            + (f" — suggested: {suggestion}" if suggestion else "")
                        ),
                    )

        if st.button("Save Matching Corrections", key=f"{key_prefix}save", type="primary"):
            new_overrides = dict(current_overrides)
            new_deleted: set = set(st.session_state.get(deleted_ss_key, set()))
            for _, row in issues.iterrows():
                mkey = row["master_key"]
                issue_srcs = [
                    s for s in sources
                    if row.get(f"{s}_status") in ("fuzzy", "possible", "unmatched")
                ]
                for src in issue_srcs:
                    override_key = f"{src}::{mkey}"
                    wkey = f"{key_prefix}{src}_{mkey}"
                    sel = st.session_state.get(wkey, "(no change)")
                    if sel == "(no change)":
                        new_overrides.pop(override_key, None)
                        new_deleted.discard(mkey)
                    elif sel == "(delete student)":
                        new_overrides[override_key] = "__DELETED__"
                        new_deleted.add(mkey)
                    elif sel == "(ignore issue)":
                        new_overrides[override_key] = "__IGNORED__"
                        new_deleted.discard(mkey)
                    elif sel == "(mark as unmatched)":
                        new_overrides[override_key] = "__UNMATCHED__"
                        new_deleted.discard(mkey)
                    else:
                        new_overrides[override_key] = sel
                        new_deleted.discard(mkey)
            st.session_state[ss_key] = new_overrides
            st.session_state[deleted_ss_key] = new_deleted
            st.success("Matching corrections saved.")
            st.rerun()

        if current_overrides:
            if st.button(
                "Clear All Matching Corrections",
                key=f"{key_prefix}clear",
                type="secondary",
            ):
                st.session_state[ss_key] = {}
                st.rerun()


def render_grade_distribution_chart(targets_df: pd.DataFrame, mode: str) -> None:
    """Grade distribution as cumulative percentage per subject."""
    if mode == "GCSE":
        # Cumulative from top: "9", "8+", "7+", ..., "2+"
        cum_labels = [str(9)] + [f"{g}+" for g in range(8, 1, -1)]
        cum_sets: dict[str, set] = {
            str(9): {9},
            **{f"{g}+": set(range(g, 10)) for g in range(8, 1, -1)},
        }
    else:
        al_order = ["A*", "A", "B", "C", "D", "E"]
        cum_labels = ["A*", "A*-A", "A*-B", "A*-C", "A*-D", "A*-E"]
        cum_sets = {
            "A*":   {"A*"},
            "A*-A": {"A*", "A"},
            "A*-B": {"A*", "A", "B"},
            "A*-C": {"A*", "A", "B", "C"},
            "A*-D": {"A*", "A", "B", "C", "D"},
            "A*-E": {"A*", "A", "B", "C", "D", "E"},
        }

    meta_cols = {"surname", "forename", "form", "year_group", "overall_score", "avg_gcse"}
    subj_cols = sorted([c for c in targets_df.columns if c.lower() not in meta_cols and c not in meta_cols])
    if not subj_cols:
        return

    def _to_comparable(v: object):
        """Return comparable grade value (int for GCSE, str for AL) or None."""
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        s = str(v).strip()
        if s.lower() in ("nan", "n/a", ""):
            return None
        if mode == "GCSE":
            try:
                return int(round(float(s)))
            except (ValueError, TypeError):
                return None
        return s

    rows = []
    for subj in subj_cols:
        col_comp = targets_df[subj].apply(_to_comparable).dropna()
        n = len(col_comp)
        row: dict = {"Subject": subj}
        for label in cum_labels:
            gs = cum_sets[label]
            count = int(col_comp.apply(lambda v: v in gs).sum())
            row[label] = f"{count / n * 100:.1f}%" if n > 0 else "—"
        row["n"] = n
        rows.append(row)

    if not rows:
        return

    chart_df = pd.DataFrame(rows).set_index("Subject")

    st.markdown("#### Grade Distribution by Subject (cumulative %)")
    st.caption(
        "Each column shows the % of students at or above that grade threshold. "
        "'n' = students with a prediction for that subject."
    )
    st.dataframe(chart_df, use_container_width=True)


def render_student_editor(
    df_display: pd.DataFrame,
    overrides: dict,
    subject_cols: list[str],
    mode: str = "GCSE",
    key_prefix: str = "sted_gcse_",
) -> dict:
    """
    Full per-student target editor.
    Shows a student selector and a table of their current targets.
    Returns the (possibly updated) overrides dict.
    """
    from target_engine import ALEVEL_GRADES_ORDERED, ALEVEL_GRADE_MAP

    if mode == "GCSE":
        grade_options: list = list(range(9, 0, -1))
    else:
        grade_options = ALEVEL_GRADES_ORDERED

    # Build sorted student list
    students: list[tuple[str, str]] = sorted(
        {(str(row["surname"]).strip(), str(row["forename"]).strip())
         for _, row in df_display.iterrows()
         if pd.notna(row.get("surname")) and pd.notna(row.get("forename"))},
        key=lambda x: (x[0].lower(), x[1].lower()),
    )
    if not students:
        return overrides

    display_opts = [f"{sn.title()}, {fn.title()}" for sn, fn in students]
    sel_idx = st.selectbox(
        "Select student",
        range(len(display_opts)),
        format_func=lambda i: display_opts[i],
        key=f"{key_prefix}sel",
    )
    if sel_idx is None:
        return overrides

    sn, fn = students[sel_idx]
    student_key = f"{sn.lower()}|{fn.lower()}"

    mask = (
        (df_display["surname"].str.lower() == sn.lower())
        & (df_display["forename"].str.lower() == fn.lower())
    )
    rows_match = df_display[mask]
    if rows_match.empty:
        st.warning("Student not found in targets DataFrame.")
        return overrides

    student_row = rows_match.iloc[0]
    existing_student_overrides = overrides.get(student_key, {})

    # Build a preview table of current targets
    preview = []
    for subj in subject_cols:
        val = student_row.get(subj)
        if pd.notna(val) and val not in ("", "N/A", None):
            is_ovr = subj in existing_student_overrides
            try:
                disp = str(int(round(float(val)))) if mode == "GCSE" else str(val)
            except (ValueError, TypeError):
                disp = str(val)
            preview.append({
                "Subject": subj,
                "Current Target": disp,
                "Overridden": "🔧" if is_ovr else "",
            })

    if preview:
        st.dataframe(
            pd.DataFrame(preview),
            use_container_width=True,
            hide_index=True,
            height=min(200, 35 + 35 * len(preview)),
        )

    st.markdown("**Set a new target for one subject:**")
    c1, c2, c3 = st.columns([3, 2, 2])
    with c1:
        sel_subj = st.selectbox("Subject", subject_cols, key=f"{key_prefix}subj")
    with c2:
        # Pre-fill current value
        cur_val = student_row.get(sel_subj)
        try:
            cur_grade = int(round(float(cur_val))) if mode == "GCSE" else str(cur_val)
        except (TypeError, ValueError):
            cur_grade = grade_options[0]
        default_idx = grade_options.index(cur_grade) if cur_grade in grade_options else 0
        sel_grade = st.selectbox(
            "New Grade", grade_options, index=default_idx, key=f"{key_prefix}grade"
        )
    with c3:
        st.write("")
        st.write("")
        if st.button("Apply", key=f"{key_prefix}apply", type="primary"):
            if student_key not in overrides:
                overrides[student_key] = {}
            overrides[student_key][sel_subj] = sel_grade
            st.success(f"Set {sn.title()} {fn.title()} — {sel_subj} → {sel_grade}")
            st.rerun()

    # Clear student overrides
    if existing_student_overrides:
        st.caption(f"{len(existing_student_overrides)} override(s) active for this student.")
        if st.button(
            f"Clear all overrides for {sn.title()} {fn.title()}",
            key=f"{key_prefix}clear_student",
            type="secondary",
        ):
            overrides.pop(student_key, None)
            st.rerun()

    return overrides


def render_historical_comparison(
    targets_df: pd.DataFrame,
    historical_df: pd.DataFrame,
    mode: str = "GCSE",
) -> None:
    """
    Compare current target cumulative % against historical outcomes per subject.
    """
    from historical_adapter import (
        aggregate_historical,
        compare_targets_to_historical,
        GCSE_CUM_LABELS,
        ALEVEL_CUM_LABELS,
    )

    if historical_df is None or historical_df.empty:
        st.info("No historical results loaded.")
        return

    cum_labels = GCSE_CUM_LABELS if mode == "GCSE" else ALEVEL_CUM_LABELS
    top_label  = cum_labels[0]   # "9" or "A*"
    mid_label  = cum_labels[2]   # "7+" or "A*-B"

    hist_agg = aggregate_historical(historical_df, mode)
    if hist_agg.empty:
        st.warning("Historical data could not be aggregated.")
        return

    cmp = compare_targets_to_historical(targets_df, hist_agg, mode)
    if cmp.empty:
        st.info(
            "No subjects overlap between current targets and historical data. "
            "Check that subject names match exactly."
        )
        return

    years_present = sorted(historical_df["Year"].unique()) if "Year" in historical_df.columns else []
    if len(years_present) > 1:
        st.caption(f"Historical data covers: {', '.join(str(y) for y in years_present)}")

    st.markdown("#### Target vs Historical (cumulative %)")
    st.caption(
        "Cumulative % at or above each grade threshold. "
        "Δ = target% − historical%  (positive = targeting higher than historical)."
    )

    summary_rows = []
    for _, row in cmp.iterrows():
        t_top = row.get(f"{top_label}_target%", 0)
        h_top = row.get(f"{top_label}_hist%", 0)
        d_top = row.get(f"{top_label}_Δ", 0)
        t_mid = row.get(f"{mid_label}_target%", 0)
        h_mid = row.get(f"{mid_label}_hist%", 0)
        d_mid = row.get(f"{mid_label}_Δ", 0)
        signal = "🔼 Higher" if isinstance(d_top, (int, float)) and d_top > 5 else (
                 "🔽 Lower"  if isinstance(d_top, (int, float)) and d_top < -5 else "➡ Similar")
        summary_rows.append({
            "Subject": row["Subject"],
            "n": int(row.get("n_students", 0)),
            f"{top_label} target": f"{t_top:.0f}%",
            f"{top_label} hist":   f"{h_top:.0f}%",
            f"{top_label} Δ":      f"{d_top:+.1f}%" if isinstance(d_top, (int, float)) else "—",
            f"{mid_label} target": f"{t_mid:.0f}%",
            f"{mid_label} hist":   f"{h_mid:.0f}%",
            f"{mid_label} Δ":      f"{d_mid:+.1f}%" if isinstance(d_mid, (int, float)) else "—",
            "Trend": signal,
        })

    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    with st.expander("Subject drill-down (all thresholds)"):
        subj_choices = cmp["Subject"].tolist()
        sel_subj = st.selectbox("Subject", subj_choices, key="hist_cmp_subj_sel")
        if sel_subj:
            subj_row = cmp[cmp["Subject"] == sel_subj].iloc[0]
            detail_rows = []
            for label in cum_labels:
                t_pct = subj_row.get(f"{label}_target%", 0)
                h_pct = subj_row.get(f"{label}_hist%", 0)
                delta = subj_row.get(f"{label}_Δ", 0)
                detail_rows.append({
                    "Threshold": label,
                    "Target %": f"{t_pct:.1f}%",
                    "Historical %": f"{h_pct:.1f}%",
                    "Δ": f"{delta:+.1f}%" if isinstance(delta, (int, float)) else "—",
                })
            st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

    if len(years_present) > 1:
        with st.expander("Year-by-year historical breakdown"):
            cum_cols = [f"cum_pct_{l}" for l in cum_labels]
            overlap_subjects = sorted(
                s for s in targets_df.columns
                if s not in {"surname", "forename", "form", "year_group", "overall_score", "avg_gcse"}
                and s in historical_df["Subject"].values
            )
            if overlap_subjects:
                sel_subj2 = st.selectbox("Subject", overlap_subjects, key="hist_year_subj_sel")
                yearly = historical_df[historical_df["Subject"] == sel_subj2]
                if not yearly.empty:
                    display_cols = ["Year"] + [c for c in cum_cols if c in yearly.columns] + ["n"]
                    yearly_display = yearly[display_cols].copy()
                    yearly_display.columns = [c.replace("cum_pct_", "") for c in yearly_display.columns]
                    st.dataframe(yearly_display, use_container_width=True, hide_index=True)

def render_target_explanation(
    targets_df: pd.DataFrame,
    mode: str,
    session_state: dict,
    key_prefix: str = "texpl_",
) -> None:
    """
    Interactive target explanation selector: choose a student and subject to see
    a breakdown of how their target was derived.

    session_state should be st.session_state (passed in for testability).
    """
    from target_engine import ALEVEL_GRADE_MAP, ALEVEL_GRADES_ORDERED

    meta_cols = {"surname", "forename", "form", "year_group", "overall_score", "avg_gcse"}
    subj_cols = sorted([c for c in targets_df.columns if c not in meta_cols])
    if not subj_cols:
        st.info("No subject columns found in targets.")
        return

    students_sorted = sorted(
        {(str(r["surname"]).strip(), str(r["forename"]).strip())
         for _, r in targets_df.iterrows()
         if pd.notna(r.get("surname")) and pd.notna(r.get("forename"))},
        key=lambda x: (x[0].lower(), x[1].lower()),
    )
    if not students_sorted:
        return

    display_opts = [f"{sn.title()}, {fn.title()}" for sn, fn in students_sorted]
    c1, c2 = st.columns(2)
    with c1:
        sel_idx = st.selectbox(
            "Student",
            range(len(display_opts)),
            format_func=lambda i: display_opts[i],
            key=f"{key_prefix}student",
        )
    with c2:
        sel_subj = st.selectbox("Subject", subj_cols, key=f"{key_prefix}subject")

    if sel_idx is None or not sel_subj:
        return

    sn, fn = students_sorted[sel_idx]
    student_key = f"{sn.lower()}|{fn.lower()}"
    display_name = f"{sn.title()} {fn.title()}"

    # Look up current target for this student/subject
    mask = (
        (targets_df["surname"].str.lower() == sn.lower())
        & (targets_df["forename"].str.lower() == fn.lower())
    )
    rows = targets_df[mask]
    if rows.empty:
        st.warning(f"Student {display_name} not found in targets DataFrame.")
        return

    row = rows.iloc[0]
    target_val = row.get(sel_subj)
    target_display = (
        str(int(round(float(target_val)))) if mode == "GCSE" and pd.notna(target_val)
        else (str(target_val) if pd.notna(target_val) else "N/A")
    )
    has_override = (
        sel_subj in session_state.get("overrides", {}).get(student_key, {})
    )

    st.markdown(f"**{display_name} — {sel_subj}**")
    st.markdown(f"**Target: {target_display}**{'  🔧 *(manually overridden)*' if has_override else ''}")
    st.divider()

    if mode == "GCSE":
        _explain_gcse_target(sn, fn, student_key, sel_subj, target_val, session_state, targets_df)
    else:
        _explain_alevel_target(sn, fn, student_key, sel_subj, target_val, session_state, targets_df)


def _explain_gcse_target(sn, fn, student_key, subject, target_val, ss, targets_df):
    """Render GCSE target explanation."""
    use_pred = ss.get("gcse_use_predictions", False) and ss.get("gcse_yellis_pred_data")

    # Yellis baseline score
    yellis_df = ss.get("gcse_yellis_df")
    yellis_score = None
    if yellis_df is not None:
        mask = (
            (yellis_df["surname"].str.lower() == sn.lower())
            & (yellis_df["forename"].str.lower().str.startswith(fn.lower()[:3]))
        )
        m_rows = yellis_df[mask]
        if not m_rows.empty:
            yellis_score = m_rows.iloc[0].get("overall_score")

    if yellis_score is not None:
        st.metric("Yellis baseline score", f"{yellis_score:.1f}")

    if use_pred:
        # Yellis predictions mode
        from gcse_predictions_adapter import YellisGCSELookup
        pred_data = ss.get("gcse_yellis_pred_data", {})
        pct = ss.get("gcse_yellis_pred_percentile", "standard")
        src = ss.get("gcse_yellis_pred_source", "score")
        bound = ss.get("gcse_yellis_pred_bound", "lower")

        lookup = YellisGCSELookup(pred_data, percentile=pct, source=src, grade_bound=bound)
        row_idx = lookup._resolve_name(student_key)
        col_name = lookup._resolve_subject(subject)

        st.markdown(f"**Method:** Yellis per-student predictions ({pct} percentile, {src} data)")

        if row_idx is not None and col_name is not None and lookup._df is not None:
            raw_val = lookup._df.at[row_idx, col_name]
            if src == "score":
                try:
                    st.metric("Raw decimal prediction", f"{float(raw_val):.2f}")
                    st.caption("Rounded to nearest integer grade.")
                except (TypeError, ValueError):
                    st.write(f"Raw value: {raw_val}")
            else:
                st.metric("Grade boundary", str(raw_val))
                st.caption(f"Using {bound} bound of boundary pair.")
        else:
            st.warning(
                "Student or subject not found in predictions file. "
                "Grade may have been set to N/A or defaulted."
            )

        # Dept adjustment
        dept_adj = ss.get("dept_adjustments", {}).get(subject, 0)
        if dept_adj:
            st.metric("Department adjustment", f"{dept_adj:+.1f} grades")
        else:
            st.caption("No department adjustment for this subject.")

    else:
        # Distribution mode
        st.markdown("**Method:** Distribution curve (rank-based)")

        subj_df = targets_df[targets_df[subject].notna()].copy() if subject in targets_df.columns else pd.DataFrame()
        if yellis_score is not None and not subj_df.empty:
            if "overall_score" in subj_df.columns:
                subj_df_sorted = subj_df.sort_values("overall_score", ascending=False)
                rank_vals = subj_df_sorted["overall_score"].tolist()
                rank = next((i + 1 for i, s in enumerate(rank_vals) if abs(float(s or 0) - float(yellis_score or 0)) < 0.01), None)
                n_subj = len(rank_vals)
                if rank:
                    st.metric("Rank in subject cohort", f"{rank} of {n_subj}")
                    st.caption(
                        f"Students are ranked by Yellis score. "
                        f"The target grade distribution is applied across these {n_subj} students."
                    )

        dist = ss.get("distribution", {})
        if dist:
            st.markdown("**Grade distribution applied:**")
            dist_rows = [{"Grade": g, "Proportion": f"{v:.0%}"} for g, v in sorted(dist.items(), reverse=True)]
            st.dataframe(pd.DataFrame(dist_rows), hide_index=True, use_container_width=False)
        else:
            st.caption("No distribution configured — default used.")

        dept_adj = ss.get("dept_adjustments", {}).get(subject, 0)
        if dept_adj:
            st.metric("Department adjustment", f"{dept_adj:+.1f} grades")
        else:
            st.caption("No department adjustment for this subject.")

    # GCSE sub-score note
    if ss.get("use_subscores", False):
        weights = ss.get("subscore_weights", {})
        st.caption(
            "Sub-scores are weighted: "
            + ", ".join(f"{k}={v:.0%}" for k, v in weights.items() if v)
        )


def _explain_alevel_target(sn, fn, student_key, subject, target_val, ss, targets_df):
    """Render A Level target explanation."""
    from target_engine import ALEVEL_GRADE_MAP, ALEVEL_GRADES_ORDERED

    has_alis = ss.get("al_alis_data") is not None
    has_composite = (
        ss.get("al_yellis_df") is not None
        and ss.get("al_gcse_wide_df") is not None
    )

    # ALIS score
    alis_score = row_val = None
    if "overall_score" in targets_df.columns:
        mask = (
            (targets_df["surname"].str.lower() == sn.lower())
            & (targets_df["forename"].str.lower() == fn.lower())
        )
        m = targets_df[mask]
        if not m.empty:
            row_val = m.iloc[0].get("overall_score")
            alis_score = row_val

    avg_gcse = None
    if "avg_gcse" in targets_df.columns:
        mask = (
            (targets_df["surname"].str.lower() == sn.lower())
            & (targets_df["forename"].str.lower() == fn.lower())
        )
        m = targets_df[mask]
        if not m.empty:
            avg_gcse = m.iloc[0].get("avg_gcse")

    if alis_score is not None and pd.notna(alis_score):
        st.metric("ALIS score (baseline)", f"{alis_score:.1f}")
    if avg_gcse is not None and pd.notna(avg_gcse):
        st.metric("Average GCSE grade", f"{avg_gcse:.2f}")

    if has_alis:
        from alis_adapter import ALISLookup, DEFAULT_PROXY_MAP, ALIS_TO_APP
        pct = ss.get("al_alis_percentile", "75th")
        mode_str = ss.get("al_alis_mode", "direct")
        proxy_map = dict(DEFAULT_PROXY_MAP)
        proxy_map.update(ss.get("al_alis_proxy_map", {}))
        match_overrides = ss.get("match_overrides", {})

        st.markdown(f"**Method:** ALIS Adapt ({pct} percentile, {mode_str} mode)")

        # Find the ALIS subject key for this subject
        alis_subj_key = None
        for app_subj, alis_subj in ALIS_TO_APP.items():
            if alis_subj.lower() == subject.lower() or app_subj.lower() == subject.lower():
                alis_subj_key = app_subj
                break
        if alis_subj_key is None:
            # Try proxy map
            for proxy_from, proxy_to in proxy_map.items():
                if proxy_to.lower() == subject.lower():
                    alis_subj_key = proxy_from
                    break

        alis_data = ss.get("al_alis_data")
        if alis_data and alis_subj_key:
            try:
                lookup = ALISLookup(
                    alis_data,
                    percentile=pct,
                    mode=mode_str,
                    proxy_map=proxy_map,
                )
                # Resolve student key via match overrides
                remap = {
                    k[len("ALIS Adapt::"):]: v
                    for k, v in match_overrides.items()
                    if k.startswith("ALIS Adapt::")
                    and v not in ("__UNMATCHED__", "__IGNORED__", "__DELETED__")
                }
                effective_key = remap.get(student_key, student_key)
                raw_grade = lookup.get_grade(effective_key, subject)
                if raw_grade is not None:
                    st.metric("ALIS predicted grade", raw_grade)
                else:
                    st.caption(f"No ALIS prediction found for {subject} (key: {effective_key}).")
            except Exception as e:
                st.caption(f"Could not retrieve ALIS prediction: {e}")
        else:
            st.caption(f"Subject '{subject}' has no direct ALIS mapping.")

    if has_composite and not has_alis:
        st.markdown("**Method:** Composite (Yellis + GCSE baseline)")
        blend_w = ss.get("al_alis_blend_weight", 0.5)
        st.caption(
            f"ALIS/Yellis weight: {blend_w:.0%}   GCSE baseline weight: {1 - blend_w:.0%}"
        )

    if has_alis and ss.get("al_gcse_baseline_data") is not None:
        blend_w = ss.get("al_alis_blend_weight", 0.5)
        if blend_w < 1.0:
            st.caption(f"Blend: {blend_w:.0%} ALIS + {1 - blend_w:.0%} GCSE baseline.")

    # Department adjustment
    dept_adj = ss.get("dept_adjustments", {}).get(subject, 0)
    if dept_adj:
        try:
            pre_adj_num = ALEVEL_GRADE_MAP.get(str(target_val))
            if pre_adj_num is not None:
                post_num = int(round(pre_adj_num - dept_adj))
                post_num = max(1, min(6, post_num))
                from target_engine import ALEVEL_GRADE_REVERSE
                pre_grade = ALEVEL_GRADE_REVERSE.get(int(round(pre_adj_num)))
                st.metric("Department adjustment", f"{dept_adj:+.1f}", help="Positive = grade boosted")
                st.caption(f"Pre-adjustment grade would have been: {pre_grade}")
        except Exception:
            st.metric("Department adjustment", f"{dept_adj:+.1f} grades")
    else:
        st.caption("No department adjustment for this subject.")
