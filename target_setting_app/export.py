"""Excel export logic for GCSE and A Level target grades."""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import openpyxl
from openpyxl.styles import (
    PatternFill,
    Font,
    Alignment,
    Border,
    Side,
)
from openpyxl.utils import get_column_letter

from target_engine import compute_gcse_summary, compute_alevel_summary

AMBER_FILL = PatternFill(start_color="FFC000", end_color="FFC000", fill_type="solid")
HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
BAND_A_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
BAND_B_FILL = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
BAND_C_FILL = PatternFill(start_color="FFCC99", end_color="FFCC99", fill_type="solid")
BAND_D_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
FOOTER_FILL = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")


def _is_blank(val) -> bool:
    """Return True if val is NA, None, empty string, or pd.NA."""
    if val is None:
        return True
    try:
        if pd.isna(val):
            return True
    except (TypeError, ValueError):
        pass
    return str(val) == ""


def _auto_fit_columns(ws, min_width: int = 6, max_width: int = 30) -> None:
    for column_cells in ws.columns:
        length = max(
            len(str(cell.value)) if cell.value is not None else 0
            for cell in column_cells
        )
        col_letter = get_column_letter(column_cells[0].column)
        ws.column_dimensions[col_letter].width = max(min_width, min(length + 2, max_width))


