"""
reconcile.py
─────────────
POST /api/run     – Run the full reconciliation pipeline.
GET  /api/download – Stream the Excel file.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend.api import state
from backend.api.db import get_db
from backend.api.routes.mapping_config       import build_lookups_from_config, _load_config
from backend.processors.gl_processor         import process_gl
from backend.processors.payroll_processor    import process_payroll
from backend.utils.date_utils                import parse_dates_smart
from backend.processors.reconciliation_processor import (
    build_reconciliation, get_summary_stats,
)
from backend.utils.excel_exporter            import export_to_excel

logger = logging.getLogger(__name__)
router = APIRouter()


class RunRequest(BaseModel):
    session_id:   str
    client_name:  str = "default"
    period_label: str = ""
    period_start: Optional[str] = None   # "YYYY-MM"  e.g. "2024-01"
    period_end:   Optional[str] = None   # "YYYY-MM"  e.g. "2024-12"
    user_id:      Optional[str] = None   # signed-in user (optional)


@router.post("/run")
async def run_reconciliation(req: RunRequest):
    sess = state.get(req.session_id)
    if sess is None:
        raise HTTPException(404, "Session not found.")

    # Only GL and PR files needed now — mapping comes from config
    gl_file  = state.get_file(req.session_id, "gl_report")
    pr_file  = state.get_file(req.session_id, "payroll_register")
    gl_col_map = state.get_mapping(req.session_id, "gl_report")
    pr_col_map = state.get_mapping(req.session_id, "payroll_register")

    if not gl_file or not pr_file:
        raise HTTPException(400, "GL Report and Payroll Register must both be uploaded.")
    if not gl_col_map or not pr_col_map:
        raise HTTPException(400, "Column mappings for GL Report and Payroll Register must be confirmed.")

    try:
        # ── Build lookup dictionaries from saved mapping config ────────────
        mapping_rows = _load_config(req.client_name)
        gl_lookup, pr_lookup, gl_pr_amount = build_lookups_from_config(mapping_rows)

        # ── Convert { col → role } → { role → col } for processors ────────
        # Session state stores { col_name → semantic_role } (same format as
        # identify_columns returns).  Processors need { role → col_name }.
        def _invert(m: dict) -> dict:
            return {role: col for col, role in m.items() if role}

        inv_gl_col_map = _invert(gl_col_map)
        inv_pr_col_map = _invert(pr_col_map)

        # ── Pre-run column mapping validation ─────────────────────────────
        # Before doing any processing, check that the mapped GL code column
        # actually contains GL account codes that exist in the config.
        # If 0 config codes match, the column is wrong (e.g. Fund Code mapped
        # instead of Account Code) and results will be completely meaningless.
        _col_validation = _validate_column_mapping(
            gl_df      = gl_file["df"],
            inv_gl_map = inv_gl_col_map,
            gl_lookup  = gl_lookup,
        )
        if _col_validation["gl_code_match_pct"] == 0 and _col_validation["config_gl_codes"] > 0:
            raise HTTPException(400, {
                "error":   "wrong_gl_column",
                "message": (
                    f"The column mapped as 'GL Code' ('{_col_validation['gl_code_col']}') "
                    f"contains no values that match your reconciliation config "
                    f"({_col_validation['config_gl_codes']} configured GL codes). "
                    f"Sample values from that column: {_col_validation['gl_col_sample']}. "
                    f"This is likely a Fund/Department code column, not the GL account code column. "
                    f"Please go to Upload Files and re-confirm the column mapping — "
                    f"select the column that contains 4-5 digit account codes (e.g. 5000, 2115, 1020)."
                ),
                "gl_code_col":    _col_validation["gl_code_col"],
                "sample_values":  _col_validation["gl_col_sample"],
                "config_gl_codes": _col_validation["config_gl_codes"],
            })

        # ── Extract available date range from date columns (before filtering) ─
        gl_range = _extract_date_range(gl_file["df"], inv_gl_col_map)
        pr_range = _extract_date_range(pr_file["df"], inv_pr_col_map)
        all_mins  = [r["min"] for r in [gl_range, pr_range] if r.get("min")]
        all_maxes = [r["max"] for r in [gl_range, pr_range] if r.get("max")]
        available_date_range = {
            "min":      min(all_mins)  if all_mins  else None,
            "max":      max(all_maxes) if all_maxes else None,
            "gl_range": gl_range,
            "pr_range": pr_range,
        }

        # ── Process GL ─────────────────────────────────────────────────────
        gl_mapped, gl_pivot, unmapped_gl, gl_filter_info = process_gl(
            df           = gl_file["df"],
            col_map      = inv_gl_col_map,
            gl_lookup    = gl_lookup,
            period_start = req.period_start,
            period_end   = req.period_end,
        )

        # ── Process Payroll Register ───────────────────────────────────────
        pr_mapped, pr_pivot, unmapped_pr, pr_filter_info = process_payroll(
            df           = pr_file["df"],
            col_map      = inv_pr_col_map,
            pr_lookup    = pr_lookup,
            period_start = req.period_start,
            period_end   = req.period_end,
        )

        # ── Net Pay total for bank cross-check ────────────────────────────
        net_col      = inv_pr_col_map.get("net_amount")
        pr_net_total = None
        if net_col and net_col in pr_mapped.columns:
            pr_net_total = pd.to_numeric(
                pr_mapped[net_col].astype(str).str.replace(",", ""),
                errors="coerce",
            ).fillna(0).sum()

        # ── Build diagnostics to surface in UI ────────────────────────────
        trans_src_col   = inv_gl_col_map.get("trans_source", "")
        gl_earn_total   = float(gl_pivot.loc[
            gl_pivot["GL Code"].astype(str).str.match(r"^5|^6"), "Sum of Net Amount"
        ].sum()) if not gl_pivot.empty else 0.0

        pr_earn_col = inv_pr_col_map.get("earn_amount", "")
        pr_earn_total = float(
            pd.to_numeric(pr_mapped[pr_earn_col].astype(str).str.replace(",", ""), errors="coerce").fillna(0).sum()
        ) if pr_earn_col and pr_earn_col in pr_mapped.columns else 0.0

        gl_rows_used     = len(gl_mapped)
        pr_rows_used     = len(pr_mapped)
        gl_rows_original = len(gl_file["df"])
        pr_rows_original = len(pr_file["df"])

        # Use the authoritative filter result from processors
        gl_filter_skipped = gl_filter_info.get("skipped", False)
        pr_filter_skipped = pr_filter_info.get("skipped", False)

        # ── Data range mismatch guard ──────────────────────────────────────
        # If a period filter was requested but the GL filter was skipped (date
        # parsing failed), AND the GL file actually spans beyond the requested
        # period, the results will include multiple years of GL data vs a single
        # year of PR data — completely wrong.  Surface this as a blocking error.
        filter_error = None
        if gl_filter_skipped and (req.period_start or req.period_end):
            gl_min = gl_range.get("min")
            gl_max = gl_range.get("max")
            # Check if GL data genuinely extends outside the requested window
            outside = False
            if gl_min and req.period_start and gl_min < req.period_start:
                outside = True
            if gl_max and req.period_end and gl_max > req.period_end:
                outside = True
            if outside:
                filter_error = {
                    "type":             "gl_date_filter_failed",
                    "gl_data_range":    f"{gl_min} to {gl_max}",
                    "period_requested": f"{req.period_start or '?'} to {req.period_end or '?'}",
                    "date_col":         gl_filter_info.get("date_col", ""),
                    "reason":           gl_filter_info.get("reason", ""),
                    "rows_affected":    gl_rows_original,
                    "sample_dates":     gl_filter_info.get("sample_dates", []),
                }
                logger.warning(
                    "Filter mismatch: GL data spans %s–%s but filter to %s–%s failed (%s). "
                    "Results include all %d GL rows.",
                    gl_min, gl_max,
                    req.period_start, req.period_end,
                    gl_filter_info.get("reason", ""),
                    gl_rows_original,
                )

        # ── PR vs GL date range mismatch ───────────────────────────────────
        # Even when both filters succeed, warn if their data ranges are very different
        pr_min = pr_range.get("min")
        pr_max = pr_range.get("max")
        gl_min = gl_range.get("min")
        gl_max = gl_range.get("max")

        # Detect likely period mismatch: if gross earnings differ by >20%
        period_warning = ""
        if filter_error:
            period_warning = (
                f"GL date filter failed — '{filter_error['date_col']}' column dates could not be parsed. "
                f"GL file contains data from {filter_error['gl_data_range']} "
                f"but filter to {filter_error['period_requested']} was skipped. "
                f"All {gl_rows_original:,} GL rows are included. "
                f"Sample date values from GL: {filter_error['sample_dates']}"
            )
        elif gl_filter_skipped and (req.period_start or req.period_end):
            period_warning = (
                f"GL date filter could not be applied — the date column '{gl_filter_info.get('date_col', '')}' "
                "values may be in an unrecognised format. All GL rows are included."
            )
        elif gl_earn_total and pr_earn_total:
            ratio = pr_earn_total / gl_earn_total if gl_earn_total != 0 else 0
            if ratio > 1.15 or ratio < 0.85:
                period_warning = (
                    f"GL gross earnings ({gl_earn_total:,.2f}) differ from "
                    f"PR gross earnings ({pr_earn_total:,.2f}) by {abs(ratio-1)*100:.0f}%. "
                    f"Check that both files cover the same pay period."
                )

        diagnostics = {
            "gl_rows_used":        gl_rows_used,
            "pr_rows_used":        pr_rows_used,
            "gl_rows_total":       gl_rows_original,
            "pr_rows_total":       pr_rows_original,
            "gl_earn_total":       _safe_float(gl_earn_total),
            "pr_earn_total":       _safe_float(pr_earn_total),
            "pr_net_total":        _safe_float(pr_net_total) if pr_net_total is not None else None,
            "period_warning":      period_warning,
            "period_start":        req.period_start,
            "period_end":          req.period_end,
            "gl_date_col":         gl_filter_info.get("date_col") or _resolve_date_col(inv_gl_col_map, gl_file["df"].columns),
            "pr_date_col":         pr_filter_info.get("date_col") or _resolve_date_col(inv_pr_col_map, pr_file["df"].columns),
            "gl_filter_skipped":   gl_filter_skipped,
            "pr_filter_skipped":   pr_filter_skipped,
            "gl_filter_reason":    gl_filter_info.get("reason", ""),
            "pr_filter_reason":    pr_filter_info.get("reason", ""),
        }

        # ── Reconciliation ─────────────────────────────────────────────────
        recon_df      = build_reconciliation(gl_pivot, pr_pivot, gl_lookup, pr_net_total, gl_pr_amount)
        summary_stats = get_summary_stats(recon_df)
        summary_stats["diagnostics"] = diagnostics

        # ── Terminal report ────────────────────────────────────────────────
        try:
            _print_terminal_report(
                recon_df     = recon_df,
                summary      = summary_stats,
                client_name  = req.client_name,
                period_label = req.period_label,
                period_start = req.period_start,
                period_end   = req.period_end,
                gl_filename  = gl_file.get("filename", ""),
                pr_filename  = pr_file.get("filename", ""),
                unmapped_gl  = list(sorted(unmapped_gl)) if unmapped_gl else [],
                unmapped_pr  = [list(k) for k in sorted(unmapped_pr)] if unmapped_pr else [],
            )
        except Exception as _rpt_err:
            logger.warning("Terminal report failed (non-critical): %s", _rpt_err, exc_info=True)

        # ── Add Variance column to PR Pivot ────────────────────────────────
        # Build GL code → variance map from recon results (exclude TOTAL row)
        _gl_var = {
            str(r["GL Code"]).strip(): float(r["Variance"])
            for _, r in recon_df.iterrows()
            if str(r.get("Reconciliation Step", "")).upper() != "TOTAL"
               and str(r.get("GL Code", "")).strip()
        }

        def _pr_row_variance(recon_mapping: str) -> float:
            # Extract 4+-digit GL codes from strings like
            # "5130 - Insurance Benefits & 2145 - Health Insurance ER"
            codes = re.findall(r"\b(\d{4,})\b", str(recon_mapping))
            return round(sum(_gl_var.get(c, 0.0) for c in codes), 2)

        pr_pivot = pr_pivot.copy()
        pr_pivot["Variance"] = pr_pivot["Reconciliation Mapping"].apply(_pr_row_variance)

        # ── Save run history to MongoDB (non-blocking best-effort) ─────────
        try:
            db = get_db()
            if db is not None:
                result_payload = {
                    "recon_table": _df_to_json(recon_df),
                    "gl_pivot":    _df_to_json(gl_pivot),
                    "pr_pivot":    _df_to_json(pr_pivot),
                    "unmapped_gl": list(sorted(unmapped_gl)) if unmapped_gl else [],
                    "unmapped_pr": [list(k) for k in sorted(unmapped_pr)] if unmapped_pr else [],
                }
                record = {
                    "client_name":   req.client_name,
                    "period_label":  req.period_label,
                    "gl_filename":   gl_file.get("filename", ""),
                    "pr_filename":   pr_file.get("filename", ""),
                    "gl_row_count":  int(len(gl_file["df"])),
                    "pr_row_count":  int(len(pr_file["df"])),
                    "summary_stats": summary_stats,
                    "result_data":   result_payload,
                    "created_at":    datetime.now(timezone.utc),
                }
                if req.user_id:
                    record["user_id"] = req.user_id
                db["recon_history"].insert_one(record)
        except Exception:
            logger.warning("Could not save reconciliation history to MongoDB.", exc_info=True)

        # ── Excel export ───────────────────────────────────────────────────
        excel_bytes = export_to_excel(
            gl_mapped    = gl_mapped,
            pr_mapped    = pr_mapped,
            gl_pivot     = gl_pivot,
            pr_pivot     = pr_pivot,
            recon_df     = recon_df,
            period_label = req.period_label,
            client_name  = req.client_name,
            mapping_rows = mapping_rows,
        )

        # ── Store results ──────────────────────────────────────────────────
        state.set_results(req.session_id, {
            "gl_mapped":    gl_mapped,
            "pr_mapped":    pr_mapped,
            "gl_pivot":     gl_pivot,
            "pr_pivot":     pr_pivot,
            "recon_df":     recon_df,
            "summary_stats":summary_stats,
            "unmapped_gl":  list(sorted(unmapped_gl)) if unmapped_gl else [],
            "unmapped_pr":  [list(k) for k in sorted(unmapped_pr)] if unmapped_pr else [],
            "excel_bytes":  excel_bytes,
            "period_label": req.period_label,
            "client_name":  req.client_name,
        })

        # ── Return JSON-serialisable results ──────────────────────────────
        return JSONResponse({
            "ok":              True,
            "summary_stats":   summary_stats,
            "recon_table":     _df_to_json(recon_df),
            "gl_pivot":        _df_to_json(gl_pivot),
            "pr_pivot":        _df_to_json(pr_pivot),
            "unmapped_gl":          list(sorted(unmapped_gl)) if unmapped_gl else [],
            "unmapped_pr":          [list(k) for k in sorted(unmapped_pr)] if unmapped_pr else [],
            "available_date_range": available_date_range,
            "period_start":         req.period_start,
            "period_end":           req.period_end,
            "filter_error":         filter_error,   # None when no problem; dict when GL data spans beyond filter
        })

    except HTTPException:
        raise   # let 400/404/422 pass through unchanged
    except ValueError as e:
        logger.exception("ValueError in reconciliation pipeline")
        raise HTTPException(422, str(e))
    except Exception as e:
        logger.exception("Reconciliation failed")
        raise HTTPException(500, f"Processing error: {e}")


@router.get("/download")
async def download_excel(session_id: str, period_label: str = ""):
    results = state.get_results(session_id)
    if not results or not results.get("excel_bytes"):
        raise HTTPException(404, "No results found. Run reconciliation first.")

    timestamp    = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    safe_period  = re.sub(r"[^\w]", "_", period_label or "report")
    safe_client  = re.sub(r"[^\w]", "_", results.get("client_name", "") or "")
    client_part  = f"{safe_client}_" if safe_client and safe_client.lower() != "default" else ""
    filename     = f"Payroll_Recon_{client_part}{safe_period}_{timestamp}.xlsx"

    return StreamingResponse(
        iter([results["excel_bytes"]]),
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers    = {"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/recon-history")
async def get_recon_history(client_name: str = "", user_id: str = "", limit: int = 50):
    """Return recent reconciliation runs from MongoDB (most recent first, no result_data)."""
    db = get_db()
    if db is None:
        return JSONResponse({"ok": False, "message": "MongoDB not configured.", "runs": []})

    query: dict = {}
    if user_id:
        query["user_id"] = user_id
    elif client_name:
        query["client_name"] = client_name
    # Exclude heavy result_data from the list view
    cursor = (
        db["recon_history"]
        .find(query, {"result_data": 0})
        .sort("created_at", -1)
        .limit(max(1, min(limit, 200)))
    )
    runs = []
    for doc in cursor:
        doc["_id"] = str(doc["_id"])
        doc["created_at"] = doc["created_at"].strftime("%Y-%m-%d %H:%M UTC") \
            if hasattr(doc.get("created_at"), "strftime") else str(doc.get("created_at", ""))
        runs.append(doc)
    return JSONResponse({"ok": True, "runs": runs})


@router.get("/download-history/{record_id}")
async def download_history_excel(record_id: str):
    """Regenerate and stream an Excel file for a historical reconciliation record."""
    db = get_db()
    if db is None:
        raise HTTPException(503, "MongoDB not configured.")
    try:
        from bson import ObjectId
        doc = db["recon_history"].find_one({"_id": ObjectId(record_id)})
    except Exception:
        raise HTTPException(400, "Invalid record ID.")
    if doc is None:
        raise HTTPException(404, "Record not found.")

    rd = doc.get("result_data", {})

    def _json_to_df(d: dict) -> pd.DataFrame:
        if not d or not d.get("columns"):
            return pd.DataFrame()
        df = pd.DataFrame(d["rows"], columns=d["columns"])
        for col in df.columns:
            if any(frag in col.lower() for frag in
                   ["amount", "amt", "earn", "bene", "deduc", "tax",
                    "net", "debit", "credit", "variance", "balance"]):
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        return df

    recon_df = _json_to_df(rd.get("recon_table"))
    gl_pivot = _json_to_df(rd.get("gl_pivot"))
    pr_pivot = _json_to_df(rd.get("pr_pivot"))

    try:
        mapping_rows = _load_config(doc.get("client_name", "default"))
    except Exception:
        mapping_rows = []

    excel_bytes = export_to_excel(
        gl_mapped    = pd.DataFrame(),
        pr_mapped    = pd.DataFrame(),
        gl_pivot     = gl_pivot,
        pr_pivot     = pr_pivot,
        recon_df     = recon_df,
        period_label = doc.get("period_label", ""),
        client_name  = doc.get("client_name", ""),
        mapping_rows = mapping_rows,
    )

    timestamp   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    safe_period = re.sub(r"[^\w]", "_", doc.get("period_label", "") or "report")
    safe_client = re.sub(r"[^\w]", "_", doc.get("client_name", "") or "")
    client_part = f"{safe_client}_" if safe_client and safe_client.lower() != "default" else ""
    filename    = f"Payroll_Recon_{client_part}{safe_period}_{timestamp}.xlsx"

    return StreamingResponse(
        iter([excel_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/recon-history/{record_id}")
async def get_recon_history_record(record_id: str):
    """Return a single history record including full result_data."""
    db = get_db()
    if db is None:
        raise HTTPException(503, "MongoDB not configured.")
    try:
        from bson import ObjectId
        doc = db["recon_history"].find_one({"_id": ObjectId(record_id)})
    except Exception:
        raise HTTPException(400, "Invalid record ID.")
    if doc is None:
        raise HTTPException(404, "Record not found.")
    doc["_id"] = str(doc["_id"])
    doc["created_at"] = doc["created_at"].strftime("%Y-%m-%d %H:%M UTC") \
        if hasattr(doc.get("created_at"), "strftime") else str(doc.get("created_at", ""))
    return JSONResponse({"ok": True, "record": doc})


@router.get("/gl-codes")
async def get_gl_codes(session_id: str):
    """Return unique GL code → title pairs from the session's uploaded GL file."""
    gl_file   = state.get_file(session_id, "gl_report")
    gl_col_map = state.get_mapping(session_id, "gl_report")
    if not gl_file or not gl_col_map:
        return JSONResponse({"ok": False, "codes": {}})

    df  = gl_file["df"]
    inv = {role: col for col, role in gl_col_map.items() if role}
    code_col  = inv.get("gl_code")
    title_col = inv.get("gl_title")

    if not code_col or code_col not in df.columns:
        return JSONResponse({"ok": False, "codes": {}})

    subset_cols = [code_col] + ([title_col] if title_col and title_col in df.columns else [])
    subset = df[subset_cols].drop_duplicates()

    codes: dict = {}
    for _, row in subset.iterrows():
        code = str(row[code_col]).strip().split(".")[0]
        title = str(row[title_col]).strip() if title_col and title_col in df.columns else ""
        if code and code.lower() != "nan":
            codes[code] = title

    # Sort numerically when possible
    def _sort_key(c):
        try: return (0, int(c))
        except ValueError: return (1, c)

    sorted_codes = dict(sorted(codes.items(), key=lambda kv: _sort_key(kv[0])))
    return JSONResponse({"ok": True, "codes": sorted_codes})


