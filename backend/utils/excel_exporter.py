"""
excel_exporter.py
──────────────────
Produces the final Excel workbook with 5 formatted sheets:

  Sheet 1 – GL_Mapped          Full GL (PRS filtered) + Reconciliation Mapping col
  Sheet 2 – PR_Mapped          Full Payroll Register   + Reconciliation Mapping col
  Sheet 3 – GL_Pivot           Aggregated GL pivot
  Sheet 4 – PR_Pivot           Aggregated Payroll Register pivot
  Sheet 5 – Reconciliation     GL vs PR side-by-side + Variance + Status

All sheets are formatted with:
  • Frozen header row
  • Auto-fit column widths
  • Currency format for amount columns
  • Conditional colour on Status column (green = match, red = variance)
"""

import io
import logging
import re
from typing import Dict, Optional

import pandas as pd
import xlsxwriter


def _strip_step_prefix(text: str) -> str:
    """Remove leading letter-based classification prefix.
    'A. Earning/ Gross wages' → 'Earning/ Gross wages'
    'B.1 Benefits / Expenses' → 'Benefits / Expenses'
    """
    return re.sub(r"^[A-Z][0-9.]*\.?\s+", "", str(text).strip())

logger = logging.getLogger(__name__)

# ── Colour palette ────────────────────────────────────────────────────────────
CLR_HEADER_DARK   = "#1F3864"   # dark navy — sheet headers
CLR_HEADER_LIGHT  = "#BDD7EE"   # light blue — secondary headers
CLR_ACCENT        = "#F4B942"   # gold — used for section headings
CLR_MATCH_BG      = "#C6EFCE"   # green fill — matched rows
CLR_MATCH_FG      = "#276221"
CLR_VARIANCE_BG   = "#FFC7CE"   # red fill — variance rows
CLR_VARIANCE_FG   = "#9C0006"
CLR_TOTAL_BG      = "#D9D9D9"   # grey — totals row
CLR_WHITE         = "#FFFFFF"
CLR_ALT_ROW       = "#EEF4FB"   # very light blue — alternating rows

# ── Amount column name fragments (used to apply currency format) ──────────────
_AMOUNT_FRAGMENTS = [
    "amount", "amt", "earn", "bene", "deduc", "tax",
    "net", "debit", "credit", "variance", "balance",
]


def _is_amount_col(col_name: str) -> bool:
    lower = col_name.lower()
    return any(frag in lower for frag in _AMOUNT_FRAGMENTS)


def _col_width(series: pd.Series, col_name: str, min_w: int = 10, max_w: int = 50) -> int:
    """Estimate column width from content length."""
    try:
        max_len = max(
            len(str(col_name)),
            series.astype(str).str.len().max(),
        )
    except Exception:
        max_len = len(str(col_name))
    return min(max(max_len + 2, min_w), max_w)


def _write_payroll_process_sheet(workbook, mapping_rows: list, report_tag: str, fmt_header, fmt_subheader):
    """
    Write Sheet 6 — Payroll Process.
    Shows the full reconciliation mapping configuration the user defined:
    steps, GL codes, GL titles, pay codes, code types, and amount columns.
    """
    ws = workbook.add_worksheet("Payroll_Process")

    # ── Extra formats ──────────────────────────────────────────────────────
    fmt_step = workbook.add_format({
        "bold": True, "bg_color": "#D6E4F7", "border": 1,
        "font_size": 10, "font_color": "#1F3864",
    })
    fmt_text = workbook.add_format({"border": 1, "font_size": 10})
    fmt_alt  = workbook.add_format({"border": 1, "font_size": 10, "bg_color": "#EEF4FB"})
    fmt_code = workbook.add_format({
        "border": 1, "font_size": 10,
        "bg_color": "#E8F5E9", "font_color": "#1B5E20", "bold": True,
    })
    fmt_type = workbook.add_format({
        "border": 1, "font_size": 10, "align": "center",
        "bg_color": "#FFF3E0", "font_color": "#C15700", "bold": True,
    })

    # ── Title row ──────────────────────────────────────────────────────────
    ws.merge_range(0, 0, 0, 6, f"Payroll Process — Reconciliation Mapping Configuration{report_tag}", fmt_subheader)

    # ── Column headers ─────────────────────────────────────────────────────
    headers = [
        "Reconciliation Step",
        "GL Code",
        "GL Title",
        "Pay Code",
        "Pay Code Title",
        "Amount Column",
        "Code Type",
    ]
    col_widths = [38, 10, 34, 14, 30, 16, 12]

    for c, (hdr, w) in enumerate(zip(headers, col_widths)):
        ws.write(1, c, hdr, fmt_header)
        ws.set_column(c, c, w)

    ws.freeze_panes(2, 0)

    # ── Data rows with group headers ───────────────────────────────────────
    excel_row  = 2
    last_step  = None
    data_count = 0

    for row in mapping_rows:
        step = _strip_step_prefix(str(row.get("recon_step", "")))

        # Group separator row when the reconciliation step changes
        if step and step != last_step:
            ws.merge_range(excel_row, 0, excel_row, 6, step, fmt_step)
            excel_row += 1
            last_step  = step

        is_alt = data_count % 2 == 1
        base   = fmt_alt if is_alt else fmt_text

        ws.write(excel_row, 0, step,                                            base)
        ws.write(excel_row, 1, str(row.get("gl_code",        "")).strip(),      fmt_code)
        ws.write(excel_row, 2, str(row.get("gl_title",       "")).strip(),      base)
        ws.write(excel_row, 3, str(row.get("pay_code",       "")).strip(),      fmt_code)
        ws.write(excel_row, 4, str(row.get("pay_code_title", "")).strip(),      base)
        ws.write(excel_row, 5, str(row.get("amount_column",  "")).strip(),      base)
        ws.write(excel_row, 6, str(row.get("code_type",      "")).strip(),      fmt_type)

        excel_row  += 1
        data_count += 1


