"""
file_reader.py
───────────────
Smart file reading with automatic header-row detection.

The Problem
-----------
MIP and accounting software exports rarely have the header in row 0.
Common patterns:
  - Rows 0-2 = report title, company name, date
  - Row 3     = blank
  - Row 4     = ACTUAL column headers   ← we want this
  - Row 5+    = data

The Process of Reconciliation file has a MERGED header row:
  Row 0: "General Ledger (GL)"  | NaN | NaN | "Payroll Register" | NaN
  Row 1: "STEPS of Recon..."    | "GL CODE" | "GL TITLE" | "Pay Code" | "Code Type"  ← want this
  Row 2+: data

Detection Algorithm
-------------------
1. Read the file without any header assumption (header=None, first 20 rows).
2. Score each row as a candidate header based on:
   - % of non-null values (more = better)
   - % of short string values (column names are short)
   - % of values that look like identifiers (CamelCase, snake_case, ALLCAPS, spaces)
   - Bonus if any value partially matches a known alias (low threshold)
3. Pick the highest-scoring row as the header.
4. Re-read the full file with that row as the header.
5. Drop any unnamed / NaN columns (artifacts of merged cells).
"""

import io
import logging
import re
from typing import Optional, Tuple, Union

import pandas as pd

logger = logging.getLogger(__name__)

_MAX_HEADER_SCAN_ROWS = 15   # scan at most this many rows to find the header
_MIN_FILL_RATIO       = 0.3  # a valid header row must have at least 30% non-null


# ── public entry point ─────────────────────────────────────────────────────────

def read_file(
    source: Union[str, bytes, io.BytesIO],
    filename: str,
    sheet_name: Optional[Union[str, int]] = 0,
) -> Tuple[pd.DataFrame, int, list]:
    """
    Intelligently read an Excel or CSV file, auto-detecting the header row.

    Parameters
    ----------
    source      : File path, raw bytes, or BytesIO object.
    filename    : Original filename (used to determine .csv vs .xlsx).
    sheet_name  : Which sheet to read (Excel only); 0 = first sheet.

    Returns
    -------
    df           : Clean DataFrame with correct headers.
    header_row   : The row index (0-based) that was used as the header.
    sheet_names  : List of sheet names (Excel only; empty for CSV).
    """
    if isinstance(source, bytes):
        source = io.BytesIO(source)

    fname_lower = filename.lower()
    is_csv  = fname_lower.endswith(".csv")
    is_tsv  = fname_lower.endswith(".tsv") or fname_lower.endswith(".txt")
    is_ods  = fname_lower.endswith(".ods")
    is_xlsb = fname_lower.endswith(".xlsb")
    is_xls  = fname_lower.endswith(".xls")   # legacy Excel 97-2003 binary format
    is_excel = not is_csv and not is_tsv  # .xlsx, .xls, .xlsm, .xltx, .ods, .xlsb

    # ── get sheet names for Excel / ODS ───────────────────────────────────
    sheet_names: list = []
    if is_excel:
        try:
            engine = "pyxlsb" if is_xlsb else ("odf" if is_ods else ("xlrd" if is_xls else None))
            xl_file     = pd.ExcelFile(source, engine=engine) if engine else pd.ExcelFile(source)
            sheet_names = xl_file.sheet_names
            if isinstance(source, io.BytesIO):
                source.seek(0)
        except Exception:
            pass

    # ── read raw (no header) for scanning ─────────────────────────────────
    raw_df = _read_raw(source, filename, sheet_name, is_csv, is_tsv, is_xlsb, is_ods, is_xls)

    if raw_df is None or raw_df.empty:
        return pd.DataFrame(), 0, sheet_names

    # ── detect best header row ─────────────────────────────────────────────
    header_row = _detect_header_row(raw_df)
    logger.info("Detected header row at index %d for '%s'.", header_row, filename)

    # ── re-read with the correct header ───────────────────────────────────
    if isinstance(source, io.BytesIO):
        source.seek(0)

    df = _read_with_header(source, filename, sheet_name, is_csv, is_tsv, is_xlsb, is_ods, is_xls, header_row)
    df = _clean_columns(df)

    return df, header_row, sheet_names


def get_sheet_names(source: Union[str, bytes, io.BytesIO], filename: str) -> list:
    """Return sheet names from an Excel/ODS file (empty list for CSV/TSV)."""
    fname_lower = filename.lower()
    if fname_lower.endswith((".csv", ".tsv", ".txt")):
        return []
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    try:
        engine = "pyxlsb" if fname_lower.endswith(".xlsb") else ("odf" if fname_lower.endswith(".ods") else ("xlrd" if fname_lower.endswith(".xls") else None))
        xl = pd.ExcelFile(source, engine=engine) if engine else pd.ExcelFile(source)
        return xl.sheet_names
    except Exception:
        return []


# ── private helpers ────────────────────────────────────────────────────────────

def _read_raw(source, filename, sheet_name, is_csv, is_tsv, is_xlsb=False, is_ods=False, is_xls=False) -> Optional[pd.DataFrame]:
    """Read first N rows without any header."""
    try:
        if is_csv:
            return pd.read_csv(
                source, header=None, dtype=str,
                nrows=_MAX_HEADER_SCAN_ROWS, encoding_errors="replace",
                on_bad_lines="skip",
            )
        if is_tsv:
            return pd.read_csv(
                source, header=None, dtype=str, sep="\t",
                nrows=_MAX_HEADER_SCAN_ROWS, encoding_errors="replace",
                on_bad_lines="skip",
            )
        # Excel family + ODS + XLSB
        engine = "pyxlsb" if is_xlsb else ("odf" if is_ods else ("xlrd" if is_xls else None))
        kwargs = {"engine": engine} if engine else {}
        return pd.read_excel(
            source, header=None, dtype=str,
            nrows=_MAX_HEADER_SCAN_ROWS, sheet_name=sheet_name,
            **kwargs,
        )
    except Exception as e:
        logger.error("Raw read failed: %s", e)
        return None


