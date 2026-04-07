"""
mapping_config.py
──────────────────
Manages the per-client reconciliation mapping configuration.

GET  /api/mapping-config              → return saved config (or default template)
POST /api/mapping-config              → save config for a client
DELETE /api/mapping-config            → reset to default
GET  /api/mapping-config/template     → return the default template always
"""

import json
import logging
import re
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config.default_mapping import DEFAULT_MAPPING_ROWS
from config.settings import (
    CLIENT_MAPPINGS_DIR, AWS_REGION, AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY, BEDROCK_MODEL_ID,
)
from backend.api.db import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Pydantic models ────────────────────────────────────────────────────────────

class MappingRow(BaseModel):
    recon_step:      str
    gl_code:         str
    gl_title:        str
    pay_code:        str
    pay_code_title:  str
    amount_column:   str
    code_type:       str
    account_type:    str = ""   # "expense" | "liability" | "bank" | "glonly" | ""


class SaveMappingRequest(BaseModel):
    client_name: str
    rows:        List[MappingRow]


class GenerateMappingRequest(BaseModel):
    client_name: str = "default"
    description: str
    current_rows: list = []   # existing table rows — empty means generate from scratch


# ── Helpers ────────────────────────────────────────────────────────────────────

def _config_path(client_name: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in client_name)
    return CLIENT_MAPPINGS_DIR / f"{safe}__recon_config.json"


def _merge_with_defaults(saved: list) -> list:
    """Merge saved rows with DEFAULT_MAPPING_ROWS.

    Any default row not present in the saved config is appended so that
    new default entries added after a config was first saved always appear.
    Saved-only rows (client customisations) are preserved as-is.
    """
    default_rows  = [dict(r) for r in DEFAULT_MAPPING_ROWS]
    saved_keys    = {
        f"{r.get('recon_step', '')}|{r.get('gl_code', '')}|{r.get('pay_code', '')}"
        for r in saved
    }

    merged = list(saved)
    for row in default_rows:
        key = f"{row['recon_step']}|{row['gl_code']}|{row['pay_code']}"
        if key not in saved_keys:
            merged.append(row)

    # Keep default step-order; custom-only steps go to the end
    step_order = list(dict.fromkeys(r["recon_step"] for r in default_rows))
    def _step_rank(r):
        try:
            return step_order.index(r.get("recon_step", ""))
        except ValueError:
            return len(step_order)

    merged.sort(key=_step_rank)
    return merged


def _load_config(client_name: str) -> list:
    """Return the saved config for client_name, or the default template if none saved.

    Saved configs are returned as-is — no auto-merging with defaults.
    Auto-merging caused removed rows to reappear after a client deleted them,
    and prevented updated default values (e.g. amount_column fixes) from taking
    effect. To pick up new defaults, users can reset via DELETE /api/mapping-config.
    """
    # ── Try MongoDB first ──────────────────────────────────────────────────
    db = get_db()
    if db is not None:
        doc = db["mapping_configs"].find_one({"client_name": client_name})
        if doc:
            return doc["rows"]   # saved config is authoritative
        return [dict(r) for r in DEFAULT_MAPPING_ROWS]

    # ── Fallback: file storage ─────────────────────────────────────────────
    path = _config_path(client_name)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)  # saved config is authoritative
    return [dict(r) for r in DEFAULT_MAPPING_ROWS]


