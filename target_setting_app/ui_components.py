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
) -> None:
    """
    Display cross-source student matching status and correction controls.
    Reads and writes match overrides via st.session_state[ss_key].

    Args:
        master_keys:  list of 'surname|forename' keys from the subject list (source of truth)
        source_keys:  {'Source Name': [keys...]} for each uploaded data source
        ss_key:       session_state key under which overrides dict is stored
        key_prefix:   prefix for all widget keys (avoids collisions between GCSE/A Level)
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

                options = ["(no change)"] + s_keys + ["(mark as unmatched)"]

                # Determine pre-fill value
                saved = current_overrides.get(override_key)
                if saved == "__UNMATCHED__":
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
                    elif sel == "(mark as unmatched)":
                        new_overrides[override_key] = "__UNMATCHED__"
                    else:
                        new_overrides[override_key] = sel
            st.session_state[ss_key] = new_overrides
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
    """Grade distribution pivot table per subject."""
    if mode == "GCSE":
        grade_order = [str(g) for g in range(9, 0, -1)]
    else:
        grade_order = ["A*", "A", "B", "C", "D", "E"]

    meta_cols = {"surname", "forename", "form", "year_group", "overall_score", "avg_gcse"}
    subj_cols = sorted([c for c in targets_df.columns if c.lower() not in meta_cols and c not in meta_cols])
    if not subj_cols:
        return

    def _to_grade_str(v: object) -> str | None:
        """Normalise a grade value to a string label (e.g. 7.0 → '7')."""
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        s = str(v).strip()
        if s.lower() in ("nan", "n/a", ""):
            return None
        if mode == "GCSE":
            try:
                return str(int(round(float(s))))
            except (ValueError, TypeError):
                pass
        return s

    rows = []
    for subj in subj_cols:
        col_raw = targets_df[subj]
        col_str = col_raw.apply(_to_grade_str).dropna()
        row = {"Subject": subj}
        total = len(col_str)
        for grade in grade_order:
            row[grade] = int((col_str == grade).sum())
        row["n"] = total
        rows.append(row)

    if not rows:
        return

    chart_df = pd.DataFrame(rows).set_index("Subject")
    cols_present = [g for g in grade_order if g in chart_df.columns]
    chart_df = chart_df[cols_present + ["n"]]

    st.markdown("#### Grade Distribution by Subject")
    st.caption("Count of students at each grade. 'n' = students with a prediction for that subject.")
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
    Compare current target grade distribution against historical outcomes per subject.
    """
    from historical_adapter import aggregate_historical, compare_targets_to_historical

    if historical_df is None or historical_df.empty:
        st.info("No historical results loaded.")
        return

    grades = [str(g) for g in range(9, 0, -1)] if mode == "GCSE" else ["A*", "A", "B", "C", "D", "E"]

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

    # ---- Summary table (one row per subject) ----
    years_present = sorted(historical_df["Year"].unique()) if "Year" in historical_df.columns else []
    if len(years_present) > 1:
        st.caption(f"Historical data covers: {', '.join(str(y) for y in years_present)}")

    st.markdown("#### Target vs Historical Distribution")
    st.caption(
        "Shows current target grade distribution alongside historical outcomes. "
        "Δ = target% − historical%  (positive = targeting higher than historical)."
    )

    # Compact view: highlight top grade and avg delta
    summary_rows = []
    top_grade = grades[0]  # "9" or "A*"
    for _, row in cmp.iterrows():
        t_top = row.get(f"{top_grade}_target%", 0)
        h_top = row.get(f"{top_grade}_hist%", 0)
        delta_top = row.get(f"{top_grade}_Δ", 0)
        avg_t = row.get("avg_target", "")
        avg_h = row.get("avg_hist", "")
        avg_d = row.get("avg_Δ", "")

        if isinstance(delta_top, (int, float)):
            if delta_top > 5:
                signal = "🔼 Higher"
            elif delta_top < -5:
                signal = "🔽 Lower"
            else:
                signal = "➡ Similar"
        else:
            signal = "—"

        summary_rows.append({
            "Subject": row["Subject"],
            "n (targets)": int(row.get("n_students", 0)),
            f"{top_grade} target%": f"{t_top:.0f}%",
            f"{top_grade} hist%": f"{h_top:.0f}%",
            f"{top_grade} Δ": f"{delta_top:+.1f}%" if isinstance(delta_top, (int, float)) else "—",
            "Avg target": avg_t,
            "Avg hist": avg_h,
            "Avg Δ": f"{avg_d:+.2f}" if isinstance(avg_d, (int, float)) else "—",
            "Trend": signal,
        })

    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    # Per-subject drill-down
    with st.expander("Subject drill-down (full grade breakdown)"):
        subj_choices = cmp["Subject"].tolist()
        sel_subj = st.selectbox("Subject", subj_choices, key="hist_cmp_subj_sel")
        if sel_subj:
            subj_row = cmp[cmp["Subject"] == sel_subj].iloc[0]
            detail_rows = []
            for g in grades:
                t_pct = subj_row.get(f"{g}_target%", 0)
                h_pct = subj_row.get(f"{g}_hist%", 0)
                delta  = subj_row.get(f"{g}_Δ", 0)
                detail_rows.append({
                    "Grade": g,
                    "Target %": f"{t_pct:.1f}%",
                    "Historical %": f"{h_pct:.1f}%",
                    "Δ": f"{delta:+.1f}%" if isinstance(delta, (int, float)) else "—",
                })
            st.dataframe(
                pd.DataFrame(detail_rows),
                use_container_width=True,
                hide_index=True,
            )

    # Year-by-year view if multiple years
    if len(years_present) > 1:
        with st.expander("Year-by-year historical breakdown"):
            subj_choices2 = sorted(
                s for s in targets_df.columns
                if s not in {"surname", "forename", "form", "year_group", "overall_score", "avg_gcse"}
                and s in historical_df["Subject"].values
            )
            if subj_choices2:
                sel_subj2 = st.selectbox("Subject", subj_choices2, key="hist_year_subj_sel")
                yearly = historical_df[historical_df["Subject"] == sel_subj2]
                if not yearly.empty:
                    display_cols = ["Year"] + [g for g in grades if g in yearly.columns] + ["n"]
                    st.dataframe(yearly[display_cols], use_container_width=True, hide_index=True)
