"""
prepaid_data_adapter.py
Prepaid Expense Data Adapter & Validation Layer

Converts raw prepaid ledger and amortization schedule exports into the
exact normalized schemas expected by reconciliation_engine.py.

Sits between raw user files and the existing engine:

    Raw user files
    ↓
    prepaid_data_adapter.py
    ↓
    normalized ledger + normalized amortization schedule
    ↓
    reconciliation_engine.run_analysis()
    ↓
    dashboard
"""

import pandas as pd
import numpy as np
import re
from datetime import datetime, timedelta


# ════════════════════════════════════════════════════════════════
# TARGET SCHEMAS (must match reconciliation_engine.py exactly)
# ════════════════════════════════════════════════════════════════

LEDGER_SCHEMA = [
    "transaction_id", "transaction_date", "accounting_period",
    "entity", "transaction_type", "document_number", "vendor_name",
    "description", "amount", "running_balance", "prepaid_item_id",
]

AMORT_SCHEMA = [
    "schedule_id", "prepaid_item_id", "entity", "vendor_name",
    "description", "original_amount", "start_date", "end_date",
    "total_periods", "accounting_period", "period_number",
    "scheduled_amortization", "expected_ending_balance",
    "source_document", "status",
]

# Critical fields — analysis cannot proceed without data in these
CRITICAL_LEDGER = ["amount", "accounting_period", "transaction_type"]
CRITICAL_AMORT  = ["scheduled_amortization", "accounting_period"]


# ════════════════════════════════════════════════════════════════
# SYNONYM DICTIONARY
# ════════════════════════════════════════════════════════════════
# Maps messy ERP column names to target fields.
# Include both raw and post-clean_column_names variants.

SYNONYMS = {
    # ── Ledger fields ─────────────────────────────────────────
    "transaction_id": [
        "transaction_id", "transaction id", "txn id", "id",
        "line id", "entry id", "internal id",
    ],
    "transaction_date": [
        "transaction_date", "transaction date", "date",
        "posting date", "gl date", "accounting date",
        "entry date", "doc date",
    ],
    "accounting_period": [
        "accounting_period", "accounting period",
        "accounting period: name", "period", "period name",
        "fiscal period", "gl period",
        "amortization date/ period", "amortization date/period",
    ],
    "transaction_type": [
        "transaction_type", "transaction type", "type",
        "document type", "source type", "entry type",
    ],
    "document_number": [
        "document_number", "document number", "doc number",
        "doc no", "invoice number", "bill number",
        "transaction number", "reference", "voucher number",
    ],
    "vendor_name": [
        "vendor_name", "vendor name", "vendor", "supplier",
        "supplier name", "customer/vendor", "payee",
    ],
    "description": [
        "description", "memo", "line memo", "comments",
        "transaction description", "narration",
        "lookup reference", "details", "schedule name",
    ],
    "amount": [
        "amount", "net amount", "signed amount",
        "transaction amount", "debit/credit", "net", "value",
    ],
    "running_balance": [
        "running_balance", "running balance", "balance",
        "ending balance", "account balance",
    ],
    "prepaid_item_id": [
        "prepaid_item_id", "prepaid item id", "asset id",
        "reference id", "item id",
    ],
    "entity": [
        "entity", "company", "subsidiary", "legal entity",
        "business unit", "organization",
    ],
    # ── Amortization fields ───────────────────────────────────
    "schedule_id": [
        "schedule_id", "schedule id",
        "amortization schedule id", "schedule number",
    ],
    "original_amount": [
        "original_amount", "original amount",
        "amount schedule total",          # post-clean of "Amount (Schedule Total)"
        "amount (schedule total)",        # pre-clean
        "schedule amount", "total amount",
    ],
    "scheduled_amortization": [
        "scheduled_amortization", "scheduled amortization",
        "period amortization amount", "period amount",
        "amortization amount", "monthly amount",
    ],
    "expected_ending_balance": [
        "expected_ending_balance", "expected ending balance",
        "remaining balance",
    ],
    "source_document": [
        "source_document", "source document",
        "created from transaction", "source transaction",
        "origin document",
    ],
    "status": [
        "status", "schedule status", "amortization status",
    ],
    "start_date": [
        "start_date", "start date", "effective date",
        "begin date",
    ],
    "end_date": [
        "end_date", "end date", "expiration date",
    ],
    "total_periods": [
        "total_periods", "total periods",
        "number of periods", "term",
    ],
    "period_number": [
        "period_number", "period number", "sequence",
    ],
}

