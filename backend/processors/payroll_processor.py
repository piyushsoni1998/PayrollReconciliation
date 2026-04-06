"""
payroll_processor.py
─────────────────────
Processes the Payroll Register:

  1. Adds a "Reconciliation Mapping" column by looking up
     (PayCode, CodeType) in pr_lookup.
     — For dual-entry items (BENEFIT, some TAXES) the mapping string
       contains both GL codes joined by " & ", e.g.
       "5130 - Insurance Benefits & 2146 - Dental Insurance ER"

  2. Builds the Payroll Register Pivot:
       Code Type | Reconciliation Mapping |
       Sum EarnAmt | Sum BeneAmt | Sum DeducAmt | Sum EETax | Sum ERTax
"""

import logging
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

from backend.utils.date_utils import parse_dates_smart, get_sample_values

logger = logging.getLogger(__name__)

RECON_MAPPING_COL = "Reconciliation Mapping"
UNMAPPED_LABEL    = "UNMAPPED"

# Columns to aggregate in the pivot
_AMOUNT_ROLES = [
    "earn_amount",
    "benefit_amount",
    "deduction_amount",
    "ee_tax",
    "er_tax",
]

_PIVOT_COL_LABELS = {
    "earn_amount":      "Sum EarnAmt",
    "benefit_amount":   "Sum BeneAmt",
    "deduction_amount": "Sum DeducAmt",
    "ee_tax":           "Sum EETax",
    "er_tax":           "Sum ERTax",
}