@router.get("/pr-codes")
async def get_pr_codes(session_id: str):
    """Return unique pay_code → code_type pairs from the session's uploaded payroll register."""
    pr_file    = state.get_file(session_id, "payroll_register")
    pr_col_map = state.get_mapping(session_id, "payroll_register")
    if not pr_file or not pr_col_map:
        return JSONResponse({"ok": False, "codes": {}})

    df  = pr_file["df"]
    inv = {role: col for col, role in pr_col_map.items() if role}
    pay_code_col  = inv.get("pay_code")
    code_type_col = inv.get("code_type")

    if not pay_code_col or pay_code_col not in df.columns:
        return JSONResponse({"ok": False, "codes": {}})

    title_col = inv.get("pay_code_title")
    subset_cols = [pay_code_col]
    if code_type_col and code_type_col in df.columns:
        subset_cols.append(code_type_col)
    if title_col and title_col in df.columns:
        subset_cols.append(title_col)
    subset = df[subset_cols].drop_duplicates()

    codes: dict = {}
    for _, row in subset.iterrows():
        code  = str(row[pay_code_col]).strip()
        ctype = str(row[code_type_col]).strip() if code_type_col and code_type_col in df.columns else ""
        title = str(row[title_col]).strip() if title_col and title_col in df.columns else ""
        if code and code.lower() != "nan":
            codes[code] = {
                "code_type": ctype if ctype.lower() != "nan" else "",
                "title":     title if title.lower() != "nan" else "",
            }

    sorted_codes = dict(sorted(codes.items(), key=lambda kv: kv[0]))
    return JSONResponse({"ok": True, "codes": sorted_codes})


