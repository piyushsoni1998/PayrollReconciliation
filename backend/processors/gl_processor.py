"""
gl_processor.py
────────────────
Processes the General Ledger (GL) report:

  1. Filters for payroll transactions by auto-detecting which TransSource
     values correspond to GL codes in the mapping config. Falls back to
     using all rows if TransSource is not mapped or no match is found.
  2. Adds a "Reconciliation Mapping" column (= the STEPS of Reconciliation
     for the row's GL code, looked up from gl_lookup).
  3. Builds the GL Pivot:
       Reconciliation Mapping | GL Code | GL Title | Sum of Net Amount
"""

import logging
from typing import Dict, Optional

import pandas as pd

from backend.utils.date_utils import parse_dates_smart, get_sample_values

logger = logging.getLogger(__name__)

RECON_MAPPING_COL = "Reconciliation Mapping"
UNMAPPED_LABEL    = "UNMAPPED"


def process_gl(
    df: pd.DataFrame,
    col_map: Dict[str, str],
    gl_lookup: Dict[str, dict],
    period_start: Optional[str] = None,   # "YYYY-MM"
    period_end:   Optional[str] = None,   # "YYYY-MM"
) -> tuple:
    """
    Parameters
    ----------
    df       : Raw GL DataFrame (all rows).
    col_map  : { semantic_role → actual_column_name }.
    gl_lookup: Built by mapping_parser.build_lookups().

    Returns
    -------
    gl_mapped      : Full GL DataFrame (payroll rows only) with Reconciliation Mapping column.
    gl_pivot       : Aggregated pivot table.
    unmapped_codes : Set of GL codes not found in gl_lookup.
    filter_info    : Dict describing what the date filter did:
                     {date_col, applied, skipped, reason, rows_before, rows_after, sample_dates}
    """
    # ── resolve column names ───────────────────────────────────────────────
    trans_source_col = col_map.get("trans_source")   # optional
    gl_code_col      = col_map.get("gl_code")
    gl_title_col     = col_map.get("gl_title")
    net_amount_col   = col_map.get("net_amount")

    missing = [r for r, c in {
        "gl_code":    gl_code_col,
        "gl_title":   gl_title_col,
        "net_amount": net_amount_col,
    }.items() if c is None]

    if missing:
        raise ValueError(f"GL processing failed — roles not mapped: {missing}")

    work = df.copy()

    # ── filter for payroll transactions (dynamic — no hardcoded source value) ──
    #
    # Logic: A payroll batch entry touches ALL payroll GL accounts simultaneously
    # (salary expense, tax liabilities, benefit liabilities, bank, etc.).
    # Non-payroll transactions (GJE adjustments, AP payments, etc.) touch only
    # one or two accounts at a time.
    #
    # → Identify the TransSource value(s) that cover the MAXIMUM number of
    #   distinct GL codes from the mapping config.  That is the payroll source.
    #
    # If TransSource is not mapped (or the column doesn't exist), skip the
    # filter entirely — the file is assumed to be pre-filtered.
    if trans_source_col and trans_source_col in work.columns:
        work[trans_source_col] = work[trans_source_col].astype(str).str.strip().str.upper()

        # Normalise GL codes for matching (strip spaces + decimal suffixes)
        raw_gl = work[gl_code_col].astype(str).str.strip().str.split(".").str[0]
        known_gl_codes = set(gl_lookup.keys())

        # Rows whose GL code is in our mapping config
        config_mask = raw_gl.isin(known_gl_codes)
        config_rows = work[config_mask].copy()
        config_rows["_norm_gl"] = raw_gl[config_mask].values

        if not config_rows.empty:
            # For each TransSource, count:
            #   (a) distinct config GL codes covered  — payroll hits ALL accounts
            #   (b) total row count                   — payroll has many rows per GL code
            #                                           journal entries have 1 row per GL code
            gl_coverage = (
                config_rows.groupby(trans_source_col)["_norm_gl"]
                .nunique()
            )
            row_counts = config_rows.groupby(trans_source_col).size()
            max_coverage = int(gl_coverage.max())

            # Primary: sources with the highest GL code coverage
            top_by_coverage = gl_coverage[gl_coverage == max_coverage]

            if len(top_by_coverage) == 1:
                # Clear winner — use it
                payroll_sources = set(top_by_coverage.index)
            else:
                # Tie on GL code coverage → break by total row count.
                # A payroll batch has hundreds of rows; a GJE has one row per GL code.
                # Pick ONLY the single source with the most rows.
                best = row_counts[top_by_coverage.index].idxmax()
                payroll_sources = {best}
                logger.info(
                    "TransSource tie on GL code coverage (%d codes) — "
                    "selecting '%s' by row count (%d rows) from candidates %s",
                    max_coverage, best, int(row_counts[best]),
                    sorted(top_by_coverage.index.tolist()),
                )

            payroll_sources.discard("")
            payroll_sources.discard("NAN")

            if payroll_sources:
                logger.info(
                    "Auto-detected payroll TransSource: %s "
                    "(covers %d / %d config GL codes, %d rows)",
                    sorted(payroll_sources), max_coverage, len(known_gl_codes),
                    int(row_counts[list(payroll_sources)].sum()),
                )
                gl_mapped = work[work[trans_source_col].isin(payroll_sources)].copy()
            else:
                logger.warning(
                    "TransSource detection returned no valid sources for '%s'. "
                    "Processing all GL rows.",
                    trans_source_col,
                )
                gl_mapped = work.copy()
        else:
            # No config GL codes present in file at all — fall back to all rows
            logger.warning(
                "No config GL codes found in column '%s'. "
                "Processing all GL rows without source filter.",
                gl_code_col,
            )
            gl_mapped = work.copy()
    else:
        # TransSource not mapped — file is assumed pre-filtered to payroll only
        gl_mapped = work.copy()

    # ── period filter (month-year range) ───────────────────────────────────
    _date_fallbacks = ["date", "doc_date", "pay_date", "period_end_date", "period_start_date"]
    date_col = next(
        (col_map.get(r) for r in _date_fallbacks if col_map.get(r) and col_map.get(r) in gl_mapped.columns),
        None,
    )

    filter_info: dict = {
        "date_col":    date_col or "",
        "applied":     False,
        "skipped":     False,
        "reason":      "no_filter_requested",
        "rows_before": len(gl_mapped),
        "rows_after":  len(gl_mapped),
        "sample_dates": [],
    }

    if (period_start or period_end) and date_col:
        filter_info["sample_dates"] = get_sample_values(gl_mapped[date_col])
        try:
            parsed = parse_dates_smart(gl_mapped[date_col], col_name=date_col)
            mask = pd.Series(True, index=gl_mapped.index)
            if period_start:
                start_dt = pd.Timestamp(period_start + "-01")
                mask &= parsed >= start_dt
            if period_end:
                end_dt = pd.Timestamp(period_end + "-01") + pd.offsets.MonthEnd(1)
                mask &= parsed <= end_dt

            before    = len(gl_mapped)
            filtered  = gl_mapped[mask].copy()

            # Safety valve: if filter wipes all rows, skip it and warn
            if len(filtered) == 0 and before > 0:
                logger.warning(
                    "GL period filter [%s → %s] on column '%s' produced 0 rows from %d. "
                    "Dates in this column may not match the selected period or could not be parsed. "
                    "Filter skipped — using all %d GL rows. Sample values: %s",
                    period_start or "start", period_end or "end", date_col, before, before,
                    filter_info["sample_dates"],
                )
                filter_info["skipped"] = True
                filter_info["reason"]  = "parse_produced_zero_rows"
            else:
                gl_mapped = filtered
                filter_info["applied"]    = True
                filter_info["rows_after"] = len(gl_mapped)
                logger.warning(
                    "GL period filter [%s → %s] on column '%s': %d → %d rows.",
                    period_start or "start", period_end or "end", date_col, before, len(gl_mapped),
                )
        except Exception as exc:
            logger.warning("GL period filter failed on column '%s': %s", date_col, exc)
            filter_info["skipped"] = True
            filter_info["reason"]  = f"exception: {exc}"
    elif (period_start or period_end) and not date_col:
        logger.warning(
            "GL period filter requested but no date column found in mapping "
            "(checked roles: %s). Filter skipped.",
            _date_fallbacks,
        )
        filter_info["skipped"] = True
        filter_info["reason"]  = "no_date_column_mapped"

    # ── clean GL code ──────────────────────────────────────────────────────
    gl_mapped[gl_code_col] = (
        gl_mapped[gl_code_col]
        .astype(str)
        .str.strip()
        .str.split(".").str[0]   # remove decimal part if present (e.g. "5000.0")
    )

    # ── assign Reconciliation Mapping ──────────────────────────────────────
    unmapped_codes: set = set()

    def _get_recon_step(gl_code: str) -> str:
        entry = gl_lookup.get(gl_code)
        if entry:
            return entry.get("recon_step") or entry.get("recon_steps") or UNMAPPED_LABEL
        unmapped_codes.add(gl_code)
        return UNMAPPED_LABEL

    gl_mapped[RECON_MAPPING_COL] = gl_mapped[gl_code_col].apply(_get_recon_step)

    # ── ensure net_amount is numeric ───────────────────────────────────────
    gl_mapped[net_amount_col] = pd.to_numeric(
        gl_mapped[net_amount_col].astype(str).str.replace(",", ""),
        errors="coerce",
    ).fillna(0)

    # ── GL Pivot ───────────────────────────────────────────────────────────
    gl_pivot = (
        gl_mapped
        .groupby(
            [RECON_MAPPING_COL, gl_code_col, gl_title_col],
            dropna=False,
        )[net_amount_col]
        .sum()
        .reset_index()
    )
    gl_pivot.columns = [
        "Reconciliation Mapping",
        "GL Code",
        "GL Title",
        "Sum of Net Amount",
    ]
    gl_pivot.sort_values("Reconciliation Mapping", inplace=True)
    gl_pivot.reset_index(drop=True, inplace=True)

    if unmapped_codes:
        logger.warning(
            "GL codes not found in reconciliation mapping: %s",
            sorted(unmapped_codes),
        )

    return gl_mapped, gl_pivot, unmapped_codes, filter_info
