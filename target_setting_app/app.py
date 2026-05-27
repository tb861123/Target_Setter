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
    parse_alis_adapt,
)
from target_engine import (
    GCSETargetEngine,
    ALevelTargetEngine,
    ALevelALISEngine,
    compute_gcse_summary,
    compute_alevel_summary,
)
from alis_adapter import (
    ALISLookup,
    ALISBlendedLookup,
    PERCENTILE_LABELS,
    DEFAULT_PROXY_MAP,
    ALIS_COVERED_SUBJECTS,
    ALIS_TO_APP,
)
from subject_profiles import DEFAULT_PROFILES, ALL_A_LEVEL_SUBJECTS
from export import export_gcse, export_alevel
from templates import (
    template_yellis_gcse,
    template_yellis_alevel,
    template_gcse_grades,
    template_subject_list_long,
    template_subject_list_wide,
)
from ui_components import (
    render_distribution_inputs,
    render_dept_adjustments,
    render_gcse_matrix,
    render_alevel_matrix,
    render_validation_warnings,
    render_matching_dashboard,
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
            has_alis = st.session_state.get("al_alis_data") is not None
            has_composite = (
                st.session_state.get("al_yellis_df") is not None
                and st.session_state.get("al_gcse_wide_df") is not None
            )

            if has_alis:
                proxy_map = dict(DEFAULT_PROXY_MAP)
                proxy_map.update(st.session_state.get("al_alis_proxy_map", {}))
                chosen_pct = st.session_state.get("al_alis_percentile", "75th")
                match_overrides = st.session_state.get("match_overrides", {})

                # Build key remaps from confirmed match corrections
                def _extract_remap(source_prefix: str) -> dict[str, str]:
                    prefix = f"{source_prefix}::"
                    return {
                        k[len(prefix):]: v
                        for k, v in match_overrides.items()
                        if k.startswith(prefix) and v != "__UNMATCHED__"
                    }

                alis_lookup = ALISLookup(
                    data=st.session_state["al_alis_data"],
                    percentile=chosen_pct,
                    proxy_map=proxy_map,
                    key_remap=_extract_remap("ALIS Adapt"),
                )

                # If GCSE baseline file is also loaded, blend the two
                gcse_base = st.session_state.get("al_gcse_baseline_data")
                if gcse_base is not None:
                    gcse_pct = st.session_state.get("al_gcse_baseline_percentile", chosen_pct)
                    gcse_lookup = ALISLookup(
                        data=gcse_base,
                        percentile=gcse_pct,
                        proxy_map=proxy_map,
                        key_remap=_extract_remap("GCSE Baseline"),
                    )
                    alis_w = st.session_state.get("al_alis_blend_weight", 0.5)
                    lookup = ALISBlendedLookup(
                        alis_lookup=alis_lookup,
                        gcse_lookup=gcse_lookup,
                        alis_weight=alis_w,
                        gcse_weight=1.0 - alis_w,
                    )
                else:
                    lookup = alis_lookup

                # Build per-subject lookups for percentile overrides
                subject_pct_overrides = st.session_state.get("al_subject_pct_overrides", {})
                subject_lookups: dict = {}
                for _subj, _pct in subject_pct_overrides.items():
                    if _pct == chosen_pct:
                        continue  # same as global, skip
                    _sl = ALISLookup(
                        data=st.session_state["al_alis_data"],
                        percentile=_pct,
                        proxy_map=proxy_map,
                        key_remap=_extract_remap("ALIS Adapt"),
                    )
                    if gcse_base is not None:
                        _gcse_pct = st.session_state.get("al_gcse_baseline_percentile", _pct)
                        _gl = ALISLookup(
                            data=gcse_base,
                            percentile=_gcse_pct,
                            proxy_map=proxy_map,
                            key_remap=_extract_remap("GCSE Baseline"),
                        )
                        _alis_w = st.session_state.get("al_alis_blend_weight", 0.5)
                        subject_lookups[_subj] = ALISBlendedLookup(
                            alis_lookup=_sl,
                            gcse_lookup=_gl,
                            alis_weight=_alis_w,
                            gcse_weight=1.0 - _alis_w,
                        )
                    else:
                        subject_lookups[_subj] = _sl

                engine = ALevelALISEngine(
                    alis_lookup=lookup,
                    subject_list_df=st.session_state["al_subject_list_df"],
                    yellis_df=st.session_state.get("al_yellis_df"),
                    gcse_wide_df=st.session_state.get("al_gcse_wide_df"),
                    mode=st.session_state.get("al_alis_mode", "direct"),
                    distribution=st.session_state.get("distribution", {}),
                    dept_adjustments=st.session_state.get("dept_adjustments", {}),
                    profile_overrides=st.session_state.get("profile_overrides", {}),
                    subject_lookups=subject_lookups,
                )
            elif has_composite:
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
            else:
                st.error("No data available for target generation. Upload ALIS or Yellis+GCSE data.")
                return

            targets = engine.generate()

            # Attach ALIS baseline scores if available from Yellis df
            if has_alis and st.session_state.get("al_yellis_df") is not None:
                yellis_df = st.session_state["al_yellis_df"]
                yw_key = (
                    yellis_df["surname"].str.strip().str.lower()
                    + "|"
                    + yellis_df["firstname"].str.strip().str.lower()
                )
                yw_score = dict(zip(yw_key, yellis_df["overall_score"]))
                if "overall_score" not in targets.columns or targets["overall_score"].isna().all():
                    targets["_sl_key"] = (
                        targets["surname"].str.strip().str.lower()
                        + "|"
                        + targets["forename"].str.strip().str.lower()
                    )
                    targets["overall_score"] = targets["_sl_key"].map(yw_score)
                    targets = targets.drop(columns=["_sl_key"])

            st.session_state["targets_df"] = targets
            st.rerun()
        except Exception as e:
            st.error(f"Error generating targets: {e}")
            raise


def _render_prediction_comparison(
    alis_data: dict,
    gcse_data: dict,
    percentile: str,
) -> None:
    """Show a mini table comparing ALIS vs GCSE baseline predictions for sample students."""
    from alis_adapter import ALIS_TO_APP
    a_df = alis_data.get(percentile)
    g_df = gcse_data.get(percentile)
    if a_df is None or g_df is None:
        st.info("Data not available for selected percentile.")
        return

    subj_cols = [c for c in a_df.columns if c not in ("_key", "_name", "baseline")]
    rows = []
    for _, arow in a_df.head(20).iterrows():
        key = arow["_key"]
        grows = g_df[g_df["_key"] == key]
        if grows.empty:
            continue
        grow = grows.iloc[0]
        for subj in subj_cols:
            av = arow.get(subj)
            gv = grow.get(subj)
            if av is None or str(av) in ("nan", "None", "") :
                continue
            if gv is None or str(gv) in ("nan", "None", ""):
                continue
            if str(av) != str(gv):
                rows.append({
                    "Student": arow["_name"],
                    "Subject": subj,
                    "ALIS test": str(av),
                    "GCSE baseline": str(gv),
                })

    if rows:
        st.dataframe(
            pd.DataFrame(rows).head(20),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(f"Showing students where predictions differ at {percentile} percentile.")
    else:
        st.info("No differences found for displayed students at this percentile.")


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


def _sheet_picker(file, default_sheet: str, ss_key: str) -> str:
    """
    Return the sheet name to use.  If `default_sheet` is not found in the file,
    shows the user a selectbox and stores the choice in session_state[ss_key].
    """
    from data_ingestion import _available_sheets
    sheets = _available_sheets(file)
    if not sheets or default_sheet in sheets:
        return default_sheet
    # case-insensitive match
    lower = {s.lower(): s for s in sheets}
    if default_sheet.lower() in lower:
        return lower[default_sheet.lower()]
    # Need user input
    current = st.session_state.get(ss_key, sheets[0])
    if current not in sheets:
        current = sheets[0]
    st.warning(
        f"Sheet **'{default_sheet}'** not found. "
        f"Available: `{'`, `'.join(sheets)}`. Please pick the correct sheet:"
    )
    chosen = st.selectbox("Sheet to use:", sheets, index=sheets.index(current), key=ss_key)
    return chosen  # st.selectbox already saves to st.session_state[ss_key]


def _col_mapper_expander(
    file,
    sheet_name: str,
    required_cols: list[str],
    header_row: int,
    ss_key: str,
) -> dict[str, str] | None:
    """
    If file columns don't match required_cols, show a column-mapping expander.
    Returns {standard_name: actual_col} or None if auto-mapping is fine.
    """
    try:
        file.seek(0)
    except Exception:
        pass
    try:
        raw = pd.read_excel(file, sheet_name=sheet_name, header=header_row, nrows=0)
        file.seek(0)
    except Exception:
        return None

    actual_cols = raw.columns.tolist()
    lower_actual = {c.lower(): c for c in actual_cols}

    missing = [r for r in required_cols if r.lower() not in lower_actual]
    if not missing:
        return None  # auto-mapping will work

    # Show mapper
    saved = st.session_state.get(ss_key, {})
    with st.expander(
        f"Column mapping — {len(missing)} column(s) not found automatically",
        expanded=True,
    ):
        st.caption(
            f"Columns detected: `{'`, `'.join(actual_cols)}`. "
            f"Map the missing columns below."
        )
        result = dict(saved)
        col_widgets = st.columns(min(len(missing), 4))
        for i, col_name in enumerate(missing):
            with col_widgets[i % len(col_widgets)]:
                options = ["(not present)"] + actual_cols
                curr = result.get(col_name, saved.get(col_name, options[0]))
                idx = options.index(curr) if curr in options else 0
                sel = st.selectbox(f"{col_name}", options, index=idx, key=f"{ss_key}_{col_name}")
                if sel != "(not present)":
                    result[col_name] = sel
                else:
                    result.pop(col_name, None)

        if st.button("Apply column mapping", key=f"{ss_key}_apply"):
            st.session_state[ss_key] = result
            st.rerun()

    return st.session_state.get(ss_key) or None


_FORMAT_HINTS = {
    "yellis_gcse": (
        "📋 **Expected format — Yellis GCSE file (.xlsx)**\n\n"
        "- Sheet name: **Sheet1**\n"
        "- First 3 rows are headers — data starts row 4\n"
        "- Columns (in order): Surname, Forename, Form, Sex, Overall Score, Overall Band, "
        "Vocab Score, Vocab Band, Maths Score, Maths Band, Patterns Score, Patterns Band, Range\n\n"
        "_This is the standard Yellis GCSE export from CEM — upload as downloaded._"
    ),
    "yellis_alevel": (
        "📋 **Expected format — Yellis A Level file (.xlsx)**\n\n"
        "- Sheet name: **Data**\n"
        "- First 3 rows are headers — data starts row 4\n"
        "- Columns (in order): Code, Surname, Firstname, Gender, DOB, Overall Score, "
        "Overall Band, Vocab Score, Vocab Band, Maths Score, Maths Band, Nonverbal Score, "
        "Nonverbal Band\n\n"
        "_This is the standard Yellis A Level export from CEM — upload as downloaded._"
    ),
    "gcse_grades": (
        "📋 **Expected format — GCSE Grades file (.xlsx)**\n\n"
        "- Sheet name: **iSams import**\n"
        "- Header row is row **2** (row 1 is blank/title)\n"
        "- Required columns: **Surname**, **Forename**, **Subject**, **Grade**\n"
        "- Long format: one row per student × subject\n"
        "- Surname and Forename can be blank (forward-filled from the first row per student)\n\n"
        "_Export from iSams: Reports → Data Export → GCSE Grades Import format._"
    ),
    "subject_list": (
        "📋 **Expected format — Subject List (CSV or .xlsx)**\n\n"
        "Two formats are supported:\n\n"
        "**Long format** (one subjects column):\n"
        "| Surname | Forename | Subjects |\n"
        "|---------|----------|----------|\n"
        "| Smith | Alice | Mathematics, Physics, Chemistry |\n\n"
        "**Wide format** (one column per subject, 1/Y/X = taking it):\n"
        "| Surname | Forename | Mathematics | Physics | Art |\n"
        "|---------|----------|-------------|---------|-----|\n"
        "| Smith | Alice | 1 | 1 | |\n\n"
        "_Column headers must include Surname and Forename (or Last Name / First Name)._"
    ),
    "alis_adapt": (
        "📋 **Expected format — ALIS Adapt file (.xls or .xlsx)**\n\n"
        "- Multi-sheet file from **CEM ALIS Adapt**\n"
        "- Required sheets (any subset): 50th Percentile, 75th Percentile, 90th Percentile, "
        "97th Percentile, 99th Percentile\n"
        "- Each sheet has: **StudentName** (format: 'Surname, Firstname'), **baseline**, "
        "then one column per subject\n\n"
        "_Upload the file exactly as downloaded from the CEM ALIS platform._"
    ),
    "gcse_baseline": (
        "📋 **Expected format — GCSE Baseline Predictions file (.xls or .xlsx)**\n\n"
        "- Same structure as the ALIS Adapt file but uses **mean GCSE score** as the predictor\n"
        "- Multi-sheet from **CEM ALIS Adapt** (GCSE baseline variant)\n"
        "- Sheets: 50th Percentile through 99th Percentile\n"
        "- Columns: StudentName, baseline (GCSE mean, 1–9 scale), subject predictions\n\n"
        "_Upload the file exactly as downloaded from CEM._"
    ),
}


def _format_hint(key: str) -> None:
    """Render a collapsible format hint for a given file type."""
    hint = _FORMAT_HINTS.get(key)
    if hint:
        with st.expander("Expected format ▶", expanded=False):
            st.markdown(hint)


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
        # ALIS Adapt data (ALIS test score based)
        "al_alis_data": None,          # dict[percentile_label: DataFrame]
        "al_alis_percentile": "75th",  # chosen percentile
        "al_alis_mode": "direct",      # "direct" | "ranked"
        "al_alis_proxy_map": {},       # overrides to DEFAULT_PROXY_MAP
        "al_use_alis": False,
        # GCSE baseline file (same structure, different predictor)
        "al_gcse_baseline_data": None,
        "al_gcse_baseline_percentile": "75th",
        # Blending weight: 0 = pure GCSE baseline, 1 = pure ALIS test
        "al_alis_blend_weight": 0.5,
        # Per-subject percentile overrides e.g. {"Further Mathematics": "90th"}
        "al_subject_pct_overrides": {},
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
        "match_overrides": {},
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
            _format_hint("yellis_gcse")
            st.download_button(
                "📥 Download template",
                data=template_yellis_gcse(),
                file_name="Template_Yellis_GCSE.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_tmpl_yellis_gcse",
            )
            yellis_file = st.file_uploader(
                "Upload Yellis GCSE Excel (.xlsx)",
                type=["xlsx", "xls"],
                key="gcse_yellis_upload",
            )
            if yellis_file:
                sheet = _sheet_picker(yellis_file, "Sheet1", "gcse_yellis_sheet")
                try:
                    yellis_file.seek(0)
                except Exception:
                    pass
                try:
                    df, warnings = parse_yellis_gcse(yellis_file, sheet_name=sheet)
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
            _format_hint("subject_list")
            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    "📥 Long-format template",
                    data=template_subject_list_long(),
                    file_name="Template_SubjectList_Long.csv",
                    mime="text/csv",
                    key="dl_tmpl_sl_long_gcse",
                )
            with c2:
                st.download_button(
                    "📥 Wide-format template",
                    data=template_subject_list_wide(),
                    file_name="Template_SubjectList_Wide.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_tmpl_sl_wide_gcse",
                )
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
            st.divider()
            # Build matching inputs
            _gcse_yw = st.session_state["gcse_yellis_df"]
            _gcse_sl = st.session_state["gcse_subject_list_df"]
            _gcse_master = (
                _gcse_sl["surname"].str.strip().str.lower()
                + "|"
                + _gcse_sl["forename"].str.strip().str.lower()
            ).tolist()
            _gcse_src_keys = {
                "Yellis": (
                    _gcse_yw["surname"].str.strip().str.lower()
                    + "|"
                    + _gcse_yw["forename"].str.strip().str.lower()
                ).tolist(),
            }
            render_matching_dashboard(
                master_keys=_gcse_master,
                source_keys=_gcse_src_keys,
                ss_key="match_overrides",
                key_prefix="gcse_md_",
            )

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

        # ---- ALIS Adapt file (primary) ----
        st.subheader("ALIS Adapt Predictions (recommended)")
        st.caption(
            "Upload the ALIS Adapt XLS file containing percentile grade predictions "
            "per student per subject. This is the most accurate basis for A Level targets."
        )
        _format_hint("alis_adapt")
        alis_file = st.file_uploader(
            "Upload ALIS Adapt file (.xls or .xlsx)",
            type=["xls", "xlsx"],
            key="al_alis_upload",
        )
        if alis_file:
            try:
                alis_file.seek(0)
            except Exception:
                pass
            try:
                alis_data, alis_warnings = parse_alis_adapt(alis_file)
                st.session_state["al_alis_data"] = alis_data
                st.session_state["al_use_alis"] = True
                avail = list(alis_data.keys())
                n_students = len(next(iter(alis_data.values())))
                st.success(
                    f"Loaded ALIS Adapt data: **{n_students} students**, "
                    f"sheets: {', '.join(avail)}"
                )
                if alis_warnings:
                    for w in alis_warnings:
                        st.warning(w)
                # Show subject coverage
                sample_df = next(iter(alis_data.values()))
                subj_cols = [c for c in sample_df.columns if c not in ("_key", "_name", "baseline")]
                subj_counts = {
                    s: int(sample_df[s].notna().sum())
                    for s in subj_cols
                    if int(sample_df[s].notna().sum()) > 0
                }
                with st.expander("Subject coverage (students enrolled per subject)"):
                    cdf = pd.DataFrame(
                        sorted(subj_counts.items(), key=lambda x: x[1], reverse=True),
                        columns=["Subject", "Students"],
                    )
                    st.dataframe(cdf, use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"Error parsing ALIS Adapt file: {e}")

        _format_hint("gcse_baseline")
        gcse_base_file = st.file_uploader(
            "Upload GCSE Baseline Predictions file (.xls or .xlsx) — optional",
            type=["xls", "xlsx"],
            key="al_gcse_baseline_upload",
        )
        if gcse_base_file:
            try:
                gcse_base_data, gcse_base_warnings = parse_alis_adapt(gcse_base_file)
                st.session_state["al_gcse_baseline_data"] = gcse_base_data
                n_gb = len(next(iter(gcse_base_data.values())))
                st.success(
                    f"Loaded GCSE Baseline data: **{n_gb} students**, "
                    f"sheets: {', '.join(gcse_base_data.keys())}"
                )
                for w in gcse_base_warnings:
                    st.warning(w)
            except Exception as e:
                st.error(f"Error parsing GCSE Baseline file: {e}")

        if st.session_state.get("al_alis_data") is not None and st.session_state.get("al_gcse_baseline_data") is not None:
            st.success("Both prediction files loaded — blending available in Configure step.")
        elif st.session_state.get("al_alis_data") is None and st.session_state.get("al_gcse_baseline_data") is None:
            st.info(
                "Neither prediction file uploaded yet. You can still use the composite "
                "GCSE + Yellis scoring approach by uploading the files below."
            )

        st.divider()

        # ---- Other data files ----
        col1, col2, col3 = st.columns(3)

        with col1:
            st.subheader("Yellis Baseline (Year 12)")
            st.caption("Required for GCSE-composite mode; also provides baseline scores for ALIS mode.")
            _format_hint("yellis_alevel")
            st.download_button(
                "📥 Download template",
                data=template_yellis_alevel(),
                file_name="Template_Yellis_ALevel.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_tmpl_yellis_al",
            )
            yellis_file = st.file_uploader(
                "Upload Yellis A Level Excel (.xlsx)",
                type=["xlsx", "xls"],
                key="al_yellis_upload",
            )
            if yellis_file:
                sheet = _sheet_picker(yellis_file, "Data", "al_yellis_sheet")
                try:
                    yellis_file.seek(0)
                except Exception:
                    pass
                try:
                    df, warnings = parse_yellis_alevel(yellis_file, sheet_name=sheet)
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
            st.caption("Required for GCSE-composite mode.")
            _format_hint("gcse_grades")
            st.download_button(
                "📥 Download template",
                data=template_gcse_grades(),
                file_name="Template_GCSE_Grades.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_tmpl_gcse_grades",
            )
            gcse_file = st.file_uploader(
                "Upload GCSE grades Excel (.xlsx)",
                type=["xlsx", "xls"],
                key="al_gcse_upload",
            )
            if gcse_file:
                sheet = _sheet_picker(gcse_file, "iSams import", "al_gcse_sheet")
                col_map = _col_mapper_expander(
                    gcse_file, sheet,
                    required_cols=["Surname", "Forename", "Subject", "Grade"],
                    header_row=1,
                    ss_key="al_gcse_col_map",
                )
                try:
                    gcse_file.seek(0)
                except Exception:
                    pass
                try:
                    gcse_df, gcse_warnings = parse_gcse_grades(
                        gcse_file, sheet_name=sheet, col_map=col_map
                    )
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
            st.caption("Required for all modes — links students to their A Level subjects.")
            _format_hint("subject_list")
            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    "📥 Long template",
                    data=template_subject_list_long(),
                    file_name="Template_SubjectList_Long.csv",
                    mime="text/csv",
                    key="dl_tmpl_sl_long_al",
                )
            with c2:
                st.download_button(
                    "📥 Wide template",
                    data=template_subject_list_wide(),
                    file_name="Template_SubjectList_Wide.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_tmpl_sl_wide_al",
                )
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

        # Minimum: subject list required; ALIS OR (Yellis + GCSE) required
        has_subj = st.session_state.get("al_subject_list_df") is not None
        has_alis = st.session_state.get("al_alis_data") is not None
        has_composite = (
            st.session_state.get("al_yellis_df") is not None
            and st.session_state.get("al_gcse_wide_df") is not None
        )

        all_ready = has_subj and (has_alis or has_composite)

        if all_ready:
            sl = st.session_state["al_subject_list_df"]
            al_master_keys = (
                sl["surname"].str.strip().str.lower()
                + "|"
                + sl["forename"].str.strip().str.lower()
            ).tolist()

            # Build source key dicts for matching
            al_source_keys: dict[str, list[str]] = {}

            if has_alis:
                alis_data = st.session_state["al_alis_data"]
                _adf = next(iter(alis_data.values()))
                al_source_keys["ALIS Adapt"] = _adf["_key"].tolist()

            if st.session_state.get("al_gcse_baseline_data") is not None:
                _gbdf = next(iter(st.session_state["al_gcse_baseline_data"].values()))
                al_source_keys["GCSE Baseline"] = _gbdf["_key"].tolist()

            if st.session_state.get("al_yellis_df") is not None:
                _ydf = st.session_state["al_yellis_df"]
                al_source_keys["Yellis"] = (
                    _ydf["surname"].str.strip().str.lower()
                    + "|"
                    + _ydf["firstname"].str.strip().str.lower()
                ).tolist()

            if st.session_state.get("al_gcse_wide_df") is not None:
                _gdf = st.session_state["al_gcse_wide_df"]
                al_source_keys["GCSE Grades"] = (
                    _gdf["Surname"].str.strip().str.lower()
                    + "|"
                    + _gdf["Forename"].str.strip().str.lower()
                ).tolist()

            st.divider()
            render_matching_dashboard(
                master_keys=al_master_keys,
                source_keys=al_source_keys,
                ss_key="match_overrides",
                key_prefix="al_md_",
            )

            _nav_buttons(back=False, forward_label="Next: Configure →", forward_key="al_s0")

    # -------------------------------------------------------------------
    # Step 1 — Configure
    # -------------------------------------------------------------------
    elif step == 1:
        st.header("Step 2 — Setup & Configuration")

        has_subj = st.session_state.get("al_subject_list_df") is not None
        has_alis = st.session_state.get("al_alis_data") is not None
        has_composite = (
            st.session_state.get("al_yellis_df") is not None
            and st.session_state.get("al_gcse_wide_df") is not None
        )

        if not has_subj and not has_alis and not has_composite:
            st.warning("Please upload data first.")
            if st.button("← Back to Upload"):
                st.session_state["step"] = 0
                st.rerun()
        else:
            # Determine which tabs to show based on uploaded data
            tab_labels = ["Target Distribution", "Department Adjustments"]
            if has_alis:
                tab_labels.insert(1, "ALIS Percentile & Proxies")
            if has_composite:
                tab_labels += ["Score Weighting", "Fallback Ratio", "Subject Profiles"]

            tabs = st.tabs(tab_labels)
            tab_idx = {label: i for i, label in enumerate(tab_labels)}

            with tabs[tab_idx["Target Distribution"]]:
                dist = render_distribution_inputs(
                    "A Level",
                    existing=st.session_state.get("distribution", {}),
                )
                st.session_state["distribution"] = dist

            if has_alis:
                with tabs[tab_idx["ALIS Percentile & Proxies"]]:
                    st.markdown("**Percentile target level**")
                    st.caption(
                        "Each percentile represents how a student with this ALIS baseline "
                        "score would perform relative to similar students nationally. "
                        "75th percentile means 'better than 75% of students with a similar ability score'."
                    )

                    alis_data = st.session_state["al_alis_data"]
                    avail_pct = list(alis_data.keys())

                    # Map short label to full sheet description
                    pct_descriptions = {
                        "50th": "50th percentile — median expectation for this ability",
                        "75th": "75th percentile — aspirational (top 25% nationally) ✓ recommended",
                        "90th": "90th percentile — ambitious (top 10% nationally)",
                        "97th": "97th percentile — highly ambitious (top 3% nationally)",
                        "99th": "99th percentile — exceptional (top 1% nationally)",
                    }
                    pct_options = [p for p in ["50th", "75th", "90th", "97th", "99th"] if p in avail_pct]

                    curr_pct = st.session_state.get("al_alis_percentile", "75th")
                    if curr_pct not in pct_options:
                        curr_pct = pct_options[0]

                    sel_pct = st.radio(
                        "Aspirational percentile",
                        options=pct_options,
                        format_func=lambda p: pct_descriptions.get(p, p),
                        index=pct_options.index(curr_pct),
                        key="alis_pct_radio",
                    )
                    st.session_state["al_alis_percentile"] = sel_pct

                    # GCSE baseline file blending (shown only when both files loaded)
                    if st.session_state.get("al_gcse_baseline_data") is not None:
                        st.divider()
                        st.markdown("**Blend ALIS test predictions with GCSE baseline predictions**")
                        st.caption(
                            "Both prediction files are loaded. The ALIS test captures cognitive "
                            "aptitude independently of prior schooling; the GCSE baseline reflects "
                            "academic habits and subject knowledge. Blending both gives a more "
                            "rounded picture. A 50/50 blend is a reasonable starting point."
                        )

                        # Same percentile for both by default; allow independent choice
                        gcse_base_data = st.session_state["al_gcse_baseline_data"]
                        avail_gcse_pct = list(gcse_base_data.keys())
                        gcse_pct_options = [p for p in ["50th", "75th", "90th", "97th", "99th"] if p in avail_gcse_pct]
                        curr_gcse_pct = st.session_state.get("al_gcse_baseline_percentile", sel_pct)
                        if curr_gcse_pct not in gcse_pct_options:
                            curr_gcse_pct = gcse_pct_options[0]

                        use_same_pct = st.checkbox(
                            "Use same percentile for both files",
                            value=True,
                            key="alis_same_pct",
                        )
                        if use_same_pct:
                            st.session_state["al_gcse_baseline_percentile"] = sel_pct
                        else:
                            gcse_sel_pct = st.radio(
                                "GCSE baseline percentile",
                                options=gcse_pct_options,
                                format_func=lambda p: pct_descriptions.get(p, p),
                                index=gcse_pct_options.index(curr_gcse_pct),
                                key="gcse_base_pct_radio",
                                horizontal=True,
                            )
                            st.session_state["al_gcse_baseline_percentile"] = gcse_sel_pct

                        blend_w = st.slider(
                            "ALIS test weight  ←————→  GCSE baseline weight",
                            min_value=0.0,
                            max_value=1.0,
                            value=float(st.session_state.get("al_alis_blend_weight", 0.5)),
                            step=0.05,
                            format="%.2f",
                            key="alis_blend_slider",
                        )
                        st.session_state["al_alis_blend_weight"] = blend_w
                        c1, c2 = st.columns(2)
                        c1.metric("ALIS test weight", f"{blend_w:.0%}")
                        c2.metric("GCSE baseline weight", f"{(1 - blend_w):.0%}")

                        # Quick comparison table
                        with st.expander("Preview: how predictions differ between files (sample students)"):
                            _render_prediction_comparison(
                                st.session_state["al_alis_data"],
                                st.session_state["al_gcse_baseline_data"],
                                sel_pct,
                            )

                    st.divider()
                    st.markdown("**Target generation mode**")
                    mode_choice = st.radio(
                        "Mode",
                        ["Direct (use ALIS grade as target)", "Ranked (re-rank by ALIS score, apply school distribution)"],
                        index=0 if st.session_state.get("al_alis_mode", "direct") == "direct" else 1,
                        key="alis_mode_radio",
                    )
                    st.session_state["al_alis_mode"] = "direct" if "Direct" in mode_choice else "ranked"

                    if st.session_state["al_alis_mode"] == "ranked":
                        st.caption(
                            "Ranked mode uses the ALIS grade as a ranking score, then applies "
                            "Emanuel's own target distribution curve. Use this if you want to "
                            "override the national distribution with school-specific expectations."
                        )
                    else:
                        st.caption(
                            "Direct mode uses the ALIS prediction at the chosen percentile exactly "
                            "as the target grade. Department adjustments can still shift grades up/down."
                        )

                    st.divider()
                    st.markdown("**Per-subject percentile overrides**")
                    st.caption(
                        "Override the global percentile for individual subjects — e.g. target "
                        "Further Maths at 90th while keeping everything else at 75th."
                    )

                    _spo = dict(st.session_state.get("al_subject_pct_overrides", {}))
                    _subjs_in_alis = sorted(
                        s for s in subjects_in_use2 if s in alis_subj_cols
                    )

                    with st.expander(
                        f"Subject-level overrides"
                        + (f" ({len(_spo)} set)" if _spo else " (none set)"),
                        expanded=bool(_spo),
                    ):
                        _changed_spo = False
                        _cols_spo = st.columns(min(3, max(1, len(_subjs_in_alis))))
                        for _si, _subj in enumerate(_subjs_in_alis):
                            _curr_pct = _spo.get(_subj, "(use global)")
                            _opts = ["(use global)"] + pct_options
                            _idx = _opts.index(_curr_pct) if _curr_pct in _opts else 0
                            with _cols_spo[_si % len(_cols_spo)]:
                                _sel = st.selectbox(
                                    _subj,
                                    _opts,
                                    index=_idx,
                                    key=f"subj_pct_{_subj}",
                                )
                            if _sel == "(use global)":
                                _spo.pop(_subj, None)
                            else:
                                _spo[_subj] = _sel
                    st.session_state["al_subject_pct_overrides"] = _spo
                    if _spo:
                        st.caption(
                            "Overrides: "
                            + ", ".join(f"**{s}** → {v}" for s, v in sorted(_spo.items()))
                        )

                    st.divider()
                    st.markdown("**Subject proxy mapping**")
                    st.caption(
                        "These subjects are not directly in the ALIS file. "
                        "Specify which ALIS subject to use as a proxy."
                    )

                    # Subjects in use but not covered by ALIS
                    subjects_in_use2: set[str] = set()
                    if has_subj:
                        for subs in st.session_state["al_subject_list_df"]["subjects"]:
                            subjects_in_use2.update(subs)

                    sample_df2 = next(iter(alis_data.values()))
                    alis_subj_cols = [
                        c for c in sample_df2.columns if c not in ("_key", "_name", "baseline")
                    ]

                    proxy_map = dict(DEFAULT_PROXY_MAP)
                    proxy_map.update(st.session_state.get("al_alis_proxy_map", {}))

                    needs_proxy = sorted(
                        s for s in subjects_in_use2
                        if s not in alis_subj_cols and s not in proxy_map
                    )
                    has_proxy = sorted(
                        s for s in subjects_in_use2
                        if s not in alis_subj_cols and s in proxy_map
                    )

                    if has_proxy:
                        st.markdown("*Current proxy assignments:*")
                        for subj in has_proxy:
                            proxy_options = alis_subj_cols
                            curr = proxy_map.get(subj, proxy_options[0])
                            if curr not in proxy_options:
                                curr = proxy_options[0]
                            new_proxy = st.selectbox(
                                f"{subj} → use ALIS data from:",
                                proxy_options,
                                index=proxy_options.index(curr),
                                key=f"proxy_{subj}",
                            )
                            proxy_map[subj] = new_proxy

                    if needs_proxy:
                        st.markdown("*Subjects needing proxy assignment:*")
                        for subj in needs_proxy:
                            new_proxy = st.selectbox(
                                f"{subj} → use ALIS data from:",
                                alis_subj_cols,
                                key=f"proxy_new_{subj}",
                            )
                            proxy_map[subj] = new_proxy

                    st.session_state["al_alis_proxy_map"] = proxy_map

            if has_composite:
                with tabs[tab_idx["Score Weighting"]]:
                    st.markdown("**GCSE vs Yellis baseline weighting**")
                    st.caption(
                        "GCSE grades are a stronger predictor of A Level outcomes as they reflect "
                        "study habits, revision skills, and subject breadth. The Yellis baseline "
                        "provides an aptitude measure independent of prior schooling."
                    )
                    gcse_w = st.slider(
                        "GCSE weight",
                        0.0, 1.0,
                        float(st.session_state.get("gcse_weight", 0.80)),
                        0.05, format="%.2f",
                        key="gcse_weight_slider",
                    )
                    st.session_state["gcse_weight"] = gcse_w
                    st.session_state["yellis_weight"] = round(1.0 - gcse_w, 2)
                    c1, c2 = st.columns(2)
                    c1.metric("GCSE weight", f"{gcse_w:.0%}")
                    c2.metric("Yellis weight", f"{round(1.0 - gcse_w, 2):.0%}")

                with tabs[tab_idx["Fallback Ratio"]]:
                    st.markdown("**Fallback ratio for missing GCSE subjects**")
                    fb = st.slider(
                        "Overall GCSE mean weight (fallback)",
                        0.0, 1.0,
                        float(st.session_state.get("fallback_ratio", 0.60)),
                        0.05, format="%.2f",
                        key="fallback_ratio_slider",
                    )
                    st.session_state["fallback_ratio"] = fb
                    c1, c2 = st.columns(2)
                    c1.metric("Overall mean weight", f"{fb:.0%}")
                    c2.metric("Proxy subject weight", f"{round(1.0 - fb, 2):.0%}")

                with tabs[tab_idx["Subject Profiles"]]:
                    st.markdown("**Subject Weighting Profiles**")
                    profile_overrides = st.session_state.get("profile_overrides", {})
                    subjects_in_use3: set[str] = set()
                    if has_subj:
                        for subs in st.session_state["al_subject_list_df"]["subjects"]:
                            subjects_in_use3.update(subs)
                    subjects_to_show = sorted(
                        subjects_in_use3 if subjects_in_use3 else set(DEFAULT_PROFILES.keys())
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
                            profile_overrides[subj] = {"primary": new_primary, "fallback": new_fallback}
                    st.session_state["profile_overrides"] = profile_overrides

            with tabs[tab_idx["Department Adjustments"]]:
                if has_subj:
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

        _has_subj_s2 = st.session_state.get("al_subject_list_df") is not None
        _has_alis_s2 = st.session_state.get("al_alis_data") is not None
        _has_composite_s2 = (
            st.session_state.get("al_yellis_df") is not None
            and st.session_state.get("al_gcse_wide_df") is not None
        )
        all_ready = _has_subj_s2 and (_has_alis_s2 or _has_composite_s2)

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