# Transaction type normalization
TXN_TYPE_MAP = {
    "bill": "Bill",
    "invoice": "Bill",
    "vendor bill": "Bill",
    "bill credit": "Bill Credit",
    "credit memo": "Bill Credit",
    "vendor credit": "Bill Credit",
    "journal": "Journal Entry",
    "journal entry": "Journal Entry",
    "general journal": "Journal Entry",
    "je": "Journal Entry",
    "currency revaluation": "__DROP__",
}

# File-type detection signals
AMORT_SIGNALS = {
    "amortization schedule id", "schedule id",
    "amortization date/ period", "amortization date/period",
    "period amortization amount", "schedule name",
    "created from transaction",
}
LEDGER_SIGNALS = {
    "type", "transaction type", "document number",
    "balance", "running balance", "amount",
    "accounting period: name", "accounting period", "date",
}


# ════════════════════════════════════════════════════════════════
# 1. read_file
# ════════════════════════════════════════════════════════════════

def read_file(file_or_path, sheet_name=0):
    """Read a CSV or Excel file into a raw DataFrame.

    Returns:
        tuple: (DataFrame, metadata dict)
    """
    meta = {"filename": "", "format": "", "rows": 0, "cols": 0}
    name = getattr(file_or_path, "name", str(file_or_path))
    meta["filename"] = name
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    try:
        if ext == "csv":
            df = pd.read_csv(file_or_path, dtype=str)
            meta["format"] = "csv"
        elif ext in ("xlsx", "xls", "xlsm"):
            df = pd.read_excel(file_or_path, sheet_name=sheet_name,
                               dtype=str, engine="openpyxl")
            meta["format"] = "excel"
        else:
            try:
                df = pd.read_csv(file_or_path, dtype=str)
                meta["format"] = "csv"
            except Exception:
                if hasattr(file_or_path, "seek"):
                    file_or_path.seek(0)
                df = pd.read_excel(file_or_path, sheet_name=sheet_name,
                                   dtype=str, engine="openpyxl")
                meta["format"] = "excel"

        meta["rows"], meta["cols"] = df.shape
        return df, meta

    except Exception as e:
        raise ValueError(f"Cannot read file '{name}': {e}")


# ════════════════════════════════════════════════════════════════
# 2. detect_header_row
# ════════════════════════════════════════════════════════════════

def detect_header_row(raw_df, max_scan=20):
    """Find the most likely header row in files that may have
    report titles, blank rows, or metadata above the data table.

    Returns:
        int: 0-based row index to use as the header
    """
    known = set()
    for syns in SYNONYMS.values():
        for s in syns:
            known.add(s.lower().strip())

    best_row, best_score = 0, 0
    for i in range(min(max_scan, len(raw_df))):
        vals = raw_df.iloc[i].astype(str).str.lower().str.strip()
        score = sum(1 for v in vals if v in known)
        texts = sum(1 for v in vals
                    if v not in ("", "nan", "none")
                    and not _is_numeric(v)
                    and len(v) < 50)
        score += texts * 0.3
        if score > best_score:
            best_score = score
            best_row = i

    return best_row


def _apply_header(raw_df, header_row):
    """Promote a detected row to column names."""
    if header_row == 0:
        return raw_df.copy()
    cols = raw_df.iloc[header_row].astype(str).str.strip().tolist()
    df = raw_df.iloc[header_row + 1:].copy()
    df.columns = cols
    return df.reset_index(drop=True)


# ════════════════════════════════════════════════════════════════
# 3. clean_column_names
# ════════════════════════════════════════════════════════════════

def clean_column_names(df):
    """Standardize column names to lowercase with consistent spacing."""
    df = df.copy()
    out = []
    for col in df.columns:
        c = str(col).strip().lower()
        c = re.sub(r"[()]", " ", c)
        c = re.sub(r"\s+", " ", c).strip()
        c = re.sub(r"[^\w\s/:#\-.]", "", c)
        out.append(c)
    df.columns = out
    return df


# ════════════════════════════════════════════════════════════════
# 4. suggest_column_mapping
# ════════════════════════════════════════════════════════════════

