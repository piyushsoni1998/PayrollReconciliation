import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent

# ── AWS Bedrock ────────────────────────────────────────────────────────────────
AWS_REGION              = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID       = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY   = os.getenv("AWS_SECRET_ACCESS_KEY", "")
BEDROCK_MODEL_ID        = os.getenv(
    "BEDROCK_MODEL_ID",
    "anthropic.claude-3-haiku-20240307-v1:0"
)

# ── Column identification thresholds ──────────────────────────────────────────
FUZZY_THRESHOLD          = int(os.getenv("FUZZY_THRESHOLD", 85))
LLM_CONFIDENCE_THRESHOLD = float(os.getenv("LLM_CONFIDENCE_THRESHOLD", 0.75))
SAMPLE_ROWS              = int(os.getenv("SAMPLE_ROWS", 10))

# ── MongoDB ────────────────────────────────────────────────────────────────────
MONGO_URI = os.getenv("MONGO_URI", "")          # e.g. mongodb://localhost:27017
MONGO_DB  = os.getenv("MONGO_DB",  "payroll_recon")

# ── Paths ─────────────────────────────────────────────────────────────────────
CLIENT_MAPPINGS_DIR = BASE_DIR / "client_mappings"
CLIENT_MAPPINGS_DIR.mkdir(exist_ok=True)

# ── Semantic roles expected in each file type ─────────────────────────────────
FILE_TYPE_ROLES = {
    "payroll_register": [
        "employee_id", "employee_name", "code_type", "pay_code",
        "pay_code_title", "pay_date", "period_start_date", "period_end_date",
        "earn_amount", "benefit_amount", "deduction_amount",
        "ee_tax", "er_tax", "net_amount",
        "ee_wc_amount", "er_wc_amount", "doc_number", "doc_date", "gl_liab_code",
        "date",
    ],
    "gl_report": [
        "gl_code", "gl_title", "trans_source", "net_amount",
        "doc_number", "doc_date", "period", "description",
        "debit_amount", "credit_amount", "date",
    ],
    "process_of_reconciliation": [
        "recon_steps", "gl_code", "gl_title", "pay_code", "code_type"
    ]
}