@router.get("/db-status")
async def db_status():
    """Return whether MongoDB is connected."""
    db = get_db()
    return JSONResponse({
        "mongo_connected": db is not None,
        "storage": "mongodb" if db is not None else "file",
    })


# ── helpers ────────────────────────────────────────────────────────────────────

def _validate_column_mapping(
    gl_df:      pd.DataFrame,
    inv_gl_map: dict,
    gl_lookup:  dict,
) -> dict:
    """
    Check that the mapped GL code column actually contains GL account codes
    that exist in the reconciliation config.

    Returns a dict with diagnostic info — the caller decides whether to block.
    """
    gl_code_col = inv_gl_map.get("gl_code", "")
    result = {
        "gl_code_col":      gl_code_col,
        "gl_col_sample":    [],
        "config_gl_codes":  len(gl_lookup),
        "gl_code_match_pct": 0,
        "gl_col_max_len":   0,
    }

    if not gl_code_col or gl_code_col not in gl_df.columns:
        return result

    # Sample unique values from the mapped gl_code column
    raw_values = (
        gl_df[gl_code_col]
        .dropna()
        .astype(str)
        .str.strip()
        .str.split(".")
        .str[0]        # strip ".0" suffix (e.g. "5000.0" → "5000")
        .unique()
    )
    sample = [v for v in raw_values[:20] if v and v.lower() != "nan"]
    result["gl_col_sample"] = sample[:10]

    if not sample:
        return result

    # Detect max value length — fund codes are 1-2 digits, GL codes are 4-5
    max_len = max((len(v) for v in sample), default=0)
    result["gl_col_max_len"] = max_len

    if not gl_lookup:
        return result

    # Count how many column values match config GL codes
    file_codes  = set(sample)
    config_codes = set(gl_lookup.keys())
    matches = len(file_codes & config_codes)
    result["gl_code_match_pct"] = round(matches / len(config_codes) * 100, 1) if config_codes else 0

    return result