def suggest_column_mapping(df, target_schema):
    """Match source columns to target fields using the synonym dictionary.

    Returns:
        dict: {target_field: {"source": str|None,
                              "confidence": "high"|"medium"|"missing",
                              "method": str}}

    Each source column is used at most once (no double-mapping).
    """
    cols_lower = {str(c).lower().strip(): c for c in df.columns}
    mapping = {}
    used = set()

    # Pass 1: exact/synonym match
    for target in target_schema:
        synonyms = SYNONYMS.get(target, [target])
        hit = None
        for syn in synonyms:
            key = syn.lower().strip()
            if key in cols_lower and cols_lower[key] not in used:
                hit = cols_lower[key]
                used.add(hit)
                mapping[target] = {
                    "source": hit,
                    "confidence": "high",
                    "method": f"synonym: '{syn}'" if key != target else "exact",
                }
                break
        if target not in mapping:
            mapping[target] = {"source": None, "confidence": "missing",
                               "method": "not found"}

    # Pass 2: partial match for remaining
    for target in target_schema:
        if mapping[target]["source"] is not None:
            continue
        synonyms = SYNONYMS.get(target, [target])
        for syn in synonyms:
            sl = syn.lower()
            if len(sl) <= 3:
                continue
            for col_key, col_orig in cols_lower.items():
                if col_orig in used:
                    continue
                if sl in col_key or col_key in sl:
                    mapping[target] = {
                        "source": col_orig,
                        "confidence": "medium",
                        "method": f"partial: '{col_key}' ≈ '{syn}'",
                    }
                    used.add(col_orig)
                    break
            if mapping[target]["source"] is not None:
                break

    return mapping


# ════════════════════════════════════════════════════════════════
# 5. normalize_ledger
# ════════════════════════════════════════════════════════════════

def normalize_ledger(raw_df, mapping=None, entity=None):
    """Convert a raw prepaid ledger export into the engine's schema.

    Parameters:
        raw_df  : DataFrame (already header-detected, cleaned columns)
        mapping : column mapping dict (auto-generated if None)
        entity  : entity name to assign if not in the data

    Returns:
        tuple: (normalized_df, mapping, warnings)
    """
    warnings = []
    df = clean_column_names(raw_df.copy())
    df = df.dropna(how="all").reset_index(drop=True)

    # Filter blank-type rows
    type_col = _find_col(df, "transaction_type")
    if type_col:
        blank = df[type_col].astype(str).str.strip().replace("", np.nan).isna()
        n = blank.sum()
        if n:
            df = df[~blank].reset_index(drop=True)
            warnings.append(f"Dropped {n} row(s) with blank transaction type.")

    if mapping is None:
        mapping = suggest_column_mapping(df, LEDGER_SCHEMA)

    result = _apply_mapping(df, mapping, entity)

    # Drop Currency Revaluation
    if "transaction_type" in result.columns:
        cr = result["transaction_type"] == "__DROP__"
        n_cr = cr.sum()
        if n_cr:
            result = result[~cr].reset_index(drop=True)
            warnings.append(
                f"Filtered {n_cr} Currency Revaluation row(s) — "
                f"FX adjustments are not prepaid transactions."
            )

    # Drop unparseable accounting periods
    if "accounting_period" in result.columns:
        parseable = result["accounting_period"].apply(_parse_period).notna()
        n_bad = (~parseable).sum()
        if n_bad:
            bad = result.loc[~parseable, "accounting_period"].unique()[:5]
            result = result[parseable].reset_index(drop=True)
            warnings.append(f"Filtered {n_bad} row(s) with unparseable periods: {list(bad)}.")

    # Ensure all required columns
    for col in LEDGER_SCHEMA:
        if col not in result.columns:
            result[col] = ""
            warnings.append(f"'{col}' not found in source — filled with blanks.")

    result = result[LEDGER_SCHEMA].reset_index(drop=True)
    result["prepaid_item_id"] = result["prepaid_item_id"].fillna("").astype(str)

    return result, mapping, warnings


# ════════════════════════════════════════════════════════════════
# 6. normalize_amortization_schedule
# ════════════════════════════════════════════════════════════════

