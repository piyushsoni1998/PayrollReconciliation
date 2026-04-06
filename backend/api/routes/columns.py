"""
columns.py
───────────
POST /api/confirm-mapping
  - Saves the user-confirmed column mapping for a file type.

POST /api/clients
  - Returns list of clients with saved mappings.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Dict, List

from backend.api import state
from backend.column_identifier import save_confirmed_mapping
from backend.utils.file_reader import read_file

router = APIRouter()


class ConfirmMappingRequest(BaseModel):
    session_id:  str
    file_type:   str
    mapping:     Dict[str, str]
    client_name: str  = "default"
    save_cache:  bool = True


@router.post("/confirm-mapping")
async def confirm_mapping(req: ConfirmMappingRequest):
    sess = state.get(req.session_id)
    if sess is None:
        raise HTTPException(404, "Session not found.")

    file_data = state.get_file(req.session_id, req.file_type)
    if file_data is None:
        raise HTTPException(400, f"No file uploaded for file_type '{req.file_type}'.")

    # Save to session
    state.set_mapping(req.session_id, req.file_type, req.mapping)

    # Persist to disk cache if requested
    if req.save_cache:
        save_confirmed_mapping(
            df               = file_data["df"],
            file_type        = req.file_type,
            confirmed_mapping= req.mapping,
            client_name      = req.client_name,
        )

    warnings: List[str] = []

    # Warn when the confirmed gl_code column looks like fund/dimension codes
    # (1-2 digit values) rather than real GL account codes (4-5 digit values).
    if req.file_type == "gl_report":
        gl_code_col = next(
            (col for col, role in req.mapping.items() if role == "gl_code"), None
        )
        if gl_code_col and gl_code_col in file_data["df"].columns:
            sample_vals = (
                file_data["df"][gl_code_col]
                .dropna()
                .astype(str)
                .str.strip()
                .str.split(".")
                .str[0]
                .unique()[:20]
            )
            non_empty = [v for v in sample_vals if v and v.lower() != "nan"]
            if non_empty:
                avg_len = sum(len(v) for v in non_empty) / len(non_empty)
                if avg_len <= 2.5:
                    warnings.append(
                        f"The column '{gl_code_col}' mapped as GL Code contains very short "
                        f"values (e.g. {non_empty[:5]}). These appear to be Fund or Department "
                        f"codes, not GL account codes. GL account codes are typically 4-5 digits "
                        f"(e.g. 5000, 2115, 1020). Please verify you selected the correct column."
                    )

    return JSONResponse({
        "ok":        True,
        "file_type": req.file_type,
        "saved":     req.save_cache,
        "warnings":  warnings,
    })
