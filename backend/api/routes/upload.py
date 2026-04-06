"""
upload.py
──────────
POST /api/upload/{file_type}

Accepts a file upload, auto-detects the header row, runs column
identification (fuzzy → Bedrock), and returns:
  - detected column → role mapping with confidence scores
  - first 5 rows as preview
  - which header row was detected
"""

import logging
import os
from typing import Optional

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from backend.api import state
from backend.column_identifier import identify_columns
from backend.utils.file_reader import get_sheet_names, read_file
from config.settings import FILE_TYPE_ROLES

logger    = logging.getLogger(__name__)
router    = APIRouter()
FILE_TYPES = {"gl_report", "payroll_register"}

SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".xlsm", ".xltx", ".xlsb", ".csv", ".tsv", ".txt", ".ods"}


@router.post("/upload/{file_type}")
async def upload_file(
    file_type:   str,
    file:        UploadFile = File(...),
    session_id:  str        = Form(...),
    sheet_name:  Optional[str] = Form(None),
    client_name: str        = Form("default"),
    use_bedrock: bool       = Form(True),
    use_cache:   bool       = Form(True),
):
    if file_type not in FILE_TYPES:
        raise HTTPException(400, f"Unknown file_type '{file_type}'. Must be one of {FILE_TYPES}")

    sess = state.get(session_id)
    if sess is None:
        raise HTTPException(404, "Session not found. Please refresh the page.")

    raw_bytes = await file.read()

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext and ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")

    # ── sheet selection ────────────────────────────────────────────────────
    sheets = get_sheet_names(raw_bytes, file.filename)

    # If the client specified a sheet name use it, else use first sheet
    selected_sheet = None
    if sheets:
        if sheet_name and sheet_name in sheets:
            selected_sheet = sheet_name
        else:
            selected_sheet = sheets[0]

    # ── smart read ─────────────────────────────────────────────────────────
    df, header_row, _ = read_file(
        source     = raw_bytes,
        filename   = file.filename,
        sheet_name = selected_sheet if selected_sheet is not None else 0,
    )

    if df.empty:
        raise HTTPException(422, f"Could not read any data from '{file.filename}'. "
                                  "Check that the file is not empty and is a valid Excel/CSV.")

    # ── store in session ───────────────────────────────────────────────────
    state.set_file(session_id, file_type, df, file.filename, header_row)

    # ── column identification ──────────────────────────────────────────────
    mapping, confidence, unmatched = identify_columns(
        df          = df,
        file_type   = file_type,
        client_name = client_name,
        use_cache   = use_cache,
        use_bedrock = use_bedrock,
    )

    # ── build preview ──────────────────────────────────────────────────────
    preview = df.head(5).fillna("").astype(str).to_dict(orient="records")

    return JSONResponse({
        "ok":          True,
        "file_type":   file_type,
        "filename":    file.filename,
        "header_row":  header_row,
        "row_count":   len(df),
        "col_count":   len(df.columns),
        "columns":     list(df.columns),
        "sheets":      sheets,
        "mapping":     mapping,
        "confidence":  confidence,
        "unmatched":   unmatched,
        "roles":       FILE_TYPE_ROLES.get(file_type, []),
        "preview":     preview,
    })


@router.get("/sheets")
async def get_sheets(filename: str, session_id: str):
    """Return sheet names for an already-uploaded file (for sheet switching)."""
    file_data = state.get_file(session_id, "")
    if not file_data:
        return JSONResponse({"sheets": []})
    return JSONResponse({"sheets": file_data.get("sheets", [])})
