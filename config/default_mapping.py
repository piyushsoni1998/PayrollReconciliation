"""
default_mapping.py
───────────────────
The standard MIP payroll reconciliation mapping template.

FIXED columns  (same across ALL clients — never change):
    recon_step, pay_code, pay_code_title, amount_column, code_type

VARIABLE columns  (user fills in per client):
    gl_code, gl_title

amount_column values:
    EarnAmt        → earnings
    BeneAmt        → benefits
    DeducAmt       → deductions
    EETax          → employee tax
    ERTax          → employer tax
    EETax & ERTax  → both (e.g. Medicare / Social Security)
    NetAmt         → net pay — bank cross-check only (GL 1020)
    GLOnly         → GL balance shown as-is; no PR comparison
                     (accrual accounts, clearing accounts, etc.)
"""

# ── Recon step labels ──────────────────────────────────────────────────────────
_EARN    = "A. Earning/ Gross wages"
_BENE    = "B. Benefits / Employer expenses"
_BENE_L  = "B.1 Benefits / Employer expenses - Liabilities"
_DEDUCT  = "C. Deductions / Employee Deductions - Liabilities"
_TAXES   = "D. Employee & Employer Taxes - Liabilities"
_ERTAX   = "E. ERTax / Employer Taxes"
_BANK    = "F. Bank Payment to Employee"
_ACCRUE  = "G. Accrued Payroll Liability"

# ── GL title constants ─────────────────────────────────────────────────────────
_SAL     = "Salaries & Wages"
_INS_B   = "Insurance Benefits"
_RET_EXP = "Retirement expense"
_ER_SCHW = "Employer Ret. Pybl - SCHWAB"
_EE_SCHW = "EE Retiremt payable - SCHWAB"
_FED_TAX = "Federal payroll taxes payable"

# ── Pay code / title constants ─────────────────────────────────────────────────
_401K_T   = "401K Retirement"
_401K50A  = "401K+50A"
_401K50AT = "401K over 50 Amount"
_401K50   = "401K+50"
_401KAMT  = "401Kamt"
_401KAMT_T= "401K Retirement Amount"
_ROTH     = "Roth"
_MET      = "MLIFE151"
_MET_T    = "2015 Met Life Deduction"
_VIS      = "Vision16"
_VIS_T    = "Vision 2016"
_EE_ER    = "EeTax & ERTax"

