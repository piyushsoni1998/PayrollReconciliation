"""
accrual_classifier.py
──────────────────────
Classifies each Payroll Register row into one of 5 fiscal-year cases
and computes the correct proration factor for accrual accounting.

Case definitions (CY = Current Fiscal Year):
───────────────────────────────────────────────────────────────────────────────
Case 1  Normal payroll (fully in CY)
        PayDate ∈ CY, Period Start ∈ CY, Period End ∈ CY
        → Include 100%.  No accrual adjustment.

Case 2  Prior-Year payroll paid in CY
        PayDate ∈ CY, Period Start ∈ PY, Period End ∈ PY
        → Exclude from CY earnings/benefits/deductions/taxes reconciliation.
          NetAmt clears the PY accrual already sitting in GL 2157.

Case 3  CY payroll paid in Next Year
        PayDate ∈ NY, Period Start ∈ CY, Period End ∈ CY
        → Include 100% in CY reconciliation.
          NetAmt is the CY accrual that will be booked to GL 2157.

Case 4  Split period — paid in CY (beginning-of-year accrual reversal)
        PayDate ∈ CY, Period Start ∈ PY, Period End ∈ CY
        → Include only the CY-prorated portion (working-day basis).
          CY-prorated NetAmt clears part of the PY accrual in GL 2157.

Case 5  Split period — paid in Next Year (year-end accrual)
        PayDate ∈ NY, Period Start ∈ CY, Period End ∈ NY
        → Include only the CY-prorated portion.
          CY-prorated NetAmt is the year-end accrual booked to GL 2157.

Proration formula (Cases 4 & 5):
    CY Amount = Pay Code Amount × (Working Days in CY ÷ Total Working Days in Pay Run)
    Working days = Mon–Fri (weekends excluded; no holiday calendar required).
───────────────────────────────────────────────────────────────────────────────
"""

import logging
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from backend.utils.date_utils import parse_dates_smart

logger = logging.getLogger(__name__)

# Columns added by this module
COL_CASE       = "_pay_run_case"
COL_CY_FACTOR  = "_cy_factor"
COL_2157_FACTOR= "_2157_factor"

# Amount roles that get prorated
_AMOUNT_ROLES = [
    "earn_amount",
    "benefit_amount",
    "deduction_amount",
    "ee_tax",
    "er_tax",
    "net_amount",
]


def _count_working_days(start: pd.Timestamp, end: pd.Timestamp) -> int:
    """Count Monday–Friday days between start and end dates, inclusive."""
    if pd.isna(start) or pd.isna(end) or end < start:
        return 0
    # np.busday_count counts Mon-Fri days in [start, end)
    # Add 1 day to end to make it inclusive
    return int(np.busday_count(start.date(), (end + pd.Timedelta(days=1)).date()))


def _parse_col(series: pd.Series, col_name: str) -> pd.Series:
    """Parse a date column robustly, returning NaT for unparseable values."""
    try:
        return parse_dates_smart(series, col_name=col_name)
    except Exception:
        return pd.to_datetime(series, errors="coerce")


def _classify_row(
    pay_date: pd.Timestamp,
    bgn:      pd.Timestamp,
    end:      pd.Timestamp,
    fy_start: pd.Timestamp,
    fy_end:   pd.Timestamp,
) -> Tuple[int, float, float]:
    """
    Classify a single pay run and return (case, cy_factor, factor_2157).

    cy_factor    : fraction of the pay run amounts to include in CY reconciliation
    factor_2157  : fraction of NetAmt that affects GL 2157
    """
    no_pay  = pd.isna(pay_date)
    no_bgn  = pd.isna(bgn)
    no_end  = pd.isna(end)

    # If we have no date information at all, treat as Case 1 (include fully)
    if no_pay and no_bgn and no_end:
        return 1, 1.0, 0.0

    # Determine where each date falls
    pay_in_cy = (not no_pay) and (fy_start <= pay_date <= fy_end)
    pay_in_ny = (not no_pay) and (pay_date > fy_end)
    pay_in_py = (not no_pay) and (pay_date < fy_start)

    bgn_in_cy = (not no_bgn) and (fy_start <= bgn <= fy_end)
    bgn_in_py = (not no_bgn) and (bgn < fy_start)

    end_in_cy = (not no_end) and (fy_start <= end <= fy_end)
    end_in_ny = (not no_end) and (end > fy_end)
    end_in_py = (not no_end) and (end < fy_start)

    # ── Case 2: PY payroll paid in CY ────────────────────────────────────────
    # PayDate ∈ CY, entire period in PY
    if pay_in_cy and (bgn_in_py or no_bgn) and (end_in_py or no_end):
        return 2, 0.0, 1.0

    # ── Case 3: CY payroll paid in Next Year ──────────────────────────────────
    # PayDate ∈ NY, entire period in CY
    if pay_in_ny and (bgn_in_cy or no_bgn) and end_in_cy:
        return 3, 1.0, 1.0

    # ── Case 4: Split period — paid in CY (beginning-of-year accrual) ────────
    # PayDate ∈ CY, period straddles PY→CY boundary
    if pay_in_cy and bgn_in_py and end_in_cy:
        total_days = _count_working_days(bgn, end)
        cy_days    = _count_working_days(fy_start, end)
        factor     = round(cy_days / total_days, 6) if total_days > 0 else 0.0
        return 4, factor, factor

    # ── Case 5: Split period — paid in Next Year (year-end accrual) ──────────
    # PayDate ∈ NY, period straddles CY→NY boundary
    if pay_in_ny and bgn_in_cy and end_in_ny:
        total_days = _count_working_days(bgn, end)
        cy_days    = _count_working_days(bgn, fy_end)
        factor     = round(cy_days / total_days, 6) if total_days > 0 else 0.0
        return 5, factor, factor

    # ── Case 1: Normal (fully in CY) ─────────────────────────────────────────
    return 1, 1.0, 0.0


