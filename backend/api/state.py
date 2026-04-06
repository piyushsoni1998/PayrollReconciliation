"""
state.py
─────────
In-memory session store.  Each browser session gets a UUID; the server
holds the uploaded DataFrames, confirmed mappings, and results in RAM.

This is intentionally simple (single-process, no Redis/DB) because
the tool is designed for a small team running it locally.
"""

import uuid
from typing import Any, Dict, Optional


_store: Dict[str, Dict[str, Any]] = {}


def new_session() -> str:
    sid = str(uuid.uuid4())
    _store[sid] = {
        "files":    {},   # file_type → { df, filename, header_row }
        "mappings": {},   # file_type → { col_name → role }
        "results":  {},   # keys: gl_mapped, pr_mapped, gl_pivot, pr_pivot, recon_df, summary_stats, unmapped_gl, unmapped_pr, excel_bytes
    }
    return sid


def get(sid: str) -> Optional[Dict]:
    return _store.get(sid)


def set_file(sid: str, file_type: str, df, filename: str, header_row: int):
    _store[sid]["files"][file_type] = {
        "df": df, "filename": filename, "header_row": header_row
    }


def set_mapping(sid: str, file_type: str, mapping: Dict[str, str]):
    _store[sid]["mappings"][file_type] = mapping


def set_results(sid: str, results: Dict[str, Any]):
    _store[sid]["results"] = results


def get_file(sid: str, file_type: str) -> Optional[Dict]:
    return _store.get(sid, {}).get("files", {}).get(file_type)


def get_mapping(sid: str, file_type: str) -> Optional[Dict]:
    return _store.get(sid, {}).get("mappings", {}).get(file_type)


def get_results(sid: str) -> Optional[Dict]:
    return _store.get(sid, {}).get("results")


def all_files_uploaded(sid: str) -> bool:
    files = _store.get(sid, {}).get("files", {})
    return all(ft in files for ft in ("gl_report", "payroll_register"))


def all_mappings_confirmed(sid: str) -> bool:
    mappings = _store.get(sid, {}).get("mappings", {})
    return all(ft in mappings for ft in ("gl_report", "payroll_register"))


def reset_session(sid: str):
    """Clear files, mappings, and results — keeping the session ID alive."""
    if sid in _store:
        _store[sid] = {"files": {}, "mappings": {}, "results": {}}
