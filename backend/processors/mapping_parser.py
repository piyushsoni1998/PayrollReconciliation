"""
mapping_parser.py
──────────────────
Parses the client-specific "Process of Reconciliation" file and builds
two lookup dictionaries used by the GL and Payroll Register processors.

Input columns (identified dynamically, not hardcoded):
    recon_steps  – e.g. "A. Earnings / Gross Wages"
    gl_code      – e.g. "5000"
    gl_title     – e.g. "Salaries & Wages"
    pay_code     – e.g. "Wages"
    code_type    – e.g. "EARNING"

Output:
    gl_lookup  → { gl_code_str: { "gl_title", "recon_steps", "code_type" } }
    pr_lookup  → { (pay_code_upper, code_type_upper): "GL_CODE - GL_TITLE [& ...]" }
"""

import logging
from collections import defaultdict
from typing import Dict, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


def build_lookups(
    df: pd.DataFrame,
    col_map: Dict[str, str],
) -> Tuple[Dict[str, dict], Dict[Tuple[str, str], str]]:
    """
    Build GL and Payroll Register lookup dictionaries from the reconciliation
    mapping DataFrame.

    Parameters
    ----------
    df      : The Process of Reconciliation DataFrame (all rows, no pre-filter).
    col_map : { semantic_role → actual_column_name } confirmed mapping.

    Returns
    -------
    gl_lookup : { "5000": {"gl_title": "Salaries & Wages",
                            "recon_steps": "A. Earnings / Gross Wages",
                            "code_type": "EARNING"} }

    pr_lookup : { ("WAGES", "EARNING"): "5000 - Salaries & Wages",
                  ("DENTAL16", "BENEFIT"):
                      "5130 - Insurance Benefits & 2146 - Dental Insurance ER" }
    """
    # ── resolve column names ───────────────────────────────────────────────
    recon_col  = col_map.get("recon_steps")
    glcode_col = col_map.get("gl_code")
    gltitle_col= col_map.get("gl_title")
    paycode_col= col_map.get("pay_code")
    codetype_col= col_map.get("code_type")

    missing = [
        role for role, col in {
            "recon_steps": recon_col,
            "gl_code":     glcode_col,
            "gl_title":    gltitle_col,
            "pay_code":    paycode_col,
            "code_type":   codetype_col,
        }.items()
        if col is None
    ]
    if missing:
        raise ValueError(
            f"Cannot build lookups — these roles were not mapped: {missing}"
        )

    # ── clean the DataFrame ────────────────────────────────────────────────
    work = df[[recon_col, glcode_col, gltitle_col, paycode_col, codetype_col]].copy()
    work.dropna(subset=[glcode_col, paycode_col, codetype_col], how="any", inplace=True)

    for col in work.columns:
        work[col] = work[col].astype(str).str.strip()

    # ── GL lookup ──────────────────────────────────────────────────────────
    gl_lookup: Dict[str, dict] = {}

    for _, row in work.iterrows():
        gl_code = row[glcode_col]
        if gl_code and gl_code.lower() != "nan":
            gl_lookup[gl_code] = {
                "gl_title":   row[gltitle_col],
                "recon_steps": row[recon_col],
                "code_type":  row[codetype_col].upper(),
            }

    # ── PR lookup  ─────────────────────────────────────────────────────────
    # Group by (pay_code, code_type); each group may have MULTIPLE GL codes
    # (dual entries for BENEFIT and TAXES).  Combine them with " & ".
    pr_groups: Dict[Tuple[str, str], list] = defaultdict(list)

    for _, row in work.iterrows():
        pay_code  = row[paycode_col].upper()
        code_type = row[codetype_col].upper()
        gl_str    = f"{row[glcode_col]} - {row[gltitle_col]}"

        if gl_str not in pr_groups[(pay_code, code_type)]:
            pr_groups[(pay_code, code_type)].append(gl_str)

    pr_lookup: Dict[Tuple[str, str], str] = {
        key: " & ".join(gl_strings)
        for key, gl_strings in pr_groups.items()
    }

    logger.info(
        "Built GL lookup (%d entries) and PR lookup (%d entries).",
        len(gl_lookup),
        len(pr_lookup),
    )
    return gl_lookup, pr_lookup


def get_recon_steps_list(gl_lookup: Dict[str, dict]) -> list:
    """Return unique reconciliation steps in insertion order."""
    seen = []
    for entry in gl_lookup.values():
        step = entry["recon_steps"]
        if step not in seen:
            seen.append(step)
    return seen