_DATE_ROLE_FALLBACKS = [
    "date", "doc_date", "pay_date", "period_end_date", "period_start_date",
]


def _resolve_date_col(inv_col_map: dict, df_columns) -> Optional[str]:
    """Return the first mapped date-like column that exists in the DataFrame."""
    for role in _DATE_ROLE_FALLBACKS:
        col = inv_col_map.get(role)
        if col and col in df_columns:
            return col
    return None


def _extract_date_range(df: pd.DataFrame, inv_col_map: dict) -> dict:
    """Return {"min": "YYYY-MM", "max": "YYYY-MM"} from the best available date column."""
    date_col = _resolve_date_col(inv_col_map, df.columns)
    if not date_col:
        logger.warning(
            "Period filter: no date column found in mapping (checked roles: %s). "
            "Available columns: %s",
            _DATE_ROLE_FALLBACKS,
            list(df.columns),
        )
        return {}
    try:
        parsed = parse_dates_smart(df[date_col], col_name=date_col).dropna()
        if parsed.empty:
            return {}
        return {
            "min": parsed.min().strftime("%Y-%m"),
            "max": parsed.max().strftime("%Y-%m"),
        }
    except Exception:
        return {}


def _safe_float(v) -> Optional[float]:
    """Return a JSON-safe float (None for NaN/inf instead of raising ValueError)."""
    try:
        f = float(v)
        if f != f or f == float("inf") or f == float("-inf"):
            return None
        return round(f, 2)
    except (TypeError, ValueError):
        return None