def normalize_amortization_schedule(raw_df, mapping=None, entity=None):
    """Convert a raw amortization export into the engine's schema.

    Parameters:
        raw_df  : DataFrame (already header-detected, cleaned columns)
        mapping : column mapping dict (auto-generated if None)
        entity  : entity name to assign if not in the data

    Returns:
        tuple: (normalized_df, mapping, warnings)
    """
    warnings = []
    df = clean_column_names(raw_df.copy())
    df = df.dropna(how="all").reset_index(drop=True)

    if mapping is None:
        mapping = suggest_column_mapping(df, AMORT_SCHEMA)

    result = _apply_mapping(df, mapping, entity)
    sid = "schedule_id"

    # Derive schedule_id from numeric first column
    if sid in result.columns:
        if result[sid].isna().all() or (result[sid].astype(str).str.strip() == "").all():
            first = df.iloc[:, 0]
            if pd.to_numeric(first, errors="coerce").notna().sum() > len(df) * 0.8:
                result[sid] = first.values
                warnings.append(f"Used first column '{df.columns[0]}' as schedule_id.")

    # Derive prepaid_item_id from schedule_id
    if "prepaid_item_id" in result.columns and sid in result.columns:
        pid_blank = result["prepaid_item_id"].isna() | (result["prepaid_item_id"].astype(str).str.strip() == "")
        if pid_blank.all() and result[sid].notna().any():
            result["prepaid_item_id"] = result[sid].astype(str)
            warnings.append("Derived prepaid_item_id from schedule_id.")

    # Compute derived fields
    if result[sid].notna().any():
        result["_pdt"] = result["accounting_period"].apply(_parse_period)
        result = result.sort_values([sid, "_pdt"]).reset_index(drop=True)

        # total_periods
        if pd.to_numeric(result.get("total_periods"), errors="coerce").isna().all():
            result["total_periods"] = result.groupby(sid)[sid].transform("count")
            warnings.append("Computed total_periods from row counts per schedule.")

        # period_number
        if pd.to_numeric(result.get("period_number"), errors="coerce").isna().all():
            result["period_number"] = result.groupby(sid).cumcount() + 1
            warnings.append("Generated period_number by chronological rank.")

        # start_date / end_date
        for field, agg in [("start_date", "min"), ("end_date", "max")]:
            if field in result.columns and result[field].isna().all():
                derived = result.groupby(sid)["_pdt"].transform(agg)
                result[field] = derived.dt.strftime("%b %Y").values
                label = "first" if agg == "min" else "last"
                warnings.append(f"Derived {field} from {label} period per schedule.")

        # expected_ending_balance
        orig = pd.to_numeric(result.get("original_amount"), errors="coerce")
        sched = pd.to_numeric(result.get("scheduled_amortization"), errors="coerce")
        if sched.notna().any() and orig.notna().any():
            cum = result.groupby(sid)["scheduled_amortization"].cumsum()
            result["expected_ending_balance"] = (orig - cum).round(2)
            warnings.append("Computed expected_ending_balance = original − cumulative amortization.")

        result = result.drop(columns=["_pdt"], errors="ignore")

    # Ensure all required columns
    for col in AMORT_SCHEMA:
        if col not in result.columns:
            result[col] = ""
            warnings.append(f"'{col}' not found in source — filled with blanks.")

    result = result[AMORT_SCHEMA].reset_index(drop=True)

    # Add source_document_type (extra column — engine ignores extras safely)
    parsed = result["source_document"].apply(parse_source_document)
    result["source_document_type"] = parsed.apply(lambda t: t[0])

    # Coerce ID columns to string
    for col in ["prepaid_item_id", "schedule_id"]:
        result[col] = result[col].fillna("").astype(str)

    # Vendor name fallback — engine crashes on empty .split()[0]
    if "vendor_name" in result.columns:
        blank_vn = result["vendor_name"].astype(str).str.strip() == ""
        if blank_vn.any():
            fb = result["source_document"].astype(str).str.replace(
                r"^(Bill|Journal|Bill Credit)\s*#\s*", "", regex=True
            ).str.strip()
            fb = fb.where(fb != "", result["description"].astype(str).str.strip())
            fb = fb.where(fb != "", "Prepaid Item")
            result.loc[blank_vn, "vendor_name"] = fb[blank_vn]
            warnings.append("Populated blank vendor_name from source document references.")

    return result, mapping, warnings


# ════════════════════════════════════════════════════════════════
# 7. validate_prepaid_inputs
# ════════════════════════════════════════════════════════════════

