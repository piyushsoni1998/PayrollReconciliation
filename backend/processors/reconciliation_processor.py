"""
reconciliation_processor.py
────────────────────────────
Compares the GL Pivot with the Payroll Register Pivot.

Key improvement: uses the 'amount_column' field from the mapping config
directly — no more keyword inference or guessing. The mapping row says
exactly which PR column maps to each GL code:

    EarnAmt          → earn_amount  (EARNING)
    BeneAmt          → benefit_amount (BENEFIT)
    DeducAmt         → deduction_amount (DEDUCT)
    EETax            → ee_tax
    ERTax            → er_tax
    EETax & ERTax    → sum of both (Medicare / SS employer liability)
    NetAmt           → net pay cross-check (GL 1020 / bank)
    GLOnly           → GL balance shown as-is; no PR comparison

Sign Convention
───────────────
Expense accounts (5xxx/6xxx) → GL positive, PR positive → Variance = GL − PR
Liability accounts (2xxx)    → GL negative, PR positive → Variance = GL + PR
Bank/Asset accounts (1xxx)   → amount_column == "NetAmt" → bank cross-check
(Sign flip driven by GL code range only — no step-label keyword matching.)
"""

import logging
import re
from collections import defaultdict
from typing import Dict, Optional

import pandas as pd

logger    = logging.getLogger(__name__)
TOLERANCE = 0.01   # cents tolerance for floating-point rounding

MATCH_STATUS    = "✓ Match"
VARIANCE_STATUS = "⚠ Variance"
GL_ONLY_STATUS  = "GL Only"

# ── Output column name constants ───────────────────────────────────────────────
_COL_STEP   = "Reconciliation Step"
_COL_CODE   = "GL Code"
_COL_TITLE  = "GL Title"
_COL_GL_NET = "GL Net Amount"
_COL_PR_AMT = "PR Amount"
_COL_VAR    = "Variance"
_COL_STATUS = "Status"
_COL_NOTES  = "Notes"

_RECON_MAPPING_COL = "Reconciliation Mapping"

# Amount column → PR pivot column name
_AMOUNT_COL_MAP = {
    "earnamt":          "Sum EarnAmt",
    "beneamt":          "Sum BeneAmt",
    "deducamt":         "Sum DeducAmt",
    "eetax":            "Sum EETax",
    "ertax":            "Sum ERTax",
    "eetax & ertax":    "BOTH_TAXES",   # special — sum EETax + ERTax
    "netamt":           "Sum NetAmt",   # bank cross-check
}


def _resolve_amount_col(amount_column: str) -> str:
    """Map the config's amount_column string to the PR pivot column name.
    Normalises spacing around '&' so 'EeTax&ERTax' and 'EeTax & ERTax' both work.
    """
    key = " & ".join(p.strip() for p in amount_column.strip().lower().split("&"))
    return _AMOUNT_COL_MAP.get(key, "")


def _is_liability(gl_code: str) -> bool:
    """True for credit-normal (2xxx) accounts — drives sign flip in variance calc."""
    code = str(gl_code).strip().lstrip("0")
    return bool(code) and code[0] == "2"


def _build_pr_index(pr_pivot: pd.DataFrame) -> dict:
    """Pre-build inverted index {gl_code → [pr_pivot row indices]}.

    Replaces O(n) regex scan per GL code (was O(m×n)) with O(m+n) total.
    """
    idx: dict = defaultdict(list)
    for i, pr_row in pr_pivot.iterrows():
        mapping = str(pr_row.get(_RECON_MAPPING_COL, ""))
        for code in re.findall(r"\b(\d{4,})\b", mapping):
            idx[code].append(i)
    return idx


def _sum_pr_amount(
    matching_pr:       pd.DataFrame,
    gl_code:           str,
    default_col_key:   str,
    gl_pr_amount:      dict,
) -> float:
    """Sum the correct PR amount column(s) across all matching PR pivot rows.

    Uses per-row amount-column lookup (gl_pr_amount) when available so that
    GL codes like 2115 — where FIT uses EETax but MC/SS use EETax+ERTax —
    are handled correctly per row rather than using a single global column.
    """
    total = 0.0
    row_overrides = gl_pr_amount.get(gl_code, {})

    for _, pr_row in matching_pr.iterrows():
        pr_mapping  = pr_row.get(_RECON_MAPPING_COL, "")
        col_key     = _resolve_amount_col(row_overrides[pr_mapping]) \
                      if pr_mapping in row_overrides else default_col_key

        if col_key == "BOTH_TAXES":
            total += float(pr_row.get("Sum EETax", 0) or 0)
            total += float(pr_row.get("Sum ERTax", 0) or 0)
        elif col_key and col_key in pr_row.index:
            total += float(pr_row.get(col_key, 0) or 0)

    return total


