# Payroll Reconciliation Tool — Complete Technical & Functional Documentation

**Version:** 1.0  
**Last Updated:** April 2026  
**Audience:** Accountants, Developers, QA Testers, Onboarding Teams

---

## Table of Contents

1. [Purpose & Overview](#1-purpose--overview)
2. [Technology Stack](#2-technology-stack)
3. [Project Structure](#3-project-structure)
4. [Core Concept: What Is Payroll Reconciliation?](#4-core-concept-what-is-payroll-reconciliation)
5. [Input Files](#5-input-files)
6. [Complete User Workflow](#6-complete-user-workflow)
7. [Column Identification Pipeline](#7-column-identification-pipeline)
8. [Reconciliation Mapping Configuration](#8-reconciliation-mapping-configuration)
9. [GL Report Processing](#9-gl-report-processing)
10. [Payroll Register Processing & Accrual Classification](#10-payroll-register-processing--accrual-classification)
11. [The 5-Case Accrual Classification System](#11-the-5-case-accrual-classification-system)
12. [Accrual Proration Formula](#12-accrual-proration-formula)
13. [GL 2157 — Accrued Payroll Liability Reconciliation](#13-gl-2157--accrued-payroll-liability-reconciliation)
14. [Variance Calculation & Sign Convention](#14-variance-calculation--sign-convention)
15. [Account Type System (Multi-Client Support)](#15-account-type-system-multi-client-support)
16. [Combined GL Codes](#16-combined-gl-codes)
17. [Dual-Entry Items (Benefits & Taxes)](#17-dual-entry-items-benefits--taxes)
18. [Excel Output — Sheet Descriptions](#18-excel-output--sheet-descriptions)
19. [Multi-Client Architecture](#19-multi-client-architecture)
20. [API Endpoints](#20-api-endpoints)
21. [Configuration Files](#21-configuration-files)
22. [Key Business Rules](#22-key-business-rules)
23. [Known Limitations & Edge Cases](#23-known-limitations--edge-cases)
24. [Glossary](#24-glossary)

---

## 1. Purpose & Overview

The **Payroll Reconciliation Tool** automates the reconciliation of a **General Ledger (GL) Report** against a **Payroll Register**, both typically exported from MIP accounting software.

In standard accrual accounting, every payroll transaction simultaneously creates:
- An **expense** entry (e.g., Salaries Expense — debit)
- A **liability** entry (e.g., Tax Payable — credit)
- A **bank** entry (Cash in Bank — credit)

The tool verifies that the amounts recorded in the GL for each account **exactly match** the corresponding amounts in the Payroll Register. Any difference is reported as a **variance**.

### What the Tool Produces

- A formatted **6-sheet Excel workbook** with GL vs. PR side-by-side comparison
- **Variance amounts** per GL account with status (Match / Variance)
- **Accrual-adjusted** payroll amounts when fiscal year bounds are provided
- A complete **GL 2157 Accrued Payroll Liability** reconciliation
- **Unmapped item lists** for accounts and pay codes not in the config

---

## 2. Technology Stack

| Component | Technology |
|---|---|
| Web API | FastAPI + Uvicorn |
| UI (Streamlit) | Streamlit (alternative frontend) |
| Data Processing | Pandas |
| Excel Export | xlsxwriter |
| Column Identification (AI) | AWS Bedrock (Claude Haiku) |
| Fuzzy String Matching | rapidfuzz |
| Working Day Calculation | numpy.busday_count |
| Storage (optional) | MongoDB |
| Auth | SHA-256 token-based |
| Config Storage | JSON files per client |

---

## 3. Project Structure

```
payroll_Reconciliation/
├── backend/
│   ├── api/
│   │   ├── main.py                  FastAPI app entry point
│   │   ├── state.py                 In-memory session store
│   │   ├── db.py                    MongoDB wrapper (optional)
│   │   └── routes/
│   │       ├── upload.py            File upload + auto column identification
│   │       ├── columns.py           Confirm column mappings
│   │       ├── reconcile.py         Run reconciliation pipeline
│   │       ├── mapping_config.py    GL↔PayCode config CRUD + build_lookups_from_config
│   │       └── auth.py              Register / Login / Verify
│   ├── column_identifier/
│   │   ├── __init__.py              3-stage identification orchestrator
│   │   ├── fuzzy_matcher.py         rapidfuzz string matching (Stage 2)
│   │   ├── bedrock_identifier.py    AWS Bedrock LLM fallback (Stage 3)
│   │   └── mapping_cache.py         Per-client column mapping cache
│   ├── processors/
│   │   ├── mapping_parser.py        Build lookup dicts from uploaded mapping file
│   │   ├── gl_processor.py          GL report → filtered + pivot
│   │   ├── payroll_processor.py     Payroll register → classified + prorated + pivot
│   │   ├── accrual_classifier.py    5-case pay run classification + proration
│   │   └── reconciliation_processor.py  GL vs PR variance calculation
│   └── utils/
│       ├── file_reader.py           Multi-format reader + auto header detection
│       ├── date_utils.py            13-strategy smart date parser
│       └── excel_exporter.py        6-sheet Excel workbook generator
├── config/
│   ├── settings.py                  AWS, MongoDB, thresholds, COLUMN_ALIASES
│   └── default_mapping.py           Standard GL↔Pay Code mapping template
├── client_mappings/                 Per-client saved configs (JSON)
├── frontend/
│   ├── app.py                       Streamlit UI
│   └── components/
│       ├── file_upload.py
│       ├── column_mapping_ui.py
│       └── report_viewer.py
└── run.py                           Application entry point
```

---

## 4. Core Concept: What Is Payroll Reconciliation?

A payroll reconciliation compares the **General Ledger** (what the accounting system recorded) against the **Payroll Register** (what the payroll system calculated).

### Example

When payroll is run for $100,000 gross wages:

| GL Account | Type | GL Entry | PR Source |
|---|---|---|---|
| 5000 Salaries & Wages | Expense (debit) | +$100,000 | EarnAmt |
| 2115 Federal Tax Payable | Liability (credit) | −$22,000 | EETax + ERTax |
| 2120 State Tax Payable | Liability (credit) | −$5,000 | EETax |
| 2127 Employee 401K Payable | Liability (credit) | −$3,000 | DeducAmt |
| 1020 Cash in Bank | Asset (credit) | −$70,000 | NetAmt |

The tool verifies each GL account balance against its PR counterpart and reports any discrepancy.

---

## 5. Input Files

### 5.1 GL Report

Exported from MIP Accounting (or any accounting system). Contains every journal entry posted for the payroll period.

**Required columns (identified automatically):**

| Semantic Role | Example Column Names |
|---|---|
| `gl_code` | GL Code, Account, AccountCode, Acct |
| `gl_title` | GL Title, Account Name, Description |
| `net_amount` | NetAmt, Net Amount, Amount, Balance |
| `trans_source` | TransSource, Source (optional — used to filter payroll batches) |
| `date` | PostToDate, EffectiveDate, TranDate, GL Date |

### 5.2 Payroll Register

Exported from MIP Payroll. Contains one row per employee per pay code per pay run.

**Required columns (identified automatically):**

| Semantic Role | Example Column Names |
|---|---|
| `code_type` | CodeType, Type, PayCodeType |
| `pay_code` | PayCode, PayCode, EarningCode |
| `earn_amount` | EarnAmt, GrossWages, EarningAmount |
| `benefit_amount` | BeneAmt, BenefitAmount |
| `deduction_amount` | DeducAmt, DeductionAmount |
| `ee_tax` | EETax, EmployeeTax |
| `er_tax` | ERTax, EmployerTax |
| `net_amount` | NetAmt, NetPay |
| `pay_date` | PayDate, CheckDate |
| `period_start_date` | BgnPayPeriodDate, PeriodStart |
| `period_end_date` | EndPayPeriodDate, PeriodEnd |

### 5.3 Supported File Formats

`.xlsx`, `.xls`, `.xlsb`, `.csv`, `.tsv`, `.txt`, `.ods`

The tool automatically detects which row is the header row (handles MIP exports that include title rows above the actual data headers).

---

## 6. Complete User Workflow

```
┌──────────────────────────────────────────────────────────────────────┐
│  STEP 1: Upload GL Report + Payroll Register                         │
│  → Auto header-row detection                                         │
│  → Automatic column identification (fuzzy + AI)                      │
└──────────────────────────────────────────────────────────────────────┘
                               ↓
┌──────────────────────────────────────────────────────────────────────┐
│  STEP 2: Confirm Column Mappings                                     │
│  → User reviews auto-identified column roles                         │
│  → Validate GL Code column (must match config codes)                 │
│  → Save mapping per client for future use                            │
└──────────────────────────────────────────────────────────────────────┘
                               ↓
┌──────────────────────────────────────────────────────────────────────┐
│  STEP 3: Configure Reconciliation Mapping (per client)               │
│  → Set GL Code ↔ Pay Code relationships                              │
│  → Specify amount column per GL code (EarnAmt, BeneAmt, etc.)        │
│  → Set account_type per GL code (expense/liability/bank)             │
│  → Save to client profile                                            │
└──────────────────────────────────────────────────────────────────────┘
                               ↓
┌──────────────────────────────────────────────────────────────────────┐
│  STEP 4: Run Reconciliation                                          │
│  (Optional) Set fiscal year period: YYYY-MM to YYYY-MM               │
│                                                                      │
│  Pipeline:                                                           │
│  A. Build GL lookup + PR lookup from mapping config                  │
│  B. Process GL Report:                                               │
│     - Auto-detect payroll TransSource batch                          │
│     - Apply date filter (if period provided)                         │
│     - Add Reconciliation Mapping column                              │
│     - Build GL Pivot                                                 │
│  C. Process Payroll Register:                                        │
│     - Convert amounts to numeric                                     │
│     - Classify pay runs into 5 cases (if FY bounds provided)         │
│     - Prorate amounts for Cases 4 & 5                                │
│     - Exclude Case 2 rows (cy_factor = 0)                            │
│     - Build 2157 net amount from Cases 2, 3, 4, 5                    │
│     - Add Reconciliation Mapping column                              │
│     - Build PR Pivot                                                 │
│  D. Build Reconciliation Table:                                      │
│     - For each GL code: find matching PR rows                        │
│     - Read correct amount column (EarnAmt/BeneAmt/etc.)              │
│     - Apply sign convention (expense vs liability vs bank)           │
│     - Calculate Variance = GL Net ± PR Amount                        │
│     - Assign status: Match / Variance / GL Only                      │
│  E. Generate Excel workbook (6 sheets)                               │
└──────────────────────────────────────────────────────────────────────┘
                               ↓
┌──────────────────────────────────────────────────────────────────────┐
│  STEP 5: Download Excel Report                                       │
│  → Review variances                                                  │
│  → Investigate unmapped items                                        │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 7. Column Identification Pipeline

The tool automatically identifies which column in the uploaded file corresponds to which semantic role (e.g., which column is the GL Code, which is the amount, etc.).

### Three-Stage Pipeline

**Stage 1 — Cache Lookup (instant)**
- If this client has uploaded this file type before and confirmed mappings, load from cache
- Cache key = `{client_name}__{file_type}__{hash(column_names)}.json`
- Hash prevents stale cache if the file structure changes

**Stage 2 — Fuzzy Matching (instant, zero cost)**
- Compare each column name against ~500 known aliases using `rapidfuzz`
- Threshold: 85% similarity score
- Columns matching above threshold → assigned to that role
- Below threshold → sent to Stage 3

**Stage 3 — AWS Bedrock LLM Fallback (~30–60 seconds)**
- Only for columns that fuzzy matching couldn't resolve
- Sends unmatched column names + 10 sample data rows to Claude Haiku
- Claude returns `{ column_name: { role, confidence, reason } }`
- Confidence threshold: 0.75
- Columns below threshold → marked as unknown

### Exclusion Rules

Certain roles have explicit exclusions to prevent wrong matches:
- `gl_code`: excludes fund codes, department codes, cost centers, project codes
- `gl_title`: excludes dimension name columns

This prevents a common MIP issue where fund codes (2-digit) are mistakenly mapped as GL account codes (4-5 digit).

---

## 8. Reconciliation Mapping Configuration

The mapping config defines **which GL codes correspond to which Pay Codes**, and how amounts should be compared.

### Config Row Structure

```json
{
  "recon_step":     "A. Earning/ Gross wages",
  "gl_code":        "5000",
  "gl_title":       "Salaries & Wages",
  "pay_code":       "Wages",
  "pay_code_title": "Regular Wages",
  "amount_column":  "EarnAmt",
  "code_type":      "EARNING",
  "account_type":   "expense"
}
```

### Amount Column Values

| Value | PR Column Used | Typical Use |
|---|---|---|
| `EarnAmt` | Sum EarnAmt | Salary/wage expense accounts (5xxx) |
| `BeneAmt` | Sum BeneAmt | Benefits expense and benefit liabilities |
| `DeducAmt` | Sum DeducAmt | Employee deduction liabilities |
| `EETax` | Sum EETax | Employee tax liabilities (FIT, SWT) |
| `ERTax` | Sum ERTax | Employer FICA expense |
| `EeTax & ERTax` | Sum EETax + Sum ERTax | Medicare, Social Security (both sides) |
| `NetAmt` | Net Pay Total | Bank account (1020) or accrual liability (2157) |
| `GLOnly` | None | Informational only — no PR comparison |

### Account Type Values

| Value | GL Nature | Sign Convention |
|---|---|---|
| `expense` | Debit-normal (5xxx, 6xxx) | Variance = GL − PR |
| `liability` | Credit-normal (2xxx) | Variance = GL + PR |
| `bank` | Asset — net pay disbursement (1xxx) | Variance = GL + Net Pay |
| `glonly` | Informational | Variance = 0, no comparison |

**Important:** `account_type` is now explicitly stored in the config. If missing from a saved config, it is automatically derived from the GL code's first digit for backwards compatibility.

### Per-Client Config Storage

- Saved as: `client_mappings/{client_name}__recon_config.json`
- Or in MongoDB: `mapping_configs` collection
- Each client has their own GL codes and GL titles
- Pay codes and amount columns are standardized across clients

### Default Template

The default template ships with common MIP pay codes and generic GL codes. The user must fill in the actual GL codes for their specific chart of accounts. Key defaults:

| Step | GL Code | GL Title (generic) | Pay Code | Amount |
|---|---|---|---|---|
| A. Earnings | 5000 | Salaries & Wages | Wages, Retro, Holiday, etc. | EarnAmt |
| A. Earnings | 5001 | OT Wages | Overtime | EarnAmt |
| A. Earnings | 6000 | Stipends | STX-1000 | EarnAmt |
| B. Benefits | 5130 | Insurance Benefits | Health16, Dental16, etc. | BeneAmt |
| B. Benefits | 5140 | Retirement Expense | 401K, Roth, etc. | BeneAmt |
| B.1 Liabilities | 2126 | Employer Retirement Payable | 401K, Roth | BeneAmt |
| C. Deductions | 2127 | Employee Retirement Payable | 401K, Roth | DeducAmt |
| D. Taxes | 2115 | Federal Payroll Taxes Payable | FIT, MC, SS | EeTax & ERTax |
| D. Taxes | 2120 | State Payroll Taxes Payable | SWT | EETax |
| E. ER Tax | 5100 | FICA Expense | MC, SS | ERTax |
| F. Bank | 1020 | Cash in Bank - Payroll | — | NetAmt |
| G. Accrual | 2157 | Accrued Payroll Liability | — | NetAmt |

---

## 9. GL Report Processing

**File:** `backend/processors/gl_processor.py`

### Step 1 — Auto-detect Payroll TransSource

Many GL files contain mixed transaction types (payroll, AP payments, journal entries). The tool automatically identifies which `TransSource` value represents the payroll batch.

**Algorithm:**
1. For each TransSource value in the file, count how many distinct GL codes from the mapping config it touches
2. A payroll batch touches ALL configured GL accounts simultaneously (salary expense, tax liabilities, bank, etc.)
3. Non-payroll transactions touch only 1–2 accounts
4. Select the TransSource with the **highest count of distinct config GL codes**
5. If tied on GL code count → pick the one with the most rows (payroll has many employee rows per GL code)
6. If no TransSource column mapped → use all rows (file assumed pre-filtered)

### Step 2 — Date Filter (Optional)

If `period_start` and `period_end` are provided:
- Parse the date column using the 13-strategy smart date parser
- Filter rows to the requested period (YYYY-MM)
- Safety valve: if filter produces 0 rows, skip it and warn rather than returning empty results
- If the GL data spans outside the requested period AND filter failed → blocking error surfaced to user

### Step 3 — Add Reconciliation Mapping Column

Each GL row gets a `Reconciliation Mapping` column = the recon step label for that GL code, looked up from `gl_lookup`.

### Step 4 — Build GL Pivot

Group by `Reconciliation Mapping | GL Code | GL Title` and sum `Net Amount`.

Output columns:
```
Reconciliation Mapping | GL Code | GL Title | Sum of Net Amount
```

---

## 10. Payroll Register Processing & Accrual Classification

**File:** `backend/processors/payroll_processor.py`

### Step 1 — Clean Key Columns

`CodeType` and `PayCode` are converted to UPPERCASE for consistent lookup.

### Step 2 — Date Filter (Optional)

Same period filter logic as GL processing. Date column priority:
`pay_date → period_end_date → period_start_date → doc_date`

### Step 3 — Convert Amount Columns to Numeric

All amount columns (EarnAmt, BeneAmt, DeducAmt, EETax, ERTax, NetAmt) are converted to float, stripping commas. NaN values filled with 0.

### Step 4 — Accrual Classification (if FY bounds provided)

See Section 11 below.

### Step 5 — Assign Reconciliation Mapping

Each PR row gets a `Reconciliation Mapping` column by looking up `(PayCode_upper, CodeType_upper)` in `pr_lookup`.

Format: `"GL_CODE - GL_TITLE"` or `"GL_CODE - GL_TITLE & GL_CODE2 - GL_TITLE2"` for dual-entry items.

### Step 6 — Build PR Pivot

Group by `CodeType | Reconciliation Mapping` and sum each amount column.

Output columns:
```
Code Type | Reconciliation Mapping | Sum EarnAmt | Sum BeneAmt | Sum DeducAmt | Sum EETax | Sum ERTax
```

**Note:** Case 2 rows (PY pay runs paid in CY) have `cy_factor = 0` after classification, so their amounts are already zeroed out before the pivot is built. They appear in the mapped DataFrame but contribute 0 to the pivot — correctly excluding them from CY reconciliation.

---

## 11. The 5-Case Accrual Classification System

**File:** `backend/processors/accrual_classifier.py`

This system handles the fiscal year boundary problem in payroll: pay periods do not align perfectly with fiscal year start/end dates. US GAAP accrual accounting requires that expenses and liabilities are recognized in the period the work was performed, not when payment occurs.

The classification uses three date columns per pay run:
- **PayDate** — when the check was issued
- **BgnPayPeriodDate** — start of the work period
- **EndPayPeriodDate** — end of the work period

And compares them against the user-defined fiscal year:
- **fy_start** — first day of the fiscal year (derived from `period_start`)
- **fy_end** — last day of the fiscal year (derived from `period_end`)

### Case Definitions

#### Case 1 — Normal Payroll (Fully in CY)
```
PayDate ∈ CY
Period Start ∈ CY
Period End ∈ CY
```
**Treatment:** Include 100% in reconciliation. No adjustment needed.

**Example:** Pay period Dec 1–15, Pay Date Dec 20. All within fiscal year.

---

#### Case 2 — Prior Year Payroll Paid in CY
```
PayDate ∈ CY
Period Start ∈ PY
Period End ∈ PY
```
**Treatment:** **Exclude completely** from CY earnings/benefits/deductions/taxes reconciliation (`cy_factor = 0`).

The NetAmt from this pay run **clears** the prior-year accrual balance sitting in GL 2157 (a debit entry to 2157 in CY).

**Example:** Pay period Dec 16–31 (PY), Pay Date Jan 5 (CY). This is PY work being paid in CY — it was already accrued in GL 2157 at the prior year-end.

---

#### Case 3 — CY Payroll Paid in Next Year
```
PayDate ∈ Next Year
Period Start ∈ CY
Period End ∈ CY
```
**Treatment:** Include 100% in CY reconciliation for all earnings/benefits/deductions/taxes.

The NetAmt creates a **year-end accrual** in GL 2157 (a credit entry to 2157 in CY because the cash hasn't been paid yet).

**Example:** Pay period Dec 17–31 (CY), Pay Date Jan 5 (NY). Work is fully in CY but payment hasn't happened — must accrue.

---

#### Case 4 — Split Period, Paid in CY (Beginning-of-Year Accrual Reversal)
```
PayDate ∈ CY
Period Start ∈ PY
Period End ∈ CY
```
**Treatment:** Include only the **CY-prorated portion** based on working days.

The CY-prorated NetAmt partially clears the prior-year accrual in GL 2157.

**Example:** Pay period Dec 28 (PY) – Jan 10 (CY), Pay Date Jan 10. 10 total working days, 8 in CY → cy_factor = 0.80.

---

#### Case 5 — Split Period, Paid in Next Year (Year-End Accrual)
```
PayDate ∈ Next Year
Period Start ∈ CY
Period End ∈ Next Year
```
**Treatment:** Include only the **CY-prorated portion** based on working days.

The CY-prorated NetAmt is the year-end accrual booked to GL 2157.

**Example:** Pay period Dec 24 (CY) – Jan 6 (NY), Pay Date Jan 6 (NY). 10 total working days, 6 in CY → cy_factor = 0.60.

---

### Classification Decision Tree

```
Does PayDate ∈ CY?
  ├── YES:
  │     Are Period Start AND Period End both in PY?
  │     ├── YES → Case 2 (PY run paid in CY)
  │     └── NO:
  │           Does Period Start ∈ PY AND Period End ∈ CY?
  │           ├── YES → Case 4 (Split start, prorate)
  │           └── NO → Case 1 (Normal)
  └── NO (PayDate ∈ Next Year):
        Are Period Start AND Period End both in CY?
        ├── YES → Case 3 (CY run paid in NY, include 100%)
        └── NO:
              Does Period Start ∈ CY AND Period End ∈ NY?
              ├── YES → Case 5 (Split end, prorate)
              └── NO → Case 1 (default fallback)
```

---

## 12. Accrual Proration Formula

**Applies to:** Cases 4 and 5

**Formula:**
```
CY Amount = Pay Code Amount × (CY Working Days ÷ Total Working Days in Pay Run)
```

**Working Days Definition:** Monday through Friday. Weekends excluded. No holiday calendar required.

**Working Days Calculation:** Uses `numpy.busday_count(start_date, end_date + 1 day)` for inclusive date ranges.

**Applied to ALL amount columns:**
- EarnAmt × cy_factor
- BeneAmt × cy_factor
- DeducAmt × cy_factor
- EETax × cy_factor
- ERTax × cy_factor
- NetAmt × cy_factor (for 2157 accrual calculation)

**Original amounts** are preserved in `_orig_{column_name}` columns for audit trail purposes.

### Example Calculation (Case 5)

Pay period: Dec 24 – Jan 6 (10 total working days, 6 in CY)

| Pay Code Amount | cy_factor | CY Amount Included |
|---|---|---|
| EarnAmt = $5,000 | 0.60 | $3,000 |
| BeneAmt = $500 | 0.60 | $300 |
| DeducAmt = $250 | 0.60 | $150 |
| EETax = $750 | 0.60 | $450 |
| NetAmt = $4,000 | 0.60 | $2,400 (→ GL 2157 accrual) |

---

## 13. GL 2157 — Accrued Payroll Liability Reconciliation

GL 2157 (Accrued Payroll Liability) was previously marked as `GLOnly` (informational, no PR comparison). It is now fully reconciled.

### What GL 2157 Represents

At fiscal year-end, GL 2157 holds the **net payroll liability** that has been earned by employees but not yet paid. It is a credit-normal (negative) liability account.

### PR-Side Amount Construction

The PR counterpart to GL 2157 is built exclusively from the **accrual-classified pay runs**:

| Case | Contribution to GL 2157 |
|---|---|
| Case 2 (PY paid in CY) | Full original NetAmt — this **clears** a PY credit (debit to 2157) |
| Case 3 (CY paid in NY) | Full original NetAmt — this **creates** a CY credit (credit to 2157) |
| Case 4 (Split start) | CY-prorated NetAmt — partial clearing of PY accrual |
| Case 5 (Split end) | CY-prorated NetAmt — partial year-end accrual |
| Case 1 (Normal) | Not included — paid fully in CY, never touches 2157 |

### Variance Calculation for 2157

```
Variance = GL Net (2157) + PR 2157 Net
```

Using liability sign convention (GL is negative, PR is positive):
- GL 2157 balance at year-end = −$50,000 (credit = liability owed)
- PR 2157 Net = $50,000 (sum of prorated net pays from Cases 2–5)
- Variance = −50,000 + 50,000 = 0 ✓ Match

---

## 14. Variance Calculation & Sign Convention

**File:** `backend/processors/reconciliation_processor.py`

### Sign Convention by Account Type

| Account Type | GL Nature | Variance Formula | Example |
|---|---|---|---|
| `expense` | Debit-normal (positive) | `GL − PR` | 5000 Salaries |
| `liability` | Credit-normal (negative) | `GL + PR` | 2115 Tax Payable |
| `bank` | Asset disbursement | `GL + Net Pay` | 1020 Cash |
| `glonly` | Informational | Always 0 | (none currently) |

### Why Liability is `GL + PR`

Liability accounts carry a **credit balance** (negative in standard GL exports). The PR side is always **positive** (the amount withheld/owed). So:

```
GL balance = −$15,000   (credit — money owed to tax authorities)
PR amount  = +$15,000   (positive — amount withheld from employees)

Variance = GL + PR = −15,000 + 15,000 = 0  ✓ Match
```

If displayed, the PR Amount is shown as `−PR` (negated) to match the credit convention.

### Variance Tolerance

Variances below **$0.01** (1 cent) are treated as **Match** status. This handles floating-point rounding in arithmetic operations.

### Status Labels

| Status | Meaning |
|---|---|
| `✓ Match` | `abs(Variance) < $0.01` |
| `⚠ Variance` | `abs(Variance) >= $0.01` |
| `GL Only` | `account_type = glonly` — informational, no comparison |
| `⚠ No PR Match` | GL code not found in any PR Reconciliation Mapping |

---

## 15. Account Type System (Multi-Client Support)

### The Problem It Solves

Previously, the sign convention was hardcoded: GL codes starting with `2` = liability, `5` or `6` = expense, `1` = bank. This only works for clients whose chart of accounts uses this exact numbering scheme.

### The Solution

Each row in the mapping config now carries an explicit `account_type` field:
- `"expense"` — debit-normal account
- `"liability"` — credit-normal account
- `"bank"` — net pay disbursement account
- `"glonly"` — informational, no comparison

### Auto-Derivation (Backwards Compatibility)

If a saved config does not have `account_type` set, `_derive_account_type()` in `mapping_config.py` automatically fills it:
- First digit `1` → `bank`
- First digit `2` → `liability`
- `GLOnly` amount column → `glonly`
- Anything else → `expense`

This means existing client configs work without modification.

### How It Enables Multi-Client Support

A client with expenses at `7xxx` and liabilities at `4xxx` simply sets:
```json
{ "gl_code": "7000", "account_type": "expense" }
{ "gl_code": "4115", "account_type": "liability" }
```

The sign convention is now driven entirely by the config — not by GL code digits.

---

## 16. Combined GL Codes

Some mapping configs use a single config row that covers **two GL codes** separated by a slash, e.g., `"2142/2150"`.

### How They Work

1. Both GL codes are processed **separately** in the GL Pivot (each has its own rows in the GL file)
2. Both map to the **same PR Reconciliation Mapping** row
3. During reconciliation, rows for `2142` and `2150` are individually processed
4. The `_merge_combined_gl_rows()` function then **merges** them into one output row:
   - GL Net = sum(GL 2142 balance) + sum(GL 2150 balance)
   - PR Amount = taken once (not doubled — both codes point to the same PR row)
   - Variance = recalculated on the merged totals
5. Output row shows `GL Code = "2142/2150"`

---

## 17. Dual-Entry Items (Benefits & Taxes)

Some pay codes hit **two GL accounts simultaneously**. For example, a 401K contribution:
- Debits `5140 Retirement Expense` (employer cost)
- Credits `2126 Employer Retirement Payable` (liability)

Both entries come from the same pay code (`401K`, `BENEFIT`).

### How It Works in the Config

Two config rows share the same pay code:
```json
{ "gl_code": "5140", "pay_code": "401K", "code_type": "BENEFIT", "amount_column": "BeneAmt" }
{ "gl_code": "2126", "pay_code": "401K", "code_type": "BENEFIT", "amount_column": "BeneAmt" }
```

### PR Lookup Result

`pr_lookup[("401K", "BENEFIT")] = "5140 - Retirement Expense & 2126 - Employer Retirement Payable"`

Both GL codes appear in the same PR Reconciliation Mapping string.

### GL 2115 — Special Case (Different Amount Columns per Pay Code)

GL 2115 (Federal Tax Payable) receives from multiple pay codes using different amount columns:
- `FIT` → `EETax` only (employee federal income tax withholding)
- `MC` → `EeTax & ERTax` (both employee and employer Medicare)
- `SS` → `EeTax & ERTax` (both employee and employer Social Security)

The `gl_pr_amount` dictionary handles this per-row override:
```python
gl_pr_amount["2115"] = {
    "2115 - Federal Payroll Taxes Payable":               "EETax",
    "2115 - Federal Payroll Taxes Payable & 5100 - FICA": "EeTax & ERTax"
}
```

---

## 18. Excel Output — Sheet Descriptions

**File:** `backend/utils/excel_exporter.py`

The tool produces a formatted Excel workbook with 6 sheets.

### Sheet 1 — GL_Mapped

Full GL report filtered to payroll transactions only (after TransSource detection), with an added `Reconciliation Mapping` column showing which recon step each GL code belongs to.

**Use:** Audit which GL rows were included and how they were categorized.

### Sheet 2 — PR_Mapped

Full Payroll Register with an added `Reconciliation Mapping` column. For clients using accrual classification, the amount columns reflect the **prorated (CY) amounts**. The original amounts are in `_orig_{column}` columns.

**Use:** Audit which PR rows were included, their case classification, and prorated amounts.

### Sheet 3 — GL_Pivot

Aggregated GL by `Reconciliation Mapping | GL Code | GL Title | Sum of Net Amount`.

**Use:** See the total GL balance per account code.

### Sheet 4 — PR_Pivot

Aggregated PR by `Code Type | Reconciliation Mapping | Sum EarnAmt | Sum BeneAmt | Sum DeducAmt | Sum EETax | Sum ERTax`.

Also includes a `Variance` column — the variance from the reconciliation table mapped back to each PR row.

**Use:** See the total PR amounts per pay code and their variance.

### Sheet 5 — Reconciliation

The core comparison table:

| Column | Description |
|---|---|
| Reconciliation Step | Step label (A. Earnings, B. Benefits, etc.) |
| GL Code | Account code |
| GL Title | Account name |
| GL Net Amount | Sum from GL Pivot |
| PR Amount | Sum from PR Pivot (sign-adjusted) |
| Variance | GL Net ± PR Amount |
| Status | ✓ Match / ⚠ Variance / GL Only |
| Notes | Liability (credit normal) / Bank cross-check / etc. |

Last row = **TOTAL** with grand sums.

**Formatting:** Green fill for Match rows, red fill for Variance rows.

### Sheet 6 — Payroll_Process

The full reconciliation mapping configuration used for this run — all step labels, GL codes, GL titles, pay codes, amount columns, code types, and account types.

**Use:** Reference sheet showing exactly what mapping was applied.

---

## 19. Multi-Client Architecture

### Session Isolation

Each browser session gets a unique UUID. All uploaded files, column mappings, and results are stored in memory per session and never shared between clients.

### Per-Client Config Storage

```
client_mappings/
├── client_a__recon_config.json     Client A's GL↔PayCode mapping
├── client_b__recon_config.json     Client B's GL↔PayCode mapping
└── default__recon_config.json      Fallback default template
```

### Per-Client Column Mapping Cache

```
client_mappings/
├── client_a__gl_report__{hash}.json        Client A's GL column roles
├── client_a__payroll_register__{hash}.json Client A's PR column roles
```

The hash is computed from the DataFrame's column names. If the file structure changes (new columns added), the cache is automatically invalidated.

### MongoDB Alternative

If MongoDB is configured (`MONGO_URI` in `.env`):
- `mapping_configs` collection: per-client reconciliation config
- `recon_history` collection: audit trail of all reconciliation runs

---

## 20. API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/session` | Create new session |
| `GET` | `/api/session/{id}/status` | Check upload/mapping status |
| `POST` | `/api/session/{id}/reset` | Clear session |
| `POST` | `/api/upload/{file_type}` | Upload file + auto-identify columns |
| `POST` | `/api/confirm-mapping` | Save confirmed column mapping |
| `GET` | `/api/mapping-config` | Get client's reconciliation config |
| `POST` | `/api/mapping-config` | Save reconciliation config |
| `DELETE` | `/api/mapping-config` | Reset config to default |
| `GET` | `/api/mapping-config/template` | Get default template |
| `GET` | `/api/mapping-config/export` | Download config as Excel |
| `POST` | `/api/mapping-config/import` | Upload config from Excel |
| `POST` | `/api/generate-mapping` | AI-generate config from description |
| `POST` | `/api/run` | Run full reconciliation pipeline |
| `GET` | `/api/download` | Download Excel results |
| `GET` | `/api/gl-codes` | List GL codes from uploaded file |
| `GET` | `/api/pr-codes` | List pay codes from uploaded file |
| `GET` | `/api/recon-history` | List historical runs (MongoDB) |
| `GET` | `/api/recon-history/{id}` | Get single historical run |
| `GET` | `/api/download-history/{id}` | Re-download historical run Excel |

---

## 21. Configuration Files

### `.env` Environment Variables

```
# AWS Bedrock (for AI column identification)
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0

# Thresholds
FUZZY_THRESHOLD=85          # 0-100, minimum fuzzy match score
LLM_CONFIDENCE_THRESHOLD=0.75  # 0-1, minimum Bedrock confidence

# MongoDB (optional)
MONGO_URI=mongodb://localhost:27017
MONGO_DB=payroll_recon

SAMPLE_ROWS=10              # rows sent to Bedrock for context
```

### `config/settings.py`

- `COLUMN_ALIASES`: dictionary of 50+ semantic roles → list of known column name variants
- `FILE_TYPE_ROLES`: expected roles per file type
- `CLIENT_MAPPINGS_DIR`: path to client config JSON files

### `config/default_mapping.py`

- `DEFAULT_MAPPING_ROWS`: the standard template with 40+ pre-configured GL↔Pay Code mappings
- `FIXED_COLUMNS`: columns that are standardized (pay codes, amount types)
- `EDITABLE_COLUMNS`: columns the user fills in per client (GL codes, GL titles)
- `AMOUNT_COLUMN_OPTIONS`, `CODE_TYPE_OPTIONS`, `ACCOUNT_TYPE_OPTIONS`: valid dropdown values

---

## 22. Key Business Rules

1. **Both files required** — reconciliation cannot run without both GL Report and Payroll Register uploaded and column-confirmed.

2. **GL Code column validation** — if 0% of values in the mapped GL Code column match config codes, reconciliation is blocked. This prevents fund/department code columns being silently misused as GL account codes.

3. **$0.01 variance tolerance** — variances below one cent are treated as Match to handle floating-point arithmetic.

4. **Period filter is advisory for PR, mandatory guard for GL** — if the GL date filter fails AND GL data spans outside the requested period, a blocking error is raised. For PR, if filter fails it is skipped with a warning.

5. **Payroll TransSource is auto-detected** — never hardcoded. The source covering the most distinct config GL codes is selected as the payroll batch.

6. **Account type drives sign convention** — not GL code digits. Each GL code carries an explicit `account_type` from the config. If absent, it is derived from the first digit as a fallback.

7. **GL 2157 is a real liability** — it is reconciled against accrual-adjusted net pay (Cases 2–5), not marked as informational.

8. **Proration applies to all amount columns** — for Cases 4 and 5, every amount (earnings, benefits, deductions, taxes, net pay) is multiplied by the same `cy_factor` (working-day ratio).

9. **Case 2 rows are fully excluded** — prior-year pay runs paid in CY have `cy_factor = 0`. Their amounts are zeroed before the PR pivot is built.

10. **Combined GL codes are merged post-reconciliation** — `2142/2150` type entries are processed individually then merged into one output row with summed GL net and a single PR amount.

11. **Original amounts preserved** — after proration, `_orig_{column}` columns retain the pre-proration values for audit.

12. **Per-client isolation** — every client has their own mapping config, column cache, and session state. No data leaks between clients.

---

## 23. Known Limitations & Edge Cases

| Limitation | Details |
|---|---|
| Holiday calendar | Working days uses Mon–Fri only. Public holidays are not excluded from the working day count for proration. |
| 13-month PR extract | The system processes whatever dates are in the uploaded PR file. The user is responsible for ensuring the 13-month extract (CY + 1 month of next FY) is included if accrual classification is needed. |
| FY bounds required for accrual | If `period_start` / `period_end` are not provided, accrual classification is skipped and all rows are included at 100%. |
| No SUTA in default config | SUTA (State Unemployment Tax) is not in the default template as it varies significantly by state and client. Add it manually to the config. |
| Combined codes limited to `/` | Combined GL codes must use `/` as the separator (e.g., `2142/2150`). Other separators are not supported. |
| In-memory sessions | Session data is lost on server restart. If persistence is needed, MongoDB must be configured. |
| AI column identification | Requires valid AWS credentials. If Bedrock is unavailable, only fuzzy matching is used. |

---

## 24. Glossary

| Term | Definition |
|---|---|
| **CY** | Current Fiscal Year — the year being reconciled |
| **PY** | Prior Fiscal Year — the year before CY |
| **NY** | Next Year — the year after CY |
| **GL** | General Ledger — the accounting system's record of all financial transactions |
| **PR** | Payroll Register — the payroll system's record of employee pay details |
| **Variance** | The difference between the GL balance and the PR amount for a given account |
| **Recon Step** | A labeled grouping of related GL codes (e.g., "A. Earnings", "B. Benefits") |
| **Pay Code** | A code in the payroll system identifying the type of payment (e.g., Wages, FIT, 401K) |
| **Code Type** | Category of a pay code: EARNING, BENEFIT, DEDUCT, or TAXES |
| **TransSource** | Source batch identifier in MIP GL (e.g., "PRS" for payroll) |
| **cy_factor** | Proration factor: CY working days ÷ total working days in the pay period |
| **account_type** | Explicit field in config: expense, liability, bank, or glonly |
| **GLOnly** | A GL code with no PR counterpart — informational, variance forced to 0 |
| **Dual-entry** | A pay code that simultaneously posts to two GL accounts (e.g., 401K → 5140 & 2126) |
| **Combined GL** | Two GL codes merged in config and output as one row (e.g., 2142/2150) |
| **2157** | GL Accrued Payroll Liability — holds net payroll owed but not yet paid at year-end |
| **Accrual** | Recording an expense/liability in the period the work occurred, regardless of payment date |
| **Working Days** | Monday through Friday (weekends excluded), used for proration calculation |
| **MIP** | Abila MIP Fund Accounting — the primary accounting software this tool targets |
| **Fuzzy Matching** | String similarity comparison to identify columns by approximate name matching |
| **FY** | Fiscal Year — may be calendar year (Jan–Dec) or any custom 12-month period |
