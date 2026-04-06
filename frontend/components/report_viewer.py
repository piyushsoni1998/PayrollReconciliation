"""
report_viewer.py
─────────────────
Streamlit component: renders the four report tabs after processing.

Tabs:
  1. Reconciliation    — the comparison table (GL vs PR + variance)
  2. GL Pivot          — aggregated GL
  3. PR Pivot          — aggregated Payroll Register
  4. Unmapped Items    — rows that could not be mapped (need attention)
"""

from typing import Optional, Set, Tuple

import pandas as pd
import streamlit as st
from pandas.io.formats.style import Styler


# ── Colour helpers ─────────────────────────────────────────────────────────────

def _style_recon(df: pd.DataFrame) -> Styler:
    """Apply green/red row highlighting to the Reconciliation table."""

    def _row_style(row):
        status = str(row.get("Status", ""))
        if "Match" in status:
            return ["background-color: #C6EFCE; color: #276221"] * len(row)
        if "Variance" in status or "No PR" in status:
            return ["background-color: #FFC7CE; color: #9C0006"] * len(row)
        if str(row.get("Reconciliation Step", "")).strip().upper() == "TOTAL":
            return ["background-color: #D9D9D9; font-weight: bold"] * len(row)
        return [""] * len(row)

    currency_cols = [c for c in df.columns if any(
        frag in c.lower()
        for frag in ["amount", "amt", "variance", "net"]
    )]

    styler = df.style.apply(_row_style, axis=1)
    if currency_cols:
        styler = styler.format(
            {c: "{:,.2f}" for c in currency_cols},
            na_rep="—",
        )
    return styler


def _style_pivot(df: pd.DataFrame) -> Styler:
    """Light formatting for pivot tables."""
    currency_cols = [c for c in df.columns if any(
        frag in c.lower()
        for frag in ["amount", "amt", "earn", "bene", "deduc", "tax", "net", "variance"]
    )]
    styler = df.style
    if currency_cols:
        styler = styler.format(
            {c: "{:,.2f}" for c in currency_cols},
            na_rep="—",
        )
    return styler


# ── public entry-point ─────────────────────────────────────────────────────────

def render_reports(
    recon_df:       pd.DataFrame,
    gl_pivot:       pd.DataFrame,
    pr_pivot:       pd.DataFrame,
    gl_mapped:      pd.DataFrame,
    pr_mapped:      pd.DataFrame,
    summary_stats:  dict,
    unmapped_gl:    Optional[Set] = None,
    unmapped_pr:    Optional[Set] = None,
):
    """
    Render the full results section.

    Parameters
    ----------
    recon_df      : Reconciliation comparison table.
    gl_pivot      : GL pivot table.
    pr_pivot      : Payroll Register pivot table.
    gl_mapped     : Full GL data with Reconciliation Mapping column.
    pr_mapped     : Full PR data with Reconciliation Mapping column.
    summary_stats : Dict from reconciliation_processor.get_summary_stats().
    unmapped_gl   : Set of GL codes not found in mapping.
    unmapped_pr   : Set of (pay_code, code_type) tuples not found in mapping.
    """
    # ── Summary banner ────────────────────────────────────────────────────
    _render_summary(summary_stats)

    st.divider()

    # ── Tabs ──────────────────────────────────────────────────────────────
    tab_recon, tab_gl_pivot, tab_pr_pivot, tab_detail, tab_unmapped = st.tabs([
        "📊 Reconciliation",
        "📒 GL Pivot",
        "📋 PR Pivot",
        "🔍 Full Detail",
        "⚠️  Unmapped",
    ])

    with tab_recon:
        st.markdown("### Reconciliation — GL vs Payroll Register")
        st.caption(
            "Green rows = amounts match.  "
            "Red rows = variance detected.  "
            "Grey row = grand total."
        )
        if not recon_df.empty:
            st.dataframe(
                _style_recon(recon_df),
                use_container_width=True,
                height=500,
            )
        else:
            st.info("No reconciliation data to display.")

    with tab_gl_pivot:
        st.markdown("### GL Pivot — Net Amount by Reconciliation Step")
        if not gl_pivot.empty:
            st.dataframe(
                _style_pivot(gl_pivot),
                use_container_width=True,
                height=500,
            )
            _show_totals("GL Net Total", gl_pivot, "Sum of Net Amount")
        else:
            st.info("No GL pivot data.")

    with tab_pr_pivot:
        st.markdown("### Payroll Register Pivot")
        if not pr_pivot.empty:
            st.dataframe(
                _style_pivot(pr_pivot),
                use_container_width=True,
                height=500,
            )
            _show_pr_totals(pr_pivot)
        else:
            st.info("No Payroll Register pivot data.")

    with tab_detail:
        st.markdown("### Full GL Data (PRS filtered + Reconciliation Mapping)")
        st.dataframe(gl_mapped, use_container_width=True, height=350)

        st.markdown("### Full Payroll Register (+ Reconciliation Mapping)")
        st.dataframe(pr_mapped, use_container_width=True, height=350)

    with tab_unmapped:
        _render_unmapped(unmapped_gl, unmapped_pr)


# ── private helpers ────────────────────────────────────────────────────────────

def _render_summary(stats: dict):
    if not stats:
        return

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Total Lines",    stats.get("total_lines", 0))
    c2.metric("Matched ✓",      stats.get("matched", 0))
    c3.metric("Variances ⚠️",   stats.get("variances", 0))

    total_var = stats.get("total_variance", 0.0)
    c4.metric(
        "Total Variance",
        f"${total_var:,.2f}",
        delta         = "Clean ✓" if stats.get("is_clean") else f"${total_var:,.2f}",
        delta_color   = "normal" if stats.get("is_clean") else "inverse",
    )


def _show_totals(label: str, df: pd.DataFrame, col: str):
    if col in df.columns:
        total = df[col].sum()
        st.markdown(f"**{label}: `${total:,.2f}`**")


def _show_pr_totals(pr_pivot: pd.DataFrame):
    cols = ["Sum EarnAmt", "Sum BeneAmt", "Sum DeducAmt", "Sum EETax", "Sum ERTax"]
    totals = {c: pr_pivot[c].sum() for c in cols if c in pr_pivot.columns}
    if totals:
        st.markdown("**Payroll Register Totals:**")
        cols_disp = st.columns(len(totals))
        for i, (col, val) in enumerate(totals.items()):
            cols_disp[i].metric(col.replace("Sum ", ""), f"${val:,.2f}")


def _render_unmapped(
    unmapped_gl: Optional[Set],
    unmapped_pr: Optional[Set],
):
    st.markdown("### Unmapped Items")
    st.caption(
        "These items appear in your files but were not found in the "
        "Process of Reconciliation mapping. Review and update the mapping file."
    )

    has_issues = False

    if unmapped_gl:
        has_issues = True
        st.error(f"**{len(unmapped_gl)} GL code(s) not in mapping:**")
        st.dataframe(
            pd.DataFrame(sorted(unmapped_gl), columns=["GL Code"]),
            use_container_width=True,
        )

    if unmapped_pr:
        has_issues = True
        st.error(f"**{len(unmapped_pr)} Payroll Register (PayCode, CodeType) pair(s) not in mapping:**")
        st.dataframe(
            pd.DataFrame(sorted(unmapped_pr), columns=["Pay Code", "Code Type"]),
            use_container_width=True,
        )

    if not has_issues:
        st.success("✅  No unmapped items — all rows were reconciled.")