def _write_combined_pivot_sheet(
    workbook,
    gl_pivot: pd.DataFrame,
    pr_pivot: pd.DataFrame,
    report_tag: str,
    fmt_header,
):
    """
    Sheet: 'GL vs PR Pivot' — GL Pivot on the left, blank separator, PR Pivot on the right.
    Matches the screenshot layout: side-by-side with section title rows.
    """
    ws = workbook.add_worksheet("Reconciliation")

    # Section title formats
    fmt_title_gl = workbook.add_format({
        "bold": True, "font_size": 11, "font_color": "#FFFFFF",
        "bg_color": "#1F3864", "border": 1, "align": "center", "valign": "vcenter",
    })
    fmt_title_pr = workbook.add_format({
        "bold": True, "font_size": 11, "font_color": "#FFFFFF",
        "bg_color": "#1F4E79", "border": 1, "align": "center", "valign": "vcenter",
    })
    fmt_text     = workbook.add_format({"border": 1, "font_size": 10})
    fmt_text_alt = workbook.add_format({"border": 1, "font_size": 10, "bg_color": CLR_ALT_ROW})
    fmt_curr     = workbook.add_format({"num_format": '#,##0.00_);(#,##0.00)', "border": 1, "font_size": 10})
    fmt_curr_alt = workbook.add_format({"num_format": '#,##0.00_);(#,##0.00)', "border": 1, "font_size": 10, "bg_color": CLR_ALT_ROW})
    fmt_var_ok   = workbook.add_format({"num_format": '#,##0.00_);(#,##0.00)', "border": 1, "font_size": 10, "bg_color": CLR_MATCH_BG, "font_color": CLR_MATCH_FG})
    fmt_var_bad  = workbook.add_format({"num_format": '#,##0.00_);(#,##0.00)', "border": 1, "font_size": 10, "bg_color": CLR_VARIANCE_BG, "font_color": CLR_VARIANCE_FG})

    gl_cols = list(gl_pivot.columns) if not gl_pivot.empty else []
    pr_cols = list(pr_pivot.columns) if not pr_pivot.empty else []

    sep_col      = len(gl_cols)          # blank column between the two halves
    pr_start_col = len(gl_cols) + 1

    # ── Row 0: section title headers ──────────────────────────────────────
    if gl_cols:
        ws.merge_range(0, 0, 0, len(gl_cols) - 1,
                       f"Pivot of GL{report_tag}", fmt_title_gl)
    if pr_cols:
        ws.merge_range(0, pr_start_col, 0, pr_start_col + len(pr_cols) - 1,
                       f"Pivot of Payroll Register{report_tag}", fmt_title_pr)

    # ── Row 1: column headers ─────────────────────────────────────────────
    for c, col in enumerate(gl_cols):
        ws.write(1, c, col, fmt_header)
    for c, col in enumerate(pr_cols):
        ws.write(1, pr_start_col + c, col, fmt_header)

    ws.freeze_panes(2, 0)

    # ── GL data rows ──────────────────────────────────────────────────────
    for r, (_, row) in enumerate(gl_pivot.iterrows()):
        erow   = 2 + r
        is_alt = r % 2 == 1
        for c, col in enumerate(gl_cols):
            val = row[col]
            if pd.isna(val):
                ws.write_blank(erow, c, None, fmt_text_alt if is_alt else fmt_text)
            elif _is_amount_col(col):
                try:
                    ws.write_number(erow, c, float(val), fmt_curr_alt if is_alt else fmt_curr)
                except Exception:
                    ws.write_string(erow, c, str(val), fmt_text_alt if is_alt else fmt_text)
            else:
                ws.write_string(erow, c, str(val), fmt_text_alt if is_alt else fmt_text)

    # ── PR data rows ──────────────────────────────────────────────────────
    for r, (_, row) in enumerate(pr_pivot.iterrows()):
        erow   = 2 + r
        is_alt = r % 2 == 1
        for c, col in enumerate(pr_cols):
            val = row[col]
            col_c = pr_start_col + c
            if col == "Variance":
                try:
                    v   = float(val) if not pd.isna(val) else 0.0
                    fmt = fmt_var_ok if abs(v) < 0.01 else fmt_var_bad
                    ws.write_number(erow, col_c, v, fmt)
                except Exception:
                    ws.write_string(erow, col_c, str(val), fmt_text)
            elif pd.isna(val):
                ws.write_blank(erow, col_c, None, fmt_text_alt if is_alt else fmt_text)
            elif _is_amount_col(col):
                try:
                    ws.write_number(erow, col_c, float(val), fmt_curr_alt if is_alt else fmt_curr)
                except Exception:
                    ws.write_string(erow, col_c, str(val), fmt_text_alt if is_alt else fmt_text)
            else:
                ws.write_string(erow, col_c, str(val), fmt_text_alt if is_alt else fmt_text)

    # ── Column widths ─────────────────────────────────────────────────────
    for c, col in enumerate(gl_cols):
        ws.set_column(c, c, _col_width(gl_pivot[col], col))
    ws.set_column(sep_col, sep_col, 3)  # blank separator
    for c, col in enumerate(pr_cols):
        ws.set_column(pr_start_col + c, pr_start_col + c, _col_width(pr_pivot[col], col))