def _read_with_header(source, filename, sheet_name, is_csv, is_tsv, is_xlsb, is_ods, is_xls, header_row) -> pd.DataFrame:
    """Re-read the full file using the detected header row."""
    try:
        if is_csv:
            return pd.read_csv(
                source, header=header_row, dtype=str,
                encoding_errors="replace", on_bad_lines="skip",
            )
        if is_tsv:
            return pd.read_csv(
                source, header=header_row, dtype=str, sep="\t",
                encoding_errors="replace", on_bad_lines="skip",
            )
        engine = "pyxlsb" if is_xlsb else ("odf" if is_ods else ("xlrd" if is_xls else None))
        kwargs = {"engine": engine} if engine else {}
        return pd.read_excel(
            source, header=header_row, dtype=str, sheet_name=sheet_name,
            **kwargs,
        )
    except Exception as e:
        logger.error("Header read failed: %s", e)
        return pd.DataFrame()


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    - Drop columns whose name is NaN / 'Unnamed: N' (artifacts of merged cells).
    - Strip whitespace from column names.
    - Drop completely empty rows.
    - Strip time component from datetime-like string values.
    """
    # Clean column names
    new_cols = []
    seen: dict = {}
    for col in df.columns:
        col_str = str(col).strip()
        # Drop merged-cell artifacts
        if col_str.lower().startswith("unnamed:") or col_str in ("nan", ""):
            col_str = None
        if col_str is not None:
            if col_str in seen:
                seen[col_str] += 1
                col_str = f"{col_str}_{seen[col_str]}"
            else:
                seen[col_str] = 0
        new_cols.append(col_str)

    # Keep only non-None columns
    keep_mask = [c is not None for c in new_cols]
    df        = df.loc[:, keep_mask].copy()
    df.columns = [c for c in new_cols if c is not None]

    # Drop rows that are entirely NaN or empty
    df.dropna(how="all", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Strip time from datetime strings (e.g. "2023-12-31 00:00:00" → "2023-12-31")
    df = _strip_datetime_times(df)

    return df


_DT_WITH_TIME_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}(\.\d+)?$"
)


def _strip_datetime_times(df: pd.DataFrame) -> pd.DataFrame:
    """
    For any string column where most values look like 'YYYY-MM-DD HH:MM:SS',
    strip the time component so only the date part remains.
    """
    for col in df.columns:
        if df[col].dtype != object:
            continue
        sample = df[col].dropna().head(30)
        if sample.empty:
            continue
        match_ratio = sample.str.match(
            r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", na=False
        ).mean()
        if match_ratio > 0.5:
            df[col] = df[col].str.replace(
                r"^(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}(\.\d+)?$",
                r"\1",
                regex=True,
            )
    return df


def _detect_header_row(raw_df: pd.DataFrame) -> int:
    """
    Score each of the first N rows and return the index of the best header row.
    """
    n_cols   = len(raw_df.columns)
    best_row = 0
    best_score = -1.0

    for i in range(min(_MAX_HEADER_SCAN_ROWS, len(raw_df))):
        row    = raw_df.iloc[i]
        values = [str(v).strip() for v in row if pd.notna(v) and str(v).strip() not in ("", "nan")]

        # Must have enough non-null values
        fill_ratio = len(values) / max(n_cols, 1)
        if fill_ratio < _MIN_FILL_RATIO:
            continue

        score = fill_ratio * _header_value_score(values)

        logger.debug("Row %d score=%.3f  values=%s", i, score, values[:5])

        if score > best_score:
            best_score = score
            best_row   = i

    return best_row


def _header_value_score(values: list) -> float:
    """
    Score a list of candidate column-name strings.
    Higher = more likely to be actual column headers.
    """
    if not values:
        return 0.0

    total = 0.0
    for v in values:
        pts = 0.0

        # Short values are more column-name-like
        if len(v) <= 50:
            pts += 2.0
        elif len(v) <= 80:
            pts += 0.5
        else:
            pts -= 1.0   # very long → probably a sentence, not a header

        # Purely numeric values are almost never column headers
        try:
            float(v.replace(",", ""))
            pts -= 2.0
        except ValueError:
            pts += 0.5

        # Date patterns → data, not headers
        if re.match(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", v):
            pts -= 1.5

        # CamelCase / snake_case / ALLCAPS / Title Case → header-like
        if re.search(r"[A-Z][a-z]|[a-z][A-Z]", v):   # CamelCase
            pts += 1.5
        if "_" in v:                                    # snake_case
            pts += 1.0
        if v.isupper() and len(v) > 1:                 # ALLCAPS
            pts += 1.0

        # Common accounting / payroll header keywords → strong signal
        _HEADER_KEYWORDS = [
            "code", "type", "date", "amount", "amt", "name", "id",
            "source", "title", "pay", "gl", "steps", "recon", "tax",
            "earn", "bene", "deduc", "net", "period", "empl",
        ]
        v_lower = v.lower()
        if any(kw in v_lower for kw in _HEADER_KEYWORDS):
            pts += 2.0

        total += pts

    return total / len(values)
