"""
app.py  —  Payroll Reconciliation Tool
════════════════════════════════════════
Streamlit front-end.  All heavy lifting is delegated to the backend
package — this file is UI-only.

Run with:
    streamlit run frontend/app.py
"""

import sys
import os

# Ensure project root is on the path so backend/config imports work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime

import pandas as pd
import streamlit as st

# ── backend imports ────────────────────────────────────────────────────────────
from backend.column_identifier import (
    identify_columns,
    save_confirmed_mapping,
    delete_cached_mapping,
)
from backend.processors.mapping_parser       import build_lookups
from backend.processors.gl_processor         import process_gl
from backend.processors.payroll_processor    import process_payroll
from backend.processors.reconciliation_processor import (
    build_reconciliation,
    get_summary_stats,
)
from backend.utils.excel_exporter            import export_to_excel

# ── frontend component imports ─────────────────────────────────────────────────
from frontend.components.file_upload         import upload_and_read
from frontend.components.column_mapping_ui   import show_column_mapping
from frontend.components.report_viewer       import render_reports

# ─────────────────────────────────────────────────────────────────────────────
# Page configuration
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title = "Payroll Reconciliation Tool",
    page_icon  = "📊",
    layout     = "wide",
    initial_sidebar_state = "expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — configuration
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Configuration")

    client_name = st.text_input(
        "Client Name",
        value       = "default",
        help        = "Used to cache column mappings per client.",
    )

    period_label = st.text_input(
        "Pay Period (optional)",
        placeholder = "e.g. January 2026",
        help        = "Shown in the exported report title.",
    )

    st.divider()
    st.subheader("Column Identification")

    use_bedrock = st.toggle(
        "Use AWS Bedrock (Claude) for unmatched columns",
        value = True,
        help  = (
            "When enabled, columns that fuzzy matching cannot resolve are "
            "sent to AWS Bedrock Claude for identification. "
            "Requires valid AWS credentials in .env"
        ),
    )

    use_cache = st.toggle(
        "Use cached column mappings",
        value = True,
        help  = "Load saved mappings for this client to skip re-identification.",
    )

    st.divider()

    if st.button("🗑️ Clear cached mappings for this client"):
        st.info(
            f"Cache clearing requires re-uploading files — "
            f"mappings will be re-identified on next upload for '{client_name}'."
        )

    st.divider()
    st.caption("📦 Payroll Reconciliation Tool v1.0")
    st.caption("Data stays local / within your AWS account.")

# ─────────────────────────────────────────────────────────────────────────────
# Session-state initialisation
# ─────────────────────────────────────────────────────────────────────────────
_state_keys = [
    "mapping_df", "mapping_col_map", "mapping_valid",
    "gl_df",      "gl_col_map",      "gl_valid",
    "pr_df",      "pr_col_map",      "pr_valid",
    "results_ready",
    "gl_mapped",  "pr_mapped", "gl_pivot", "pr_pivot",
    "recon_df",   "summary_stats",
    "unmapped_gl","unmapped_pr",
    "excel_bytes",
]
for k in _state_keys:
    if k not in st.session_state:
        st.session_state[k] = None

# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────
st.title("📊 Payroll Reconciliation Tool")
st.markdown(
    "Upload the three files below, confirm column mappings, "
    "then click **Run Reconciliation** to generate reports."
)
st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# Step 1 – Upload & identify: Process of Reconciliation
# ─────────────────────────────────────────────────────────────────────────────
st.header("Step 1 — Process of Reconciliation (Mapping File)")
st.caption(
    "This file defines how GL codes relate to pay codes. "
    "It changes per client — upload the correct version for this period."
)

mapping_df, mapping_fname = upload_and_read(
    label      = "Upload Process of Reconciliation file",
    key        = "upload_mapping",
    help_text  = "Excel or CSV with columns: STEPS of Reconciliation, GL CODE, GL TITLE, Pay Code, Code Type",
)