# ── Canonical aliases for fuzzy matching ──────────────────────────────────────
# Each role maps to a list of known column-name variants across MIP exports.
# Add more aliases here if a new client uses different naming.
COLUMN_ALIASES = {
    # ── Payroll Register ──
    "employee_id": [
        "empl", "emp_id", "employee_id", "empid", "emp#", "employee#",
        "employeeid", "empl_id", "employee number", "emp no"
    ],
    "employee_name": [
        "eefullname", "full_name", "employee_name", "name", "emp_name",
        "fullname", "employee full name", "employeename"
    ],
    "code_type": [
        "codetype", "code_type", "cd_type", "type", "paycode_type",
        "pay_type", "transaction_type", "transtype"
    ],
    # ── Payroll Register columns (exact MIP names first, then variants) ──
    "pay_code": [
        # MIP exact
        "PayCode", "paycode",
        # variants
        "pay_code", "p_code", "pcode", "pay code", "pay cd",
        "earningcode", "earning_code", "paycd", "earningcd",
    ],
    "pay_code_title": [
        # MIP exact
        "PayCodeTitle", "paycodetitle",
        # variants
        "pay_code_title", "code_title", "paycode_title",
        "earning_description", "pay code title", "paycodetitledescription",
    ],
    "pay_date": [
        # MIP exact
        "PayDate", "paydate",
        # variants
        "pay_date", "check_date", "checkdate", "payment_date",
        "dt_pay", "chkdate", "check date", "payment date",
    ],
    "period_start_date": [
        # MIP exact
        "BgnPayPeriodDate", "bgnpayperioddate",
        # variants
        "period_start", "start_date", "pay_period_start",
        "period_begin", "periodstart", "bgn_pay_period",
        "period start date", "pay period start", "begin date",
    ],
    "period_end_date": [
        # MIP exact
        "EndPayPeriodDate", "endpayperioddate",
        # variants
        "period_end", "end_date", "pay_period_end",
        "periodend", "end_pay_period",
        "period end date", "pay period end", "end date",
    ],
    "earn_amount": [
        # MIP exact
        "EarnAmt", "earnamt",
        # variants
        "earn_amount", "earning_amount", "amt_earn",
        "gross_wages", "wages_amount", "earnings", "earningamt",
        "earn amt", "earning amt", "gross pay",
    ],
    "benefit_amount": [
        # MIP exact
        "BeneAmt", "beneamt",
        # variants
        "benefit_amount", "ben_amount", "benefit_amt",
        "benefits", "benefitamt", "bene amt", "benefit amt",
    ],
    "deduction_amount": [
        # MIP exact
        "DeducAmt", "deducamt",
        # variants
        "deduction_amount", "deduct_amount", "ded_amount",
        "deductions", "dedamt", "deduc amt", "deduction amt",
    ],
    "ee_tax": [
        # MIP exact
        "EETax", "eetax",
        # variants
        "ee_tax", "employee_tax", "emp_tax",
        "tax_ee", "ee_taxes", "eetaxamt", "ee tax",
        "employee tax", "emp tax withheld",
    ],
    "er_tax": [
        # MIP exact
        "ERTax", "ertax",
        # variants
        "er_tax", "employer_tax", "emp_er_tax",
        "tax_er", "er_taxes", "ertaxamt", "er tax",
        "employer tax", "employer fica",
    ],
    "net_amount": [
        # MIP exact
        "NetAmt", "netamt",
        # variants
        "net_amount", "net_pay", "net", "amount_net", "netpay",
        "net amt", "net pay", "take home",
    ],
    "ee_wc_amount": [
        # MIP exact
        "EEWCAmt", "eewcamt",
        # variants
        "ee_wc_amount", "ee_workers_comp", "eewc",
        "ee wc amt", "ee workers comp",
    ],
    "er_wc_amount": [
        # MIP exact
        "ERWCAmt", "erwcamt",
        # variants
        "er_wc_amount", "er_workers_comp", "erwc",
        "er wc amt", "er workers comp",
    ],
    "doc_number": [
        # MIP exact — note: MIP spells it "DocNur" (not DocNum)
        "DocNur", "docnur",
        # variants
        "doc_number", "document_number", "doc_num",
        "check_number", "docnum", "docno", "doc num",
        "check number", "check no", "document number",
    ],
    "doc_date": [
        # MIP exact
        "DocDate", "docdate",
        # variants
        "doc_date", "document_date", "docdt", "doc date",
        "document date", "check date posted",
    ],
    "gl_liab_code": [
        # MIP exact
        "GLliabCode", "glliabcode",
        # variants
        "gl_liab_code", "gl_liability_code", "liability_code",
        "liabcode", "gl liab code", "gl liability code",
    ],

    # ── GL Report (MIP Accounting export column names) ────────────────────
    "gl_code": [
        # MIP / common GL export names
        "GL Code", "GLCode", "glcode", "gl_code",
        "Account", "account", "Acct", "acct",
        "Account Code", "account_code", "AccountCode",
        "Account Number", "account_number", "AccountNumber",
        "Account No", "account no", "acctno", "AccountNo",
        "GL Account", "glaccount", "GL#", "gl#",
    ],
    "gl_title": [
        # MIP / common GL export names
        "GL Title", "GLTitle", "gltitle", "gl_title",
        "Account Name", "account_name", "AccountName",
        "Account Title", "account_title", "AccountTitle",
        "Account Description", "account_description",
        "Acct Name", "acct_name", "AcctName",
        "Description", "description",
    ],
    "trans_source": [
        # MIP exact
        "TransSource", "transsource", "trans_source",
        # variants
        "Source", "source", "Transaction Source", "transaction_source",
        "Txn Source", "txn_source", "Trx Source", "trx_source",
        "TransactionSource", "Src", "src", "Journal Source",
    ],
    "net_amount": [                  # also used by GL (overrides PR alias above)
        # MIP exact for both PR and GL
        "NetAmt", "netamt", "Net", "net",
        # GL-specific
        "Net Amount", "net_amount", "NetAmount",
        "Amount", "amount", "Balance", "balance",
        "Net Balance", "net_balance",
        # PR variants already above — listing again for GL context
        "net_pay", "netpay", "Net Pay",
    ],
    "debit_amount": [
        "Debit", "debit", "DebitAmt", "debitamt",
        "Debit Amount", "debit_amount", "Dr", "dr",
        "Dr Amount", "dr_amount",
    ],
    "credit_amount": [
        "Credit", "credit", "CreditAmt", "creditamt",
        "Credit Amount", "credit_amount", "Cr", "cr",
        "Cr Amount", "cr_amount",
    ],
    "period": [
        "Period", "period", "Fiscal Period", "fiscal_period",
        "Accounting Period", "accounting_period",
        "Pay Period", "pay_period", "Prd", "prd", "Per", "per",
        "Period No", "period_no", "Month", "month",
    ],
    "description": [
        "Description", "description", "Memo", "memo",
        "Journal Description", "journal_description",
        "Narrative", "narrative", "Notes", "notes", "Desc", "desc",
    ],

    # ── Date column (used for year filtering in both GL and PR) ──────────
    "date": [
        # GL report date columns (MIP exact names first)
        "PostToDate", "posttodate", "Post To Date", "post_to_date",
        "EffectiveDate", "effectivedate", "Effective Date", "effective_date",
        "TranDate", "trandate", "Transaction Date", "transaction_date",
        "PostDate", "postdate", "Posting Date", "posting_date",
        "JournalDate", "journaldate", "Journal Date", "journal_date",
        "FiscalDate", "fiscaldate", "Fiscal Date", "fiscal_date",
        "GL Date", "gl_date", "gldate",
        "EntryDate", "entrydate", "Entry Date", "entry_date",
        "TransactionDate", "Trans Date", "trans_date",
        "Period Date", "period_date", "perioddate",
        # Payroll Register date columns
        "PayDate", "paydate", "Pay Date", "pay_date",
        "CheckDate", "checkdate", "Check Date", "check_date",
        "Payment Date", "payment_date", "PaymentDate",
        "EndPayPeriodDate", "endpayperioddate", "End Pay Period Date",
        "BgnPayPeriodDate", "bgnpayperioddate",
        # Generic
        "Date", "date", "Dt", "dt",
    ],

    # ── Process of Reconciliation (exact header names from the file) ──────
    "recon_steps": [
        # Exact as seen in the file image
        "STEPS of Reconciliation", "Steps of Reconciliation",
        "steps of reconciliation", "StepsofReconciliation",
        # variants
        "recon_steps", "reconciliation_steps",
        "Reconciliation Mapping", "reconciliation mapping",
        "Recon Mapping", "recon mapping",
        "Recon Step", "recon step", "Step", "steps",
        "GL Mapping", "gl mapping", "Reconciliation",
        "Mapping", "mapping",
    ],
}
