"""
reconciliation_processor.py
────────────────────────────
Compares the GL Pivot with the Payroll Register Pivot.

Sign Convention (config-driven — NOT hardcoded to GL code digit)
────────────────────────────────────────────────────────────────
Each GL code carries an 'account_type' field set in the mapping config.
If not explicitly set, it is derived from the GL code's first digit as a
safe fallback (2 → liability, 1 → bank, everything else → expense).

  account_type = "expense"   → GL debit-normal (positive)
                               Variance = GL Net − PR Amount
  account_type = "liability" → GL credit-normal (negative), PR positive
                               Variance = GL Net + PR Amount
  account_type = "bank"      → Net pay cross-check (amount_column = NetAmt)
  account_type = "glonly"    → Informational; shown as-is, no PR comparison

amount_column field drives which PR pivot column to read:
  EarnAmt          → Sum EarnAmt
  BeneAmt          → Sum BeneAmt
  DeducAmt         → Sum DeducAmt
  EETax            → Sum EETax
  ERTax            → Sum ERTax
  EeTax & ERTax    → Sum EETax + Sum ERTax
  NetAmt           → Net pay cross-check (bank row OR 2157 accrual)
  GLOnly           → GL balance shown as-is; no PR comparison
"""

import logging
import re
from collections import defaultdict
from typing import Dict, Optional

import pandas as pd

logger    = logging.getLogger(__name__)
TOLERANCE = 0.01

MATCH_STATUS    = "✓ Match"
VARIANCE_STATUS = "⚠ Variance"
GL_ONLY_STATUS  = "GL Only"

_COL_STEP   = "Reconciliation Step"
_COL_CODE   = "GL Code"
_COL_TITLE  = "GL Title"
_COL_GL_NET = "GL Net Amount"
_COL_PR_AMT = "PR Amount"
_COL_VAR    = "Variance"
_COL_STATUS = "Status"
_COL_NOTES  = "Notes"

_RECON_MAPPING_COL = "Reconciliation Mapping"

_AMOUNT_COL_MAP = {
    "earnamt":          "Sum EarnAmt",
    "beneamt":          "Sum BeneAmt",
    "deducamt":         "Sum DeducAmt",
    "eetax":            "Sum EETax",
    "ertax":            "Sum ERTax",
    "eetax & ertax":    "BOTH_TAXES",
    "netamt":           "Sum NetAmt",
}


def _resolve_amount_col(amount_column: str) -> str:
    key = " & ".join(p.strip() for p in amount_column.strip().lower().split("&"))
    return _AMOUNT_COL_MAP.get(key, "")


def _get_account_type(gl_code: str, gl_lookup: dict) -> str:
    """
    Return account type for a GL code.
    1. Uses 'account_type' from gl_lookup (set explicitly in mapping config).
    2. Falls back to first digit of GL code for backwards compatibility.
    """
    meta = gl_lookup.get(gl_code, {})
    account_type = str(meta.get("account_type", "")).strip().lower()
    if account_type in ("expense", "liability", "bank", "glonly"):
        return account_type

    # Fallback: derive from GL code digit
    code = str(gl_code).strip().lstrip("0")
    if not code:
        return "expense"
    d = code[0]
    if d == "2":
        return "liability"
    if d == "1":
        return "bank"
    return "expense"


def _build_pr_index(pr_pivot: pd.DataFrame) -> dict:
    idx: dict = defaultdict(list)
    for i, pr_row in pr_pivot.iterrows():
        mapping = str(pr_row.get(_RECON_MAPPING_COL, ""))
        for code in re.findall(r"\b(\d{4,})\b", mapping):
            idx[code].append(i)
    return idx