def validate_prepaid_inputs(ledger_df, amort_df):
    """Validate two normalized DataFrames before passing to the engine.

    Returns:
        dict: validation report (see build_validation_report for structure)
    """
    issues = {
        "missing_ledger_cols": [],
        "missing_amort_cols": [],
        "empty_critical": [],
        "data_quality": [],
        "linkage": [],
        "suggested_fixes": [],
    }

    # ── Column checks ─────────────────────────────────────────
    for col in LEDGER_SCHEMA:
        if col not in ledger_df.columns:
            issues["missing_ledger_cols"].append(col)
    for col in AMORT_SCHEMA:
        if col not in amort_df.columns:
            issues["missing_amort_cols"].append(col)

    # ── Critical field checks ─────────────────────────────────
    for col in CRITICAL_LEDGER:
        if col in ledger_df.columns:
            blank = ledger_df[col].isna() | (ledger_df[col].astype(str).str.strip() == "")
            if blank.all():
                issues["empty_critical"].append(f"Ledger '{col}' is entirely blank.")

    for col in CRITICAL_AMORT:
        if col in amort_df.columns:
            blank = amort_df[col].isna() | (amort_df[col].astype(str).str.strip() == "")
            if blank.all():
                issues["empty_critical"].append(f"Amortization '{col}' is entirely blank.")

    # ── Data quality checks ───────────────────────────────────
    if "amount" in ledger_df.columns:
        non_numeric = pd.to_numeric(ledger_df["amount"], errors="coerce").isna().sum()
        if non_numeric > 0:
            issues["data_quality"].append(
                f"{non_numeric} ledger amount(s) are not numeric."
            )

    if "accounting_period" in ledger_df.columns:
        bad_periods = ledger_df["accounting_period"].apply(_parse_period).isna().sum()
        if bad_periods > 0:
            issues["data_quality"].append(
                f"{bad_periods} ledger accounting period(s) cannot be parsed."
            )

    if "transaction_type" in ledger_df.columns:
        known = {"Bill", "Bill Credit", "Journal Entry"}
        types = set(ledger_df["transaction_type"].dropna().unique())
        unknown = types - known - {""}
        if unknown:
            issues["data_quality"].append(
                f"Unrecognized transaction types: {sorted(unknown)[:5]}. "
                f"These will be classified as OTHER."
            )

    # ── Linkage check ─────────────────────────────────────────
    if "prepaid_item_id" in ledger_df.columns and "prepaid_item_id" in amort_df.columns:
        ledger_ids = set(ledger_df["prepaid_item_id"].astype(str).str.strip()) - {"", "nan"}
        amort_ids = set(amort_df["prepaid_item_id"].astype(str).str.strip()) - {"", "nan"}
        if ledger_ids and amort_ids:
            overlap = ledger_ids & amort_ids
            if not overlap:
                issues["linkage"].append(
                    "No matching prepaid_item_id values between ledger and amortization schedule. "
                    "The engine may not link transactions to schedules."
                )
        elif not ledger_ids:
            issues["linkage"].append(
                "Ledger has no prepaid_item_id values. "
                "Root cause analysis may produce limited results."
            )

    # ── Row count check ───────────────────────────────────────
    if len(ledger_df) == 0:
        issues["empty_critical"].append("Ledger contains no data rows.")
    if len(amort_df) == 0:
        issues["empty_critical"].append("Amortization schedule contains no data rows.")

    # ── Suggested fixes ───────────────────────────────────────
    if issues["missing_ledger_cols"]:
        if "running_balance" in issues["missing_ledger_cols"]:
            issues["suggested_fixes"].append(
                "Cannot run reconciliation because running_balance is missing from the ledger. "
                "Please export a GL detail report that includes period-ending balance."
            )
        if "amount" in issues["missing_ledger_cols"]:
            issues["suggested_fixes"].append(
                "Ledger is missing the 'amount' column. "
                "Ensure the export includes signed transaction amounts."
            )

    if issues["missing_amort_cols"]:
        if "scheduled_amortization" in issues["missing_amort_cols"]:
            issues["suggested_fixes"].append(
                "Amortization schedule is missing 'scheduled_amortization'. "
                "The export must include per-period amortization amounts."
            )

    return issues


# ════════════════════════════════════════════════════════════════
# 8. build_validation_report
# ════════════════════════════════════════════════════════════════

def build_validation_report(issues, ledger_meta=None, amort_meta=None):
    """Convert raw validation issues into a structured, business-friendly report.

    Returns:
        dict: {
            "can_run": bool,
            "summary": str,
            "missing_columns": list,
            "empty_critical_fields": list,
            "data_quality_warnings": list,
            "linkage_warnings": list,
            "suggested_fixes": list,
            "metadata": dict,
        }
    """
    missing = issues["missing_ledger_cols"] + issues["missing_amort_cols"]
    critical = issues["empty_critical"]

    can_run = (len(missing) == 0 and len(critical) == 0)

    if can_run:
        n_warnings = (len(issues["data_quality"]) + len(issues["linkage"]))
        summary = (
            f"Validation passed. {n_warnings} warning(s) noted."
            if n_warnings else "Validation passed — no issues detected."
        )
    else:
        blockers = len(missing) + len(critical)
        summary = (
            f"Cannot run reconciliation — {blockers} blocking issue(s) found. "
            f"See details below."
        )

    return {
        "can_run": can_run,
        "summary": summary,
        "missing_columns": missing,
        "empty_critical_fields": critical,
        "data_quality_warnings": issues["data_quality"],
        "linkage_warnings": issues["linkage"],
        "suggested_fixes": issues["suggested_fixes"],
        "metadata": {
            "ledger": ledger_meta or {},
            "amortization": amort_meta or {},
        },
    }


