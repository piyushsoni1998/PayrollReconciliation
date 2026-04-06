"""
main.py
────────
FastAPI application entry point.

Endpoints
---------
POST  /api/session                   – Create a new session, returns session_id
POST  /api/upload/{file_type}        – Upload + auto-identify columns
POST  /api/confirm-mapping           – Save confirmed column mapping
POST  /api/run                       – Run full reconciliation
GET   /api/download?session_id=...   – Download Excel report
GET   /                              – Serve frontend HTML
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api          import state as session_state
from backend.api.routes   import upload, columns, reconcile
from backend.api.routes   import mapping_config
from backend.api.routes   import auth

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")

app = FastAPI(
    title       = "Payroll Reconciliation API",
    description = "Automated GL vs Payroll Register reconciliation",
    version     = "1.0.0",
)

# ── CORS (for local dev with separate frontend) ────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── API routes ─────────────────────────────────────────────────────────────────
app.include_router(upload.router,         prefix="/api")
app.include_router(columns.router,        prefix="/api")
app.include_router(reconcile.router,      prefix="/api")
app.include_router(mapping_config.router, prefix="/api")
app.include_router(auth.router,           prefix="/api")


@app.post("/api/session")
async def create_session():
    """Create a new session and return its ID."""
    sid = session_state.new_session()
    return JSONResponse({"session_id": sid})


@app.get("/api/session/{session_id}/status")
async def get_session_status(session_id: str):
    """Return whether this session still exists on the server (lightweight ping)."""
    sess = session_state.get(session_id)
    if sess is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Session not found.")
    files    = sess.get("files",    {})
    mappings = sess.get("mappings", {})
    results  = sess.get("results",  {})
    return JSONResponse({
        "session_id":          session_id,
        "gl_report_uploaded":  "gl_report"        in files,
        "gl_report_confirmed": "gl_report"        in mappings,
        "pr_uploaded":         "payroll_register" in files,
        "pr_confirmed":        "payroll_register" in mappings,
        "has_results":         bool(results),
    })


@app.post("/api/session/{session_id}/reset")
async def reset_session(session_id: str):
    """Clear all uploaded files, mappings and results for the session (keep ID alive)."""
    if session_state.get(session_id) is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Session not found.")
    session_state.reset_session(session_id)
    return JSONResponse({"ok": True})


# ── Static files (frontend) ────────────────────────────────────────────────────
_static_dir = os.path.join(FRONTEND_DIR, "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# ── Serve index.html for / ─────────────────────────────────────────────────────
from fastapi.responses import FileResponse

@app.get("/")
async def root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse({"message": "Payroll Reconciliation API is running."})