def _df_to_json(df: pd.DataFrame) -> dict:
    """Convert DataFrame to {columns: [], rows: [[]]} for the frontend table."""
    df_clean = df.fillna("").copy()
    # Round floats for display
    for col in df_clean.select_dtypes(include="number").columns:
        df_clean[col] = df_clean[col].round(2)
    return {
        "columns": list(df_clean.columns),
        "rows":    df_clean.astype(str).values.tolist(),
    }


# ── Terminal report ────────────────────────────────────────────────────────────

def _print_terminal_report(
    recon_df:     pd.DataFrame,
    summary:      dict,
    client_name:  str,
    period_label: str,
    period_start: Optional[str],
    period_end:   Optional[str],
    gl_filename:  str,
    pr_filename:  str,
    unmapped_gl:  list,
    unmapped_pr:  list,
) -> None:
    """Print a formatted reconciliation report to the terminal (stdout / log)."""

    W = 100   # total width

    def _line(char: str = "─") -> str:
        return char * W

    def _centre(text: str, char: str = " ") -> str:
        return text.center(W, char)

    def _fmt(v) -> str:
        try:
            f = float(v)
            if f != f:      # NaN check (NaN != NaN is always True)
                return "            N/A"
            sign = "-" if f < 0 else " "
            return f"{sign}${abs(f):>14,.2f}"
        except (TypeError, ValueError):
            return f"  {str(v or ''):>14}"

    now = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")

    # ── header ──────────────────────────────────────────────────────────────
    lines = [
        "",
        _line("═"),
        _centre("  PAYROLL RECONCILIATION REPORT  "),
        _line("═"),
        f"  Client   : {client_name}",
        f"  Period   : {period_label or 'All data'}",
    ]
    if period_start or period_end:
        lines.append(f"  Filter   : {period_start or '?'} → {period_end or '?'}")
    lines += [
        f"  GL File  : {gl_filename}",
        f"  PR File  : {pr_filename}",
        f"  Run at   : {now}",
        _line(),
    ]

    # ── summary ─────────────────────────────────────────────────────────────
    diag = summary.get("diagnostics", {})
    gl_rows   = diag.get("gl_rows_used", "?")
    pr_rows   = diag.get("pr_rows_used", "?")
    gl_earn   = diag.get("gl_earn_total", 0)
    pr_earn   = diag.get("pr_earn_total", 0)
    total_var = summary.get("total_variance", 0)
    matched   = summary.get("matched", 0)
    variances = summary.get("variances", 0)
    total_ln  = summary.get("total_lines", 0)
    gl_only   = summary.get("gl_only_lines", 0)
    is_clean  = summary.get("is_clean", False)

    def _int(v) -> str:
        """Format an integer count — safe for '?' strings and None."""
        try:
            return f"{int(v):,}"
        except (TypeError, ValueError):
            return str(v or "?")

    status_icon = "✓  CLEAN" if is_clean else f"⚠  {variances} VARIANCE(S)"
    lines += [
        f"  Status   : {status_icon}",
        f"  Matched  : {matched} / {total_ln} lines" + (f"  |  GL-Only: {gl_only}" if gl_only else ""),
        f"  GL rows  : {_int(gl_rows)}  |  PR rows: {_int(pr_rows)}",
        f"  GL Gross : {_fmt(gl_earn)}  |  PR Gross: {_fmt(pr_earn)}",
        f"  Total Variance: {_fmt(total_var).strip()}",
        _line(),
    ]

    # ── reconciliation table ─────────────────────────────────────────────────
    # Column widths
    _CW = {"step": 34, "code": 6, "title": 28, "gl": 14, "pr": 14, "var": 14, "status": 12}
    _HDR = (
        f"  {'Step':<{_CW['step']}} {'Code':>{_CW['code']}}  "
        f"{'Title':<{_CW['title']}} {'GL Net':>{_CW['gl']}}  "
        f"{'PR Amount':>{_CW['pr']}}  {'Variance':>{_CW['var']}}  {'Status':<{_CW['status']}}"
    )
    lines.append(_HDR)
    lines.append("  " + _line("─")[2:])

    last_step = None
    data_rows = recon_df[recon_df["Reconciliation Step"] != "TOTAL"]

    for _, row in data_rows.iterrows():
        step   = str(row.get("Reconciliation Step", "")).strip()
        code   = str(row.get("GL Code", "")).strip()
        title  = str(row.get("GL Title", "")).strip()
        gl_net = row.get("GL Net Amount", 0)
        pr_amt = row.get("PR Amount", 0)
        var    = row.get("Variance", 0)
        status = str(row.get("Status", "")).strip()
        notes  = str(row.get("Notes", "")).strip()

        # Section header when step changes
        if step != last_step:
            lines.append(f"\n  ── {step} ──")
            last_step = step

        # Truncate title for display
        title_d  = (title[:_CW["title"] - 1] + "…") if len(title) > _CW["title"] else title
        step_d   = ""   # already shown in section header

        var_str  = _fmt(var)
        is_match = "Match" in status
        is_only  = "GL Only" in status

        if is_only:
            status_d = "GL Only"
        elif is_match:
            status_d = "✓ Match"
        else:
            status_d = "⚠ Variance"

        line = (
            f"  {step_d:<{_CW['step']}} {code:>{_CW['code']}}  "
            f"{title_d:<{_CW['title']}} {_fmt(gl_net):>{_CW['gl']}}  "
            f"{_fmt(pr_amt):>{_CW['pr']}}  {var_str:>{_CW['var']}}  {status_d:<{_CW['status']}}"
        )
        if notes and not is_match and not is_only:
            line += f"  [{notes}]"
        lines.append(line)

    # Total row
    total_row = recon_df[recon_df["Reconciliation Step"] == "TOTAL"]
    if not total_row.empty:
        tr = total_row.iloc[0]
        lines += [
            "  " + _line("─")[2:],
            (
                f"  {'GRAND TOTAL':<{_CW['step']}} {'':>{_CW['code']}}  "
                f"{'':< {_CW['title']}} {_fmt(tr['GL Net Amount']):>{_CW['gl']}}  "
                f"{_fmt(tr['PR Amount']):>{_CW['pr']}}  {_fmt(tr['Variance']):>{_CW['var']}}"
            ),
        ]

    lines.append(_line())

    # ── unmapped ─────────────────────────────────────────────────────────────
    if unmapped_gl:
        lines.append(f"  ⚠  GL codes not in config ({len(unmapped_gl)}): {', '.join(str(c) for c in unmapped_gl)}")
    if unmapped_pr:
        pr_strs = [f"{k[0]}/{k[1]}" for k in unmapped_pr]
        lines.append(f"  ⚠  PR pay codes not in config ({len(unmapped_pr)}): {', '.join(pr_strs)}")
    if unmapped_gl or unmapped_pr:
        lines.append(_line())

    lines.append("")
    print("\n".join(lines), flush=True)   # flush ensures immediate output in the terminal