def export_gcse(
    targets_df: pd.DataFrame,
    overrides: dict | None = None,
    academic_year: str = "",
) -> bytes:
    """Generate two-sheet Excel for GCSE targets. Returns bytes."""
    overrides = overrides or {}
    subject_cols = [
        c for c in targets_df.columns
        if c not in ("surname", "forename", "form", "overall_score")
    ]
    subject_cols = sorted(subject_cols)
    year_str = academic_year or _current_academic_year()

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Matrix View"

    # Title row
    ws1.cell(row=1, column=1, value=f"Emanuel School — GCSE Target Grades {year_str}")
    ws1.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws1.merge_cells(start_row=1, start_column=1, end_row=1, end_column=3 + len(subject_cols))

    # Header row 3
    header_cols = ["Surname", "Forename", "Form"] + subject_cols
    for col_idx, header in enumerate(header_cols, start=1):
        cell = ws1.cell(row=3, column=col_idx, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    # Data rows
    df_sorted = targets_df.sort_values("overall_score", ascending=False, na_position="last")
    data_start_row = 4

    for r_idx, (_, row) in enumerate(df_sorted.iterrows(), start=data_start_row):
        ws1.cell(row=r_idx, column=1, value=str(row.get("surname", "")))
        ws1.cell(row=r_idx, column=2, value=str(row.get("forename", "")))
        ws1.cell(row=r_idx, column=3, value=str(row.get("form", "")))

        for c_idx, subj in enumerate(subject_cols, start=4):
            val = row.get(subj)
            if _is_blank(val):
                continue
            cell = ws1.cell(row=r_idx, column=c_idx, value=val)
            cell.alignment = Alignment(horizontal="center")

            # Highlight overrides
            student_key = f"{row['surname']}|{row['forename']}"
            if student_key in overrides and subj in overrides[student_key]:
                cell.fill = AMBER_FILL

    # Summary footer
    footer_start = data_start_row + len(df_sorted) + 2
    summary_df = compute_gcse_summary(targets_df, subject_cols)
    ws1.cell(row=footer_start - 1, column=1, value="Grade Distribution").font = Font(bold=True)

    for r_idx, (_, row) in enumerate(summary_df.iterrows(), start=footer_start):
        ws1.cell(row=r_idx, column=1, value=row["Band"]).font = Font(bold=True)
        ws1.cell(row=r_idx, column=1).fill = FOOTER_FILL
        for c_idx, subj in enumerate(subject_cols, start=4):
            cell = ws1.cell(row=r_idx, column=c_idx, value=row.get(subj, ""))
            cell.fill = FOOTER_FILL
            cell.alignment = Alignment(horizontal="center")
        all_cell = ws1.cell(row=r_idx, column=4 + len(subject_cols), value=row.get("All", ""))
        all_cell.fill = FOOTER_FILL
        all_cell.font = Font(bold=True)
        all_cell.alignment = Alignment(horizontal="center")

    _auto_fit_columns(ws1)

    # Sheet 2: Unpivoted
    ws2 = wb.create_sheet("Unpivoted Data")
    ws2.append(["Surname", "Forename", "Form", "Subject", "Target Grade"])
    for cell in ws2[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT

    unpivot_rows = []
    for _, row in df_sorted.iterrows():
        for subj in subject_cols:
            val = row.get(subj)
            if not _is_blank(val):
                unpivot_rows.append((
                    row.get("surname", ""),
                    row.get("forename", ""),
                    row.get("form", ""),
                    subj,
                    val,
                ))

    unpivot_rows.sort(key=lambda r: (str(r[0]), str(r[1]), str(r[3])))
    for r in unpivot_rows:
        ws2.append(list(r))

    _auto_fit_columns(ws2)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_alevel(
    targets_df: pd.DataFrame,
    overrides: dict | None = None,
    academic_year: str = "",
) -> bytes:
    """Generate two-sheet Excel for A Level targets. Returns bytes."""
    overrides = overrides or {}
    subject_cols = [
        c for c in targets_df.columns
        if c not in ("surname", "forename", "year_group", "overall_score")
    ]
    subject_cols = sorted(subject_cols)
    year_str = academic_year or _current_academic_year()

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Matrix View"

    ws1.cell(row=1, column=1, value=f"Emanuel School — A Level Target Grades {year_str}")
    ws1.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws1.merge_cells(start_row=1, start_column=1, end_row=1, end_column=3 + len(subject_cols))

    header_cols = ["Surname", "Forename", "Year Group"] + subject_cols
    for col_idx, header in enumerate(header_cols, start=1):
        cell = ws1.cell(row=3, column=col_idx, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    df_sorted = targets_df.sort_values("overall_score", ascending=False, na_position="last")
    data_start_row = 4

    for r_idx, (_, row) in enumerate(df_sorted.iterrows(), start=data_start_row):
        ws1.cell(row=r_idx, column=1, value=str(row.get("surname", "")))
        ws1.cell(row=r_idx, column=2, value=str(row.get("forename", "")))
        ws1.cell(row=r_idx, column=3, value=str(row.get("year_group", "Year 12")))

        for c_idx, subj in enumerate(subject_cols, start=4):
            val = row.get(subj)
            if _is_blank(val):
                continue
            cell = ws1.cell(row=r_idx, column=c_idx, value=val)
            cell.alignment = Alignment(horizontal="center")

            student_key = f"{row['surname']}|{row['forename']}"
            if student_key in overrides and subj in overrides[student_key]:
                cell.fill = AMBER_FILL

    footer_start = data_start_row + len(df_sorted) + 2
    summary_df = compute_alevel_summary(targets_df, subject_cols)
    ws1.cell(row=footer_start - 1, column=1, value="Grade Distribution").font = Font(bold=True)

    for r_idx, (_, row) in enumerate(summary_df.iterrows(), start=footer_start):
        ws1.cell(row=r_idx, column=1, value=row["Band"]).font = Font(bold=True)
        ws1.cell(row=r_idx, column=1).fill = FOOTER_FILL
        for c_idx, subj in enumerate(subject_cols, start=4):
            cell = ws1.cell(row=r_idx, column=c_idx, value=row.get(subj, ""))
            cell.fill = FOOTER_FILL
            cell.alignment = Alignment(horizontal="center")
        all_cell = ws1.cell(row=r_idx, column=4 + len(subject_cols), value=row.get("All", ""))
        all_cell.fill = FOOTER_FILL
        all_cell.font = Font(bold=True)
        all_cell.alignment = Alignment(horizontal="center")

    _auto_fit_columns(ws1)

    # Sheet 2
    ws2 = wb.create_sheet("Unpivoted Data")
    ws2.append(["Surname", "Forename", "Year Group", "Subject", "Target Grade"])
    for cell in ws2[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT

    unpivot_rows = []
    for _, row in df_sorted.iterrows():
        for subj in subject_cols:
            val = row.get(subj)
            if not _is_blank(val):
                unpivot_rows.append((
                    row.get("surname", ""),
                    row.get("forename", ""),
                    row.get("year_group", "Year 12"),
                    subj,
                    val,
                ))

    unpivot_rows.sort(key=lambda r: (str(r[0]), str(r[1]), str(r[3])))
    for r in unpivot_rows:
        ws2.append(list(r))

    _auto_fit_columns(ws2)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _current_academic_year() -> str:
    now = datetime.now()
    if now.month >= 9:
        return f"{now.year}/{str(now.year + 1)[2:]}"
    return f"{now.year - 1}/{str(now.year)[2:]}"