if mapping_df is not None:
    with st.spinner("Identifying columns…"):
        auto_map, conf, unmatched = identify_columns(
            df          = mapping_df,
            file_type   = "process_of_reconciliation",
            client_name = client_name,
            use_cache   = use_cache,
            use_bedrock = use_bedrock,
        )

    confirmed_map, is_valid = show_column_mapping(
        df              = mapping_df,
        file_type       = "process_of_reconciliation",
        auto_mapping    = auto_map,
        confidence      = conf,
        still_unmatched = unmatched,
        key_prefix      = "mapping",
    )

    if is_valid:
        st.session_state["mapping_df"]      = mapping_df
        st.session_state["mapping_col_map"] = confirmed_map
        st.session_state["mapping_valid"]   = True
        if st.button("💾 Save column mapping for this client (mapping file)", key="save_mapping"):
            save_confirmed_mapping(mapping_df, "process_of_reconciliation", confirmed_map, client_name)
            st.success("Mapping saved!")
    else:
        st.session_state["mapping_valid"] = False

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# Step 2 – Upload & identify: GL Report
# ─────────────────────────────────────────────────────────────────────────────
st.header("Step 2 — General Ledger (GL) Report")
st.caption("Export from MIP Accounting. Must contain PRS transactions.")

gl_df, gl_fname = upload_and_read(
    label      = "Upload GL Report",
    key        = "upload_gl",
    help_text  = "Excel or CSV exported from MIP containing payroll journal entries.",
)

if gl_df is not None:
    with st.spinner("Identifying columns…"):
        auto_map_gl, conf_gl, unmatched_gl = identify_columns(
            df          = gl_df,
            file_type   = "gl_report",
            client_name = client_name,
            use_cache   = use_cache,
            use_bedrock = use_bedrock,
        )

    confirmed_gl, is_valid_gl = show_column_mapping(
        df              = gl_df,
        file_type       = "gl_report",
        auto_mapping    = auto_map_gl,
        confidence      = conf_gl,
        still_unmatched = unmatched_gl,
        key_prefix      = "gl",
    )

    if is_valid_gl:
        st.session_state["gl_df"]      = gl_df
        st.session_state["gl_col_map"] = confirmed_gl
        st.session_state["gl_valid"]   = True
        if st.button("💾 Save column mapping for this client (GL)", key="save_gl"):
            save_confirmed_mapping(gl_df, "gl_report", confirmed_gl, client_name)
            st.success("Mapping saved!")
    else:
        st.session_state["gl_valid"] = False

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# Step 3 – Upload & identify: Payroll Register
# ─────────────────────────────────────────────────────────────────────────────
st.header("Step 3 — Payroll Register")
st.caption("Export from MIP Payroll containing employee-level transactions.")

pr_df, pr_fname = upload_and_read(
    label      = "Upload Payroll Register",
    key        = "upload_pr",
    help_text  = "Excel or CSV with earnings, benefits, deductions, and taxes per employee.",
)

if pr_df is not None:
    with st.spinner("Identifying columns…"):
        auto_map_pr, conf_pr, unmatched_pr = identify_columns(
            df          = pr_df,
            file_type   = "payroll_register",
            client_name = client_name,
            use_cache   = use_cache,
            use_bedrock = use_bedrock,
        )

    confirmed_pr, is_valid_pr = show_column_mapping(
        df              = pr_df,
        file_type       = "payroll_register",
        auto_mapping    = auto_map_pr,
        confidence      = conf_pr,
        still_unmatched = unmatched_pr,
        key_prefix      = "pr",
    )

    if is_valid_pr:
        st.session_state["pr_df"]      = pr_df
        st.session_state["pr_col_map"] = confirmed_pr
        st.session_state["pr_valid"]   = True
        if st.button("💾 Save column mapping for this client (PR)", key="save_pr"):
            save_confirmed_mapping(pr_df, "payroll_register", confirmed_pr, client_name)
            st.success("Mapping saved!")
    else:
        st.session_state["pr_valid"] = False

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# Step 4 – Run Reconciliation
# ─────────────────────────────────────────────────────────────────────────────
st.header("Step 4 — Run Reconciliation")