# ════════════════════════════════════════════════════════════════
# FILE TYPE DETECTION
# ════════════════════════════════════════════════════════════════

def detect_file_type(df):
    """Determine whether a DataFrame is a ledger, amortization schedule,
    balance sheet report, or unknown.

    Returns:
        tuple: (file_type_str, confidence_str)
    """
    cols = set(str(c).lower().strip() for c in df.columns)

    amort_score = len(cols & AMORT_SIGNALS)
    ledger_score = len(cols & LEDGER_SIGNALS)

    if amort_score >= 3:
        return "amortization_schedule", "high"
    if ledger_score >= 3:
        return "ledger", "high"

    if any("financial row" in c for c in cols):
        return "balance_sheet_report", "medium"

    return "unknown", "low"


# ════════════════════════════════════════════════════════════════
# SOURCE DOCUMENT PARSING
# ════════════════════════════════════════════════════════════════

SOURCE_DOC_PATTERN = re.compile(
    r"^\s*(Bill Credit|Bill|Journal)\s*#\s*(.+?)\s*$", re.IGNORECASE
)

def parse_source_document(source_document):
    """Parse a NetSuite-style source document reference.

    Examples:
        "Bill #13436"        -> ("Bill", "13436")
        "Journal #JEISR03"   -> ("Journal", "JEISR03")
        "Bill Credit #BC123" -> ("Bill Credit", "BC123")
        "Bill ##1439-3669"   -> ("Bill", "#1439-3669")
        "" / NaN             -> ("Unknown", "")

    Returns:
        tuple: (source_type, source_number)
    """
    if source_document is None or str(source_document).strip() in ("", "nan", "None"):
        return "Unknown", ""

    s = str(source_document).strip()
    m = SOURCE_DOC_PATTERN.match(s)
    if m:
        stype = m.group(1).title()
        if stype == "Bill Credit":
            stype = "Bill Credit"
        return stype, m.group(2).strip()
    return "Unknown", s


# ════════════════════════════════════════════════════════════════
# CROSS-FILE ENRICHMENT
# ════════════════════════════════════════════════════════════════

def enrich_ledger_ids(ledger_df, amort_df):
    """Populate blank prepaid_item_id in ledger by matching document_number
    against the parsed source_number from the amortization schedule.

    Matching uses parse_source_document() so "Bill #13436", "Journal #JEISR03"
    and "Bill ##1439-3669" all match correctly by number, not raw string.

    Returns:
        tuple: (enriched_ledger_df, n_matched)
    """
    if ledger_df.empty or amort_df.empty:
        return ledger_df, 0

    # Build lookup: parsed source_number → prepaid_item_id
    # Also index a "#"-stripped variant to handle "Bill ##1439-3669" style refs.
    doc_to_pid = {}
    for _, row in amort_df.drop_duplicates("source_document").iterrows():
        _, num = parse_source_document(row.get("source_document", ""))
        pid = str(row.get("prepaid_item_id", "")).strip()
        if num and pid:
            doc_to_pid.setdefault(num, pid)
            stripped = num.lstrip("#").strip()
            if stripped and stripped != num:
                doc_to_pid.setdefault(stripped, pid)

    docs = ledger_df["document_number"].astype(str).str.strip()
    matched = docs.map(doc_to_pid)
    # Fallback: ledger doc numbers with leading '#' stripped
    fallback = docs.str.lstrip("#").str.strip().map(doc_to_pid)
    matched = matched.fillna(fallback)

    blank = ledger_df["prepaid_item_id"].astype(str).str.strip().isin(["", "nan"])
    fill_mask = blank & matched.notna()
    n = fill_mask.sum()

    result = ledger_df.copy()
    result.loc[fill_mask, "prepaid_item_id"] = matched[fill_mask]
    return result, int(n)


def _enrich_amort_entity(amort_df, ledger_df):
    """Populate blank entity in amortization schedule by looking up the
    entity associated with each prepaid_item_id in the ledger.

    Returns:
        tuple: (enriched_amort_df, n_enriched_rows)
    """
    if amort_df.empty or ledger_df.empty:
        return amort_df, 0

    blank = amort_df["entity"].isna() | (amort_df["entity"].astype(str).str.strip() == "")
    if not blank.any():
        return amort_df, 0

    # Build lookup: prepaid_item_id → entity (from ledger, first match)
    pid_to_entity = (
        ledger_df[ledger_df["entity"].astype(str).str.strip() != ""]
        .drop_duplicates("prepaid_item_id")
        .set_index("prepaid_item_id")["entity"]
        .to_dict()
    )

    matched = amort_df["prepaid_item_id"].astype(str).str.strip().map(pid_to_entity)
    fill_mask = blank & matched.notna()
    n = fill_mask.sum()

    result = amort_df.copy()
    result["entity"] = result["entity"].astype(object)
    result.loc[fill_mask, "entity"] = matched[fill_mask]
    return result, int(n)


