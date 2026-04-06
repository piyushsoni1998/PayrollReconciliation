"""
column_mapping_ui.py
─────────────────────
Streamlit component: column mapping review & confirmation.

After the backend identifies columns (fuzzy + Bedrock), this component
presents the mapping to the user in a colour-coded table and lets them
correct any errors before processing begins.

Green  = auto-matched (fuzzy ≥ threshold)
Yellow = LLM-matched (below fuzzy threshold)
Red    = unmatched (user MUST assign manually)
"""

from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from config.settings import FILE_TYPE_ROLES


def show_column_mapping(
    df: pd.DataFrame,
    file_type: str,
    auto_mapping: Dict[str, Optional[str]],
    confidence: Dict[str, float],
    still_unmatched: List[str],
    fuzzy_threshold: float = 85.0,
    key_prefix: str = "",
) -> Tuple[Dict[str, str], bool]:
    """
    Render the column mapping review UI.

    Parameters
    ----------
    df              : The uploaded DataFrame (for column names).
    file_type       : One of the known file types.
    auto_mapping    : { col_name → role | None } from the identifier.
    confidence      : { col_name → score 0-100 }.
    still_unmatched : Columns that could not be identified at all.
    fuzzy_threshold : Score above which a match is shown in green.
    key_prefix      : Unique prefix to avoid widget key collisions.

    Returns
    -------
    confirmed_mapping : { col_name → role }  (user-edited)
    is_valid          : True if all required roles are covered.
    """
    expected_roles = FILE_TYPE_ROLES.get(file_type, [])
    role_options   = ["(ignore)"] + expected_roles

    st.markdown("#### Column Mapping")
    st.caption(
        "Review and correct the detected column roles below. "
        "🟢 Auto-matched  🟡 AI-matched  🔴 Unmatched (manual required)"
    )

    confirmed: Dict[str, str] = {}

    col_header, role_header, conf_header = st.columns([3, 3, 1])
    col_header.markdown("**File Column**")
    role_header.markdown("**Detected Role**")
    conf_header.markdown("**Confidence**")

    st.divider()

    for col in df.columns:
        detected_role = auto_mapping.get(col)
        score         = confidence.get(col, 0.0)

        # Colour indicator
        if col in still_unmatched or detected_role is None:
            indicator = "🔴"
        elif score >= fuzzy_threshold:
            indicator = "🟢"
        else:
            indicator = "🟡"

        c1, c2, c3 = st.columns([3, 3, 1])

        c1.markdown(f"{indicator} `{col}`")

        # Default selectbox index
        try:
            default_idx = role_options.index(detected_role) if detected_role else 0
        except ValueError:
            default_idx = 0

        selected = c2.selectbox(
            label     = f"role_{col}",
            options   = role_options,
            index     = default_idx,
            key       = f"{key_prefix}_role_{col}",
            label_visibility = "collapsed",
        )

        conf_display = f"{score:.0f}%" if score > 0 else "—"
        c3.markdown(f"<small>{conf_display}</small>", unsafe_allow_html=True)

        if selected != "(ignore)":
            confirmed[col] = selected

    # ── validation ────────────────────────────────────────────────────────
    assigned_roles = set(confirmed.values())

    # Check required roles are present
    # For each file type we define which roles are mandatory
    _required = {
        "payroll_register":         {"code_type", "pay_code", "earn_amount", "benefit_amount", "deduction_amount", "ee_tax", "er_tax"},
        "gl_report":                {"gl_code", "gl_title", "trans_source", "net_amount"},
        "process_of_reconciliation":{"recon_steps", "gl_code", "gl_title", "pay_code", "code_type"},
    }
    required_roles = _required.get(file_type, set())
    missing        = required_roles - assigned_roles

    is_valid = len(missing) == 0

    if missing:
        st.warning(
            f"⚠️  These required roles are not assigned yet: "
            f"**{', '.join(sorted(missing))}**"
        )
    else:
        st.success("✅  All required columns are mapped.")

    return confirmed, is_valid