all_ready = (
    st.session_state.get("mapping_valid") and
    st.session_state.get("gl_valid")      and
    st.session_state.get("pr_valid")
)

if not all_ready:
    st.info(
        "⬆️  Upload and confirm column mappings for all three files above "
        "to enable reconciliation."
    )

if st.button(
    "▶️  Run Reconciliation",
    type     = "primary",
    disabled = not all_ready,
    use_container_width = True,
):
    try:
        with st.spinner("Building mapping lookups…"):
            gl_lookup, pr_lookup = build_lookups(
                df      = st.session_state["mapping_df"],
                col_map = st.session_state["mapping_col_map"],
            )

        with st.spinner("Processing GL report…"):
            gl_mapped, gl_pivot, unmapped_gl_codes = process_gl(
                df        = st.session_state["gl_df"],
                col_map   = st.session_state["gl_col_map"],
                gl_lookup = gl_lookup,
            )

        with st.spinner("Processing Payroll Register…"):
            pr_mapped, pr_pivot, unmapped_pr_keys = process_payroll(
                df        = st.session_state["pr_df"],
                col_map   = st.session_state["pr_col_map"],
                pr_lookup = pr_lookup,
            )

        # Net pay total for bank cross-check
        net_col = st.session_state["pr_col_map"].get("net_amount")
        pr_net_total = None
        if net_col and net_col in pr_mapped.columns:
            pr_net_total = pd.to_numeric(
                pr_mapped[net_col].astype(str).str.replace(",", ""),
                errors="coerce",
            ).fillna(0).sum()

        with st.spinner("Building reconciliation report…"):
            recon_df = build_reconciliation(
                gl_pivot     = gl_pivot,
                pr_pivot     = pr_pivot,
                gl_lookup    = gl_lookup,
                pr_net_total = pr_net_total,
            )
            summary_stats = get_summary_stats(recon_df)

        with st.spinner("Generating Excel export…"):
            excel_bytes = export_to_excel(
                gl_mapped    = gl_mapped,
                pr_mapped    = pr_mapped,
                gl_pivot     = gl_pivot,
                pr_pivot     = pr_pivot,
                recon_df     = recon_df,
                period_label = period_label,
            )

        # Store in session state
        st.session_state["gl_mapped"]     = gl_mapped
        st.session_state["pr_mapped"]     = pr_mapped
        st.session_state["gl_pivot"]      = gl_pivot
        st.session_state["pr_pivot"]      = pr_pivot
        st.session_state["recon_df"]      = recon_df
        st.session_state["summary_stats"] = summary_stats
        st.session_state["unmapped_gl"]   = unmapped_gl_codes
        st.session_state["unmapped_pr"]   = unmapped_pr_keys
        st.session_state["excel_bytes"]   = excel_bytes
        st.session_state["results_ready"] = True

        st.success("✅  Reconciliation complete!")

    except ValueError as e:
        st.error(f"Configuration error: {e}")
    except Exception as e:
        st.error(f"Processing error: {e}")
        st.exception(e)

# ─────────────────────────────────────────────────────────────────────────────
# Step 5 – Results
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.get("results_ready"):
    st.divider()
    st.header("Step 5 — Results")

    # Download button at the top
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M")
    safe_client= client_name.replace(" ", "_")
    fname      = f"Payroll_Recon_{safe_client}_{timestamp}.xlsx"

    st.download_button(
        label            = "⬇️  Download Excel Report",
        data             = st.session_state["excel_bytes"],
        file_name        = fname,
        mime             = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width = True,
        type             = "primary",
    )

    st.divider()

    render_reports(
        recon_df      = st.session_state["recon_df"],
        gl_pivot      = st.session_state["gl_pivot"],
        pr_pivot      = st.session_state["pr_pivot"],
        gl_mapped     = st.session_state["gl_mapped"],
        pr_mapped     = st.session_state["pr_mapped"],
        summary_stats = st.session_state["summary_stats"],
        unmapped_gl   = st.session_state["unmapped_gl"],
        unmapped_pr   = st.session_state["unmapped_pr"],
    )