def _sum_pr_amount(
    matching_pr:     pd.DataFrame,
    gl_code:         str,
    default_col_key: str,
    gl_pr_amount:    dict,
) -> float:
    total = 0.0
    row_overrides = gl_pr_amount.get(gl_code, {})

    for _, pr_row in matching_pr.iterrows():
        pr_mapping = pr_row.get(_RECON_MAPPING_COL, "")
        col_key    = _resolve_amount_col(row_overrides[pr_mapping]) \
                     if pr_mapping in row_overrides else default_col_key

        if col_key == "BOTH_TAXES":
            total += float(pr_row.get("Sum EETax", 0) or 0)
            total += float(pr_row.get("Sum ERTax", 0) or 0)
        elif col_key and col_key in pr_row.index:
            total += float(pr_row.get(col_key, 0) or 0)

    return total


def _make_row(
    recon_step: str, gl_code: str, gl_title: str,
    gl_net: float, pr_amount: float, variance: float,
    status: str, notes: str,
) -> dict:
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
    combined_map: dict = {}
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
        first      = group[0]
        gl_net     = sum(float(r.get(_COL_GL_NET, 0) or 0) for r in group)
        all_pr     = [float(r.get(_COL_PR_AMT, 0) or 0) for r in group]
        pr_display = next((v for v in all_pr if abs(v) > TOLERANCE), 0.0)

        first_code   = combined_code.split("/")[0].strip()
        account_type = _get_account_type(first_code, gl_lookup)

        if account_type == "liability":
            variance = gl_net + (-pr_display)
        else:
            variance = gl_net - pr_display

        status = MATCH_STATUS if abs(variance) < TOLERANCE else VARIANCE_STATUS
        output.append(_make_row(
            str(first.get(_COL_STEP, "")), combined_code,
            str(first.get(_COL_TITLE, "")), gl_net, pr_display,
            round(variance, 2), status, str(first.get(_COL_NOTES, "")),
        ))

    return output


def build_reconciliation(
    gl_pivot:     pd.DataFrame,
    pr_pivot:     pd.DataFrame,
    gl_lookup:    Dict[str, dict],
    pr_net_total: Optional[float] = None,
    gl_pr_amount: Optional[dict]  = None,
    pr_2157_net:  Optional[float] = None,
) -> pd.DataFrame:
    """
    Produce the reconciliation comparison table.

    Parameters
    ----------
    gl_pivot      : Output of gl_processor.process_gl()
    pr_pivot      : Output of payroll_processor.process_payroll()
    gl_lookup     : { gl_code: {gl_title, recon_step, code_type,
                                amount_column, account_type} }
    pr_net_total  : Sum of NetAmt — for bank (GL 1020) cross-check.
    gl_pr_amount  : Per-row amount column override from build_lookups_from_config.
    pr_2157_net   : Accrual-adjusted NetAmt for GL 2157 (from accrual_classifier).
    """
    pr_idx     = _build_pr_index(pr_pivot)
    _gl_pr_amt = gl_pr_amount or {}
    rows       = []

    for _, gl_row in gl_pivot.iterrows():
        row = _process_gl_row(
            gl_row, pr_pivot, pr_idx, gl_lookup, _gl_pr_amt,
            pr_net_total, pr_2157_net,
        )
        rows.append(row)

    rows     = _merge_combined_gl_rows(rows, gl_lookup)
    recon_df = pd.DataFrame(rows)
    if recon_df.empty:
        return recon_df

    recon_df = recon_df.sort_values(_COL_STEP).reset_index(drop=True)

    total_row = _make_row(
        "TOTAL", "", "",
        recon_df[_COL_GL_NET].sum(),
        recon_df[_COL_PR_AMT].sum(),
        recon_df[_COL_VAR].sum(),
        MATCH_STATUS if abs(recon_df[_COL_VAR].sum()) < TOLERANCE else VARIANCE_STATUS,
        "Grand total",
    )
    return pd.concat([recon_df, pd.DataFrame([total_row])], ignore_index=True)


