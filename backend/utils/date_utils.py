"""
date_utils.py
─────────────
Robust date parsing that works across different export formats.

Problem
-------
Different payroll/GL systems export dates in different formats:
  - US format    : 12/31/2024  (MM/DD/YYYY)
  - European     : 31/12/2024  (DD/MM/YYYY)
  - ISO          : 2024-12-31
  - With time    : 2024-12-31 00:00:00
  - Month-year   : Dec-2024  /  2024-12
  - Short year   : 12/31/24
  - Abbrev month : 31-Dec-2024
  - Compact      : 20241231
  - Fiscal period: FY25-01   /  Period 12

pandas pd.to_datetime(format="mixed") handles ISO / US well but silently
returns NaT for European or fiscal formats, causing the period filter to
drop ALL rows.

Solution
--------
Try multiple strategies in order of preference, pick the one that
successfully parses the most values.
"""

import logging
import re

import pandas as pd

logger = logging.getLogger(__name__)


def parse_dates_smart(series: pd.Series, col_name: str = "") -> pd.Series:
    """
    Parse a string date series using multiple fallback strategies.

    Returns the parsed Series (datetime64) with the fewest NaT values.
    Logs a warning (with sample raw values) if the best strategy still
    leaves >50% unparsed so the caller can diagnose the format.
    """
    if series.empty:
        return pd.Series(dtype="datetime64[ns]")

    # Work on a clean copy (strip whitespace, ignore blanks)
    s = series.astype(str).str.strip().replace({"nan": pd.NA, "": pd.NA, "None": pd.NA})

    strategies = [
        # 1. Mixed format, month-first  (US: MM/DD/YYYY, ISO, etc.)
        ("mixed-mf",     lambda x: pd.to_datetime(x, format="mixed", dayfirst=False, errors="coerce")),
        # 2. Mixed format, day-first    (European: DD/MM/YYYY)
        ("mixed-df",     lambda x: pd.to_datetime(x, format="mixed", dayfirst=True,  errors="coerce")),
        # 3. YYYY-MM  (fiscal period stored as year-month string)
        ("yyyy-mm",      lambda x: pd.to_datetime(x + "-01", format="%Y-%m-%d",      errors="coerce")),
        # 4. MM-YYYY
        ("mm-yyyy",      lambda x: pd.to_datetime("01-" + x, format="%d-%m-%Y",      errors="coerce")),
        # 5. Short year US: M/D/YY or MM/DD/YY
        ("mm/dd/yy",     lambda x: pd.to_datetime(x, format="%m/%d/%y",              errors="coerce")),
        # 6. Short year day-first: D/M/YY
        ("dd/mm/yy",     lambda x: pd.to_datetime(x, format="%d/%m/%y",              errors="coerce")),
        # 7. DD-Mon-YYYY  (15-Jan-2024)
        ("dd-mon-yyyy",  lambda x: pd.to_datetime(x, format="%d-%b-%Y",              errors="coerce")),
        # 8. DD-Mon-YY   (15-Jan-24)
        ("dd-mon-yy",    lambda x: pd.to_datetime(x, format="%d-%b-%y",              errors="coerce")),
        # 9. Mon-DD-YYYY  (Jan-15-2024)
        ("mon-dd-yyyy",  lambda x: pd.to_datetime(x, format="%b-%d-%Y",              errors="coerce")),
        # 10. YYYYMMDD compact (20241231)
        ("yyyymmdd",     lambda x: pd.to_datetime(x, format="%Y%m%d",               errors="coerce")),
        # 11. Regex: extract first YYYY-MM-DD from messy strings
        ("regex-iso",    lambda x: _regex_extract(x, r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d")),
        # 12. Regex: extract MM/DD/YYYY
        ("regex-us",     lambda x: _regex_extract(x, r"(\d{1,2}/\d{1,2}/\d{4})",    "%m/%d/%Y")),
        # 13. Regex: extract DD/MM/YYYY (try if regex-us parsed <50%)
        ("regex-eu",     lambda x: _regex_extract(x, r"(\d{1,2}/\d{1,2}/\d{4})",    "%d/%m/%Y")),
    ]

    best_parsed   = pd.Series([pd.NaT] * len(s), index=s.index, dtype="datetime64[ns]")
    best_count    = 0
    best_strategy = "none"

    non_null_total = s.notna().sum()
    if non_null_total == 0:
        return best_parsed

    for name, fn in strategies:
        try:
            parsed = fn(s)
            valid  = int(parsed.notna().sum())
            if valid > best_count:
                best_count    = valid
                best_parsed   = parsed
                best_strategy = name
            if valid >= non_null_total * 0.9:   # 90%+ success — good enough
                break
        except Exception:
            continue

    ratio = best_count / non_null_total if non_null_total else 0

    # Always log sample raw values so failures are diagnosable in server logs
    sample_vals = list(s.dropna().head(5))

    if ratio < 0.5:
        logger.warning(
            "Date column '%s': best strategy '%s' only parsed %.0f%% of %d values. "
            "Period filter results will be incomplete or skipped. "
            "Sample raw values: %s",
            col_name, best_strategy, ratio * 100, non_null_total, sample_vals,
        )
    else:
        logger.info(
            "Date column '%s': parsed %.0f%% of %d values using strategy '%s'. "
            "Sample raw values: %s",
            col_name, ratio * 100, non_null_total, best_strategy, sample_vals,
        )

    return best_parsed


def get_sample_values(series: pd.Series, n: int = 5) -> list:
    """Return up to n non-null sample values from the series as strings."""
    s = series.astype(str).str.strip().replace({"nan": pd.NA, "": pd.NA, "None": pd.NA})
    return list(s.dropna().head(n))


def _regex_extract(series: pd.Series, pattern: str, fmt: str) -> pd.Series:
    """Extract the first match of `pattern` from each string, then parse as `fmt`."""
    extracted = series.str.extract(pattern, expand=False)
    return pd.to_datetime(extracted, format=fmt, errors="coerce")
