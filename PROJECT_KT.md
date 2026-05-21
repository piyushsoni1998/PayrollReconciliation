# Payroll Reconciliation Tool — Knowledge Transfer Document

> **Purpose:** This document serves as a complete knowledge transfer (KT) guide for any engineer picking up this project. It covers the architecture, file-by-file breakdown, full data flow, business logic, and operational notes.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Tech Stack](#2-tech-stack)
3. [Directory Structure](#3-directory-structure)
4. [End-to-End Workflow](#4-end-to-end-workflow)
5. [Module-by-Module Breakdown](#5-module-by-module-breakdown)
   - [Entry Point](#51-entry-point--runpy)
   - [Configuration](#52-configuration--configsettingspy--configdefault_mappingpy)
   - [API Layer](#53-api-layer--backendapi)
   - [Column Identification Pipeline](#54-column-identification-pipeline--backendcolumn_identifier)
   - [Processors](#55-processors--backendprocessors)
   - [Utilities](#56-utilities--backendutils)
   - [Frontend](#57-frontend--frontend)
6. [Business Logic Deep Dives](#6-business-logic-deep-dives)
   - [5-Case Accrual Classification](#61-5-case-accrual-classification)
   - [Account Type & Variance Sign Convention](#62-account-type--variance-sign-convention)
   - [Auto-Detect Payroll Transactions in GL](#63-auto-detect-payroll-transactions-in-gl)
   - [Hybrid Column Identification](#64-hybrid-column-identification)
7. [API Reference](#7-api-reference)
8. [Session State Model](#8-session-state-model)
9. [Configuration & Lookup Structure](#9-configuration--lookup-structure)
10. [Excel Output Format](#10-excel-output-format)
11. [External Dependencies](#11-external-dependencies)
12. [Environment Variables](#12-environment-variables)
13. [Key Design Decisions](#13-key-design-decisions)
14. [Troubleshooting Guide](#14-troubleshooting-guide)

---

## 1. Project Overview

The **Payroll Reconciliation Tool** automates the monthly/annual reconciliation process between:

- **General Ledger (GL) Report** — accounting system export (e.g., MIP)
- **Payroll Register (PR)** — payroll processor export (e.g., ADP, Paylocity)
- **Process of Reconciliation** — client-defined mapping config linking GL accounts to payroll codes

The tool identifies which GL accounts map to which payroll components, computes amounts from both sides, calculates variances, handles fiscal-year accrual accounting, and exports a formatted multi-sheet Excel report.

**Business problem solved:** Manual payroll-to-GL reconciliation is error-prone and takes hours. This tool reduces it to minutes with automated column identification, accrual proration, and variance flagging.

---

## 2. Tech Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI + Uvicorn (Python) |
| Frontend UI | Streamlit (legacy) + HTML/CSS/JS (current) |
| Data Processing | Pandas, NumPy |
| Fuzzy Column Matching | rapidfuzz |
| LLM Column Matching | AWS Bedrock (Claude Haiku) |
| Excel Export | XlsxWriter |
| File Parsing | openpyxl, xlrd, pyxlsb, odf |
| Persistence (optional) | MongoDB (audit trail, mapping configs) |
| Cloud | AWS Bedrock |

---

## 3. Directory Structure

```
PayrollReconciliation/
│
├── run.py                                   # Entry point — starts Uvicorn server
│
├── config/
│   ├── settings.py                          # All env-var config + column alias dictionary
│   └── default_mapping.py                   # Default GL→PR reconciliation mapping template
│
├── backend/
│   ├── api/
│   │   ├── main.py                          # FastAPI app definition + all route registrations
│   │   ├── state.py                         # In-memory session store (UUID → session data)
│   │   ├── db.py                            # MongoDB connection helper
│   │   └── routes/
│   │       ├── upload.py                    # POST /api/upload/{file_type}
│   │       ├── columns.py                   # POST /api/confirm-mapping
│   │       ├── reconcile.py                 # POST /api/run (full reconciliation pipeline)
│   │       ├── mapping_config.py            # GET/POST mapping configuration
│   │       └── auth.py                      # Authentication routes
│   │
│   ├── column_identifier/
│   │   ├── __init__.py                      # Orchestration: fuzzy → Bedrock → cache
│   │   ├── fuzzy_matcher.py                 # rapidfuzz string matching (first pass)
│   │   ├── bedrock_identifier.py            # AWS Bedrock LLM column identification (second pass)
│   │   └── mapping_cache.py                 # Per-client column mapping cache (disk)
│   │
│   ├── processors/
│   │   ├── mapping_parser.py                # Parse Process of Reconciliation → lookup dicts
│   │   ├── gl_processor.py                  # GL report processing + filtering
│   │   ├── payroll_processor.py             # Payroll register processing + accrual
│   │   ├── accrual_classifier.py            # Fiscal-year accrual classification (5 cases)
│   │   └── reconciliation_processor.py      # GL vs PR comparison + variance calculation
│   │
│   └── utils/
│       ├── file_reader.py                   # Smart header detection + multi-format file parsing
│       ├── date_utils.py                    # Robust date parsing (13 strategies)
│       └── excel_exporter.py               # Multi-sheet Excel generation with formatting
│
├── frontend/
│   ├── app.py                               # Streamlit UI (legacy — see FastAPI routes)
│   ├── components/
│   │   ├── file_upload.py                   # Upload widget component
│   │   ├── column_mapping_ui.py             # Column confirmation UI component
│   │   └── report_viewer.py                 # Results display component
│   ├── static/
│   │   ├── css/style.css                    # Application styles
│   │   ├── js/
│   │   │   ├── app.js                       # Main application JS
│   │   │   ├── config.js                    # Frontend config (API base URL, etc.)
│   │   │   ├── upload.js                    # File upload handling
│   │   │   ├── results.js                   # Results rendering
│   │   │   └── history.js                   # Reconciliation history display
│   │   └── vendor/                          # jSpreadsheet library (spreadsheet widget)
│   ├── index.html                           # Main frontend entry point
│   └── history_options_preview.html         # History preview page
│
└── client_mappings/                         # Disk-cached column mappings per client
    └── {client}__{file_type}__{md5hash}.json
```

---

## 4. End-to-End Workflow

The reconciliation process has **5 sequential phases**, each triggered by user action.

### Phase 1 — Session Creation

```
Browser → POST /api/session
         ← Returns session_id (UUID)
Browser stores session_id (used in all subsequent requests)
```

### Phase 2 — File Upload & Column Identification (×3 files)

The user uploads 3 files in any order. Each file goes through the same pipeline:

```
Browser uploads file → POST /api/upload/{file_type}
                        (file_type = gl_report | payroll_register | process_of_reconciliation)
                        ↓
1. file_reader.py:    Read file → detect header row → return clean DataFrame
                        ↓
2. column_identifier: Identify what each column means
   a. Check disk cache (mapping_cache.py) — if hit, return immediately
   b. fuzzy_matcher.py — normalize + score column names vs COLUMN_ALIASES
   c. bedrock_identifier.py — for low-confidence columns, call AWS Bedrock Claude
   d. Merge results, cache to disk
                        ↓
3. Store {df, filename, mapping, confidence} in session
                        ↓
← Return: mapping, confidence scores, unmatched columns, data preview (5 rows)
```

### Phase 3 — Column Confirmation

```
User reviews mapping in UI, makes manual corrections if needed
Browser → POST /api/confirm-mapping
          Body: {session_id, file_type, mapping: {col_name: semantic_role}}
          ↓
Server stores confirmed mapping in session
← Returns: ok, any warnings
```
*Repeat Phases 2–3 for all 3 files before running reconciliation.*

### Phase 4 — Reconciliation Execution

```
User clicks "Run Reconciliation" → POST /api/run
                                    ↓
STEP A — mapping_parser.py:
  Parse "Process of Reconciliation" file → build GL lookup + PR lookup dicts
                                    ↓
STEP B — gl_processor.py:
  Filter GL for payroll transactions → add Recon Mapping column → pivot/aggregate
                                    ↓
STEP C — payroll_processor.py + accrual_classifier.py:
  Classify rows into 5 accrual cases → prorate amounts → add Recon Mapping → pivot
                                    ↓
STEP D — reconciliation_processor.py:
  For each GL code: look up matching PR amounts → calculate variance → flag status
                                    ↓
STEP E — excel_exporter.py:
  Generate 6-sheet Excel workbook (in-memory bytes)
                                    ↓
← Return: summary_stats, recon_data, excel download link
```

### Phase 5 — Report Download

```
Browser → GET /api/download?session_id=...
        ← Excel file (binary) with MIME type .xlsx
```

---

## 5. Module-by-Module Breakdown

### 5.1 Entry Point — `run.py`

Starts the Uvicorn ASGI server hosting the FastAPI application.

```python
# Equivalent to:
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

No business logic here — just server configuration (host, port, reload mode, log level).

---

### 5.2 Configuration — `config/settings.py` & `config/default_mapping.py`

#### `settings.py` — The Control Panel

All environment variables and global constants live here. Key sections:

**AWS / Bedrock:**
```python
AWS_REGION = "us-east-1"
BEDROCK_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
```

**Thresholds:**
```python
FUZZY_THRESHOLD = 85          # Minimum fuzzy score (0–100) to auto-accept a column match
LLM_CONFIDENCE_THRESHOLD = 0.75  # Minimum Bedrock confidence to accept a column match
```

**`FILE_TYPE_ROLES`** — defines expected semantic roles per file type:
```python
FILE_TYPE_ROLES = {
    "payroll_register": [
        "employee_id", "employee_name", "code_type", "pay_code",
        "earn_amt", "bene_amt", "deduc_amt", "ee_tax", "er_tax", "net_amt",
        "pay_date", "period_start_date", "period_end_date", ...
    ],
    "gl_report": [
        "gl_code", "gl_title", "trans_source", "net_amount",
        "doc_date", "fiscal_period", ...
    ],
    "process_of_reconciliation": [
        "recon_steps", "gl_code", "gl_title", "pay_code",
        "code_type", "amount_column", "account_type"
    ]
}
```

**`COLUMN_ALIASES`** — the fuzzy matching dictionary. Maps semantic role → list of known column name variants. This is the heart of column identification. Example:
```python
COLUMN_ALIASES = {
    "pay_code": ["PayCode", "paycode", "pay code", "earnings code", "EarningCode",
                 "pay_code", "PayrollCode", "EarnCode", ...],
    "gl_code":  ["GL Code", "Account", "AccountCode", "GLAccount", "acct",
                 "account_number", "GLAcct", ...],
    ...  # hundreds of entries covering MIP, ADP, Paylocity naming conventions
}
```

#### `default_mapping.py` — Reconciliation Template

Defines the default GL account → payroll component mapping used when no client-specific config exists. Each row is a dict:

```python
{
    "recon_step":    "A. Earning / Gross Wages",
    "gl_code":       "5000",
    "gl_title":      "Salaries & Wages",
    "pay_code":      "Wages",
    "pay_code_title":"Regular Wages",
    "amount_column": "EarnAmt",
    "code_type":     "EARNING",
    "account_type":  "expense"
}
```

`account_type` values and their meaning:
| Value | GL convention | Variance formula |
|---|---|---|
| `expense` | Debit-normal (5xxx/6xxx) | GL Net − PR Amount |
| `liability` | Credit-normal (2xxx) | GL Net + PR Amount |
| `bank` | Net pay cross-check (1xxx) | GL Net + (−PR Net Total) |
| `glonly` | Informational, no PR | No comparison |

`amount_column` values:
| Value | PR column used |
|---|---|
| `EarnAmt` | Earnings |
| `BeneAmt` | Employer benefits |
| `DeducAmt` | Employee deductions |
| `EETax` | Employee taxes |
| `ERTax` | Employer taxes |
| `EeTax & ERTax` | Both tax columns summed |
| `NetAmt` | Net pay (bank or accrual) |
| `GLOnly` | No PR comparison |

---

### 5.3 API Layer — `backend/api/`

#### `main.py` — FastAPI Application

- Creates the FastAPI `app` instance
- Registers all routers (upload, columns, reconcile, mapping_config, auth)
- Serves `frontend/` static files via `StaticFiles` mount
- Serves `frontend/index.html` as the root (`/`) route
- Configures CORS (allow all origins in dev)

#### `state.py` — In-Memory Session Store

Single module-level dictionary holding all live session data:

```python
_store: Dict[str, SessionData] = {}
```

Key functions:
- `new_session() → str` — Creates UUID, initializes empty session
- `get(session_id) → dict | None` — Returns session or None
- `set_file(sid, file_type, df, filename, header_row)` — Stores uploaded file data
- `set_mapping(sid, file_type, mapping_dict)` — Stores confirmed column mapping
- `reset_session(sid)` — Clears all data but keeps session alive
- `store_results(sid, results_dict)` — Stores reconciliation output

> **Important:** This is a single-process in-memory store. All sessions are lost on server restart. Suitable for single-team local deployment.

#### `db.py` — MongoDB Connection

Optional MongoDB integration for audit trail and mapping persistence. Returns `None` if `MONGO_URI` not configured — all callers handle this gracefully.

#### `routes/upload.py` — POST /api/upload/{file_type}

1. Validates `file_type` (must be one of 3 known types)
2. Validates file extension (xlsx, xls, xlsm, xlsb, ods, csv, tsv, txt)
3. Calls `file_reader.read_file()` → DataFrame
4. Calls `column_identifier.identify_columns()` → mapping, confidence, unmatched
5. Stores result in session via `state.set_file()`
6. Returns JSON with mapping, confidence, unmatched columns, and 5-row preview

#### `routes/columns.py` — POST /api/confirm-mapping

1. Validates session exists
2. Validates `file_type`
3. Stores mapping in session via `state.set_mapping()`
4. Optionally saves to disk cache (via `mapping_cache`)
5. Returns warnings if any expected roles are missing from mapping

#### `routes/reconcile.py` — POST /api/run

Orchestrates the full reconciliation pipeline:
1. Validates all 3 files are uploaded and confirmed in session
2. Calls `mapping_parser.build_lookups()`
3. Calls `gl_processor.process_gl()`
4. Calls `payroll_processor.process_payroll()`
5. Calls `reconciliation_processor.build_reconciliation()`
6. Calls `excel_exporter.export_to_excel()`
7. Stores all results in session
8. Returns summary stats + reconciliation data as JSON

#### `routes/mapping_config.py` — GET/POST mapping config

Allows clients to retrieve or update their reconciliation mapping configuration (stored in MongoDB if available, else returns default).

#### `routes/auth.py` — Authentication

Basic authentication routes (login/logout/validate). Guards API endpoints with session token validation.

---

### 5.4 Column Identification Pipeline — `backend/column_identifier/`

This pipeline solves: *"Given a DataFrame with arbitrary column names, what does each column represent?"*

#### `__init__.py` — Orchestration

```python
def identify_columns(df, file_type, client_name, use_cache=True, use_bedrock=True):
    # 1. Check disk cache
    if use_cache:
        cached = mapping_cache.load(client_name, file_type, df)
        if cached:
            return cached, confidence_100, []
    
    # 2. Fuzzy match all columns
    mapping, unmatched = fuzzy_matcher.fuzzy_match_columns(df, COLUMN_ALIASES, FUZZY_THRESHOLD)
    
    # 3. Bedrock for unmatched columns
    if use_bedrock and unmatched:
        bedrock_results = BedrockColumnIdentifier().identify_columns(
            df[unmatched], file_type, unmatched, FILE_TYPE_ROLES[file_type]
        )
        # Merge bedrock results into mapping
        for col, result in bedrock_results.items():
            if result["confidence"] >= LLM_CONFIDENCE_THRESHOLD:
                mapping[col] = result["role"]
                unmatched.remove(col)
    
    # 4. Cache results
    if use_cache:
        mapping_cache.save(client_name, file_type, df, mapping)
    
    return mapping, confidence_dict, still_unmatched
```

#### `fuzzy_matcher.py` — First Pass (Fast)

```python
def fuzzy_match_columns(df, aliases, threshold=85):
    mapping = {}
    unmatched = []
    
    for col in df.columns:
        normalized = normalize(col)  # lowercase, remove non-alphanumeric
        
        best_role, best_score = None, 0
        for role, variants in aliases.items():
            for variant in variants:
                score = rapidfuzz.fuzz.token_set_ratio(normalized, normalize(variant))
                if score > best_score:
                    best_score, best_role = score, role
        
        if best_score >= threshold:
            mapping[col] = (best_role, best_score)
        else:
            unmatched.append(col)
    
    return mapping, unmatched
```

Special logic: GL code exclusion — columns matching fund codes, department codes, or project codes are excluded from the `gl_code` role even if their name fuzzy-matches, preventing false positives in fund-accounting GL exports.

#### `bedrock_identifier.py` — Second Pass (Smart)

For columns fuzzy matching couldn't resolve, sends a prompt to AWS Bedrock Claude:

**Prompt structure:**
- File type context (e.g., "This is a Payroll Register from an HR/payroll system")
- Unmatched column names
- 10 rows of sample data for each unmatched column
- List of expected semantic roles for this file type
- Instruction to return JSON: `{col_name: {role, confidence, reason}}`

**Response parsing:** Extracts JSON from Bedrock response, validates against expected roles.

**Availability:** Checks AWS credentials + Bedrock endpoint on first call, caches result. Returns zero confidence for all columns if unavailable.

#### `mapping_cache.py` — Disk Cache

Cache key format: `{client_name}__{file_type}__{md5(sorted_column_names)}.json`

This means the cache is invalidated automatically if the file structure changes (new/renamed columns). Same structure → instant lookup, no fuzzy matching needed.

---

### 5.5 Processors — `backend/processors/`

#### `mapping_parser.py` — Build Lookups

Input: "Process of Reconciliation" DataFrame + its confirmed column mapping

Builds two lookup dictionaries used throughout the reconciliation:

**GL Lookup** — keyed by GL code:
```python
gl_lookup = {
    "5000": {
        "gl_title": "Salaries & Wages",
        "recon_steps": "A. Earning / Gross Wages",
        "amount_column": "EarnAmt",
        "account_type": "expense",
        "code_type": "EARNING"
    },
    "2126": { ... },
    ...
}
```

**PR Lookup** — keyed by (pay_code, code_type) tuple:
```python
pr_lookup = {
    ("Wages", "EARNING"):    "5000 - Salaries & Wages",
    ("401K", "BENEFIT"):     "2126 - Employer Retirement Payable",
    ("HEALTH", "BENEFIT"):   "2145 - Health Insurance Payable & 5130 - Health Insurance Expense",
    ...
}
```
Note: A single (pay_code, code_type) pair can map to multiple GL accounts (joined with ` & `).

---

#### `gl_processor.py` — Process GL Report

**`process_gl(df, col_map, gl_lookup, period_start=None, period_end=None)`**

**Step 1 — Auto-detect Payroll Transaction Source:**

The GL file typically contains transactions from multiple sources (Payroll, General Journal Entries, Accounts Payable, etc.). The system must isolate payroll transactions.

Algorithm:
1. Filter to rows whose GL code appears in `gl_lookup`
2. Group by `trans_source` column value
3. For each source: count distinct GL codes it touches
4. Select source(s) that touch the MOST GL codes (payroll hits all accounts simultaneously)
5. Tie-breaker: select the source with the most total rows
6. Filter the DataFrame to only those source(s)

If `trans_source` column is not mapped: assume the file is already pre-filtered.

**Step 2 — Period Filter (optional):**
- If `period_start` / `period_end` provided, filter rows by date column
- Tries multiple date column fallbacks: `date`, `doc_date`, `pay_date`, `period_end_date`
- Safety: if filter returns 0 rows, skip filter and log warning

**Step 3 — Add Reconciliation Mapping column:**
- For each row, look up GL code in `gl_lookup`
- Add `"Reconciliation Mapping"` column with value `"{gl_code} - {gl_title}"`

**Step 4 — Pivot/Aggregate:**
- Group by `(recon_step, gl_code, gl_title)`
- Sum `net_amount`
- Result: one row per GL code

**Output:**
- `gl_mapped` — Full GL DataFrame with Reconciliation Mapping column
- `gl_pivot` — Aggregated DataFrame
- `unmapped_codes` — Set of GL codes not in lookup
- `filter_info` — Dict with date filter details

---

#### `payroll_processor.py` — Process Payroll Register

**`process_payroll(df, col_map, pr_lookup, fy_start=None, fy_end=None, period_start=None, period_end=None)`**

**Step 1 — Period Filter (optional):** Same as GL filter.

**Step 2 — Accrual Classification (if fiscal year provided):**

Calls `accrual_classifier.classify_and_prorate()`. See [Section 6.1](#61-5-case-accrual-classification) for full details.

After classification, each row has:
- `cy_factor` — proration factor (0.0 to 1.0)
- `factor_2157` — accrual flag for GL 2157 calculation
- Prorated amount columns: `earn_amt_cy`, `bene_amt_cy`, `deduc_amt_cy`, etc.

**Step 3 — Add Reconciliation Mapping column:**
- For each row, look up `(pay_code, code_type)` tuple in `pr_lookup`
- Add `"Reconciliation Mapping"` column

**Step 4 — Pivot/Aggregate:**
- Group by `(code_type, recon_mapping)`
- Sum all 5 prorated amount columns
- Result: one row per (code_type, mapping) combination

**Step 5 — Calculate `pr_2157_net`:**
Sum of accrual-adjusted `net_amt` values (rows with `factor_2157 > 0`), used specifically for GL 2157 accrued payroll liability reconciliation.

**Output:**
- `pr_mapped` — Full PR DataFrame with Reconciliation Mapping + prorated columns
- `pr_pivot` — Aggregated DataFrame
- `unmapped_keys` — Set of (pay_code, code_type) not in pr_lookup
- `pr_2157_net` — Total accrual-adjusted net pay

---

#### `accrual_classifier.py` — Fiscal-Year Accrual Classification

See [Section 6.1](#61-5-case-accrual-classification) for complete documentation.

---

#### `reconciliation_processor.py` — Compare GL vs PR

**`build_reconciliation(gl_pivot, pr_pivot, gl_lookup, pr_net_total, pr_2157_net)`**

For each row in `gl_pivot`:

1. Look up `account_type` and `amount_column` from `gl_lookup`
2. Find matching PR rows: scan `pr_pivot["Reconciliation Mapping"]` for rows containing this GL code
3. Sum the matching PR amounts (using `amount_column` from lookup)
4. Calculate variance per account type (see [Section 6.2](#62-account-type--variance-sign-convention))
5. Set status: `✓ Match` if `abs(variance) < 0.01`, else `⚠ Variance`

**Special cases:**
- **GL 1020 (Bank):** Compare GL net against `pr_net_total` (sum of all net pay), not lookup-matched PR amounts
- **GL 2157 (Accrued Payroll Liability):** Compare GL net against `pr_2157_net` (accrual-adjusted), not regular net
- **GL Only rows:** Display GL balance, set PR = 0, variance = GL amount, status = "GL Only"
- **No PR match found:** Status = "⚠ No PR Match"

**Output:**

`recon_df` — one row per GL code:
```
Recon Step | GL Code | GL Title | GL Net Amount | PR Amount | Variance | Status | Notes
```
Plus a TOTAL summary row.

`summary_stats`:
```python
{
    "total_lines": int,
    "gl_only_lines": int,
    "matched": int,
    "variances": int,
    "total_variance": float,
    "is_clean": bool  # True if total_variance < 0.01
}
```

---

### 5.6 Utilities — `backend/utils/`

#### `file_reader.py` — Smart File Parsing

**`read_file(source, filename, sheet_name=0)`**

Problem: Accounting exports often have non-standard structures — merged cells, title rows, blank rows before the actual header. The header row is not always row 0.

Solution — Header Detection Algorithm:
1. Read first 15 rows without assigning any header
2. Score each row as a potential header:
   - % of non-null values (completeness)
   - % of short string values (column names are short)
   - % matching header keywords: `["code", "type", "date", "amount", "name", "id", ...]`
   - Bonus for naming patterns: CamelCase, snake_case, ALLCAPS
3. Select the highest-scoring row as the header
4. Re-read the entire file with that row index as the header
5. Post-processing:
   - Drop `Unnamed:` and NaN columns (artifacts from merged Excel cells)
   - Strip time components from datetime columns (keep date only)
   - Drop fully empty rows

Supports: `.xlsx`, `.xls`, `.xlsm`, `.xlsb`, `.ods`, `.csv`, `.tsv`, `.txt`

**Output:** `(clean_df, header_row_index, sheet_names_list)`

---

#### `date_utils.py` — Robust Date Parsing

**`parse_dates_smart(series, col_name)`**

Problem: Accounting exports use inconsistent date formats across clients — US vs European, with and without time, fiscal periods, compact formats.

Solution — tries 13 parsing strategies and picks the one with fewest unparsed values:

| Strategy | Example |
|---|---|
| Mixed US month-first | `01/15/2024`, `January 15, 2024` |
| Mixed European day-first | `15/01/2024` |
| YYYY-MM (fiscal period) | `2024-01` |
| MM-YYYY | `01-2024` |
| MM/DD/YY (short year) | `01/15/24` |
| DD/MM/YY | `15/01/24` |
| DD-Mon-YYYY | `15-Jan-2024` |
| DD-Mon-YY | `15-Jan-24` |
| Mon-DD-YYYY | `Jan-15-2024` |
| YYYYMMDD (compact) | `20240115` |
| Regex YYYY-MM-DD | From messy strings |
| Regex MM/DD/YYYY | From messy strings |
| Regex DD/MM/YYYY (fallback) | From messy strings |

Logs a warning if more than 50% of values fail to parse.

---

#### `excel_exporter.py` — Excel Report Generation

**`export_to_excel(gl_mapped, pr_mapped, gl_pivot, pr_pivot, recon_df, period_label, payroll_process_df)`**

Generates an in-memory `.xlsx` workbook with 6 sheets:

| Sheet | Contents |
|---|---|
| `GL_Mapped` | Full GL rows + Reconciliation Mapping column |
| `PR_Mapped` | Full PR rows + prorated amounts + Reconciliation Mapping |
| `GL_Pivot` | GL aggregated by recon step / GL code |
| `PR_Pivot` | PR aggregated by code type / mapping |
| `Reconciliation` | GL vs PR side-by-side with variance + status |
| `Payroll_Process` | The Process of Reconciliation mapping config |

**Formatting applied to all sheets:**
- Frozen header row
- Auto-fit column widths
- Currency format: `#,##0.00_);(#,##0.00)` (accounting style)

**Conditional formatting on Reconciliation sheet:**
- Green `#C6EFCE` / `#276221` → Matched rows (`✓ Match`)
- Red `#FFC7CE` / `#9C0006` → Variance rows (`⚠ Variance`)
- Grey `#D9D9D9` → TOTAL row
- Light blue `#EEF4FB` → Alternating row shading

**Output:** `bytes` object (ready to write to HTTP response or `st.download_button`)

---

### 5.7 Frontend — `frontend/`

#### `index.html` — Main Page

Single-page application shell. Loads all JS modules and CSS. Contains sections for:
- File upload cards (one per file type)
- Column mapping confirmation table
- Run reconciliation button
- Results display (summary stats + reconciliation table)
- Download button

#### `static/js/app.js` — Main Orchestrator

- Initializes session on page load (`POST /api/session`)
- Manages state machine: Upload → Confirm → Run → Results
- Coordinates all UI components

#### `static/js/upload.js` — File Upload Handler

- Handles drag-and-drop and click-to-upload
- Shows upload progress
- Calls `/api/upload/{file_type}`
- Renders column mapping table from response
- Submits confirmed mapping to `/api/confirm-mapping`

#### `static/js/results.js` — Results Renderer

- Renders reconciliation summary stats
- Renders full reconciliation table with color-coded rows
- Triggers Excel download

#### `static/js/history.js` — History View

Fetches and displays past reconciliation runs (if MongoDB is configured).

#### `frontend/app.py` — Legacy Streamlit UI

Older Streamlit-based interface. Still functional for local/dev use. Follows the same workflow but renders natively in Streamlit. Not the primary interface for production.

---

## 6. Business Logic Deep Dives

### 6.1 5-Case Accrual Classification

**Why this exists:** Payroll periods often straddle fiscal year boundaries. A pay period might start Dec 28 and end Jan 10, paid Jan 15. This single payroll run has wages that belong partly to the prior fiscal year and partly to the current year. The GL records an accrual entry (GL 2157) at year-end to capture these split-period amounts.

The classifier assigns each payroll row to one of 5 cases:

```
Legend:
  CY = Current Year (fiscal year being reconciled)
  PY = Prior Year
  NY = Next Year
  fy_start = first day of CY
  fy_end = last day of CY
```

| Case | Condition | Treatment |
|---|---|---|
| **1** Normal | PayDate ∈ CY, Period fully ∈ CY | Include 100% (`cy_factor = 1.0`) |
| **2** PY Paid in CY | PayDate ∈ CY, Period fully ∈ PY | Exclude from earnings/taxes (`cy_factor = 0.0`); NetAmt clears PY accrual in GL 2157 (`factor_2157 = 1.0`) |
| **3** CY Paid in NY | PayDate ∈ NY, Period fully ∈ CY | Include 100% (`cy_factor = 1.0`); NetAmt = CY accrual to be booked to GL 2157 (`factor_2157 = 1.0`) |
| **4** Split Period (beginning of year) | PayDate ∈ CY, Period straddles PY→CY | Prorate by working-day fraction |
| **5** Split Period (year-end) | PayDate ∈ NY, Period straddles CY→NY | Prorate by working-day fraction |

**Proration algorithm for Cases 4 & 5:**

```python
total_working_days = count_working_days(period_start, period_end)

# Case 4 (beginning of year): CY days = period_start..fy_end portion that's in CY
cy_working_days = count_working_days(fy_start, period_end)

# Case 5 (year-end): CY days = fy_start..period_end portion that's in CY
cy_working_days = count_working_days(period_start, fy_end)

cy_factor = cy_working_days / total_working_days

# Apply to all 5 amount columns
earn_amt_cy   = earn_amt   * cy_factor
bene_amt_cy   = bene_amt   * cy_factor
deduc_amt_cy  = deduc_amt  * cy_factor
ee_tax_cy     = ee_tax     * cy_factor
er_tax_cy     = er_tax     * cy_factor
net_amt_cy    = net_amt    * cy_factor
```

`count_working_days` counts Monday–Friday only (no holiday calendar).

**GL 2157 Accrued Payroll Liability:** The sum of `net_amt * factor_2157` across all rows gives `pr_2157_net`, which is what should offset GL 2157 in the reconciliation.

---

### 6.2 Account Type & Variance Sign Convention

This is the most common source of confusion for new engineers.

**Why two formulas?**

In double-entry accounting:
- **Expense accounts** (5xxx, 6xxx) are **debit-normal** — a positive balance = debit
- **Liability accounts** (2xxx) are **credit-normal** — a positive balance = credit

When payroll is posted:
- Expense (e.g., Wages 5000): **DEBIT** increases balance
- Liability (e.g., 401K Payable 2126): **CREDIT** increases balance

The GL report gives **net amounts** (debit − credit). So:
- Expense GL net: positive (net debit)
- Liability GL net: negative (net credit)
- PR amounts: always positive

Therefore:
```
Expense:  Variance = GL_net − PR_amount   (both positive; difference = variance)
Liability: Variance = GL_net + PR_amount  (GL is negative; adding positive PR = difference)
Bank:      Variance = GL_net + (−PR_net_total)  (GL is debit; net pay = credit)
```

Example:
```
GL 5000 Salaries: GL_net = $100,000   PR EarnAmt = $100,000
  Variance = 100,000 − 100,000 = $0.00 ✓ Match

GL 2126 401K Payable: GL_net = -$5,000   PR BeneAmt = $5,000
  Variance = -5,000 + 5,000 = $0.00 ✓ Match
```

---

### 6.3 Auto-Detect Payroll Transactions in GL

**Problem:** A GL report exported for the full accounting period contains ALL transaction types — payroll (PRS), general journal entries (GJE), accounts payable (AP), etc. We only want payroll transactions.

**Solution:**

```
For each unique trans_source value in the GL:
  GL_codes_covered = {gl_code for rows with this trans_source} ∩ gl_lookup.keys()
  score = len(GL_codes_covered)

Select trans_source(s) with max score.
If tied: pick the one with the most rows (payroll = many rows; GJE = few rows).
```

**Rationale:** Payroll journal entries touch ALL payroll GL accounts in one posting batch. Other sources (GJE, AP) typically touch only 1–3 GL codes at a time. So the source that covers the most GL accounts in the lookup is almost certainly payroll.

---

### 6.4 Hybrid Column Identification

**Problem:** Every client's GL or Payroll file uses different column names. "GL Code" might be called "Account", "GL Acct", "AccountNumber", "GLCode", "Acct No", etc.

**Two-pass solution:**

**Pass 1 — Fuzzy Matching (milliseconds, no cost):**
- Normalize all column names: lowercase, remove non-alphanumeric
- Score against hundreds of known aliases using `rapidfuzz.token_set_ratio`
- Accept if score ≥ 85 (configurable threshold)
- Fast, deterministic, works for 80–90% of columns

**Pass 2 — Bedrock LLM (seconds, AWS cost):**
- Only called for columns fuzzy matching couldn't identify
- Sends column names + 10 rows of sample data to Claude Haiku
- Claude understands semantic meaning from data patterns (e.g., "this column of 9-digit numbers is likely SSN/employee_id")
- Accept if confidence ≥ 0.75 (configurable threshold)

**Cache layer:**
- After first successful identification, result is cached to disk
- Cache key includes MD5 of column names — invalidates automatically if file structure changes
- Subsequent uploads of same client's file: instant, no API calls

---

## 7. API Reference

### Session

```
POST /api/session
  Response: {"session_id": "uuid-string"}

GET /api/session/{session_id}/status
  Response: {
    "session_id": str,
    "gl_report_uploaded": bool,
    "gl_report_confirmed": bool,
    "payroll_register_uploaded": bool,
    "payroll_register_confirmed": bool,
    "process_of_reconciliation_uploaded": bool,
    "process_of_reconciliation_confirmed": bool,
    "has_results": bool
  }

POST /api/session/{session_id}/reset
  Response: {"ok": true}
```

### File Upload

```
POST /api/upload/{file_type}
  file_type: gl_report | payroll_register | process_of_reconciliation
  Form data:
    file:        binary
    session_id:  str
    sheet_name:  str (optional, Excel only)
    client_name: str (optional, for cache)
    use_bedrock: bool (default true)
    use_cache:   bool (default true)
  Response: {
    "ok": bool,
    "file_type": str,
    "filename": str,
    "header_row": int,
    "row_count": int,
    "col_count": int,
    "columns": [str, ...],
    "sheets": [str, ...],
    "mapping": {col_name: role, ...},
    "confidence": {col_name: float, ...},
    "unmatched": [col_name, ...],
    "preview": [{row_dict}, ...]
  }
```

### Column Confirmation

```
POST /api/confirm-mapping
  Body (JSON): {
    "session_id": str,
    "file_type": str,
    "mapping": {col_name: role, ...},
    "client_name": str (optional),
    "save_cache": bool (optional)
  }
  Response: {
    "ok": bool,
    "file_type": str,
    "saved": bool,
    "warnings": [str, ...]
  }
```

### Reconciliation

```
POST /api/run
  Query params:
    session_id:   str (required)
    period_label: str (optional, e.g. "Jan 2024")
    client_name:  str (optional)
    fy_start:     str (optional, YYYY-MM-DD, for accrual)
    fy_end:       str (optional, YYYY-MM-DD, for accrual)
    period_start: str (optional, YYYY-MM-DD, for GL/PR filter)
    period_end:   str (optional, YYYY-MM-DD, for GL/PR filter)
  Response: {
    "ok": bool,
    "summary_stats": {
      "total_lines": int,
      "gl_only_lines": int,
      "matched": int,
      "variances": int,
      "total_variance": float,
      "is_clean": bool
    },
    "recon_data": [{row_dict}, ...],
    "excel_download_url": str
  }
```

### Download

```
GET /api/download?session_id={session_id}
  Response: Binary .xlsx file
  Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
```

---

## 8. Session State Model

```python
{
    "uuid-1234": {
        "files": {
            "gl_report": {
                "df": pd.DataFrame,
                "filename": "GL_Report_2024.xlsx",
                "header_row": 2
            },
            "payroll_register": { ... },
            "process_of_reconciliation": { ... }
        },
        "mappings": {
            "gl_report": {
                "Account Number": "gl_code",
                "Account Title":  "gl_title",
                "Trans Source":   "trans_source",
                "Net Amount":     "net_amount",
                "Trans Date":     "date"
            },
            "payroll_register": { ... },
            "process_of_reconciliation": { ... }
        },
        "results": {
            "gl_mapped":    pd.DataFrame,
            "pr_mapped":    pd.DataFrame,
            "gl_pivot":     pd.DataFrame,
            "pr_pivot":     pd.DataFrame,
            "recon_df":     pd.DataFrame,
            "summary_stats": dict,
            "unmapped_gl":  set,
            "unmapped_pr":  set,
            "excel_bytes":  bytes
        }
    }
}
```

---

## 9. Configuration & Lookup Structure

### Reconciliation Steps (Standard)

```
Step A:   Earning / Gross Wages                     → GL 5000
Step B:   Benefits / Employer Expenses              → GL 5130, 5140
Step B.1: Benefits / Employer Expenses - Liabilities → GL 2126, 2145, ...
Step C:   Deductions / Employee Deductions - Liab.  → GL 2127, 2141, ...
Step D:   Employee & Employer Taxes - Liabilities   → GL 2115, 2120
Step E:   ERTax / Employer Taxes                    → GL 5100
Step F:   Bank Payment to Employee                  → GL 1020
Step G:   Accrued Payroll Liability                 → GL 2157
```

### Payroll Code Types

```
EARNING   — Earnings (wages, PTO, overtime, etc.)
BENEFIT   — Employer-paid benefits (401K match, health, etc.)
DEDUCT    — Employee deductions (401K EE, health EE premium, etc.)
TAXES     — Payroll taxes (FICA, FUTA, SUTA, federal/state income tax)
```

### Variance Tolerance

`$0.01` — Variances below this threshold are treated as rounding and flagged ✓ Match.

---

## 10. Excel Output Format

### Sheet: Reconciliation

The key deliverable. Structure:

| Column | Description |
|---|---|
| Recon Step | Step label (A, B, B.1, C, D, E, F, G) |
| GL Code | GL account number |
| GL Title | GL account name |
| GL Net Amount | Sum from GL report |
| PR Amount | Sum from Payroll Register |
| Variance | GL vs PR difference |
| Status | ✓ Match or ⚠ Variance or GL Only |
| Notes | Any issues found (unmapped codes, etc.) |

### Color Coding

| Color | Meaning |
|---|---|
| Green background | Reconciled with zero variance |
| Red background | Variance exists — needs investigation |
| Grey background | TOTAL row |
| Alternating light blue | Standard row shading |

---

## 11. External Dependencies

### Python Packages (`requirements.txt` / `pyproject.toml`)

```
fastapi          — Web framework
uvicorn          — ASGI server
pandas           — Data processing
numpy            — Numerical operations
xlsxwriter       — Excel file generation
rapidfuzz        — Fuzzy string matching
boto3            — AWS SDK (Bedrock)
openpyxl         — .xlsx reading
xlrd             — .xls reading
pyxlsb           — .xlsb reading
odfpy            — .ods reading
pymongo          — MongoDB (optional)
streamlit        — Legacy frontend
python-dotenv    — .env file loading
```

### AWS Bedrock

- **Model:** `anthropic.claude-3-haiku-20240307-v1:0`
- **Region:** `us-east-1` (configurable)
- **Used for:** Intelligent column identification when fuzzy matching fails
- **Cost note:** Only called for unmatched columns; results are cached

### MongoDB (Optional)

- `mapping_configs` collection: Client-specific reconciliation mapping configs
- `recon_history` collection: Audit trail of reconciliation runs

---

## 12. Environment Variables

Create a `.env` file in the project root:

```env
# AWS Bedrock (required for LLM column identification)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0

# MongoDB (optional)
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=payroll_recon

# Server
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=info

# Thresholds (optional overrides)
FUZZY_THRESHOLD=85
LLM_CONFIDENCE_THRESHOLD=0.75
```

---

## 13. Key Design Decisions

| Decision | Rationale |
|---|---|
| **In-memory session store** | Zero-latency, no DB overhead. Single-process deployment for team use |
| **Hybrid column ID (fuzzy + LLM)** | Fast + cheap for common cases; smart + accurate for edge cases |
| **Disk cache for column mappings** | Skip re-identification for repeat uploads of same client file structure |
| **5-case accrual classifier** | Handles all real-world split-period and cross-year payroll scenarios |
| **Account-type-based sign convention** | Correct double-entry accounting math without hardcoding GL code ranges |
| **$0.01 variance tolerance** | Prevents floating-point rounding from creating false variances |
| **Auto-detect payroll trans source** | Adapts to any GL export; no hardcoded "PRS" or similar value |
| **Working-day proration (not calendar days)** | Accurate for payroll (wages are for working days, not weekends) |
| **XlsxWriter for export** | Full formatting control; xlsxwriter supports conditional formats, frozen panes, number formats |

---

## 14. Troubleshooting Guide

| Symptom | Likely Cause | Fix |
|---|---|---|
| Column not identified automatically | Column name too unusual for fuzzy matching | Ensure `use_bedrock=True` and AWS creds are set; or manually confirm in UI |
| Bedrock errors | Invalid/missing AWS credentials | Check `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` in `.env`; verify IAM has Bedrock access |
| Date filter produces 0 rows | Wrong date format or wrong date column mapped | Check sample values in the unmapped preview; verify date column mapping |
| GL code appears in "unmapped" | GL code is in GL report but not in Process of Reconciliation | Add the GL code to the mapping config |
| All GL amounts differ from PR | Wrong account_type in mapping | Verify `account_type` is `expense` vs `liability` correctly |
| Bank reconciliation fails | Net pay amounts differ | Check for Case 2/3/4/5 rows; ensure `fy_start`/`fy_end` are provided |
| GL 2157 accrual off | Missing fiscal year bounds | Always provide `fy_start` + `fy_end` when running if accrual is expected |
| Session lost after restart | In-memory store cleared on restart | This is by design; re-upload files to start a new session |
| Cache returns wrong mapping | Old cache hit for changed file structure | Delete cache file in `client_mappings/` folder; columns MD5 changes automatically if columns change |
| Excel download is empty/corrupt | Exception during export | Check server logs; common cause is a completely empty pivot DataFrame |

---

*Document generated from source code analysis. For any questions, trace through the relevant module starting from the API route handler and following the processor call chain.*