def classify_and_prorate(
    df:        pd.DataFrame,
    col_map:   Dict[str, str],
    fy_start:  pd.Timestamp,
    fy_end:    pd.Timestamp,
) -> pd.DataFrame:
    """
    Classify every row in the Payroll Register and apply CY proration to
    all amount columns.

    Parameters
    ----------
    df        : Raw (or period-filtered) Payroll Register DataFrame.
    col_map   : { semantic_role → actual_column_name }
    fy_start  : First day of the fiscal year (e.g. 2024-01-01).
    fy_end    : Last day of the fiscal year  (e.g. 2024-12-31).

    Returns
    -------
    DataFrame with additional columns:
        _pay_run_case  : int 1–5
        _cy_factor     : float 0.0–1.0 (fraction to include in CY recon)
        _2157_factor   : float 0.0–1.0 (fraction of NetAmt affecting GL 2157)
    Amount columns are multiplied by _cy_factor in place.
    Original amounts are preserved in _orig_{col} columns for audit.
    """
    work = df.copy()

    # ── Parse the three date columns ──────────────────────────────────────────
    _date_roles = {
        "pay_date":         col_map.get("pay_date"),
        "period_start_date":col_map.get("period_start_date"),
        "period_end_date":  col_map.get("period_end_date"),
    }
    # Fallback: use generic "date" role for pay_date if specific not mapped
    if not _date_roles["pay_date"]:
        _date_roles["pay_date"] = col_map.get("date")

    parsed: Dict[str, pd.Series] = {}
    for role, col in _date_roles.items():
        if col and col in work.columns:
            parsed[role] = _parse_col(work[col], col)
        else:
            parsed[role] = pd.Series(pd.NaT, index=work.index)

    pay_dates = parsed["pay_date"]
    bgn_dates = parsed["period_start_date"]
    end_dates  = parsed["period_end_date"]

    # ── Classify each row ─────────────────────────────────────────────────────
    cases       = []
    cy_factors  = []
    factors_2157= []

    for i in work.index:
        case, cy_f, f2157 = _classify_row(
            pay_date = pay_dates.loc[i],
            bgn      = bgn_dates.loc[i],
            end      = end_dates.loc[i],
            fy_start = fy_start,
            fy_end   = fy_end,
        )
        cases.append(case)
        cy_factors.append(cy_f)
        factors_2157.append(f2157)

    work[COL_CASE]        = cases
    work[COL_CY_FACTOR]   = cy_factors
    work[COL_2157_FACTOR] = factors_2157

    # ── Log classification summary ────────────────────────────────────────────
    case_counts = pd.Series(cases).value_counts().sort_index()
    logger.info(
        "Pay run classification (fy %s – %s): %s",
        fy_start.date(), fy_end.date(),
        {f"Case {k}": int(v) for k, v in case_counts.items()},
    )

    # ── Apply CY proration to amount columns ─────────────────────────────────
    for role in _AMOUNT_ROLES:
        col = col_map.get(role)
        if not col or col not in work.columns:
            continue
        # Ensure numeric
        work[col] = pd.to_numeric(
            work[col].astype(str).str.replace(",", ""), errors="coerce"
        ).fillna(0.0)
        # Preserve original for audit
        work[f"_orig_{col}"] = work[col]
        # Apply proration
        work[col] = work[col] * work[COL_CY_FACTOR]

    return work


def build_2157_net_amount(
    classified_df: pd.DataFrame,
    net_amount_col: Optional[str],
) -> float:
    """
    Compute the total NetAmt that should reconcile against GL 2157
    (Accrued Payroll Liability).

    Logic:
      - Case 2: Full original NetAmt (clears PY accrual — debit to 2157)
      - Case 3: Full original NetAmt (creates CY accrual — credit to 2157)
      - Case 4: Prorated original NetAmt (partial PY accrual clear)
      - Case 5: Prorated original NetAmt (partial CY year-end accrual)
      - Case 1: Not involved in 2157 (paid in full during CY)

    The result is the sum of all accrual-related NetAmt values.
    The sign convention (debit/credit) is resolved during reconciliation
    against GL 2157's actual balance.
    """
    if not net_amount_col or net_amount_col not in classified_df.columns:
        return 0.0

    orig_col = f"_orig_{net_amount_col}"
    has_orig = orig_col in classified_df.columns

    accrual_cases = classified_df[COL_CASE].isin([2, 3, 4, 5])

    total = 0.0
    for _, row in classified_df[accrual_cases].iterrows():
        factor = float(row.get(COL_2157_FACTOR, 0.0))
        if has_orig:
            net = float(row.get(orig_col, 0.0) or 0.0)
        else:
            net = float(row.get(net_amount_col, 0.0) or 0.0)
        total += net * factor

    return round(total, 2)


def get_classification_summary(classified_df: pd.DataFrame) -> dict:
    """Return a summary dict of case counts and row counts for diagnostics."""
    if COL_CASE not in classified_df.columns:
        return {}
    counts = classified_df[COL_CASE].value_counts().sort_index()
    return {
        "case_1_normal":         int(counts.get(1, 0)),
        "case_2_py_paid_in_cy":  int(counts.get(2, 0)),
        "case_3_cy_paid_in_ny":  int(counts.get(3, 0)),
        "case_4_split_start":    int(counts.get(4, 0)),
        "case_5_split_end":      int(counts.get(5, 0)),
        "total_rows":            len(classified_df),
        "accrual_rows":          int(counts.get(2, 0) + counts.get(3, 0) +
                                     counts.get(4, 0) + counts.get(5, 0)),
    }
