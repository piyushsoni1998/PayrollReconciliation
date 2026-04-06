"""
column_identifier package
──────────────────────────
Orchestrates the hybrid column-identification pipeline:

    Step 1  →  fuzzy_matcher    (instant, zero-cost)
    Step 2  →  bedrock_identifier (only for low-confidence columns)
    Step 3  →  mapping_cache    (skip Steps 1+2 on repeat uploads)

Public entry-point: ``identify_columns(...)``
"""

import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config.settings import (
    AWS_ACCESS_KEY_ID,
    AWS_REGION,
    AWS_SECRET_ACCESS_KEY,
    BEDROCK_MODEL_ID,
    CLIENT_MAPPINGS_DIR,
    COLUMN_ALIASES,
    FILE_TYPE_ROLES,
    FUZZY_THRESHOLD,
    LLM_CONFIDENCE_THRESHOLD,
    SAMPLE_ROWS,
)

from .fuzzy_matcher      import fuzzy_match_columns
from .bedrock_identifier import BedrockColumnIdentifier
from .mapping_cache      import MappingCache

logger = logging.getLogger(__name__)

_cache              = MappingCache(CLIENT_MAPPINGS_DIR)
_bedrock_identifier = BedrockColumnIdentifier(
    region               = AWS_REGION,
    model_id             = BEDROCK_MODEL_ID,
    aws_access_key_id    = AWS_ACCESS_KEY_ID or None,
    aws_secret_access_key= AWS_SECRET_ACCESS_KEY or None,
)


def identify_columns(
    df: pd.DataFrame,
    file_type: str,
    client_name: str = "default",
    use_cache: bool  = True,
    use_bedrock: bool= True,
) -> Tuple[Dict[str, str], Dict[str, float], List[str]]:
    """
    Identify semantic roles for every column in ``df``.

    Parameters
    ----------
    df          : The uploaded DataFrame.
    file_type   : One of ``payroll_register``, ``gl_report``,
                  ``process_of_reconciliation``.
    client_name : Used to namespace the cache file.
    use_cache   : Load / save from the per-client cache.
    use_bedrock : Call Bedrock for columns fuzzy could not resolve.

    Returns
    -------
    mapping     : { col_name → semantic_role }   (None = unknown)
    confidence  : { col_name → score 0-100 }
    still_unmatched : column names that could not be identified at all
    """
    expected_roles = FILE_TYPE_ROLES.get(file_type, [])

    # ── Step 0: check cache ────────────────────────────────────────────────
    if use_cache:
        cached = _cache.load(client_name, file_type, df)
        if cached is not None:
            mapping    = cached
            confidence = {col: 100.0 for col in mapping}
            unmatched  = [col for col, role in mapping.items() if role is None]
            return mapping, confidence, unmatched

    # ── Step 1: fuzzy matching ─────────────────────────────────────────────
    fuzzy_result, fuzzy_unmatched = fuzzy_match_columns(
        df, COLUMN_ALIASES, threshold=FUZZY_THRESHOLD
    )

    mapping:    Dict[str, Optional[str]] = {}
    confidence: Dict[str, float]         = {}

    for col, (role, score) in fuzzy_result.items():
        mapping[col]    = role
        confidence[col] = score

    # ── Step 2: Bedrock for unmatched columns ──────────────────────────────
    still_unmatched = list(fuzzy_unmatched)

    if use_bedrock and still_unmatched:
        if _bedrock_identifier.is_available():
            llm_result = _bedrock_identifier.identify_columns(
                df               = df,
                file_type        = file_type,
                unmatched_columns= still_unmatched,
                expected_roles   = expected_roles,
                sample_rows      = SAMPLE_ROWS,
            )

            resolved = []
            for col in still_unmatched:
                col_result = llm_result.get(col, {})
                role       = col_result.get("role")
                conf       = float(col_result.get("confidence", 0.0)) * 100

                if role and conf >= LLM_CONFIDENCE_THRESHOLD * 100:
                    mapping[col]    = role
                    confidence[col] = conf
                    resolved.append(col)
                else:
                    mapping[col]    = None
                    confidence[col] = conf

            still_unmatched = [c for c in still_unmatched if c not in resolved]
        else:
            logger.warning(
                "Bedrock is not available. %d columns remain unmatched.",
                len(still_unmatched),
            )

    return mapping, confidence, still_unmatched


def save_confirmed_mapping(
    df: pd.DataFrame,
    file_type: str,
    confirmed_mapping: Dict[str, str],
    client_name: str = "default",
) -> None:
    """Persist a user-confirmed mapping to cache."""
    _cache.save(client_name, file_type, df, confirmed_mapping)


def delete_cached_mapping(
    df: pd.DataFrame,
    file_type: str,
    client_name: str = "default",
) -> None:
    """Force re-identification by removing the cached mapping."""
    _cache.delete(client_name, file_type, df)