def _make_row(
    recon_step: str,
    gl_code:    str,
    gl_title:   str,
    gl_net:     float,
    pr_amount:  float,
    variance:   float,
    status:     str,
    notes:      str,
) -> dict:
    """Build a single reconciliation output row dict."""
    return {
        _COL_STEP:   recon_step,
        _COL_CODE:   gl_code,
        _COL_TITLE:  gl_title,
        _COL_GL_NET: round(gl_net,    2),
        _COL_PR_AMT: round(pr_amount, 2),
        _COL_VAR:    round(variance,  2),
        _COL_STATUS: status,
        _COL_NOTES:  notes,
    }


def _merge_combined_gl_rows(rows: list, gl_lookup: dict) -> list:
    """
    Merge reconciliation rows that belong to the same combined GL code
    (e.g. GL 2142 and GL 2150 both from config entry "2142/2150").

    Individual GL rows are processed separately (GL net amounts, PR amounts),
    then merged into one output row:
      - GL Net = sum of all individual GL nets
      - PR Amount = taken from the first row that has a non-zero PR match
        (all rows in the group map to the same PR pivot row, so only one
         non-duplicated PR amount exists)
      - Variance = recalculated from the merged GL net and PR amount
    """
    combined_map: dict = {}   # combined_code → list of row dicts
    output: list = []

    for row in rows:
        gl_code = str(row.get(_COL_CODE, "")).strip()
        meta    = gl_lookup.get(gl_code, {})
        ckey    = meta.get("combined_gl_code", "")

        if ckey and "/" in ckey:
            combined_map.setdefault(ckey, []).append(row)
        else:
            output.append(row)

    for combined_code, group in combined_map.items():
        first   = group[0]
        gl_net  = sum(float(r.get(_COL_GL_NET, 0) or 0) for r in group)

        # All rows in the group point to the same PR pivot row (the mapping
        # string contains all individual GL codes, e.g. "2142/2150 - Dental…").
        # Take the first non-zero PR display amount to avoid double-counting.
        all_pr  = [float(r.get(_COL_PR_AMT, 0) or 0) for r in group]
        pr_display = next((v for v in all_pr if abs(v) > TOLERANCE), 0.0)

        # Recalculate variance using the representative (first) GL code sign convention
        first_code = combined_code.split("/")[0].strip()
        if _is_liability(first_code):
            # Liability: GL is credit-normal (negative), PR positive
            # pr_display is already negated (−PR_raw), so PR_raw = −pr_display
            variance = gl_net + (-pr_display)
        else:
            variance = gl_net - pr_display

        status = MATCH_STATUS if abs(variance) < TOLERANCE else VARIANCE_STATUS
        notes  = str(first.get(_COL_NOTES, ""))

        output.append(_make_row(
            recon_step = str(first.get(_COL_STEP, "")),
            gl_code    = combined_code,
            gl_title   = str(first.get(_COL_TITLE, "")),
            gl_net     = gl_net,
            pr_amount  = pr_display,
            variance   = round(variance, 2),
            status     = status,
            notes      = notes,
        ))

    return output


def build_reconciliation(
    gl_pivot:        pd.DataFrame,
    pr_pivot:        pd.DataFrame,
    gl_lookup:       Dict[str, dict],
    pr_net_total:    Optional[float] = None,
    gl_pr_amount:    Optional[dict]  = None,
) -> pd.DataFrame:
    """
    Produce the reconciliation comparison table.

    Parameters
    ----------
    gl_pivot      : Output of gl_processor.process_gl()
    pr_pivot      : Output of payroll_processor.process_payroll()
    gl_lookup     : { gl_code: {"gl_title", "recon_step", "code_type", "amount_column"} }
    pr_net_total  : Sum of NetAmt from PR, for F. Bank Payment cross-check.
    gl_pr_amount  : { gl_code → { pr_mapping_string → amount_column } }
                    Per-row amount column override built by build_lookups_from_config.

    Returns
    -------
    DataFrame with columns:
        Reconciliation Step | GL Code | GL Title |
        GL Net Amount | PR Amount | Variance | Status | Notes
    """
    pr_idx       = _build_pr_index(pr_pivot)
    _gl_pr_amt   = gl_pr_amount or {}
    rows         = []

    for _, gl_row in gl_pivot.iterrows():
        row = _process_gl_row(gl_row, pr_pivot, pr_idx, gl_lookup, _gl_pr_amt, pr_net_total)
        rows.append(row)

    # Merge rows that belong to the same combined GL code (e.g. 2142/2150)
    rows = _merge_combined_gl_rows(rows, gl_lookup)

    recon_df = pd.DataFrame(rows)
    if recon_df.empty:
        return recon_df

    recon_df = recon_df.sort_values(_COL_STEP).reset_index(drop=True)

    total_row = _make_row(
        recon_step = "TOTAL",
        gl_code    = "",
        gl_title   = "",
        gl_net     = recon_df[_COL_GL_NET].sum(),
        pr_amount  = recon_df[_COL_PR_AMT].sum(),
        variance   = recon_df[_COL_VAR].sum(),
        status     = MATCH_STATUS if abs(recon_df[_COL_VAR].sum()) < TOLERANCE else VARIANCE_STATUS,
        notes      = "Grand total",
    )
    return pd.concat([recon_df, pd.DataFrame([total_row])], ignore_index=True)