def process_payroll(
    df: pd.DataFrame,
    col_map: Dict[str, str],
    pr_lookup: Dict[Tuple[str, str], str],
    period_start: Optional[str] = None,   # "YYYY-MM"
    period_end:   Optional[str] = None,   # "YYYY-MM"
) -> tuple:
    """
    Parameters
    ----------
    df        : Raw Payroll Register DataFrame.
    col_map   : { semantic_role → actual_column_name }.
    pr_lookup : Built by mapping_parser.build_lookups().

    Returns
    -------
    pr_mapped     : Full PR DataFrame with Reconciliation Mapping column.
    pr_pivot      : Aggregated pivot table.
    unmapped_keys : Set of (pay_code, code_type) tuples not found in pr_lookup.
    filter_info   : Dict describing what the date filter did:
                    {date_col, applied, skipped, reason, rows_before, rows_after, sample_dates}
    """
    code_type_col = col_map.get("code_type")
    pay_code_col  = col_map.get("pay_code")

    if not code_type_col or not pay_code_col:
        raise ValueError(
            "Payroll Register processing failed — 'code_type' and/or "
            "'pay_code' roles not mapped."
        )

    # ── clean key columns ──────────────────────────────────────────────────
    work = df.copy()
    work[code_type_col] = work[code_type_col].astype(str).str.strip().str.upper()
    work[pay_code_col]  = work[pay_code_col].astype(str).str.strip().str.upper()

    # ── period filter (month-year range) ───────────────────────────────────
    _date_fallbacks = ["date", "pay_date", "period_end_date", "period_start_date", "doc_date"]
    date_col = next(
        (col_map.get(r) for r in _date_fallbacks if col_map.get(r) and col_map.get(r) in work.columns),
        None,
    )

    filter_info: dict = {
        "date_col":     date_col or "",
        "applied":      False,
        "skipped":      False,
        "reason":       "no_filter_requested",
        "rows_before":  len(work),
        "rows_after":   len(work),
        "sample_dates": [],
    }

    if (period_start or period_end) and date_col:
        filter_info["sample_dates"] = get_sample_values(work[date_col])
        try:
            parsed = parse_dates_smart(work[date_col], col_name=date_col)
            mask = pd.Series(True, index=work.index)
            if period_start:
                start_dt = pd.Timestamp(period_start + "-01")
                mask &= parsed >= start_dt
            if period_end:
                end_dt = pd.Timestamp(period_end + "-01") + pd.offsets.MonthEnd(1)
                mask &= parsed <= end_dt

            before   = len(work)
            filtered = work[mask].copy()

            # Safety valve: if filter wipes all rows, skip it and warn
            if len(filtered) == 0 and before > 0:
                logger.warning(
                    "PR period filter [%s → %s] on column '%s' produced 0 rows from %d. "
                    "Dates in this column may not match the selected period or could not be parsed. "
                    "Filter skipped — using all %d PR rows. Sample values: %s",
                    period_start or "start", period_end or "end", date_col, before, before,
                    filter_info["sample_dates"],
                )
                filter_info["skipped"] = True
                filter_info["reason"]  = "parse_produced_zero_rows"
            else:
                work = filtered
                filter_info["applied"]    = True
                filter_info["rows_after"] = len(work)
                logger.warning(
                    "PR period filter [%s → %s] on column '%s': %d → %d rows.",
                    period_start or "start", period_end or "end", date_col, before, len(work),
                )
        except Exception as exc:
            logger.warning("PR period filter failed on column '%s': %s", date_col, exc)
            filter_info["skipped"] = True
            filter_info["reason"]  = f"exception: {exc}"
    elif (period_start or period_end) and not date_col:
        logger.warning(
            "PR period filter requested but no date column found in mapping "
            "(checked roles: %s). Filter skipped.",
            _date_fallbacks,
        )
        filter_info["skipped"] = True
        filter_info["reason"]  = "no_date_column_mapped"

    # ── assign Reconciliation Mapping ──────────────────────────────────────
    unmapped_keys: Set[Tuple[str, str]] = set()

    def _get_pr_mapping(row: pd.Series) -> str:
        key = (row[pay_code_col], row[code_type_col])
        mapping = pr_lookup.get(key)
        if mapping:
            return mapping
        unmapped_keys.add(key)
        return UNMAPPED_LABEL

    work[RECON_MAPPING_COL] = work.apply(_get_pr_mapping, axis=1)

    # ── convert amount columns to numeric ──────────────────────────────────
    amount_col_map: Dict[str, str] = {}   # role → actual col name

    for role in _AMOUNT_ROLES:
        actual_col = col_map.get(role)
        if actual_col and actual_col in work.columns:
            work[actual_col] = pd.to_numeric(
                work[actual_col].astype(str).str.replace(",", ""),
                errors="coerce",
            ).fillna(0)
            amount_col_map[role] = actual_col

    # ── Payroll Register Pivot ─────────────────────────────────────────────
    group_cols = [code_type_col, RECON_MAPPING_COL]
    agg_cols   = {actual_col: "sum" for actual_col in amount_col_map.values()}

    if not agg_cols:
        raise ValueError(
            "No amount columns (EarnAmt, BeneAmt, etc.) could be identified "
            "in the Payroll Register."
        )

    pr_pivot = (
        work
        .groupby(group_cols, dropna=False)
        .agg(agg_cols)
        .reset_index()
    )

    # Rename columns to friendly labels
    rename_map: Dict[str, str] = {code_type_col: "Code Type"}
    for role, actual_col in amount_col_map.items():
        rename_map[actual_col] = _PIVOT_COL_LABELS[role]

    pr_pivot.rename(columns=rename_map, inplace=True)

    # Ensure all expected pivot columns exist (fill with 0 if not in file)
    for label in _PIVOT_COL_LABELS.values():
        if label not in pr_pivot.columns:
            pr_pivot[label] = 0.0

    pr_pivot.sort_values(["Code Type", RECON_MAPPING_COL], inplace=True)
    pr_pivot.reset_index(drop=True, inplace=True)

    if unmapped_keys:
        logger.warning(
            "Payroll Register (CodeType, PayCode) pairs not in mapping: %s",
            sorted(unmapped_keys),
        )

    return work, pr_pivot, unmapped_keys, filter_info
