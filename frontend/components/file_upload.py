"""
file_upload.py
───────────────
Streamlit component: file uploader + sheet selector.

Returns a pandas DataFrame or None.
Handles both .xlsx and .csv files.
"""

import pandas as pd
import streamlit as st


def upload_and_read(
    label: str,
    key: str,
    help_text: str = "",
    accepted_types: list = None,
) -> tuple:
    """
    Render a file uploader and return (dataframe, filename).

    Parameters
    ----------
    label          : Display label shown above the uploader.
    key            : Unique Streamlit widget key.
    help_text      : Optional tooltip / caption.
    accepted_types : List of accepted MIME-like extensions.

    Returns
    -------
    (DataFrame | None, filename | None)
    """
    if accepted_types is None:
        accepted_types = ["xlsx", "xls", "csv"]

    uploaded = st.file_uploader(
        label,
        type        = accepted_types,
        key         = key,
        help        = help_text,
    )

    if uploaded is None:
        return None, None

    try:
        df, sheet_name = _read_file(uploaded)
        if df is not None and not df.empty:
            _preview(df, uploaded.name, sheet_name)
        return df, uploaded.name
    except Exception as e:
        st.error(f"Could not read **{uploaded.name}**: {e}")
        return None, None


# ── private ────────────────────────────────────────────────────────────────────


def _read_file(uploaded_file) -> tuple:
    """Read an Excel or CSV file and return (DataFrame, sheet_name_or_None)."""
    name = uploaded_file.name.lower()

    if name.endswith(".csv"):
        df = pd.read_csv(uploaded_file, dtype=str)
        return df, None

    # Excel — let user pick sheet if multiple exist
    xl = pd.ExcelFile(uploaded_file)
    sheets = xl.sheet_names

    if len(sheets) == 1:
        df = pd.read_excel(xl, sheet_name=sheets[0], dtype=str)
        return df, sheets[0]

    # Multiple sheets → user selects
    selected_sheet = st.selectbox(
        f"**{uploaded_file.name}** has multiple sheets — select one:",
        options = sheets,
        key     = f"sheet_select_{uploaded_file.name}",
    )
    df = pd.read_excel(xl, sheet_name=selected_sheet, dtype=str)
    return df, selected_sheet


def _preview(df: pd.DataFrame, filename: str, sheet: str):
    """Render a compact data preview inside an expander."""
    label = f"Preview: **{filename}**"
    if sheet:
        label += f" (sheet: *{sheet}*)"

    with st.expander(label, expanded=False):
        st.caption(f"{len(df):,} rows × {len(df.columns)} columns")
        st.dataframe(df.head(10), use_container_width=True)