# ════════════════════════════════════════════════════════════════
# FULL PIPELINE
# ════════════════════════════════════════════════════════════════

def process_raw_files(ledger_file, amort_file, entity=None):
    """Full pipeline: read → detect header → clean → normalize → validate.

    Parameters:
        ledger_file : file path or UploadedFile for GL ledger
        amort_file  : file path or UploadedFile for amortization schedule
        entity      : entity name (optional)

    Returns:
        dict: {
            "ledger_df":          normalized DataFrame or None,
            "amort_df":           normalized DataFrame or None,
            "ledger_mapping":     mapping dict,
            "amort_mapping":      mapping dict,
            "ledger_warnings":    list,
            "amort_warnings":     list,
            "validation_report":  structured report dict,
            "can_run":            bool,
        }
    """
    all_ledger_warnings = []
    all_amort_warnings = []

    # ── Read + detect header: Ledger ──────────────────────────
    raw_l, meta_l = read_file(ledger_file)
    hdr = detect_header_row(raw_l)
    if hdr > 0:
        raw_l = _apply_header(raw_l, hdr)
        all_ledger_warnings.append(f"Detected header at row {hdr} — skipped {hdr} title row(s).")

    # Check file type
    cleaned_l = clean_column_names(raw_l)
    ftype_l, conf_l = detect_file_type(cleaned_l)
    if ftype_l == "balance_sheet_report":
        return _unsupported_result(
            "This appears to be a balance sheet report, not a transaction-level GL detail. "
            "Duplicate bill and amortization posting checks require transaction-level data. "
            "Please export a GL account detail or transaction detail report instead.",
            meta_l, {}
        )
    if ftype_l == "amortization_schedule":
        all_ledger_warnings.append(
            "This file looks like an amortization schedule, not a GL ledger. "
            "Check that you uploaded the correct file."
        )

    # ── Read + detect header: Amortization ────────────────────
    raw_a, meta_a = read_file(amort_file)
    hdr_a = detect_header_row(raw_a)
    if hdr_a > 0:
        raw_a = _apply_header(raw_a, hdr_a)
        all_amort_warnings.append(f"Detected header at row {hdr_a} — skipped {hdr_a} title row(s).")

    cleaned_a = clean_column_names(raw_a)
    ftype_a, conf_a = detect_file_type(cleaned_a)
    if ftype_a == "ledger":
        all_amort_warnings.append(
            "This file looks like a GL ledger, not an amortization schedule. "
            "Check that you uploaded the correct file."
        )

    # ── Normalize ─────────────────────────────────────────────
    ledger_df, l_map, l_warn = normalize_ledger(cleaned_l, entity=entity)
    amort_df, a_map, a_warn = normalize_amortization_schedule(cleaned_a, entity=entity)
    all_ledger_warnings.extend(l_warn)
    all_amort_warnings.extend(a_warn)

    # ── Enrich ledger IDs ─────────────────────────────────────
    ledger_df, n_enriched = enrich_ledger_ids(ledger_df, amort_df)
    if n_enriched:
        all_ledger_warnings.append(
            f"Linked {n_enriched} ledger row(s) to amortization schedules via document matching."
        )

    # ── Enrich amortization entity from ledger ────────────────
    # Many amortization exports (NetSuite, SAP) don't include entity.
    # Derive it from the ledger via prepaid_item_id linkage.
    amort_df, n_ent = _enrich_amort_entity(amort_df, ledger_df)
    if n_ent:
        all_amort_warnings.append(
            f"Derived entity for {n_ent} schedule row(s) from ledger linkage."
        )

    # ── Validate ──────────────────────────────────────────────
    issues = validate_prepaid_inputs(ledger_df, amort_df)
    report = build_validation_report(issues, meta_l, meta_a)

    return {
        "ledger_df":         ledger_df,
        "amort_df":          amort_df,
        "ledger_mapping":    l_map,
        "amort_mapping":     a_map,
        "ledger_warnings":   all_ledger_warnings,
        "amort_warnings":    all_amort_warnings,
        "validation_report": report,
        "can_run":           report["can_run"],
    }