def _save_config(client_name: str, rows: list):
    # ── Try MongoDB first ──────────────────────────────────────────────────
    db = get_db()
    if db is not None:
        from datetime import datetime, timezone
        db["mapping_configs"].update_one(
            {"client_name": client_name},
            {"$set": {"rows": rows, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        return

    # ── Fallback: file storage ─────────────────────────────────────────────
    path = _config_path(client_name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/mapping-config")
async def get_mapping_config(client_name: str = "default"):
    rows = _load_config(client_name)
    return JSONResponse({"client_name": client_name, "rows": rows})


@router.get("/mapping-config/template")
async def get_default_template():
    return JSONResponse({"rows": [dict(r) for r in DEFAULT_MAPPING_ROWS]})


@router.post("/mapping-config")
async def save_mapping_config(req: SaveMappingRequest):
    if not req.rows:
        raise HTTPException(400, "Cannot save an empty mapping configuration.")

    rows = [r.dict() for r in req.rows]
    _save_config(req.client_name, rows)
    logger.info("Saved mapping config for client '%s' (%d rows).", req.client_name, len(rows))
    return JSONResponse({"ok": True, "client_name": req.client_name, "row_count": len(rows)})


_ROW_SCHEMA = """\
Each row must have EXACTLY these 7 fields:
{
  "recon_step":     "Step label, e.g. A. Earning/ Gross wages",
  "gl_code":        "GL account code, e.g. 5000",
  "gl_title":       "GL account name, e.g. Salaries & Wages",
  "pay_code":       "Payroll code, e.g. Wages",
  "pay_code_title": "Human-readable name, e.g. Regular Wages",
  "amount_column":  "Exactly one of: EarnAmt | BeneAmt | DeducAmt | EETax | ERTax | EETax & ERTax | NetAmt",
  "code_type":      "Exactly one of: EARNING | BENEFIT | DEDUCT | TAXES | (empty string)"
}"""

_GENERATE_PROMPT = """\
You are a payroll reconciliation expert for MIP accounting software.
Generate a JSON array of reconciliation mapping rows based on the user's description.

""" + _ROW_SCHEMA + """

Standard reconciliation step structure:
- Step A  (Earnings): GL 5xxx expense → EarnAmt, EARNING
- Step B  (Benefits/ER Expense): GL 5130-5140 → BeneAmt, BENEFIT
- Step B.1 (Benefit Liabilities): GL 2145-2148 liability → BeneAmt, BENEFIT
- Step C  (Deductions/EE Liabilities): GL 2121-2143 → DeducAmt, DEDUCT
- Step D  (EE & ER Tax Liabilities): GL 2115, 2120 → EETax & ERTax (or EETax), TAXES
- Step E  (ER Tax Expense): GL 5100 → ERTax, TAXES
- Step F  (Bank Payment): GL 1020 → NetAmt, "" (empty code_type)

Rules:
- Medicare and Social Security need TWO appearances: once in Step D (EeTax & ERTax) and once in Step E (ERTax only)
- Benefits with both expense and liability GLs get two rows per pay code
- Always include the Bank Payment row (Step F, GL 1020, NetAmt)
- Use the exact GL codes and pay codes the user mentions; infer standard ones for anything not mentioned
- Return ONLY a valid JSON array. No markdown, no code fences, no explanation."""


def _edit_prompt(current_rows: list) -> str:
    current_json = json.dumps(current_rows, indent=2)
    return f"""\
You are a payroll reconciliation mapping editor for MIP accounting software.

You will be given the CURRENT mapping configuration (a JSON array) and a natural-language instruction.
Apply ONLY the requested change and return the COMPLETE updated JSON array.

""" + _ROW_SCHEMA + """

EDITING RULES:
- Return ONLY a valid JSON array. No markdown, no code fences, no explanation.
- Make ONLY the changes the user requested. Preserve ALL other rows exactly as they are.
- ADD: insert the new row in the correct position (group it with rows sharing the same recon_step and gl_code).
- REMOVE: delete only the rows that match the description. Be conservative — if ambiguous, keep the row.
- MODIFY: update only the fields mentioned; leave every other field unchanged.
- RENAME / MOVE: update recon_step or gl_code across every affected row so grouping stays consistent.
- If the instruction is to generate a brand-new mapping from scratch, replace all rows.

CURRENT MAPPING ({n} rows):
{current_json}""".format(n=len(current_rows), current_json=current_json)


@router.post("/generate-mapping")
async def generate_mapping_from_description(req: GenerateMappingRequest):
    """
    Use AWS Bedrock (Claude) to generate or edit reconciliation mapping rows.
    When current_rows is provided the AI edits the existing table in place.
    When current_rows is empty the AI generates a complete mapping from the description.
    """
    if not req.description.strip():
        raise HTTPException(400, "Description cannot be empty.")

    system_prompt = _edit_prompt(req.current_rows) if req.current_rows else _GENERATE_PROMPT
    mode          = "edit" if req.current_rows else "generate"

    try:
        import boto3
        kwargs = {"region_name": AWS_REGION}
        if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
            kwargs["aws_access_key_id"]     = AWS_ACCESS_KEY_ID
            kwargs["aws_secret_access_key"] = AWS_SECRET_ACCESS_KEY

        client = boto3.client("bedrock-runtime", **kwargs)

        # Haiku has a hard 4096-token output cap; Sonnet/Opus support higher limits.
        # Use 4096 as a safe default and rely on partial-recovery logic if hit.
        model_max = 8192 if "sonnet" in BEDROCK_MODEL_ID.lower() or "opus" in BEDROCK_MODEL_ID.lower() else 4096

        body   = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": model_max,
            "system":   system_prompt,
            "messages": [{"role": "user", "content": req.description}],
        })

        response    = client.invoke_model(
            modelId     = BEDROCK_MODEL_ID,
            contentType = "application/json",
            accept      = "application/json",
            body        = body,
        )
        resp_body   = json.loads(response["body"].read())
        stop_reason = resp_body.get("stop_reason", "")
        text        = resp_body["content"][0]["text"].strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        text = text.strip()

        warning = None
        if stop_reason == "max_tokens":
            logger.warning(
                "AI mapping %s hit max_tokens (%d chars) — attempting partial JSON recovery.",
                mode, len(text),
            )
            # Try to salvage the truncated array: find the last complete object and close the array.
            last_brace = text.rfind('}')
            if last_brace != -1:
                salvaged = text[:last_brace + 1].rstrip().rstrip(',') + '\n]'
                try:
                    rows = json.loads(salvaged)
                    if isinstance(rows, list) and rows:
                        warning = (
                            f"The AI response was truncated — recovered {len(rows)} rows. "
                            "The configuration may be incomplete. Review and add any missing rows manually."
                        )
                        logger.info(
                            "AI %s (partial) — recovered %d rows for client '%s'.",
                            mode, len(rows), req.client_name,
                        )
                        return JSONResponse({
                            "ok":      True,
                            "rows":    rows,
                            "count":   len(rows),
                            "prev":    len(req.current_rows),
                            "mode":    mode,
                            "source":  "ai",
                            "warning": warning,
                        })
                except (json.JSONDecodeError, ValueError):
                    pass
            raise HTTPException(
                400,
                "The AI response was too long and could not be recovered. "
                "Try a shorter or more focused description, or configure the table manually."
            )

        rows = json.loads(text)
        if not isinstance(rows, list):
            raise ValueError("Expected a JSON array from the AI.")

        logger.info(
            "AI %s — %d rows for client '%s' (was %d).",
            mode, len(rows), req.client_name, len(req.current_rows),
        )
        return JSONResponse({
            "ok":      True,
            "rows":    rows,
            "count":   len(rows),
            "prev":    len(req.current_rows),
            "mode":    mode,
            "source":  "ai",
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("AI mapping %s failed", mode)
        raise HTTPException(500, f"AI request failed: {e}")


@router.delete("/mapping-config")
async def reset_mapping_config(client_name: str = "default"):
    db = get_db()
    if db is not None:
        db["mapping_configs"].delete_one({"client_name": client_name})
    else:
        path = _config_path(client_name)
        if path.exists():
            path.unlink()
    return JSONResponse({"ok": True, "message": f"Reset to default for '{client_name}'"})


# ── Shared helper ──────────────────────────────────────────────────────────────

def _strip_step_prefix(text: str) -> str:
    """Remove leading letter-based classification prefix from a recon step name.
    e.g. 'A. Earning/ Gross wages'  → 'Earning/ Gross wages'
         'B.1 Benefits / Expenses'  → 'Benefits / Expenses'
         'D. Employee & ER Taxes'   → 'Employee & ER Taxes'
    """
    return re.sub(r"^[A-Z][0-9.]*\.?\s+", "", text.strip())


# ── Used by the reconciliation pipeline ───────────────────────────────────────

def _derive_account_type(gl_code: str, amount_col: str) -> str:
    """
    Derive account_type from GL code first digit when not explicitly set.
    This ensures backwards compatibility with existing configs that
    don't have the account_type field.

    Rules:
      GLOnly amount_column             → glonly
      First digit 1                   → bank
      First digit 2                   → liability
      Everything else (5, 6, 7, etc.) → expense
    """
    if amount_col.strip().lower() == "glonly":
        return "glonly"
    # Handle combined codes like "2142/2150" — use first code
    first_code = gl_code.split("/")[0].strip().lstrip("0")
    if not first_code:
        return "expense"
    d = first_code[0]
    if d == "1":
        return "bank"
    if d == "2":
        return "liability"
    return "expense"


def build_lookups_from_config(rows: list):
    """
    Build GL and PR lookup dicts from the mapping config rows.

    gl_lookup : { gl_code → { gl_title, recon_step, code_type, amount_column } }
    pr_lookup : { (pay_code_upper, code_type_upper) → "GL_CODE - GL_TITLE [& ...]" }
    gl_pr_amount : { gl_code → { pr_mapping_string → amount_column } }

    The third dict is the key to correct reconciliation: different pay codes that
    map to the same GL code may use DIFFERENT amount columns (e.g. GL 2115 has
    FIT → EeTax  and  MC/SS → EeTax & ERTax).  Using a single amount_column per
    GL code (first-occurrence wins) misses the ERTax component for MC/SS, causing
    a systematic variance equal to the FICA employer tax total.
    """
    from collections import defaultdict

    gl_lookup = {}
    pr_groups = defaultdict(list)

    for row in rows:
        gl_code      = str(row.get("gl_code", "")).strip()
        gl_title     = str(row.get("gl_title", "")).strip()
        pay_code     = str(row.get("pay_code", "")).strip()
        code_type    = str(row.get("code_type", "")).strip().upper()
        recon_step   = str(row.get("recon_step", "")).strip()
        amount_col   = str(row.get("amount_column", "")).strip()
        account_type = str(row.get("account_type", "")).strip().lower()

        # Auto-derive account_type from GL code if not explicitly set
        if account_type not in ("expense", "liability", "bank", "glonly"):
            account_type = _derive_account_type(gl_code, amount_col)

        # Handle combined GL codes like "2142/2150"
        individual_codes = [c.strip() for c in gl_code.split("/") if c.strip()]
        is_combined = len(individual_codes) > 1

        # GL lookup: one entry per individual GL code
        for ind_code in individual_codes:
            if ind_code and ind_code not in gl_lookup:
                entry = {
                    "gl_title":      gl_title,
                    "recon_step":    _strip_step_prefix(recon_step),
                    "code_type":     code_type,
                    "amount_column": amount_col,
                    "account_type":  account_type,
                }
                if is_combined:
                    entry["combined_gl_code"] = gl_code
                gl_lookup[ind_code] = entry

        # PR lookup: group by (pay_code, code_type) → collect GL codes
        # Use the original gl_code (combined or not) as the display label
        if pay_code and code_type:
            key    = (pay_code.upper(), code_type)
            gl_str = f"{gl_code} - {gl_title}"
            if gl_str not in pr_groups[key]:
                pr_groups[key].append(gl_str)

    pr_lookup = {
        key: " & ".join(gl_strings)
        for key, gl_strings in pr_groups.items()
    }

    # ── Build per-PR-row amount column lookup ─────────────────────────────────
    # For each GL code, map each PR pivot "Reconciliation Mapping" string to the
    # exact amount column that should be read for that GL code from that PR row.
    #
    # This is critical when a GL code receives contributions from pay codes that
    # use DIFFERENT amount columns.  Example (default mapping, GL 2115):
    #   FIT  (EeTax only)      → PR mapping "2115 - Federal payroll taxes payable"
    #   MC   (EeTax & ERTax)   → PR mapping "2115 - ... & 5100 - Fica expense"
    #   SS   (EeTax & ERTax)   → same mapping as MC
    # Without this, summing only EeTax for the MC/SS row misses all employer FICA.
    gl_pr_amount: dict = defaultdict(dict)  # { gl_code → { pr_mapping → amount_col } }

    for row in rows:
        gl_code   = str(row.get("gl_code", "")).strip()
        pay_code  = str(row.get("pay_code", "")).strip()
        code_type = str(row.get("code_type", "")).strip().upper()
        amount_col= str(row.get("amount_column", "")).strip()

        if not gl_code or not pay_code or not code_type:
            continue

        pr_mapping = pr_lookup.get((pay_code.upper(), code_type), "")
        if not pr_mapping:
            continue

        # Register the amount column for EACH individual GL code
        for ind_code in (c.strip() for c in gl_code.split("/") if c.strip()):
            existing = gl_pr_amount[ind_code].get(pr_mapping, "")
            if not existing:
                gl_pr_amount[ind_code][pr_mapping] = amount_col
            elif existing.lower() != amount_col.lower():
                parts: set = set()
                for s in (existing, amount_col):
                    parts.update(p.strip() for p in s.replace("&", ",").split(",") if p.strip())
                has_ee = any(p.lower() == "eetax" for p in parts)
                has_er = any(p.lower() == "ertax" for p in parts)
                if has_ee and has_er:
                    gl_pr_amount[ind_code][pr_mapping] = "EeTax & ERTax"
                else:
                    gl_pr_amount[ind_code][pr_mapping] = " & ".join(sorted(parts))

    return gl_lookup, pr_lookup, dict(gl_pr_amount)


@router.get("/mapping-config/export")
async def export_mapping_config_excel(client_name: str = "default"):
    """
    Export the current mapping config for a client as a formatted Excel file.
    The user can edit it offline and re-upload via POST /api/mapping-config/import.
    """
    import io
    import xlsxwriter

    rows = _load_config(client_name)

    output = io.BytesIO()
    wb     = xlsxwriter.Workbook(output, {"in_memory": True})
    ws     = wb.add_worksheet("Mapping Config")

    # Formats
    fmt_hdr = wb.add_format({
        "bold": True, "bg_color": "#1F3864", "font_color": "#FFFFFF",
        "border": 1, "align": "center", "font_size": 10,
    })
    fmt_step = wb.add_format({"bold": True, "bg_color": "#D6E4F7", "border": 1, "font_size": 10})
    fmt_code = wb.add_format({"bg_color": "#E8F5E9", "font_color": "#1B5E20", "bold": True, "border": 1, "font_size": 10})
    fmt_text = wb.add_format({"border": 1, "font_size": 10})
    fmt_alt  = wb.add_format({"border": 1, "font_size": 10, "bg_color": "#EEF4FB"})
    fmt_drop = wb.add_format({"border": 1, "font_size": 10, "bg_color": "#FFF3E0", "font_color": "#C15700"})

    # Instructions row
    ws.merge_range(0, 0, 0, 7,
        "Payroll Reconciliation Mapping Config — Edit GL Code, GL Title, Pay Code, Pay Code Title, "
        "Amount Column, Code Type, Account Type. Do NOT change column order. Save and upload via Configuration page.",
        wb.add_format({"italic": True, "bg_color": "#FFF9C4", "border": 1, "font_size": 9, "text_wrap": True}),
    )
    ws.set_row(0, 28)

    # Headers
    headers    = ["STEPS of Reconciliation", "GL Code", "GL Title", "Pay Code", "Pay Code Title", "Amount Column", "Code Type", "Account Type"]
    col_widths = [42, 12, 32, 14, 30, 16, 12, 12]
    for c, (h, w) in enumerate(zip(headers, col_widths)):
        ws.write(1, c, h, fmt_hdr)
        ws.set_column(c, c, w)
    ws.freeze_panes(2, 0)

    # Dropdown validations
    AMOUNT_OPTIONS  = "EarnAmt,BeneAmt,DeducAmt,EETax,ERTax,EeTax & ERTax,NetAmt,GLOnly"
    TYPE_OPTIONS    = "EARNING,BENEFIT,DEDUCT,TAXES,"
    ACCT_OPTIONS    = "expense,liability,bank,glonly,"
    ws.data_validation(2, 5, 2000, 5, {"validate": "list", "source": AMOUNT_OPTIONS.split(",")})
    ws.data_validation(2, 6, 2000, 6, {"validate": "list", "source": TYPE_OPTIONS.split(",")})
    ws.data_validation(2, 7, 2000, 7, {"validate": "list", "source": ACCT_OPTIONS.split(",")})

    # Data rows
    last_step  = None
    data_count = 0
    for row in rows:
        step = str(row.get("recon_step", "")).strip()
        if step != last_step:
            ws.merge_range(2 + data_count, 0, 2 + data_count, 6, step, fmt_step)
            data_count += 1
            last_step   = step

        is_alt = data_count % 2 == 1
        base   = fmt_alt if is_alt else fmt_text
        ws.write(2 + data_count, 0, step,                                           base)
        ws.write(2 + data_count, 1, str(row.get("gl_code",        "")).strip(),     fmt_code)
        ws.write(2 + data_count, 2, str(row.get("gl_title",       "")).strip(),     base)
        ws.write(2 + data_count, 3, str(row.get("pay_code",       "")).strip(),     fmt_code)
        ws.write(2 + data_count, 4, str(row.get("pay_code_title", "")).strip(),     base)
        ws.write(2 + data_count, 5, str(row.get("amount_column",  "")).strip(),     fmt_drop)
        ws.write(2 + data_count, 6, str(row.get("code_type",      "")).strip(),     fmt_drop)
        ws.write(2 + data_count, 7, str(row.get("account_type",   "")).strip(),     fmt_drop)
        data_count += 1

    wb.close()
    output.seek(0)
    excel_bytes = output.read()

    import re as _re
    safe_client = _re.sub(r"[^\w]", "_", client_name or "default")
    filename    = f"mapping_config_{safe_client}.xlsx"

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        iter([excel_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/mapping-config/import")
async def import_mapping_config_excel(
    file:        UploadFile = File(...),
    client_name: str        = Form("default"),
):
    """
    Accept an uploaded Excel file (the exported mapping config format),
    parse it, validate the columns, and return rows for preview.
    Does NOT save automatically — call POST /api/mapping-config to save.
    """
    import io
    import pandas as pd

    raw = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(raw), header=None)
    except Exception as e:
        raise HTTPException(400, f"Could not read Excel file: {e}")

    # Find the header row — must have the keywords spread across at LEAST 2 distinct columns.
    # (The exported file has an instruction row at row 0 where all text is in one merged cell,
    #  and the real header is at row 1 with each column labelled separately.)
    header_row = None
    _HEADER_KEYWORDS = ("gl code", "steps", "pay code", "amount", "code type")
    for i, row in df.iterrows():
        vals       = [str(v).strip().lower() for v in row]
        match_cols = [j for j, v in enumerate(vals) if any(k in v for k in _HEADER_KEYWORDS)]
        if len(match_cols) >= 2:
            header_row = i
            break

    if header_row is None:
        raise HTTPException(400, "Could not find header row. Expected columns: STEPS of Reconciliation, GL Code, GL Title, Pay Code, Pay Code Title, Amount Column, Code Type")

    df.columns = [str(v).strip() for v in df.iloc[header_row]]
    df = df.iloc[header_row + 1:].reset_index(drop=True)

    # Map flexible column names
    col_map = {}
    for col in df.columns:
        cl = col.lower()
        if "step" in cl or "recon" in cl:
            col_map["recon_step"] = col
        elif "gl code" in cl or cl == "gl_code":
            col_map["gl_code"] = col
        elif "gl title" in cl or cl == "gl_title":
            col_map["gl_title"] = col
        elif "pay code title" in cl or "pay_code_title" in cl:
            col_map["pay_code_title"] = col
        elif "pay code" in cl or cl == "pay_code":
            col_map["pay_code"] = col
        elif "amount" in cl:
            col_map["amount_column"] = col
        elif "code type" in cl or "code_type" in cl:
            col_map["code_type"] = col
        elif "account type" in cl or "account_type" in cl:
            col_map["account_type"] = col

    required = ["recon_step", "gl_code", "pay_code", "amount_column", "code_type"]
    missing  = [r for r in required if r not in col_map]
    if missing:
        raise HTTPException(400, f"Missing required columns: {missing}. Found: {list(df.columns)}")

    rows = []
    current_step = ""
    for _, row in df.iterrows():
        step = str(row.get(col_map.get("recon_step", ""), "") or "").strip()
        if step and step != "nan":
            current_step = step
        gl_code = str(row.get(col_map.get("gl_code", ""), "") or "").strip()
        # Skip pure step-header rows (merged cells produce the step label in col 0 but blank GL Code)
        if not gl_code or gl_code == "nan":
            continue
        rows.append({
            "recon_step":     current_step,
            "gl_code":        gl_code,
            "gl_title":       str(row.get(col_map.get("gl_title", ""), "") or "").strip(),
            "pay_code":       str(row.get(col_map.get("pay_code", ""), "") or "").strip(),
            "pay_code_title": str(row.get(col_map.get("pay_code_title", ""), "") or "").strip(),
            "amount_column":  str(row.get(col_map.get("amount_column", ""), "") or "EarnAmt").strip(),
            "code_type":      str(row.get(col_map.get("code_type", ""), "") or "").strip().upper(),
            "account_type":   str(row.get(col_map.get("account_type", ""), "") or "").strip().lower(),
        })
        # Clean "nan" strings
        rows[-1] = {k: (v if v != "nan" else "") for k, v in rows[-1].items()}

    if not rows:
        raise HTTPException(400, "No data rows found in the uploaded file.")

    return JSONResponse({"ok": True, "rows": rows, "row_count": len(rows), "client_name": client_name})