def export_to_excel(
    gl_mapped:    pd.DataFrame,
    pr_mapped:    pd.DataFrame,
    gl_pivot:     pd.DataFrame,
    pr_pivot:     pd.DataFrame,
    recon_df:     pd.DataFrame,
    period_label: str  = "",
    client_name:  str  = "",
    mapping_rows: list = None,
) -> bytes:
    """
    Build the Excel workbook in-memory and return raw bytes.

    Parameters
    ----------
    gl_mapped    : GL DataFrame with Reconciliation Mapping column added.
    pr_mapped    : Payroll Register DataFrame with Reconciliation Mapping added.
    gl_pivot     : GL pivot table.
    pr_pivot     : PR pivot table.
    recon_df     : Reconciliation comparison table.
    period_label : Optional pay-period string for the filename / title cell.
    client_name  : Client name to include in report headers.
    mapping_rows : List of mapping config dicts (the Payroll Process definition).

    Returns
    -------
    bytes — ready to be downloaded via st.download_button.
    """
    output = io.BytesIO()

    workbook = xlsxwriter.Workbook(output, {"in_memory": True})

    # ── shared formats ────────────────────────────────────────────────────
    fmt_header = workbook.add_format({
        "bold": True, "font_color": CLR_WHITE, "bg_color": CLR_HEADER_DARK,
        "border": 1, "align": "center", "valign": "vcenter",
        "font_size": 10,
    })
    fmt_subheader = workbook.add_format({
        "bold": True, "bg_color": CLR_HEADER_LIGHT,
        "border": 1, "align": "center", "font_size": 10,
    })
    fmt_currency = workbook.add_format({
        "num_format": '#,##0.00_);(#,##0.00)', "border": 1,
    })
    fmt_currency_alt = workbook.add_format({
        "num_format": '#,##0.00_);(#,##0.00)', "border": 1,
        "bg_color": CLR_ALT_ROW,
    })
    fmt_text = workbook.add_format({"border": 1, "font_size": 10})
    fmt_text_alt = workbook.add_format({
        "border": 1, "font_size": 10, "bg_color": CLR_ALT_ROW,
    })
    fmt_match = workbook.add_format({
        "bold": True, "font_color": CLR_MATCH_FG, "bg_color": CLR_MATCH_BG,
        "border": 1,
    })
    fmt_variance = workbook.add_format({
        "bold": True, "font_color": CLR_VARIANCE_FG, "bg_color": CLR_VARIANCE_BG,
        "border": 1,
    })
    fmt_total = workbook.add_format({
        "bold": True, "bg_color": CLR_TOTAL_BG, "border": 1,
        "num_format": '#,##0.00_);(#,##0.00)',
    })
    fmt_total_text = workbook.add_format({
        "bold": True, "bg_color": CLR_TOTAL_BG, "border": 1,
    })

    # ── helper: write a DataFrame to a worksheet ──────────────────────────
    def write_sheet(
        ws,
        df: pd.DataFrame,
        title: str = "",
        highlight_status: bool = False,
        status_col: Optional[str] = "Status",
    ):
        row_offset = 0

        # Optional title row
        if title:
            ws.merge_range(0, 0, 0, max(len(df.columns) - 1, 0), title, fmt_subheader)
            row_offset = 1

        # Header row
        for c_idx, col_name in enumerate(df.columns):
            ws.write(row_offset, c_idx, col_name, fmt_header)

        ws.freeze_panes(row_offset + 1, 0)

        # Data rows
        for r_idx, (_, row) in enumerate(df.iterrows()):
            excel_row  = row_offset + 1 + r_idx
            is_alt     = r_idx % 2 == 1
            is_total   = str(row.get("Reconciliation Step", "")).strip().upper() == "TOTAL"

            for c_idx, col_name in enumerate(df.columns):
                value = row[col_name]

                # Pick format
                if is_total:
                    fmt = fmt_total if _is_amount_col(col_name) else fmt_total_text
                elif highlight_status and status_col and status_col in df.columns:
                    status_val = str(row.get(status_col, ""))
                    if "Match" in status_val:
                        fmt = fmt_match
                    elif "Variance" in status_val or "No PR" in status_val:
                        fmt = fmt_variance
                    else:
                        fmt = fmt_currency_alt if (is_alt and _is_amount_col(col_name)) else (
                              fmt_currency if _is_amount_col(col_name) else
                              fmt_text_alt if is_alt else fmt_text)
                else:
                    fmt = (
                        fmt_currency_alt if (is_alt and _is_amount_col(col_name)) else
                        fmt_currency    if _is_amount_col(col_name) else
                        fmt_text_alt    if is_alt else
                        fmt_text
                    )

                # Write numeric vs string
                if pd.isna(value):
                    ws.write_blank(excel_row, c_idx, None, fmt)
                elif isinstance(value, (int, float)):
                    ws.write_number(excel_row, c_idx, float(value), fmt)
                else:
                    ws.write_string(excel_row, c_idx, str(value), fmt)

        # Auto-fit columns
        for c_idx, col_name in enumerate(df.columns):
            width = _col_width(df[col_name], col_name)
            ws.set_column(c_idx, c_idx, width)

    # ── Build common prefix for titles ───────────────────────────────────
    client_str = f" | {client_name}" if client_name and client_name.lower() != "default" else ""
    period_str = f" | {period_label}" if period_label else ""
    report_tag = f"{client_str}{period_str}"

    # ── Sheet 1: GL Mapped ────────────────────────────────────────────────
    ws1 = workbook.add_worksheet("GL_Mapped")
    if gl_mapped is not None and not gl_mapped.empty:
        write_sheet(ws1, gl_mapped, title=f"General Ledger — PRS Transactions{report_tag}")

    # ── Sheet 2: PR Mapped ────────────────────────────────────────────────
    ws2 = workbook.add_worksheet("PR_Mapped")
    if pr_mapped is not None and not pr_mapped.empty:
        write_sheet(ws2, pr_mapped, title=f"Payroll Register{report_tag}")

    # ── Sheet 3: GL Pivot ─────────────────────────────────────────────────
    ws3 = workbook.add_worksheet("GL_Pivot")
    write_sheet(ws3, gl_pivot, title=f"GL Pivot — Net Amount by Reconciliation Step{report_tag}")

    # ── Sheet 4: PR Pivot ─────────────────────────────────────────────────
    ws4 = workbook.add_worksheet("PR_Pivot")
    write_sheet(ws4, pr_pivot, title=f"Payroll Register Pivot — Amounts by Code Type{report_tag}")

    # ── Sheet 5: Reconciliation — side-by-side GL + PR pivot ─────────────
    _write_combined_pivot_sheet(workbook, gl_pivot, pr_pivot, report_tag, fmt_header)

    # ── Sheet 6: Payroll Process (user-defined mapping config) ────────────
    if mapping_rows:
        _write_payroll_process_sheet(workbook, mapping_rows, report_tag, fmt_header, fmt_subheader)

    workbook.close()
    output.seek(0)
    return output.read()