def _unsupported_result(message, ledger_meta, amort_meta):
    """Return a result dict for an unsupported file type."""
    return {
        "ledger_df": None,
        "amort_df": None,
        "ledger_mapping": {},
        "amort_mapping": {},
        "ledger_warnings": [message],
        "amort_warnings": [],
        "validation_report": {
            "can_run": False,
            "summary": message,
            "missing_columns": [],
            "empty_critical_fields": [],
            "data_quality_warnings": [],
            "linkage_warnings": [],
            "suggested_fixes": [message],
            "metadata": {"ledger": ledger_meta, "amortization": amort_meta},
        },
        "can_run": False,
    }


# ════════════════════════════════════════════════════════════════
# MAPPING REPORT HELPERS
# ════════════════════════════════════════════════════════════════

def mapping_to_table(mapping):
    """Convert a mapping dict into a display-ready list of dicts."""
    return [
        {
            "Target Field": t,
            "Source Column": info["source"] or "—",
            "Confidence": info["confidence"],
            "Method": info["method"],
        }
        for t, info in mapping.items()
    ]


# ════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ════════════════════════════════════════════════════════════════

def _is_numeric(val):
    try:
        float(str(val).replace(",", "").replace("$", ""))
        return True
    except (ValueError, TypeError):
        return False


def _parse_date(val):
    """Parse dates including datetime strings and Excel serials."""
    if pd.isna(val) or str(val).strip() in ("", "nan", "None", "NaT"):
        return pd.NaT
    s = str(val).strip()

    # Excel serial number
    try:
        n = float(s)
        if 1 < n < 60000 and n == int(n):
            return datetime(1899, 12, 30) + timedelta(days=int(n))
    except (ValueError, TypeError):
        pass

    # Strip time component ("2021-07-28 00:00:00" → "2021-07-28")
    s_date = s.split(" ")[0] if " " in s else s

    for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d",
                "%b %d, %Y", "%d %b %Y", "%B %d, %Y",
                "%m-%d-%Y", "%d-%m-%Y", "%b %Y", "%B %Y", "%Y-%m"]:
        try:
            return datetime.strptime(s_date, fmt)
        except ValueError:
            continue

    for fmt in ["%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S"]:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue

    return pd.NaT


def _parse_period(val):
    """Parse accounting period string into datetime for sorting."""
    if pd.isna(val) or str(val).strip() in ("", "nan", "None"):
        return pd.NaT
    s = str(val).strip()
    for fmt in ["%b %Y", "%B %Y", "%Y-%m", "%m/%Y", "%m-%Y"]:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return pd.NaT


def _find_col(df, target_field):
    """Find a column in df matching synonyms for target_field."""
    synonyms = SYNONYMS.get(target_field, [target_field])
    cols_lower = {str(c).lower().strip(): c for c in df.columns}
    for syn in synonyms:
        if syn.lower().strip() in cols_lower:
            return cols_lower[syn.lower().strip()]
    return None


def _apply_mapping(df, mapping, entity=None):
    """Apply a column mapping: rename, convert types, fill defaults."""
    result = pd.DataFrame()

    for target, info in mapping.items():
        src = info["source"]
        if src is not None and src in df.columns:
            result[target] = df[src].copy()
        else:
            result[target] = np.nan

    # Generate transaction_id
    if "transaction_id" in result.columns and result["transaction_id"].isna().all():
        result["transaction_id"] = [f"TXN-{i+1:05d}" for i in range(len(result))]

    # Assign entity
    if entity and "entity" in result.columns:
        blank = result["entity"].isna() | (result["entity"].astype(str).str.strip() == "")
        if blank.all():
            result["entity"] = entity

    # Convert dates
    for col in ["transaction_date", "start_date", "end_date"]:
        if col in result.columns:
            result[col] = result[col].apply(_parse_date)

    # Convert numerics
    for col in ["amount", "running_balance", "original_amount",
                "scheduled_amortization", "expected_ending_balance"]:
        if col in result.columns:
            result[col] = pd.to_numeric(
                result[col].astype(str).str.replace(",", "").str.replace("$", ""),
                errors="coerce",
            )

    for col in ["period_number", "total_periods"]:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")

    # Normalize transaction types
    if "transaction_type" in result.columns:
        raw = result["transaction_type"].astype(str).str.strip().str.lower()
        result["transaction_type"] = raw.map(TXN_TYPE_MAP).fillna(
            result["transaction_type"]
        )

    # Fill text blanks
    for f in ["vendor_name", "description", "document_number",
              "source_document", "status"]:
        if f in result.columns:
            result[f] = result[f].fillna("").astype(str).str.strip()

    return result
