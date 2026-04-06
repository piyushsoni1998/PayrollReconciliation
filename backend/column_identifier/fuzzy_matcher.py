"""
fuzzy_matcher.py
────────────────
First-pass column identification using rapidfuzz string similarity.
No external API calls — runs instantly, zero cost.

Returns a confidence score per column. Columns below the threshold are
passed on to the Bedrock LLM identifier.
"""

import re
from typing import Dict, List, Tuple, Optional

import pandas as pd
from rapidfuzz import fuzz, process


def _normalize(text: str) -> str:
    """Lowercase and strip all non-alphanumeric chars for comparison."""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


# Columns whose normalized name must NEVER be assigned to these roles.
# Fund/department/cost-centre columns look similar to account codes but are
# dimensional fields — mapping them as gl_code produces completely wrong results.
_ROLE_EXCLUSIONS: Dict[str, List[str]] = {
    "gl_code": [
        "fundcode", "fund", "fundnumber", "fundno", "fundnum",
        "departmentcode", "department", "dept", "deptcode", "deptno",
        "costcenter", "costcentre", "costcentercode", "cc", "cccode",
        "projectcode", "project", "programcode", "program",
        "divisioncode", "division", "orgcode", "org",
        "locationcode", "location", "entitycode", "entity",
        "classificationcode", "classification",
    ],
    "gl_title": [
        "fundname", "funddescription", "funddesc",
        "departmentname", "deptname", "deptdesc",
        "costcentername", "projectname", "programname",
        "divisionname", "locationname", "entityname",
    ],
}


def build_alias_index(aliases: Dict[str, List[str]]) -> Dict[str, str]:
    """
    Flatten the alias dict into a lookup:
        normalized_alias_string → semantic_role
    """
    index: Dict[str, str] = {}
    for role, role_aliases in aliases.items():
        for alias in role_aliases:
            norm = _normalize(alias)
            if norm:
                index[norm] = role
    return index


def fuzzy_match_columns(
    df: pd.DataFrame,
    aliases: Dict[str, List[str]],
    threshold: int = 85,
) -> Tuple[Dict[str, Tuple[Optional[str], float]], List[str]]:
    """
    Match every column in ``df`` to a semantic role.

    Parameters
    ----------
    df        : DataFrame whose columns will be identified.
    aliases   : Canonical alias dictionary from settings.
    threshold : Minimum fuzzy score (0-100) to auto-accept a match.

    Returns
    -------
    result    : { col_name: (semantic_role | None, confidence 0-100) }
    unmatched : List of column names that scored below threshold.
    """
    alias_index = build_alias_index(aliases)
    all_norm_aliases = list(alias_index.keys())

    result: Dict[str, Tuple[Optional[str], float]] = {}
    unmatched: List[str] = []

    exclusion_sets: Dict[str, set] = {
        role: set(names) for role, names in _ROLE_EXCLUSIONS.items()
    }

    def _is_excluded(col_norm: str, role: str) -> bool:
        return col_norm in exclusion_sets.get(role, set())

    for col in df.columns:
        col_norm = _normalize(col)

        # ── exact match first (fastest path) ──────────────────────────────
        if col_norm in alias_index and not _is_excluded(col_norm, alias_index[col_norm]):
            result[col] = (alias_index[col_norm], 100.0)
            continue

        # ── fuzzy match ────────────────────────────────────────────────────
        if not all_norm_aliases:
            result[col] = (None, 0.0)
            unmatched.append(col)
            continue

        best = process.extractOne(
            col_norm,
            all_norm_aliases,
            scorer=fuzz.token_set_ratio,
        )

        if best and best[1] >= threshold and not _is_excluded(col_norm, alias_index[best[0]]):
            result[col] = (alias_index[best[0]], float(best[1]))
        else:
            result[col] = (None, 0.0)
            unmatched.append(col)

    return result, unmatched