def _process_gl_row(
    gl_row:       pd.Series,
    pr_pivot:     pd.DataFrame,
    pr_idx:       dict,
    gl_lookup:    dict,
    gl_pr_amount: dict,
    pr_net_total: Optional[float],
) -> dict:
    """Process one GL pivot row and return a reconciliation output row dict."""
    gl_code    = str(gl_row[_COL_CODE]).strip()
    gl_title   = str(gl_row[_COL_TITLE]).strip()
    recon_step = str(gl_row[_RECON_MAPPING_COL]).strip()
    gl_net     = float(gl_row["Sum of Net Amount"])

    meta       = gl_lookup.get(gl_code, {})
    amount_col = meta.get("amount_column", "")
    pr_col_key = _resolve_amount_col(amount_col)

    # GLOnly: informational — no PR counterpart, variance = 0 by design
    if amount_col.strip().lower() == "glonly":
        return _make_row(recon_step, gl_code, gl_title, gl_net, 0.0, 0.0,
                         GL_ONLY_STATUS, "Informational — no PR counterpart")

    # Bank / net pay cross-check (amount_column == "NetAmt")
    if pr_col_key == "Sum NetAmt":
        return _handle_bank_row(recon_step, gl_code, gl_title, gl_net, pr_net_total)

    # Standard reconciliation via inverted index
    pr_indices  = pr_idx.get(gl_code, [])
    matching_pr = pr_pivot.loc[pr_indices] if pr_indices else pr_pivot.iloc[0:0]

    if matching_pr.empty:
        return _make_row(recon_step, gl_code, gl_title, gl_net, 0.0, gl_net,
                         "⚠ No PR Match", "GL code not found in any PR mapping")

    pr_amount = _sum_pr_amount(matching_pr, gl_code, pr_col_key, gl_pr_amount)
    return _handle_standard_row(recon_step, gl_code, gl_title, gl_net, pr_amount)


def _handle_bank_row(
    recon_step:   str,
    gl_code:      str,
    gl_title:     str,
    gl_net:       float,
    pr_net_total: Optional[float],
) -> dict:
    """Build the F. Bank Payment cross-check row."""
    net_total = pr_net_total or 0.0
    variance  = gl_net + net_total   # bank debit offsets net pay
    status    = MATCH_STATUS if abs(variance) < TOLERANCE else VARIANCE_STATUS
    return _make_row(recon_step, gl_code, gl_title, gl_net, -net_total,
                     variance, status, "Bank / Net Pay cross-check")


def _handle_standard_row(
    recon_step: str,
    gl_code:    str,
    gl_title:   str,
    gl_net:     float,
    pr_amount:  float,
) -> dict:
    """Build a standard GL-vs-PR reconciliation row with correct sign handling."""
    if _is_liability(gl_code):
        # Liability (2xxx): GL credit (negative) vs PR positive → variance = GL + PR
        variance   = gl_net + pr_amount
        pr_display = -pr_amount
        notes      = "Liability (credit normal)"
    else:
        # Expense (5xxx/6xxx): GL debit (positive) vs PR positive → variance = GL - PR
        variance   = gl_net - pr_amount
        pr_display = pr_amount
        notes      = ""
    status = MATCH_STATUS if abs(variance) < TOLERANCE else VARIANCE_STATUS
    return _make_row(recon_step, gl_code, gl_title, gl_net, pr_display,
                     variance, status, notes)


def get_summary_stats(recon_df: pd.DataFrame) -> dict:
    if recon_df.empty:
        return {}
    data      = recon_df[recon_df[_COL_STEP] != "TOTAL"]
    gl_only   = data[data[_COL_STATUS] == GL_ONLY_STATUS]
    recon_data = data[data[_COL_STATUS] != GL_ONLY_STATUS]
    total_var  = recon_data[_COL_VAR].abs().sum()
    return {
        "total_lines":    int(len(recon_data)),
        "gl_only_lines":  int(len(gl_only)),
        "matched":        int((recon_data[_COL_STATUS] == MATCH_STATUS).sum()),
        "variances":      int((recon_data[_COL_STATUS] != MATCH_STATUS).sum()),
        "total_variance": round(float(total_var), 2) if total_var == total_var else 0.0,
        "is_clean":       bool(total_var < TOLERANCE) if total_var == total_var else False,
    }