def _process_gl_row(
    gl_row: pd.Series, pr_pivot: pd.DataFrame, pr_idx: dict,
    gl_lookup: dict, gl_pr_amount: dict,
    pr_net_total: Optional[float], pr_2157_net: Optional[float],
) -> dict:
    gl_code      = str(gl_row[_COL_CODE]).strip()
    gl_title     = str(gl_row[_COL_TITLE]).strip()
    recon_step   = str(gl_row[_RECON_MAPPING_COL]).strip()
    gl_net       = float(gl_row["Sum of Net Amount"])

    meta         = gl_lookup.get(gl_code, {})
    amount_col   = meta.get("amount_column", "")
    account_type = _get_account_type(gl_code, gl_lookup)
    pr_col_key   = _resolve_amount_col(amount_col)

    # GLOnly — informational
    if account_type == "glonly" or amount_col.strip().lower() == "glonly":
        return _make_row(recon_step, gl_code, gl_title, gl_net, 0.0, 0.0,
                         GL_ONLY_STATUS, "Informational — no PR counterpart")

    # Bank cross-check (account_type = bank, amount_column = NetAmt)
    if pr_col_key == "Sum NetAmt" and account_type == "bank":
        return _handle_bank_row(recon_step, gl_code, gl_title, gl_net, pr_net_total)

    # GL 2157 — Accrued Payroll Liability (liability, amount_column = NetAmt)
    if pr_col_key == "Sum NetAmt" and account_type == "liability":
        net = pr_2157_net if pr_2157_net is not None else (pr_net_total or 0.0)
        return _handle_accrual_2157_row(recon_step, gl_code, gl_title, gl_net, net)

    # Standard reconciliation
    pr_indices  = pr_idx.get(gl_code, [])
    matching_pr = pr_pivot.loc[pr_indices] if pr_indices else pr_pivot.iloc[0:0]

    if matching_pr.empty:
        return _make_row(recon_step, gl_code, gl_title, gl_net, 0.0, gl_net,
                         "⚠ No PR Match", "GL code not found in any PR mapping")

    pr_amount = _sum_pr_amount(matching_pr, gl_code, pr_col_key, gl_pr_amount)
    return _handle_standard_row(recon_step, gl_code, gl_title, gl_net, pr_amount, account_type)


def _handle_bank_row(recon_step, gl_code, gl_title, gl_net, pr_net_total):
    net_total = pr_net_total or 0.0
    variance  = gl_net + net_total
    status    = MATCH_STATUS if abs(variance) < TOLERANCE else VARIANCE_STATUS
    return _make_row(recon_step, gl_code, gl_title, gl_net, -net_total,
                     variance, status, "Bank / Net Pay cross-check")


def _handle_accrual_2157_row(recon_step, gl_code, gl_title, gl_net, pr_2157_net):
    """
    GL 2157 Accrued Payroll Liability.

    GL 2157 is credit-normal (negative at year-end = accrued liability).
    PR side = accrual-adjusted NetAmt (Cases 2–5 from accrual_classifier).
    Variance = GL Net + PR 2157 Net  (standard liability sign convention).
    """
    pr_display = -pr_2157_net
    variance   = gl_net + pr_2157_net
    status     = MATCH_STATUS if abs(variance) < TOLERANCE else VARIANCE_STATUS
    return _make_row(
        recon_step, gl_code, gl_title, gl_net, pr_display,
        variance, status,
        "Accrued Payroll Liability — accrual-adjusted Net Pay",
    )


def _handle_standard_row(recon_step, gl_code, gl_title, gl_net, pr_amount, account_type):
    if account_type == "liability":
        variance   = gl_net + pr_amount
        pr_display = -pr_amount
        notes      = "Liability (credit normal)"
    else:
        variance   = gl_net - pr_amount
        pr_display = pr_amount
        notes      = ""
    status = MATCH_STATUS if abs(variance) < TOLERANCE else VARIANCE_STATUS
    return _make_row(recon_step, gl_code, gl_title, gl_net, pr_display,
                     variance, status, notes)


def get_summary_stats(recon_df: pd.DataFrame) -> dict:
    if recon_df.empty:
        return {}
    data       = recon_df[recon_df[_COL_STEP] != "TOTAL"]
    gl_only    = data[data[_COL_STATUS] == GL_ONLY_STATUS]
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
