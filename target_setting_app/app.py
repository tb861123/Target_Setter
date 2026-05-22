"""Emanuel School — Target Setting Tool (Main Streamlit App)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import io
import pandas as pd
import streamlit as st

import session_manager as sm
from data_ingestion import (
    parse_yellis_gcse,
    parse_yellis_alevel,
    parse_gcse_grades,
    parse_subject_list,
)
from target_engine import (
    GCSETargetEngine,
    ALevelTargetEngine,
    compute_gcse_summary,
    compute_alevel_summary,
)
from subject_profiles import DEFAULT_PROFILES, ALL_A_LEVEL_SUBJECTS
from export import export_gcse, export_alevel
from ui_components import (
    render_distribution_inputs,
    render_dept_adjustments,
    render_gcse_matrix,
    render_alevel_matrix,
    render_validation_warnings,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Emanuel School — Target Setting",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

sm.init_db()

# ---------------------------------------------------------------------------
# Helper functions (must be defined before use in mode blocks below)
# ---------------------------------------------------------------------------

def _do_gcse_generate() -> None:
    with st.spinner("Generating GCSE targets..."):
        try:
            engine = GCSETargetEngine(
                yellis_df=st.session_state["gcse_yellis_df"],
                subject_list_df=st.session_state["gcse_subject_list_df"],
                distribution=st.session_state.get("distribution", {}),
                use_subscores=st.session_state.get("use_subscores", False),
                subscore_weights=st.session_state.get("subscore_weights", {}),
                dept_adjustments=st.session_state.get("dept_adjustments", {}),
            )
            targets = engine.generate()
            st.session_state["targets_df"] = targets
            st.rerun()
        except Exception as e:
            st.error(f"Error generating targets: {e}")
            raise


def _do_alevel_generate() -> None:
    with st.spinner("Generating A Level targets..."):
        try:
            engine = ALevelTargetEngine(
                yellis_df=st.session_state["al_yellis_df"],
                gcse_wide_df=st.session_state["al_gcse_wide_df"],
                subject_list_df=st.session_state["al_subject_list_df"],
                distribution=st.session_state.get("distribution", {}),
                gcse_weight=st.session_state.get("gcse_weight", 0.80),
                yellis_weight=st.session_state.get("yellis_weight", 0.20),
                fallback_ratio=st.session_state.get("fallback_ratio", 0.60),
                profile_overrides=st.session_state.get("profile_overrides", {}),
                dept_adjustments=st.session_state.get("dept_adjustments", {}),
            )
            targets = engine.generate()
            st.session_state["targets_df"] = targets
            st.rerun()
        except Exception as e:
            st.error(f"Error generating targets: {e}")
            raise


def _render_weight_editor(weights: dict, key_prefix: str) -> dict:
    """Render numeric inputs for profile component weights. Returns updated dict."""
    new_weights = {}
    total = 0.0
    items = list(weights.items())
    if not items:
        return {}
    cols = st.columns(min(len(items), 4))
    for i, (comp, w) in enumerate(items):
        with cols[i % len(cols)]:
            display_name = comp.replace("_", " ").title()
            val = st.number_input(
                display_name,
                0.0,
                1.0,
                float(w),
                0.05,
                format="%.2f",
                key=f"{key_prefix}_{comp}",
            )
            new_weights[comp] = val
            total += val
    if abs(total - 1.0) > 0.01:
        st.warning(f"Weights sum to {total:.2f} (should be 1.00)")
    return new_weights


def _progress_bar(step: int) -> None:
    steps = ["Upload Data", "Configure", "Generate Targets", "Review Matrix", "Export"]
    progress_pct = (step + 1) / len(steps)
    st.progress(progress_pct, text=f"Step {step + 1}/{len(steps)}: {steps[step]}")


def _nav_buttons(back: bool = True, forward_label: str = "Next →", forward_key: str = "fwd") -> None:
    cols = st.columns([1, 4, 1])
    with cols[0]:
        if back and st.button("← Back", key=f"back_{forward_key}"):
            st.session_state["step"] -= 1
            st.rerun()
    with cols[2]:
        if forward_label and st.button(forward_label, key=f"fwd_{forward_key}", type="primary"):
            st.session_state["step"] += 1
            st.rerun()


# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

def _init_state() -> None:
    defaults = {
        "mode": "GCSE",
        "step": 0,
        "gcse_yellis_df": None,
        "gcse_subject_list_df": None,
        "gcse_warnings": [],
        "gcse_missing_students": [],
        "al_yellis_df": None,
        "al_gcse_wide_df": None,
        "al_subject_list_df": None,
        "al_warnings": [],
        "al_missing_students": [],
        "distribution": {},
        "use_subscores": False,
        "subscore_weights": {},
        "dept_adjustments": {},
        "gcse_weight": 0.80,
        "yellis_weight": 0.20,
        "fallback_ratio": 0.60,
        "profile_overrides": {},
        "targets_df": None,
        "overrides": {},
        "session_name": "Default",
        "_confirm_regen": False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


_init_state()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("Target Setting Tool")
    st.markdown("**Emanuel School**")
    st.divider()

    mode = st.radio(
        "Mode",
        ["GCSE", "A Level"],
        index=0 if st.session_state["mode"] == "GCSE" else 1,
        horizontal=True,
    )
    if mode != st.session_state["mode"]:
        st.session_state["mode"] = mode
        st.session_state["step"] = 0
        st.session_state["targets_df"] = None
        st.session_state["overrides"] = {}
        st.rerun()

    st.divider()
    st.subheader("Session")

    session_name = st.text_input(
        "Session name",
        value=st.session_state["session_name"],
        key="session_name_input",
    )
    st.session_state["session_name"] = session_name

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Save", use_container_width=True):
            state_to_save = {
                k: v
                for k, v in st.session_state.items()
                if not k.startswith("_") and k != "session_name_input"
            }
            sm.save_session(session_name, mode, state_to_save)
            st.success("Saved.")

    sessions = sm.list_sessions(mode)
    if sessions:
        with col2:
            sel_id = st.selectbox(
                "Load session",
                options=[s["id"] for s in sessions],
                format_func=lambda x: next(
                    (
                        f"{s['name']} ({s['updated_at'][:10]})"
                        for s in sessions
                        if s["id"] == x
                    ),
                    str(x),
                ),
                key="load_session_select",
                label_visibility="collapsed",
            )
        if st.button("Load selected", use_container_width=True):
            loaded = sm.load_session(sel_id)
            if loaded:
                for k, v in loaded.items():
                    st.session_state[k] = v
                st.success("Session loaded.")
                st.rerun()

    st.divider()
    step_display = st.session_state["step"] + 1
    st.caption(f"Current step: {step_display}/5")
    if st.session_state.get("targets_df") is not None:
        st.success("Targets generated ✓")

# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

mode = st.session_state["mode"]
step = st.session_state["step"]

st.title(f"{'GCSE' if mode == 'GCSE' else 'A Level'} Target Setting — Emanuel School")
_progress_bar(step)
st.divider()

# ===========================================================================
# GCSE MODE
# ===========================================================================

if mode == "GCSE":

    # -------------------------------------------------------------------
    # Step 0 — Upload
    # -------------------------------------------------------------------
    if step == 0:
        st.header("Step 1 — Upload Data")
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Yellis Baseline (Year 10)")
            yellis_file = st.file_uploader(
                "Upload Yellis GCSE Excel (.xlsx)",
                type=["xlsx"],
                key="gcse_yellis_upload",
            )
            if yellis_file:
                try:
                    df, warnings = parse_yellis_gcse(yellis_file)
                    st.session_state["gcse_yellis_df"] = df
                    st.session_state["gcse_warnings"] = warnings
                    st.success(f"Loaded {len(df)} students.")
                    with st.expander("Preview (first 5 rows)"):
                        st.dataframe(
                            df[["surname", "forename", "form", "sex",
                                "overall_score", "overall_band"]].head()
                        )
                except Exception as e:
                    st.error(f"Error parsing Yellis file: {e}")

        with col2:
            st.subheader("Student Subject List")
            subj_file = st.file_uploader(
                "Upload subject list (CSV or Excel)",
                type=["csv", "xlsx", "xls"],
                key="gcse_subj_upload",
            )
            if subj_file:
                try:
                    sl_df, fmt, sl_warnings = parse_subject_list(subj_file)
                    st.session_state["gcse_subject_list_df"] = sl_df
                    st.session_state["gcse_warnings"] = (
                        st.session_state.get("gcse_warnings", []) + sl_warnings
                    )
                    st.success(f"Loaded {len(sl_df)} students. Format: **{fmt}**.")
                    all_s: set[str] = set()
                    for subs in sl_df["subjects"]:
                        all_s.update(subs)
                    st.info(f"Subjects detected: {', '.join(sorted(all_s))}")
                    with st.expander("Preview"):
                        p = sl_df.head().copy()
                        p["subjects"] = p["subjects"].apply(", ".join)
                        st.dataframe(p)
                except Exception as e:
                    st.error(f"Error parsing subject list: {e}")

        if st.session_state.get("gcse_warnings"):
            render_validation_warnings(st.session_state["gcse_warnings"], [])

        if (
            st.session_state.get("gcse_yellis_df") is not None
            and st.session_state.get("gcse_subject_list_df") is not None
        ):
            yellis_keys = set(
                st.session_state["gcse_yellis_df"]["surname"].str.strip().str.lower()
                + "|"
                + st.session_state["gcse_yellis_df"]["forename"].str.strip().str.lower()
            )
            sl = st.session_state["gcse_subject_list_df"]
            missing = [
                f"{r['surname']} {r['forename']}"
                for _, r in sl.iterrows()
                if (r["surname"].strip().lower() + "|" + r["forename"].strip().lower())
                not in yellis_keys
            ]
            st.session_state["gcse_missing_students"] = missing
            if missing:
                render_validation_warnings([], missing)
            else:
                st.success("All students in the subject list were found in the Yellis data.")

            _nav_buttons(back=False, forward_label="Next: Configure →", forward_key="gcse_s0")

    # -------------------------------------------------------------------
    # Step 1 — Configure
    # -------------------------------------------------------------------
    elif step == 1:
        st.header("Step 2 — Setup & Configuration")

        if st.session_state.get("gcse_yellis_df") is None:
            st.warning("Please upload data first.")
            if st.button("← Back to Upload"):
                st.session_state["step"] = 0
                st.rerun()
        else:
            tab1, tab2, tab3 = st.tabs(
                ["Target Distribution", "Sub-score Weighting", "Department Adjustments"]
            )

            with tab1:
                dist = render_distribution_inputs(
                    "GCSE",
                    existing=st.session_state.get("distribution", {}),
                )
                st.session_state["distribution"] = dist

            with tab2:
                use_sub = st.toggle(
                    "Use sub-scores for subject-specific targeting",
                    value=st.session_state.get("use_subscores", False),
                    key="use_subscores_toggle",
                )
                st.session_state["use_subscores"] = use_sub

                if use_sub:
                    st.markdown("**Sub-score weighting per subject group**")
                    st.caption(
                        "Composite = (overall_weight × overall) + (subscore_weight × sub). "
                        "Weights always sum to 1."
                    )
                    existing_sw = st.session_state.get("subscore_weights", {})
                    groups = {
                        "maths_group": "Maths / Further Maths / Physics / Computing",
                        "vocab_group": "English Literature / Drama / Film Studies",
                        "patterns_group": "Art / Design Technology / Music",
                    }
                    sw: dict = {}
                    for key, label in groups.items():
                        st.markdown(f"**{label}**")
                        default_ow = existing_sw.get(key, (0.7, 0.3))[0]
                        ow = st.slider(
                            f"Overall weight",
                            0.0,
                            1.0,
                            float(default_ow),
                            0.05,
                            key=f"sw_{key}",
                            format="%.2f",
                        )
                        sw[key] = (ow, round(1.0 - ow, 2))
                        st.caption(f"Sub-score weight: {round(1.0 - ow, 2):.2f}")
                    st.session_state["subscore_weights"] = sw

            with tab3:
                if st.session_state.get("gcse_subject_list_df") is not None:
                    all_s2: set[str] = set()
                    for subs in st.session_state["gcse_subject_list_df"]["subjects"]:
                        all_s2.update(subs)
                    adj = render_dept_adjustments(
                        sorted(all_s2),
                        existing=st.session_state.get("dept_adjustments", {}),
                        key_prefix="gcse_cfg_",
                    )
                    st.session_state["dept_adjustments"] = adj
                else:
                    st.info("Upload a subject list first.")

            _nav_buttons(back=True, forward_label="Next: Generate Targets →", forward_key="gcse_s1")

    # -------------------------------------------------------------------
    # Step 2 — Generate
    # -------------------------------------------------------------------
    elif step == 2:
        st.header("Step 3 — Generate Targets")

        if (
            st.session_state.get("gcse_yellis_df") is None
            or st.session_state.get("gcse_subject_list_df") is None
        ):
            st.warning("Please complete data upload first.")
            if st.button("← Back to Upload"):
                st.session_state["step"] = 0
                st.rerun()
        else:
            if st.session_state.get("targets_df") is not None:
                st.info("Targets already generated. Click below to regenerate.")
                if st.button("Regenerate Targets (resets overrides)", type="secondary", key="gcse_regen"):
                    st.session_state["_confirm_regen"] = True

                if st.session_state.get("_confirm_regen"):
                    st.warning("This will reset all manual overrides. Are you sure?")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("Yes, regenerate", type="primary", key="gcse_regen_yes"):
                            st.session_state["_confirm_regen"] = False
                            st.session_state["overrides"] = {}
                            _do_gcse_generate()
                    with c2:
                        if st.button("Cancel", key="gcse_regen_cancel"):
                            st.session_state["_confirm_regen"] = False
                            st.rerun()
            else:
                st.markdown(
                    "Click **Generate** to calculate target grades based on your configuration."
                )
                if st.button("Generate Targets", type="primary", key="gcse_gen_btn"):
                    _do_gcse_generate()

            if st.session_state.get("targets_df") is not None:
                df = st.session_state["targets_df"]
                s_cols = sorted([
                    c for c in df.columns
                    if c not in ("surname", "forename", "form", "overall_score")
                ])
                st.success(
                    f"Targets generated for **{len(df)}** students "
                    f"across **{len(s_cols)}** subjects."
                )
                with st.expander("Preview (first 10 rows)"):
                    st.dataframe(
                        df[["surname", "forename", "form"] + s_cols[:6]].head(10),
                        use_container_width=True,
                    )
                _nav_buttons(back=True, forward_label="Next: Review Matrix →", forward_key="gcse_s2")
            else:
                _nav_buttons(back=True, forward_label="", forward_key="gcse_s2_empty")

    # -------------------------------------------------------------------
    # Step 3 — Review Matrix
    # -------------------------------------------------------------------
    elif step == 3:
        st.header("Step 4 — Review & Edit Target Matrix")

        if st.session_state.get("targets_df") is None:
            st.warning("Please generate targets first.")
            if st.button("← Back to Generate"):
                st.session_state["step"] = 2
                st.rerun()
        else:
            df = st.session_state["targets_df"]
            s_cols = sorted([
                c for c in df.columns
                if c not in ("surname", "forename", "form", "overall_score")
            ])
            dept_adj = render_dept_adjustments(
                s_cols,
                existing=st.session_state.get("dept_adjustments", {}),
                key_prefix="gcse_mx_",
            )
            st.session_state["dept_adjustments"] = dept_adj

            _, updated_overrides = render_gcse_matrix(
                df,
                st.session_state.get("overrides", {}),
                dept_adj,
            )
            st.session_state["overrides"] = updated_overrides

            _nav_buttons(back=True, forward_label="Next: Export →", forward_key="gcse_s3")

    # -------------------------------------------------------------------
    # Step 4 — Export
    # -------------------------------------------------------------------
    elif step == 4:
        st.header("Step 5 — Export")

        if st.session_state.get("targets_df") is None:
            st.warning("Please generate targets first.")
            if st.button("← Back"):
                st.session_state["step"] = 2
                st.rerun()
        else:
            academic_year = st.text_input(
                "Academic Year (e.g. 2025/26)",
                value="2025/26",
                key="gcse_acad_year",
            )
            excel_bytes = export_gcse(
                st.session_state["targets_df"],
                overrides=st.session_state.get("overrides", {}),
                academic_year=academic_year,
            )
            st.download_button(
                label="📥 Download GCSE Targets (Excel)",
                data=excel_bytes,
                file_name=f"GCSE_Targets_{academic_year.replace('/', '-')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )

            with st.expander("Final target matrix preview"):
                df = st.session_state["targets_df"]
                s_cols = sorted([
                    c for c in df.columns
                    if c not in ("surname", "forename", "form", "overall_score")
                ])
                st.dataframe(
                    df[["surname", "forename", "form"] + s_cols],
                    use_container_width=True,
                )

            _nav_buttons(back=True, forward_label="", forward_key="gcse_s4")

# ===========================================================================
# A LEVEL MODE
# ===========================================================================

else:

    # -------------------------------------------------------------------
    # Step 0 — Upload
    # -------------------------------------------------------------------
    if step == 0:
        st.header("Step 1 — Upload Data")
        col1, col2, col3 = st.columns(3)

        with col1:
            st.subheader("Yellis Baseline (Year 12)")
            yellis_file = st.file_uploader(
                "Upload Yellis A Level Excel (.xlsx)",
                type=["xlsx"],
                key="al_yellis_upload",
            )
            if yellis_file:
                try:
                    df, warnings = parse_yellis_alevel(yellis_file)
                    st.session_state["al_yellis_df"] = df
                    st.session_state["al_warnings"] = warnings
                    st.success(f"Loaded {len(df)} students.")
                    with st.expander("Preview"):
                        st.dataframe(
                            df[["surname", "firstname", "gender", "overall_score"]].head()
                        )
                except Exception as e:
                    st.error(f"Error parsing Yellis file: {e}")

        with col2:
            st.subheader("GCSE Grades (iSams)")
            gcse_file = st.file_uploader(
                "Upload GCSE grades Excel (.xlsx)",
                type=["xlsx"],
                key="al_gcse_upload",
            )
            if gcse_file:
                try:
                    gcse_df, gcse_warnings = parse_gcse_grades(gcse_file)
                    st.session_state["al_gcse_wide_df"] = gcse_df
                    st.session_state["al_warnings"] = (
                        st.session_state.get("al_warnings", []) + gcse_warnings
                    )
                    g_subj = [c for c in gcse_df.columns if c not in ("Surname", "Forename")]
                    st.success(f"Loaded GCSE grades for {len(gcse_df)} students.")
                    st.info(f"GCSE subjects: {', '.join(g_subj)}")
                    with st.expander("Preview"):
                        st.dataframe(gcse_df.head())
                except Exception as e:
                    st.error(f"Error parsing GCSE grades file: {e}")

        with col3:
            st.subheader("Student Subject List")
            subj_file = st.file_uploader(
                "Upload subject list (CSV or Excel)",
                type=["csv", "xlsx", "xls"],
                key="al_subj_upload",
            )
            if subj_file:
                try:
                    sl_df, fmt, sl_warnings = parse_subject_list(subj_file)
                    st.session_state["al_subject_list_df"] = sl_df
                    st.session_state["al_warnings"] = (
                        st.session_state.get("al_warnings", []) + sl_warnings
                    )
                    all_s: set[str] = set()
                    for subs in sl_df["subjects"]:
                        all_s.update(subs)
                    st.success(f"Loaded {len(sl_df)} students. Format: **{fmt}**.")
                    st.info(f"A Level subjects: {', '.join(sorted(all_s))}")
                    with st.expander("Preview"):
                        p = sl_df.head().copy()
                        p["subjects"] = p["subjects"].apply(", ".join)
                        st.dataframe(p)
                except Exception as e:
                    st.error(f"Error parsing subject list: {e}")

        if st.session_state.get("al_warnings"):
            render_validation_warnings(st.session_state["al_warnings"], [])

        all_ready = (
            st.session_state.get("al_yellis_df") is not None
            and st.session_state.get("al_gcse_wide_df") is not None
            and st.session_state.get("al_subject_list_df") is not None
        )

        if all_ready:
            yellis_keys = set(
                st.session_state["al_yellis_df"]["surname"].str.strip().str.lower()
                + "|"
                + st.session_state["al_yellis_df"]["firstname"].str.strip().str.lower()
            )
            sl = st.session_state["al_subject_list_df"]
            missing = [
                f"{r['surname']} {r['forename']}"
                for _, r in sl.iterrows()
                if (r["surname"].strip().lower() + "|" + r["forename"].strip().lower())
                not in yellis_keys
            ]
            st.session_state["al_missing_students"] = missing
            if missing:
                render_validation_warnings([], missing)
            else:
                st.success("All students matched in Yellis data.")

            _nav_buttons(back=False, forward_label="Next: Configure →", forward_key="al_s0")

    # -------------------------------------------------------------------
    # Step 1 — Configure
    # -------------------------------------------------------------------
    elif step == 1:
        st.header("Step 2 — Setup & Configuration")

        if st.session_state.get("al_yellis_df") is None:
            st.warning("Please upload data first.")
            if st.button("← Back to Upload"):
                st.session_state["step"] = 0
                st.rerun()
        else:
            tab1, tab2, tab3, tab4, tab5 = st.tabs([
                "Target Distribution",
                "Score Weighting",
                "Fallback Ratio",
                "Subject Profiles",
                "Department Adjustments",
            ])

            with tab1:
                dist = render_distribution_inputs(
                    "A Level",
                    existing=st.session_state.get("distribution", {}),
                )
                st.session_state["distribution"] = dist

            with tab2:
                st.markdown("**GCSE vs Yellis baseline weighting**")
                st.caption(
                    "GCSE grades are a stronger predictor of A Level outcomes as they reflect "
                    "study habits, revision skills, and subject breadth. The Yellis baseline "
                    "provides an aptitude measure independent of prior schooling."
                )
                gcse_w = st.slider(
                    "GCSE weight",
                    0.0,
                    1.0,
                    float(st.session_state.get("gcse_weight", 0.80)),
                    0.05,
                    format="%.2f",
                    key="gcse_weight_slider",
                )
                st.session_state["gcse_weight"] = gcse_w
                st.session_state["yellis_weight"] = round(1.0 - gcse_w, 2)
                c1, c2 = st.columns(2)
                c1.metric("GCSE weight", f"{gcse_w:.0%}")
                c2.metric("Yellis weight", f"{round(1.0 - gcse_w, 2):.0%}")

            with tab3:
                st.markdown("**Fallback ratio for missing GCSE subjects**")
                st.caption(
                    "When a student is missing the primary GCSE for their A Level subject, "
                    "the composite falls back to a blend of overall GCSE mean and proxy subjects."
                )
                fb = st.slider(
                    "Overall GCSE mean weight (fallback)",
                    0.0,
                    1.0,
                    float(st.session_state.get("fallback_ratio", 0.60)),
                    0.05,
                    format="%.2f",
                    key="fallback_ratio_slider",
                )
                st.session_state["fallback_ratio"] = fb
                c1, c2 = st.columns(2)
                c1.metric("Overall mean weight", f"{fb:.0%}")
                c2.metric("Proxy subject weight", f"{round(1.0 - fb, 2):.0%}")

            with tab4:
                st.markdown("**Subject Weighting Profiles**")
                st.caption(
                    "Each A Level subject uses a weighted blend of GCSE components. "
                    "Adjust weights below — each set must sum to 1.00."
                )
                profile_overrides = st.session_state.get("profile_overrides", {})

                subjects_in_use: set[str] = set()
                if st.session_state.get("al_subject_list_df") is not None:
                    for subs in st.session_state["al_subject_list_df"]["subjects"]:
                        subjects_in_use.update(subs)

                subjects_to_show = sorted(
                    subjects_in_use if subjects_in_use else set(DEFAULT_PROFILES.keys())
                )

                for subj in subjects_to_show:
                    with st.expander(subj):
                        profile = DEFAULT_PROFILES.get(subj)
                        if not profile:
                            st.write("No default profile — will use overall mean.")
                            continue

                        override = profile_overrides.get(subj, {})
                        primary_w = override.get("primary", profile["primary"])
                        fallback_w = override.get("fallback", profile["fallback"])

                        st.markdown("**Primary weights** (when main GCSE available)")
                        new_primary = _render_weight_editor(primary_w, f"prim_{subj}")

                        st.markdown("**Fallback weights** (when main GCSE missing)")
                        new_fallback = _render_weight_editor(fallback_w, f"fall_{subj}")

                        profile_overrides[subj] = {
                            "primary": new_primary,
                            "fallback": new_fallback,
                        }

                st.session_state["profile_overrides"] = profile_overrides

            with tab5:
                if st.session_state.get("al_subject_list_df") is not None:
                    al_subjs: set[str] = set()
                    for subs in st.session_state["al_subject_list_df"]["subjects"]:
                        al_subjs.update(subs)
                    adj = render_dept_adjustments(
                        sorted(al_subjs),
                        existing=st.session_state.get("dept_adjustments", {}),
                        key_prefix="al_cfg_",
                    )
                    st.session_state["dept_adjustments"] = adj
                else:
                    st.info("Upload a subject list first.")

            _nav_buttons(back=True, forward_label="Next: Generate Targets →", forward_key="al_s1")

    # -------------------------------------------------------------------
    # Step 2 — Generate
    # -------------------------------------------------------------------
    elif step == 2:
        st.header("Step 3 — Generate Targets")

        all_ready = (
            st.session_state.get("al_yellis_df") is not None
            and st.session_state.get("al_gcse_wide_df") is not None
            and st.session_state.get("al_subject_list_df") is not None
        )

        if not all_ready:
            st.warning("Please complete data upload first.")
            if st.button("← Back to Upload"):
                st.session_state["step"] = 0
                st.rerun()
        else:
            if st.session_state.get("targets_df") is not None:
                st.info("Targets already generated. Click below to regenerate.")
                if st.button("Regenerate Targets (resets overrides)", type="secondary", key="al_regen"):
                    st.session_state["_confirm_regen"] = True

                if st.session_state.get("_confirm_regen"):
                    st.warning("This will reset all manual overrides. Are you sure?")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("Yes, regenerate", type="primary", key="al_regen_yes"):
                            st.session_state["_confirm_regen"] = False
                            st.session_state["overrides"] = {}
                            _do_alevel_generate()
                    with c2:
                        if st.button("Cancel", key="al_regen_cancel"):
                            st.session_state["_confirm_regen"] = False
                            st.rerun()
            else:
                st.markdown("Click **Generate** to calculate A Level target grades.")
                if st.button("Generate Targets", type="primary", key="al_gen_btn"):
                    _do_alevel_generate()

            if st.session_state.get("targets_df") is not None:
                df = st.session_state["targets_df"]
                s_cols = sorted([
                    c for c in df.columns
                    if c not in ("surname", "forename", "year_group", "overall_score")
                ])
                st.success(
                    f"Targets generated for **{len(df)}** students "
                    f"across **{len(s_cols)}** subjects."
                )
                with st.expander("Preview (first 10 rows)"):
                    st.dataframe(
                        df[["surname", "forename"] + s_cols[:6]].head(10),
                        use_container_width=True,
                    )
                _nav_buttons(back=True, forward_label="Next: Review Matrix →", forward_key="al_s2")
            else:
                _nav_buttons(back=True, forward_label="", forward_key="al_s2_empty")

    # -------------------------------------------------------------------
    # Step 3 — Review Matrix
    # -------------------------------------------------------------------
    elif step == 3:
        st.header("Step 4 — Review & Edit Target Matrix")

        if st.session_state.get("targets_df") is None:
            st.warning("Please generate targets first.")
            if st.button("← Back to Generate"):
                st.session_state["step"] = 2
                st.rerun()
        else:
            df = st.session_state["targets_df"]
            s_cols = sorted([
                c for c in df.columns
                if c not in ("surname", "forename", "year_group", "overall_score")
            ])
            dept_adj = render_dept_adjustments(
                s_cols,
                existing=st.session_state.get("dept_adjustments", {}),
                key_prefix="al_mx_",
            )
            st.session_state["dept_adjustments"] = dept_adj

            _, updated_overrides = render_alevel_matrix(
                df,
                st.session_state.get("overrides", {}),
                dept_adj,
            )
            st.session_state["overrides"] = updated_overrides

            _nav_buttons(back=True, forward_label="Next: Export →", forward_key="al_s3")

    # -------------------------------------------------------------------
    # Step 4 — Export
    # -------------------------------------------------------------------
    elif step == 4:
        st.header("Step 5 — Export")

        if st.session_state.get("targets_df") is None:
            st.warning("Please generate targets first.")
            if st.button("← Back"):
                st.session_state["step"] = 2
                st.rerun()
        else:
            academic_year = st.text_input(
                "Academic Year (e.g. 2025/26)",
                value="2025/26",
                key="al_acad_year",
            )
            excel_bytes = export_alevel(
                st.session_state["targets_df"],
                overrides=st.session_state.get("overrides", {}),
                academic_year=academic_year,
            )
            st.download_button(
                label="📥 Download A Level Targets (Excel)",
                data=excel_bytes,
                file_name=f"ALevel_Targets_{academic_year.replace('/', '-')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )

            with st.expander("Final target matrix preview"):
                df = st.session_state["targets_df"]
                s_cols = sorted([
                    c for c in df.columns
                    if c not in ("surname", "forename", "year_group", "overall_score")
                ])
                st.dataframe(
                    df[["surname", "forename"] + s_cols],
                    use_container_width=True,
                )

            _nav_buttons(back=True, forward_label="", forward_key="al_s4")