DEFAULT_MAPPING_ROWS = [
    # ── A. Earning / Gross Wages ──────────────────────────────────────────
    {"recon_step": _EARN,   "gl_code": "5000", "gl_title": _SAL,     "pay_code": "Wages",    "pay_code_title": "Regular Wages",                    "amount_column": "EarnAmt",       "code_type": "EARNING"},
    {"recon_step": _EARN,   "gl_code": "5000", "gl_title": _SAL,     "pay_code": "Retro",    "pay_code_title": "Retroactive Pay",                  "amount_column": "EarnAmt",       "code_type": "EARNING"},
    {"recon_step": _EARN,   "gl_code": "5000", "gl_title": _SAL,     "pay_code": "ADJUST",   "pay_code_title": "Adjustments",                      "amount_column": "EarnAmt",       "code_type": "EARNING"},
    {"recon_step": _EARN,   "gl_code": "5000", "gl_title": _SAL,     "pay_code": "PTO BUY",  "pay_code_title": "PTO BUY OUT",                      "amount_column": "EarnAmt",       "code_type": "EARNING"},
    {"recon_step": _EARN,   "gl_code": "5000", "gl_title": _SAL,     "pay_code": "SUP/HAZ",  "pay_code_title": "Supplemental/Hazard Pay",           "amount_column": "EarnAmt",       "code_type": "EARNING"},
    {"recon_step": _EARN,   "gl_code": "5000", "gl_title": _SAL,     "pay_code": "WAGES2",   "pay_code_title": "Wages - @ diff rate",               "amount_column": "EarnAmt",       "code_type": "EARNING"},
    {"recon_step": _EARN,   "gl_code": "5000", "gl_title": _SAL,     "pay_code": "Holiday",  "pay_code_title": "Holiday Pay",                      "amount_column": "EarnAmt",       "code_type": "EARNING"},
    {"recon_step": _EARN,   "gl_code": "5000", "gl_title": _SAL,     "pay_code": "LERETENT", "pay_code_title": "Law Enf Retention Pay",             "amount_column": "EarnAmt",       "code_type": "EARNING"},
    {"recon_step": _EARN,   "gl_code": "5001", "gl_title": "OT Wages",                       "pay_code": "Overtime", "pay_code_title": "Overtime wages",                   "amount_column": "EarnAmt",       "code_type": "EARNING"},
    {"recon_step": _EARN,   "gl_code": "6000", "gl_title": "Stipends",                       "pay_code": "STX-1000", "pay_code_title": "Stipend-$1000 Fed Tax Withheld",   "amount_column": "EarnAmt",       "code_type": "EARNING"},

    # ── B. Benefits / Employer Expenses ───────────────────────────────────
    {"recon_step": _BENE,   "gl_code": "5130", "gl_title": _INS_B,   "pay_code": "Dental16", "pay_code_title": "Dental 2016 Insurance Benefits",   "amount_column": "BeneAmt",       "code_type": "BENEFIT"},
    {"recon_step": _BENE,   "gl_code": "5130", "gl_title": _INS_B,   "pay_code": "Health16", "pay_code_title": "Health 2017 Insurance Benefit",    "amount_column": "BeneAmt",       "code_type": "BENEFIT"},
    {"recon_step": _BENE,   "gl_code": "5130", "gl_title": _INS_B,   "pay_code": _MET,       "pay_code_title": _MET_T,                             "amount_column": "BeneAmt",       "code_type": "BENEFIT"},
    {"recon_step": _BENE,   "gl_code": "5130", "gl_title": _INS_B,   "pay_code": _VIS,       "pay_code_title": _VIS_T,                             "amount_column": "BeneAmt",       "code_type": "BENEFIT"},
    {"recon_step": _BENE,   "gl_code": "5140", "gl_title": _RET_EXP, "pay_code": "401K",     "pay_code_title": _401K_T,                            "amount_column": "BeneAmt",       "code_type": "BENEFIT"},
    {"recon_step": _BENE,   "gl_code": "5140", "gl_title": _RET_EXP, "pay_code": _401K50A,   "pay_code_title": _401K50AT,                          "amount_column": "BeneAmt",       "code_type": "BENEFIT"},
    {"recon_step": _BENE,   "gl_code": "5140", "gl_title": _RET_EXP, "pay_code": _401K50,    "pay_code_title": "401K Over 50",                     "amount_column": "BeneAmt",       "code_type": "BENEFIT"},
    {"recon_step": _BENE,   "gl_code": "5140", "gl_title": _RET_EXP, "pay_code": _401KAMT,   "pay_code_title": _401KAMT_T,                         "amount_column": "BeneAmt",       "code_type": "BENEFIT"},
    {"recon_step": _BENE,   "gl_code": "5140", "gl_title": _RET_EXP, "pay_code": _ROTH,      "pay_code_title": "Roth",                             "amount_column": "BeneAmt",       "code_type": "BENEFIT"},

    # ── B.1 Benefits / Employer Expenses - Liabilities ────────────────────
    {"recon_step": _BENE_L, "gl_code": "2126", "gl_title": _ER_SCHW, "pay_code": "401K",     "pay_code_title": _401K_T,                            "amount_column": "BeneAmt",       "code_type": "BENEFIT"},
    {"recon_step": _BENE_L, "gl_code": "2126", "gl_title": _ER_SCHW, "pay_code": _401K50A,   "pay_code_title": _401K50AT,                          "amount_column": "BeneAmt",       "code_type": "BENEFIT"},
    {"recon_step": _BENE_L, "gl_code": "2126", "gl_title": _ER_SCHW, "pay_code": _401K50,    "pay_code_title": "401K Over 50",                     "amount_column": "BeneAmt",       "code_type": "BENEFIT"},
    {"recon_step": _BENE_L, "gl_code": "2126", "gl_title": _ER_SCHW, "pay_code": _401KAMT,   "pay_code_title": _401KAMT_T,                         "amount_column": "BeneAmt",       "code_type": "BENEFIT"},
    {"recon_step": _BENE_L, "gl_code": "2126", "gl_title": _ER_SCHW, "pay_code": _ROTH,      "pay_code_title": "Roth",                             "amount_column": "BeneAmt",       "code_type": "BENEFIT"},
    {"recon_step": _BENE_L, "gl_code": "2145", "gl_title": "Health Insurance ER",            "pay_code": "Health16", "pay_code_title": "Health 2017 Insurance Benefit",    "amount_column": "BeneAmt",       "code_type": "BENEFIT"},
    {"recon_step": _BENE_L, "gl_code": "2146", "gl_title": "Dental Insurance ER",            "pay_code": "Dental16", "pay_code_title": "Dental 2016 Insurance Benefits",   "amount_column": "BeneAmt",       "code_type": "BENEFIT"},
    {"recon_step": _BENE_L, "gl_code": "2147", "gl_title": "Vision Insurance ER",            "pay_code": _VIS,       "pay_code_title": _VIS_T,                             "amount_column": "BeneAmt",       "code_type": "BENEFIT"},
    {"recon_step": _BENE_L, "gl_code": "2148", "gl_title": "MetLife Insurance ER",           "pay_code": _MET,       "pay_code_title": _MET_T,                             "amount_column": "BeneAmt",       "code_type": "BENEFIT"},

    # ── C. Deductions / Employee Deductions - Liabilities ─────────────────
    {"recon_step": _DEDUCT, "gl_code": "1220", "gl_title": "Due To/From Employee",            "pay_code": "DUEFR EE", "pay_code_title": "Due From Employee",               "amount_column": "DeducAmt",      "code_type": "DEDUCT"},
    {"recon_step": _DEDUCT, "gl_code": "2121", "gl_title": "Tribal loan payable",             "pay_code": "TBLN",     "pay_code_title": "Tribal Loan",                     "amount_column": "DeducAmt",      "code_type": "DEDUCT"},
    {"recon_step": _DEDUCT, "gl_code": "2127", "gl_title": _EE_SCHW, "pay_code": "401K",     "pay_code_title": _401K_T,                            "amount_column": "DeducAmt",      "code_type": "DEDUCT"},
    {"recon_step": _DEDUCT, "gl_code": "2127", "gl_title": _EE_SCHW, "pay_code": _401K50A,   "pay_code_title": _401K50AT,                          "amount_column": "DeducAmt",      "code_type": "DEDUCT"},
    {"recon_step": _DEDUCT, "gl_code": "2127", "gl_title": _EE_SCHW, "pay_code": _401K50,    "pay_code_title": "Retirement Employee Ded + 50",     "amount_column": "DeducAmt",      "code_type": "DEDUCT"},
    {"recon_step": _DEDUCT, "gl_code": "2127", "gl_title": _EE_SCHW, "pay_code": _401KAMT,   "pay_code_title": _401KAMT_T,                         "amount_column": "DeducAmt",      "code_type": "DEDUCT"},
    {"recon_step": _DEDUCT, "gl_code": "2127", "gl_title": _EE_SCHW, "pay_code": "401K-L",   "pay_code_title": "401K Loan payment",                "amount_column": "DeducAmt",      "code_type": "DEDUCT"},
    {"recon_step": _DEDUCT, "gl_code": "2127", "gl_title": _EE_SCHW, "pay_code": _ROTH,      "pay_code_title": "Roth Retirement",                  "amount_column": "DeducAmt",      "code_type": "DEDUCT"},
    {"recon_step": _DEDUCT, "gl_code": "2132", "gl_title": "LegalShield",                     "pay_code": "LegalShi", "pay_code_title": "LegalShield",                     "amount_column": "DeducAmt",      "code_type": "DEDUCT"},
    {"recon_step": _DEDUCT, "gl_code": "2138", "gl_title": "Child support payable",           "pay_code": "CHILD SU", "pay_code_title": "CHILD SUPPORT",                   "amount_column": "DeducAmt",      "code_type": "DEDUCT"},
    {"recon_step": _DEDUCT, "gl_code": "2139", "gl_title": "MetLife payable EE",              "pay_code": "METLIFSU", "pay_code_title": "MetLife Supplemental",             "amount_column": "DeducAmt",      "code_type": "DEDUCT"},
    {"recon_step": _DEDUCT, "gl_code": "2139", "gl_title": "MetLife payable EE",              "pay_code": _MET,       "pay_code_title": _MET_T,                             "amount_column": "DeducAmt",      "code_type": "DEDUCT"},
    {"recon_step": _DEDUCT, "gl_code": "2140", "gl_title": "Garnishments & Levies paybl EE",  "pay_code": "GARNISHM", "pay_code_title": "Garnishment",                     "amount_column": "DeducAmt",      "code_type": "DEDUCT"},
    {"recon_step": _DEDUCT, "gl_code": "2141", "gl_title": "Health Insurance EE",             "pay_code": "Health16", "pay_code_title": "Health 2017 Insurance Deduction", "amount_column": "DeducAmt",      "code_type": "DEDUCT"},
    {"recon_step": _DEDUCT, "gl_code": "2142/2150", "gl_title": "Dental Insurance EE",        "pay_code": "DENTAL",   "pay_code_title": "Dental Insurance",                "amount_column": "DeducAmt",      "code_type": "DEDUCT"},
    {"recon_step": _DEDUCT, "gl_code": "2142/2150", "gl_title": "Dental Insurance EE",        "pay_code": "Dental16", "pay_code_title": "Dental 2016 Ins Deduction",       "amount_column": "DeducAmt",      "code_type": "DEDUCT"},
    {"recon_step": _DEDUCT, "gl_code": "2143/2150", "gl_title": "Vision Insurance EE",        "pay_code": "VISION",   "pay_code_title": "Vision Insurance",                "amount_column": "DeducAmt",      "code_type": "DEDUCT"},
    {"recon_step": _DEDUCT, "gl_code": "2143/2150", "gl_title": "Vision Insurance EE",        "pay_code": _VIS,       "pay_code_title": _VIS_T,                             "amount_column": "DeducAmt",      "code_type": "DEDUCT"},

    # ── D. Employee & Employer Taxes - Liabilities ────────────────────────
    {"recon_step": _TAXES,  "gl_code": "2115", "gl_title": _FED_TAX, "pay_code": "FIT",      "pay_code_title": "Federal Withholding",              "amount_column": "EETax",         "code_type": "TAXES"},
    {"recon_step": _TAXES,  "gl_code": "2115", "gl_title": _FED_TAX, "pay_code": "MC",       "pay_code_title": "Medicare",                         "amount_column": _EE_ER,          "code_type": "TAXES"},
    {"recon_step": _TAXES,  "gl_code": "2115", "gl_title": _FED_TAX, "pay_code": "SS",       "pay_code_title": "Social Security",                  "amount_column": _EE_ER,          "code_type": "TAXES"},
    {"recon_step": _TAXES,  "gl_code": "2120", "gl_title": "State payroll taxes payable",    "pay_code": "SWT",      "pay_code_title": "State Withholding",               "amount_column": "EETax",         "code_type": "TAXES"},

    # ── E. ERTax / Employer Taxes ─────────────────────────────────────────
    {"recon_step": _ERTAX,  "gl_code": "5100", "gl_title": "Fica expense",                   "pay_code": "MC",       "pay_code_title": "Medicare",                        "amount_column": "ERTax",         "code_type": "TAXES"},
    {"recon_step": _ERTAX,  "gl_code": "5100", "gl_title": "Fica expense",                   "pay_code": "SS",       "pay_code_title": "Social Security",                 "amount_column": "ERTax",         "code_type": "TAXES"},

    # ── F. Bank Payment to Employee ───────────────────────────────────────
    {"recon_step": _BANK,   "gl_code": "1020", "gl_title": "Cash in Bank - WF-Payroll",      "pay_code": "",         "pay_code_title": "",                                "amount_column": "NetAmt",        "code_type": ""},

    # ── G. Accrued Payroll Liability ──────────────────────────────────────
    # GLOnly: shows the GL accrual balance as informational — no PR counterpart.
    {"recon_step": _ACCRUE, "gl_code": "2157", "gl_title": "Accounts Payable - Payroll Oth", "pay_code": "",         "pay_code_title": "Accrued Payroll Liability (GL balance = prior-period accrual reversed + current-period accrual)", "amount_column": "GLOnly", "code_type": ""},
]


# Fixed columns — read-only in the UI
FIXED_COLUMNS = ["recon_step", "pay_code", "pay_code_title", "amount_column", "code_type"]

# Editable columns — user fills in per client
EDITABLE_COLUMNS = ["gl_code", "gl_title"]

# Valid amount column options
AMOUNT_COLUMN_OPTIONS = ["EarnAmt", "BeneAmt", "DeducAmt", "EETax", "ERTax", _EE_ER, "NetAmt", "GLOnly"]

# Valid code type options
CODE_TYPE_OPTIONS = ["EARNING", "BENEFIT", "DEDUCT", "TAXES", ""]
