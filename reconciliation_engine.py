"""
reconciliation_engine.py
AI Month-End Close Reconciliation Assistant — Prepaid Expense Module

Balance-first reconciliation engine.  Primary reconciliation compares
aggregate expected remaining balance against the GL balance per entity.
Period-level detail is secondary drill-down.

Public API:
    from reconciliation_engine import run_analysis
    results = run_analysis(ledger_df, amortization_df, config=None)
"""

import pandas as pd
import numpy as np
import re as _re
from datetime import datetime


# ════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════

DEFAULT_CONFIG = {
    "reconciliation_threshold": 1.00,
    "amort_tolerance": 1.00,
    "materiality_percent": 0.005,
    "controller_mode": True,
    "txn_type_map": {
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
    },
    "amortization_keywords": [
        "amortization", "amortisation", "prepaid expense recognition",
        "monthly expense", "prepaid recognition",
    ],
    "manual_adjustment_keywords": [
        "reclassif", "correction", "adjustment", "reclass",
        "write-off", "write off", "reversal", "true-up", "true up",
    ],
}


# ════════════════════════════════════════════════════════════════
# COLUMN SCHEMAS
# ════════════════════════════════════════════════════════════════

REQUIRED_LEDGER_COLS = [
    "transaction_id", "transaction_date", "accounting_period", "entity",
    "transaction_type", "document_number", "vendor_name", "description",
    "amount", "running_balance", "prepaid_item_id",
]

REQUIRED_AMORT_COLS = [
    "schedule_id", "prepaid_item_id", "entity", "vendor_name",
    "description", "original_amount", "start_date", "end_date",
    "total_periods", "accounting_period", "period_number",
    "scheduled_amortization", "expected_ending_balance",
    "source_document", "status",
]

ROOT_CAUSE_COLUMNS = [
    "root_cause_id", "entity", "root_cause_category", "severity",
    "confidence", "impacted_periods", "estimated_impact",
    "evidence_transactions", "evidence_prepaid_item_id",
    "explanation_workpaper", "management_summary",
    "recommended_action", "suggested_journal_entry",
]


# ════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════

def period_to_date(period_str):
    """Convert 'Oct 2025' → datetime.  Returns NaT on failure."""
    for fmt in ("%b %Y", "%B %Y", "%Y-%m", "%m/%Y", "%m-%Y"):
        try:
            return datetime.strptime(str(period_str).strip(), fmt)
        except (ValueError, TypeError):
            continue
    return pd.NaT


def _sort_periods(period_list):
    """Sort a list of period strings chronologically."""
    return sorted(
        [p for p in period_list if period_to_date(p) is not pd.NaT],
        key=period_to_date,
    )


def _sort_by_period(df, group_cols=None):
    """Sort a DataFrame by accounting_period chronologically."""
    df = df.copy()
    df["_sort"] = df["accounting_period"].apply(period_to_date)
    sort_cols = (group_cols or []) + ["_sort"]
    return df.sort_values(sort_cols).drop(columns=["_sort"]).reset_index(drop=True)


def _periods_from(start_period, all_periods):
    """Return comma-joined periods from start_period to end of all_periods."""
    sd = period_to_date(start_period)
    return ", ".join(p for p in all_periods if period_to_date(p) >= sd)


_SOURCE_DOC_RE = _re.compile(
    r"^\s*(Bill Credit|Bill|Journal)\s*#\s*(.+?)\s*$", _re.IGNORECASE
)

def _parse_source_doc(source_document):
    """Parse 'Bill #13436' → ('Bill', '13436')."""
    if source_document is None or str(source_document).strip() in ("", "nan", "None"):
        return "Unknown", ""
    s = str(source_document).strip()
    m = _SOURCE_DOC_RE.match(s)
    if m:
        return m.group(1).title(), m.group(2).strip()
    return "Unknown", s


def _get_vendor_label(item_id, amortization_df):
    """Short vendor label from the amortization data."""
    if "NONE" in str(item_id).upper() or pd.isna(item_id):
        return "Prepaid Expense"
    match = amortization_df.loc[
        amortization_df["prepaid_item_id"] == item_id, "vendor_name"
    ]
    if not match.empty:
        v = str(match.iloc[0]).strip()
        parts = v.split()
        return parts[0] if parts else str(item_id)
    return str(item_id).split("-")[0].title()


# ════════════════════════════════════════════════════════════════
# MODULE 1: VALIDATION
# ════════════════════════════════════════════════════════════════

def validate_inputs(ledger_df, amortization_df, config):
    """Validate schemas, normalize types, compute metadata."""
    ledger = ledger_df.copy()
    amortization = amortization_df.copy()

    # Check required columns
    for col in REQUIRED_LEDGER_COLS:
        if col not in ledger.columns:
            raise ValueError(f"Ledger missing required column: '{col}'")
    for col in REQUIRED_AMORT_COLS:
        if col not in amortization.columns:
            raise ValueError(f"Amortization missing required column: '{col}'")

    # Normalize transaction_type
    txn_map = config["txn_type_map"]
    ledger["transaction_type"] = (
        ledger["transaction_type"].astype(str).str.strip().str.lower()
        .map(txn_map).fillna(ledger["transaction_type"])
    )

    # Numeric conversions
    for col in ["amount", "running_balance"]:
        ledger[col] = pd.to_numeric(ledger[col], errors="coerce")
    for col in ["original_amount", "scheduled_amortization",
                "expected_ending_balance", "period_number", "total_periods"]:
        if col in amortization.columns:
            amortization[col] = pd.to_numeric(amortization[col], errors="coerce")

    # Ensure text columns are strings
    for col in ["prepaid_item_id", "document_number", "vendor_name",
                "description", "entity"]:
        ledger[col] = ledger[col].fillna("").astype(str).str.strip()
    for col in ["prepaid_item_id", "schedule_id", "vendor_name",
                "description", "entity", "source_document", "status"]:
        if col in amortization.columns:
            amortization[col] = amortization[col].fillna("").astype(str).str.strip()

    # Parse periods
    all_ledger_periods = _sort_periods(ledger["accounting_period"].dropna().unique())
    all_amort_periods = _sort_periods(amortization["accounting_period"].dropna().unique())
    all_periods = _sort_periods(list(set(all_ledger_periods + all_amort_periods)))

    validation_info = {
        "ledger_rows": len(ledger),
        "ledger_cols": len(ledger.columns),
        "amort_rows": len(amortization),
        "amort_cols": len(amortization.columns),
        "entities": ledger["entity"].nunique(),
        "periods": len(all_periods),
        "date_range_start": all_periods[0] if all_periods else "N/A",
        "date_range_end": all_periods[-1] if all_periods else "N/A",
    }

    return ledger, amortization, validation_info


# ════════════════════════════════════════════════════════════════
# MODULE 2: TRANSACTION CLASSIFICATION
# ════════════════════════════════════════════════════════════════

def classify_transactions(ledger, config):
    """Classify each ledger row into an accounting category."""
    ledger = ledger.copy()
    amort_kw = config["amortization_keywords"]
    adj_kw = config["manual_adjustment_keywords"]

    # Pre-compute duplicate groups (strict: same entity+doc+amount+period+pid)
    # Exclude multi-line invoices (>2 lines per doc) — these are cost components.
    bills = ledger[ledger["transaction_type"] == "Bill"].copy()
    bills["_amt_round"] = bills["amount"].round(0)
    _dlc = (bills.groupby(["entity", "document_number", "accounting_period"])
            ["transaction_id"].count().reset_index()
            .rename(columns={"transaction_id": "_dl"}))
    bills = bills.merge(_dlc, on=["entity", "document_number", "accounting_period"], how="left")
    simple = bills[bills["_dl"] <= 2]
    dup_groups = (
        simple.groupby(["entity", "document_number", "_amt_round",
                         "accounting_period", "prepaid_item_id"])
        .filter(lambda g: len(g) > 1)
    )
    dup_txn_ids = set(dup_groups["transaction_id"].unique()) if not dup_groups.empty else set()

    def _classify(row):
        ttype = row["transaction_type"]
        amt = row["amount"]
        desc = str(row["description"]).lower()
        pid = str(row["prepaid_item_id"]).strip()
        txn_id = row["transaction_id"]

        # Duplicate check first
        if txn_id in dup_txn_ids and ttype == "Bill":
            return "POTENTIAL_DUPLICATE"

        # Unlinked addition
        if ttype == "Bill" and amt > 0 and pid in ("", "nan"):
            return "UNLINKED_ADDITION"

        # Prepaid addition
        if ttype == "Bill" and amt > 0:
            return "PREPAID_ADDITION"

        # Bill credit
        if ttype == "Bill Credit":
            return "BILL_CREDIT_REVERSAL"

        # Journal entries
        if ttype == "Journal Entry" and amt < 0:
            if any(kw in desc for kw in amort_kw):
                return "AMORTIZATION_ENTRY"
            if any(kw in desc for kw in adj_kw):
                return "MANUAL_ADJUSTMENT"

        return "OTHER"

    ledger["transaction_category"] = ledger.apply(_classify, axis=1)
    counts = ledger["transaction_category"].value_counts().to_dict()
    flagged = ledger[ledger["transaction_category"].isin(
        ["POTENTIAL_DUPLICATE", "UNLINKED_ADDITION", "MANUAL_ADJUSTMENT"]
    )].copy()

    return ledger, counts, flagged


# ════════════════════════════════════════════════════════════════
# MODULE 3: WATERFALL
# ════════════════════════════════════════════════════════════════

def build_amortization_waterfall(ledger, amortization):
    """Build expected balance waterfall from amortization schedule."""
    all_ledger_periods = _sort_periods(ledger["accounting_period"].dropna().unique())
    all_amort_periods = _sort_periods(amortization["accounting_period"].dropna().unique())
    all_periods = _sort_periods(list(set(all_ledger_periods + all_amort_periods)))

    # Item metadata
    item_metadata = (
        amortization.groupby("prepaid_item_id")
        .agg(
            entity=("entity", "first"),
            vendor_name=("vendor_name", "first"),
            description=("description", "first"),
            original_amount=("original_amount", "first"),
            start_date=("start_date", "first"),
            end_date=("end_date", "first"),
            total_periods=("total_periods", "first"),
            schedule_id=("schedule_id", "first"),
        )
        .reset_index()
    )

    # Waterfall pivot: amortization per item per period
    waterfall_amort = amortization.pivot_table(
        values="scheduled_amortization",
        index=["prepaid_item_id", "entity"],
        columns="accounting_period",
        aggfunc="sum", fill_value=0,
    )
    ordered_cols = [p for p in all_periods if p in waterfall_amort.columns]
    waterfall_amort = waterfall_amort[ordered_cols]

    # Total row
    waterfall_amort_with_total = waterfall_amort.copy()
    waterfall_amort_with_total.loc[("TOTAL", ""), :] = waterfall_amort.sum()

    # Balance pivot
    waterfall_balance = amortization.pivot_table(
        values="expected_ending_balance",
        index=["prepaid_item_id", "entity"],
        columns="accounting_period",
        aggfunc="sum", fill_value=0,
    )
    balance_cols = [p for p in all_periods if p in waterfall_balance.columns]
    waterfall_balance = waterfall_balance[balance_cols]

    # Flat table for reconciliation
    expected_balance_flat = amortization[[
        "prepaid_item_id", "entity", "accounting_period",
        "scheduled_amortization", "expected_ending_balance",
    ]].copy()

    return {
        "all_periods": all_periods,
        "item_metadata": item_metadata,
        "waterfall_amort": waterfall_amort,
        "waterfall_amort_with_total": waterfall_amort_with_total,
        "waterfall_balance": waterfall_balance,
        "expected_balance_flat": expected_balance_flat,
    }


# ════════════════════════════════════════════════════════════════
# MODULE 4A: AGGREGATE RECONCILIATION (primary)
# ════════════════════════════════════════════════════════════════

def aggregate_reconciliation(ledger, amortization, all_periods, materiality):
    """Balance-first reconciliation per entity.

    Expected = latest expected_ending_balance per item up to latest ledger period.
    Actual = latest running_balance per entity.
    """
    latest_period_dt = max(period_to_date(p) for p in
                          _sort_periods(ledger["accounting_period"].unique()))
    latest_period_str = [p for p in all_periods
                         if period_to_date(p) == latest_period_dt]
    latest_period_str = latest_period_str[0] if latest_period_str else all_periods[-1]

    # Filter amortization to periods <= latest ledger period
    amort_in_range = amortization[
        amortization["accounting_period"].apply(period_to_date) <= latest_period_dt
    ].copy()

    # Latest expected ending balance per item
    amort_in_range["_pdt"] = amort_in_range["accounting_period"].apply(period_to_date)
    latest_per_item = (
        amort_in_range.sort_values("_pdt")
        .groupby("prepaid_item_id")
        .agg(
            entity=("entity", "last"),
            expected_ending_balance=("expected_ending_balance", "last"),
        )
        .reset_index()
    )

    expected = (
        latest_per_item[latest_per_item["entity"] != ""]
        .groupby("entity")["expected_ending_balance"]
        .sum().reset_index()
        .rename(columns={"expected_ending_balance": "expected_balance"})
    )

    # Actual: latest running_balance per entity in latest period
    latest_actual = (
        ledger[ledger["accounting_period"] == latest_period_str]
        .sort_values("transaction_date")
        .groupby("entity")["running_balance"]
        .last().reset_index()
        .rename(columns={"running_balance": "actual_balance"})
    )

    # If no rows in latest period, fall back to last available period per entity
    if latest_actual.empty:
        latest_actual = (
            ledger.sort_values("transaction_date")
            .groupby("entity")["running_balance"]
            .last().reset_index()
            .rename(columns={"running_balance": "actual_balance"})
        )

    agg = pd.merge(expected, latest_actual, on="entity", how="outer")
    agg[["expected_balance", "actual_balance"]] = (
        agg[["expected_balance", "actual_balance"]].fillna(0)
    )
    agg["variance"] = (agg["actual_balance"] - agg["expected_balance"]).round(2)
    agg["abs_variance"] = agg["variance"].abs()
    agg["variance_percent"] = (
        (agg["abs_variance"] / agg["expected_balance"].abs().replace(0, np.nan) * 100)
        .fillna(0).round(4)
    )
    agg["status"] = agg["abs_variance"].apply(
        lambda v: "RECONCILED" if v <= materiality else "EXCEPTION"
    )

    # Set of entities that pass aggregate reconciliation
    reconciled_entities = set(agg.loc[agg["status"] == "RECONCILED", "entity"])

    return agg, reconciled_entities, latest_period_dt


# ════════════════════════════════════════════════════════════════
# MODULE 4B: PERIOD-LEVEL RECONCILIATION (drill-down)
# ════════════════════════════════════════════════════════════════

def reconcile_balances(ledger, amortization, expected_balance_flat,
                       all_periods, config):
    """Period-level reconciliation — secondary drill-down."""
    threshold = config["reconciliation_threshold"]

    ledger_bill_items = set(
        ledger.loc[ledger["transaction_type"] == "Bill", "prepaid_item_id"]
        .dropna().astype(str).str.strip().unique()
    )
    items_schedule_only = (
        set(amortization["prepaid_item_id"].unique()) - ledger_bill_items
    )

    ebf_recon = expected_balance_flat[
        expected_balance_flat["prepaid_item_id"].isin(ledger_bill_items)
    ].copy()

    expected = (
        ebf_recon
        .groupby(["entity", "accounting_period"])["expected_ending_balance"]
        .sum().reset_index()
        .rename(columns={"expected_ending_balance": "expected_balance"})
    )
    expected = _sort_by_period(expected, group_cols=["entity"])

    actual = (
        ledger.sort_values("transaction_date")
        .groupby(["entity", "accounting_period"])["running_balance"]
        .last().reset_index()
        .rename(columns={"running_balance": "actual_balance"})
    )
    actual = _sort_by_period(actual, group_cols=["entity"])

    recon = pd.merge(expected, actual, on=["entity", "accounting_period"], how="outer")
    recon[["expected_balance", "actual_balance"]] = (
        recon[["expected_balance", "actual_balance"]].fillna(0)
    )
    recon["variance"] = (recon["expected_balance"] - recon["actual_balance"]).round(2)
    recon["abs_variance"] = recon["variance"].abs()
    recon["status"] = recon["abs_variance"].apply(
        lambda v: "RECONCILED" if v <= threshold else "EXCEPTION"
    )
    recon = _sort_by_period(recon, group_cols=["entity"])
    exceptions = recon[recon["status"] == "EXCEPTION"].copy()

    return {
        "ledger_bill_items": ledger_bill_items,
        "items_schedule_only": items_schedule_only,
        "reconciliation_summary": recon,
        "exceptions": exceptions,
    }


# ════════════════════════════════════════════════════════════════
# MODULE 5: ROOT CAUSE ANALYSIS
# ════════════════════════════════════════════════════════════════

def perform_root_cause_analysis(ledger, amortization, expected_balance_flat,
                                ledger_bill_items, all_periods, config,
                                reconciled_entities, latest_period_dt):
    """Conservative root cause identification."""
    amort_tol = config["amort_tolerance"]
    findings = []
    counter = [0]

    def _next_id():
        counter[0] += 1
        return f"RC-{counter[0]:03d}"

    # ── Rule 1: Duplicate Bill (strict same-period same-amount same-pid) ──
    # Two Bills with same doc/amount/period but DIFFERENT prepaid_item_ids
    # are cost allocations from a single invoice — not duplicates.
    # Additionally, multi-line invoices (>2 lines per doc+entity+period)
    # contain multiple cost components; same-amount pairs within them
    # are separate line items, not duplicate postings.
    bills = ledger[ledger["transaction_type"] == "Bill"].copy()
    bills["_amt_r"] = bills["amount"].round(2)

    # Count total lines per doc+entity+period to identify multi-line invoices
    _doc_line_counts = (
        bills.groupby(["entity", "document_number", "accounting_period"])
        ["transaction_id"].count().reset_index()
        .rename(columns={"transaction_id": "_doc_lines"})
    )
    bills = bills.merge(_doc_line_counts,
                        on=["entity", "document_number", "accounting_period"],
                        how="left")

    # Only consider potential duplicates from simple invoices (≤2 lines)
    simple_bills = bills[bills["_doc_lines"] <= 2]

    dup_groups = (
        simple_bills.groupby(["entity", "document_number", "_amt_r",
                              "accounting_period", "prepaid_item_id"])
        .agg(
            count=("transaction_id", "count"),
            txn_ids=("transaction_id", lambda x: ", ".join(x.tolist())),
            vendor=("vendor_name", "first"),
        )
        .reset_index()
    )

    for _, g in dup_groups[dup_groups["count"] > 1].iterrows():
        n_excess = g["count"] - 1
        impact = g["_amt_r"] * n_excess
        findings.append({
            "root_cause_id": _next_id(), "entity": g["entity"],
            "root_cause_category": "DUPLICATE_BILL", "severity": "HIGH",
            "confidence": "HIGH",
            "impacted_periods": _periods_from(g["accounting_period"], all_periods),
            "estimated_impact": round(impact, 2),
            "evidence_transactions": g["txn_ids"],
            "evidence_prepaid_item_id": g["prepaid_item_id"],
            "explanation_workpaper": (
                f"Document {g['document_number']} ({g['vendor']}) "
                f"posted {g['count']}x in {g['entity']} in "
                f"{g['accounting_period']} for the same prepaid item "
                f"with identical amount ${g['_amt_r']:,.2f}. "
                f"Excess: ${impact:,.2f}."
            ),
            "management_summary": (
                f"Invoice {g['document_number']} from {g['vendor']} "
                f"was posted {g['count']}x in {g['entity']} in the "
                f"same period for the same amount and same prepaid item, "
                f"overstating prepaid assets by ${impact:,.2f}."
            ),
            "recommended_action": (
                f"1. Confirm with AP whether duplicate invoices were received.\n"
                f"2. Reverse the duplicate posting if confirmed.\n"
                f"3. Recover payment from vendor if overpaid."
            ),
            "suggested_journal_entry": (
                f"Dr  Accounts Payable   ${impact:>12,.2f}\n"
                f"Cr  Prepaid Expenses   ${impact:>12,.2f}\n"
                f"Memo: Reversal of duplicate {g['document_number']}"
            ),
        })

    # Recurring invoice observations (INFO only)
    recurring_groups = (
        bills.groupby(["entity", "document_number"])
        .agg(count=("transaction_id", "count"),
             txn_ids=("transaction_id", lambda x: ", ".join(x.tolist())),
             pids=("prepaid_item_id", lambda x: ", ".join(
                 x.dropna().astype(str).unique().tolist())),
             vendor=("vendor_name", "first"),
             periods=("accounting_period", lambda x: ", ".join(sorted(
                 x.unique().tolist(), key=period_to_date))),
             )
        .reset_index()
    )
    # Already-flagged true-dup doc+period combos
    true_dup_docs = set(
        dup_groups[dup_groups["count"] > 1]
        .apply(lambda r: (r["entity"], r["document_number"]), axis=1)
    ) if not dup_groups[dup_groups["count"] > 1].empty else set()

    for _, g in recurring_groups[recurring_groups["count"] > 1].iterrows():
        key = (g["entity"], g["document_number"])
        if key in true_dup_docs:
            continue  # already flagged as true dup
        findings.append({
            "root_cause_id": _next_id(), "entity": g["entity"],
            "root_cause_category": "RECURRING_INVOICE_REVIEW",
            "severity": "LOW", "confidence": "INFO",
            "impacted_periods": g["periods"],
            "estimated_impact": 0.0,
            "evidence_transactions": g["txn_ids"],
            "evidence_prepaid_item_id": g["pids"],
            "explanation_workpaper": (
                f"Document {g['document_number']} appears {g['count']}x in "
                f"{g['entity']} across different periods/amounts. Consistent "
                f"with recurring invoice naming convention."
            ),
            "management_summary": "Recurring invoice — no action required.",
            "recommended_action": "No action — informational only.",
            "suggested_journal_entry": "None required.",
        })

    # ── Rule 2: Unlinked Addition ─────────────────────────────
    for _, row in ledger[ledger["transaction_category"] == "UNLINKED_ADDITION"].iterrows():
        amt = abs(row["amount"])
        findings.append({
            "root_cause_id": _next_id(), "entity": row["entity"],
            "root_cause_category": "UNLINKED_ADDITION", "severity": "HIGH",
            "confidence": "HIGH",
            "impacted_periods": _periods_from(row["accounting_period"], all_periods),
            "estimated_impact": round(amt, 2),
            "evidence_transactions": row["transaction_id"],
            "evidence_prepaid_item_id": str(row["prepaid_item_id"]),
            "explanation_workpaper": (
                f"{row['transaction_id']} ({row['document_number']}, "
                f"{row['accounting_period']}) — ${amt:,.2f} Bill in "
                f"{row['entity']} with no linked amortization schedule."
            ),
            "management_summary": (
                f"A ${amt:,.2f} prepaid payment ({row['document_number']}) in "
                f"{row['entity']} has no amortization schedule and will never "
                f"be recognised as an expense without intervention."
            ),
            "recommended_action": (
                f"Locate the transaction and determine whether it qualifies "
                f"as prepaid. If yes, create a schedule. If no, reclassify."
            ),
            "suggested_journal_entry": (
                f"If not a prepaid:\n"
                f"  Dr  [Expense Account]  ${amt:>12,.2f}\n"
                f"  Cr  Prepaid Expenses   ${amt:>12,.2f}\n"
                f"  Memo: Reclassification of {row['document_number']}"
            ),
        })

    # ── Rule 3: Manual Adjustment ─────────────────────────────
    for _, row in ledger[ledger["transaction_category"] == "MANUAL_ADJUSTMENT"].iterrows():
        amt = abs(row["amount"])
        findings.append({
            "root_cause_id": _next_id(), "entity": row["entity"],
            "root_cause_category": "MANUAL_ADJUSTMENT", "severity": "MEDIUM",
            "confidence": "HIGH",
            "impacted_periods": _periods_from(row["accounting_period"], all_periods),
            "estimated_impact": round(amt, 2),
            "evidence_transactions": row["transaction_id"],
            "evidence_prepaid_item_id": str(row["prepaid_item_id"]),
            "explanation_workpaper": (
                f"{row['transaction_id']} ({row['document_number']}) — "
                f"${amt:,.2f} manual JE in {row['entity']}. "
                f"Desc: '{row['description']}'."
            ),
            "management_summary": (
                f"A ${amt:,.2f} manual JE ({row['document_number']}) in "
                f"{row['entity']} adjusted the prepaid balance outside "
                f"the normal process."
            ),
            "recommended_action": (
                f"1. Obtain documentation for {row['document_number']}.\n"
                f"2. Confirm whether amortization schedule needs updating.\n"
                f"3. Reverse if posted in error."
            ),
            "suggested_journal_entry": (
                f"If reversal required:\n"
                f"  Dr  Prepaid Expenses           ${amt:>12,.2f}\n"
                f"  Cr  [Account originally credited] ${amt:>12,.2f}\n"
                f"  Memo: Reversal of {row['document_number']}"
            ),
        })

    # ── Rule 4: Missing Source Invoice ─────────────────────────
    scheduled_items = set(amortization["prepaid_item_id"].unique())
    orphan_schedules = scheduled_items - ledger_bill_items
    bill_docs = set(
        ledger.loc[ledger["transaction_type"] == "Bill", "document_number"]
        .astype(str).str.strip()
    )
    bill_docs |= {d.lstrip("#").strip() for d in bill_docs}

    for item_id in sorted(orphan_schedules):
        s = amortization[amortization["prepaid_item_id"] == item_id].iloc[0]
        src_type, src_num = _parse_source_doc(s.get("source_document", ""))

        # Journal / Bill Credit sources are legitimate — skip
        if src_type in ("Journal", "Bill Credit"):
            continue

        doc_in_ledger = (
            src_num in bill_docs
            or src_num.lstrip("#").strip() in bill_docs
        )

        if src_type == "Unknown":
            sev, conf = "LOW", "LOW"
        elif doc_in_ledger:
            sev, conf = "LOW", "MEDIUM"  # linkage artifact
        else:
            sev, conf = "HIGH", "HIGH"   # genuinely missing

        # Entity fallback: orphan schedules often have blank entity
        finding_entity = str(s["entity"]).strip()
        if finding_entity in ("", "nan", "None"):
            finding_entity = "Unknown Entity"

        item_periods = _sort_periods(
            amortization[amortization["prepaid_item_id"] == item_id]
            ["accounting_period"].unique().tolist()
        )

        findings.append({
            "root_cause_id": _next_id(), "entity": finding_entity,
            "root_cause_category": "MISSING_ORIGINAL_BILL",
            "severity": sev, "confidence": conf,
            "impacted_periods": ", ".join(item_periods),
            "estimated_impact": round(float(s["original_amount"]), 2),
            "evidence_transactions": "None found in ledger",
            "evidence_prepaid_item_id": item_id,
            "explanation_workpaper": (
                f"Schedule {s.get('schedule_id', 'N/A')} for {item_id} "
                f"({s['vendor_name']}, ${float(s['original_amount']):,.2f}) in "
                f"{finding_entity} has no originating Bill. "
                f"Ref: {s['source_document']}."
            ),
            "management_summary": (
                f"${float(s['original_amount']):,.2f} schedule for "
                f"{s['vendor_name']} in {finding_entity} has no corresponding "
                f"Bill in the prepaid ledger."
            ),
            "recommended_action": (
                f"1. Locate {s['source_document']} in AP.\n"
                f"2. If miscoded, recode to prepaid.\n"
                f"3. Cancel the schedule if created in error."
            ),
            "suggested_journal_entry": (
                f"If Bill was expensed:\n"
                f"  Dr  Prepaid Expenses   ${float(s['original_amount']):>12,.2f}\n"
                f"  Cr  [Expense Account]  ${float(s['original_amount']):>12,.2f}\n"
                f"  Memo: Reclassification of {s['source_document']}"
            ),
        })

    # ── Rule 5: Missing Amortization JE ───────────────────────
    # Only run if the classifier can identify amortization entries.
    # If description field is blank/unusable (zero entries classified),
    # these rules produce only false positives — skip with diagnostic.
    n_amort_entries = (ledger["transaction_category"] == "AMORTIZATION_ENTRY").sum()

    if n_amort_entries == 0:
        amort_comparison = pd.DataFrame(columns=[
            "entity", "prepaid_item_id", "accounting_period",
            "scheduled_amortization", "actual_amortization",
        ])
    else:
        # Exclude: future periods, Completed, Not Started
        _excluded_by_status = set()
        if "status" in amortization.columns:
            _completed = amortization.loc[
                amortization["status"].str.lower() == "completed",
                "prepaid_item_id"
            ].unique()
            _not_started = amortization.loc[
                amortization["status"].str.lower() == "not started",
                "prepaid_item_id"
            ].unique()
            _excluded_by_status = set(_completed) | set(_not_started)

        actual_amort = (
            ledger[ledger["transaction_category"] == "AMORTIZATION_ENTRY"]
            .groupby(["entity", "prepaid_item_id", "accounting_period"])["amount"]
            .sum().abs().reset_index()
            .rename(columns={"amount": "actual_amortization"})
        )

        sched_amort = expected_balance_flat[
            expected_balance_flat["prepaid_item_id"].isin(ledger_bill_items)
        ][["entity", "prepaid_item_id", "accounting_period",
           "scheduled_amortization"]].copy()

        # Filter future periods
        sched_amort["_pdt"] = sched_amort["accounting_period"].apply(period_to_date)
        sched_amort = sched_amort[sched_amort["_pdt"] <= latest_period_dt].copy()
        sched_amort = sched_amort.drop(columns=["_pdt"])

        # Filter by status
        sched_amort = sched_amort[
            ~sched_amort["prepaid_item_id"].isin(_excluded_by_status)
        ].copy()

        amort_comparison = pd.merge(
            sched_amort, actual_amort,
            on=["entity", "prepaid_item_id", "accounting_period"], how="left",
        )
        amort_comparison["actual_amortization"] = (
            amort_comparison["actual_amortization"].fillna(0)
        )

        # Missing JE — only for entities that FAIL aggregate reconciliation
        missing_je = amort_comparison[
            (amort_comparison["scheduled_amortization"] > 0)
            & (amort_comparison["actual_amortization"] == 0)
            & (~amort_comparison["entity"].isin(reconciled_entities))
        ].copy()

        missing_grouped = (
            missing_je.groupby(["entity", "prepaid_item_id"])
            .agg(
                total_impact=("scheduled_amortization", "sum"),
                all_missing_periods=(
                    "accounting_period",
                    lambda x: _sort_periods(x.tolist()),
                ),
                first_missed=(
                    "accounting_period",
                    lambda x: _sort_periods(x.tolist())[0],
                ),
            )
            .reset_index()
        )

        for _, row in missing_grouped.iterrows():
            vendor = _get_vendor_label(row["prepaid_item_id"], amortization)
            missed_str = ", ".join(row["all_missing_periods"])
            n_periods = len(row["all_missing_periods"])
            findings.append({
                "root_cause_id": _next_id(), "entity": row["entity"],
                "root_cause_category": "MISSING_AMORTIZATION_JE",
                "severity": "MEDIUM", "confidence": "HIGH",
                "impacted_periods": _periods_from(row["first_missed"], all_periods),
                "estimated_impact": round(row["total_impact"], 2),
                "evidence_transactions": "No JE found in ledger",
                "evidence_prepaid_item_id": row["prepaid_item_id"],
                "explanation_workpaper": (
                    f"{row['prepaid_item_id']} ({vendor}) in {row['entity']} "
                    f"required JEs in {n_periods} period(s). "
                    f"Total missed: ${row['total_impact']:,.2f}."
                ),
                "management_summary": (
                    f"Amortization for {vendor} ({row['prepaid_item_id']}) in "
                    f"{row['entity']} was not posted in {n_periods} period(s)."
                ),
                "recommended_action": (
                    f"Post catch-up amortization entries for "
                    f"{row['prepaid_item_id']}."
                ),
                "suggested_journal_entry": (
                    f"Dr  {vendor} Expense    ${row['total_impact']:>12,.2f}\n"
                    f"Cr  Prepaid Expenses  ${row['total_impact']:>12,.2f}\n"
                    f"Memo: Catch-up amortization — {n_periods} period(s)"
                ),
            })

        # Over / Under Amortization (only for non-reconciled entities)
        comp_non_rec = amort_comparison[
            ~amort_comparison["entity"].isin(reconciled_entities)
        ]

        over = comp_non_rec[
            (comp_non_rec["actual_amortization"] > 0)
            & (comp_non_rec["actual_amortization"]
               > comp_non_rec["scheduled_amortization"] + amort_tol)
        ].copy()

        under = comp_non_rec[
            (comp_non_rec["actual_amortization"] > 0)
            & (comp_non_rec["actual_amortization"]
               < comp_non_rec["scheduled_amortization"] - amort_tol)
        ].copy()

        for _, row in over.iterrows():
            excess = row["actual_amortization"] - row["scheduled_amortization"]
            vendor = _get_vendor_label(row["prepaid_item_id"], amortization)
            findings.append({
                "root_cause_id": _next_id(), "entity": row["entity"],
                "root_cause_category": "OVER_AMORTIZATION",
                "severity": "MEDIUM", "confidence": "HIGH",
                "impacted_periods": _periods_from(row["accounting_period"], all_periods),
                "estimated_impact": round(excess, 2),
                "evidence_transactions": "",
                "evidence_prepaid_item_id": row["prepaid_item_id"],
                "explanation_workpaper": (
                    f"{row['prepaid_item_id']} ({vendor}) posted "
                    f"${row['actual_amortization']:,.2f} vs scheduled "
                    f"${row['scheduled_amortization']:,.2f}. "
                    f"Excess: ${excess:,.2f}."
                ),
                "management_summary": (
                    f"{vendor} over-amortized by ${excess:,.2f} in "
                    f"{row['accounting_period']}."
                ),
                "recommended_action": "Review and reverse excess if confirmed.",
                "suggested_journal_entry": (
                    f"Dr  Prepaid Expenses  ${excess:>12,.2f}\n"
                    f"Cr  {vendor} Expense   ${excess:>12,.2f}\n"
                    f"Memo: Reversal of excess amortization"
                ),
            })

        for _, row in under.iterrows():
            shortfall = row["scheduled_amortization"] - row["actual_amortization"]
            vendor = _get_vendor_label(row["prepaid_item_id"], amortization)
            findings.append({
                "root_cause_id": _next_id(), "entity": row["entity"],
                "root_cause_category": "UNDER_AMORTIZATION",
                "severity": "LOW", "confidence": "HIGH",
                "impacted_periods": _periods_from(row["accounting_period"], all_periods),
                "estimated_impact": round(shortfall, 2),
                "evidence_transactions": "",
                "evidence_prepaid_item_id": row["prepaid_item_id"],
                "explanation_workpaper": (
                    f"{row['prepaid_item_id']} ({vendor}) posted "
                    f"${row['actual_amortization']:,.2f} vs scheduled "
                    f"${row['scheduled_amortization']:,.2f}. "
                    f"Shortfall: ${shortfall:,.2f}."
                ),
                "management_summary": (
                    f"{vendor} under-amortized by ${shortfall:,.2f} in "
                    f"{row['accounting_period']}."
                ),
                "recommended_action": f"Post catch-up amortization of ${shortfall:,.2f}.",
                "suggested_journal_entry": (
                    f"Dr  {vendor} Expense    ${shortfall:>12,.2f}\n"
                    f"Cr  Prepaid Expenses  ${shortfall:>12,.2f}\n"
                    f"Memo: Catch-up amortization shortfall"
                ),
            })

    # Assemble
    if findings:
        root_cause_report = pd.DataFrame(findings)[ROOT_CAUSE_COLUMNS].reset_index(drop=True)
    else:
        root_cause_report = pd.DataFrame(columns=ROOT_CAUSE_COLUMNS)

    return {
        "root_cause_report": root_cause_report,
        "amort_comparison": amort_comparison,
    }


# ════════════════════════════════════════════════════════════════
# MODULE 6: INVESTIGATION REPORT
# ════════════════════════════════════════════════════════════════

def build_investigation_report(root_cause_report, amortization, config=None):
    """Business-friendly investigation report from actionable findings only."""
    if root_cause_report.empty:
        return pd.DataFrame()

    cfg = {**DEFAULT_CONFIG, **(config or {})}
    materiality = cfg.get("materiality_threshold", 100.0)
    controller_mode = cfg.get("controller_mode", True)

    ir = root_cause_report[[
        "root_cause_id", "entity", "root_cause_category", "severity",
        "confidence", "impacted_periods", "estimated_impact",
        "evidence_transactions", "evidence_prepaid_item_id",
    ]].copy()

    # Exclude non-actionable findings
    ir = ir[ir["root_cause_category"] != "RECURRING_INVOICE_REVIEW"].copy()
    ir = ir[~(
        (ir["root_cause_category"] == "MISSING_ORIGINAL_BILL")
        & (ir["confidence"] != "HIGH")
    )].copy()
    if ir.empty:
        return pd.DataFrame()

    # ── Title generation ──────────────────────────────────────
    def _title(row):
        cat = row["root_cause_category"]
        vl = _get_vendor_label(row["evidence_prepaid_item_id"], amortization)
        titles = {
            "DUPLICATE_BILL": f"Duplicate {vl} Invoice Detected",
            "UNLINKED_ADDITION": f"{vl} Prepaid Without a Schedule",
            "MISSING_ORIGINAL_BILL": f"Amortization Schedule Exists Without Original Invoice",
            "MISSING_AMORTIZATION_JE": f"Required Monthly Amortization Was Not Posted",
            "OVER_AMORTIZATION": f"{vl} Amortized Faster Than Scheduled",
            "UNDER_AMORTIZATION": f"{vl} Amortization Incomplete",
            "MANUAL_ADJUSTMENT": f"Manual Prepaid Adjustment Requires Review",
        }
        return titles.get(cat, f"{cat.replace('_', ' ').title()}")

    def _why(row):
        cat, impact, entity = row["root_cause_category"], row["estimated_impact"], row["entity"]
        whys = {
            "DUPLICATE_BILL": f"This invoice appears to have been recorded twice in {entity}. Prepaid expenses are likely overstated by approximately ${impact:,.2f}.",
            "UNLINKED_ADDITION": f"A ${impact:,.2f} payment in {entity} has no amortization schedule. It will never be recognised as an expense without intervention.",
            "MISSING_ORIGINAL_BILL": f"An amortization schedule for ${impact:,.2f} in {entity} has no corresponding invoice.",
            "MISSING_AMORTIZATION_JE": f"${impact:,.2f} of expense in {entity} has not been recognised because required amortization entries were not posted.",
            "OVER_AMORTIZATION": f"${impact:,.2f} of excess amortization in {entity} understates the prepaid balance.",
            "UNDER_AMORTIZATION": f"${impact:,.2f} of unrecognised expense in {entity} overstates prepaid assets.",
            "MANUAL_ADJUSTMENT": f"A ${impact:,.2f} manual adjustment in {entity} changed the prepaid balance outside the normal process.",
        }
        return whys.get(cat, "")

    def _next_step(row):
        cat = row["root_cause_category"]
        item_id = str(row["evidence_prepaid_item_id"])
        steps = {
            "DUPLICATE_BILL": "Confirm with AP and reverse the duplicate if confirmed.",
            "UNLINKED_ADDITION": "Create amortization schedule or reclassify to expense.",
            "MISSING_ORIGINAL_BILL": f"Search AP records for the original invoice for {item_id}.",
            "MISSING_AMORTIZATION_JE": f"Post catch-up amortization entries for {item_id}.",
            "OVER_AMORTIZATION": "Review and reverse excess amortization.",
            "UNDER_AMORTIZATION": "Post catch-up amortization entry.",
            "MANUAL_ADJUSTMENT": "Obtain documentation and confirm approval.",
        }
        return steps.get(cat, "Investigate and document.")

    def _exec(row):
        cat, impact, entity = row["root_cause_category"], row["estimated_impact"], row["entity"]
        item_id = str(row["evidence_prepaid_item_id"])
        sums = {
            "DUPLICATE_BILL": f"A duplicate invoice in {entity} likely overstates prepaid expenses by ${impact:,.2f}.",
            "UNLINKED_ADDITION": f"A ${impact:,.2f} prepaid in {entity} has no schedule and will never be expensed.",
            "MISSING_ORIGINAL_BILL": f"A ${impact:,.2f} schedule in {entity} ({item_id}) has no corresponding invoice.",
            "MISSING_AMORTIZATION_JE": f"${impact:,.2f} in {entity} ({item_id}) has not been recognised as expense.",
            "OVER_AMORTIZATION": f"Prepaid in {entity} was over-amortized by ${impact:,.2f}.",
            "UNDER_AMORTIZATION": f"Prepaid in {entity} was under-amortized by ${impact:,.2f}.",
            "MANUAL_ADJUSTMENT": f"A ${impact:,.2f} manual adjustment in {entity} requires review.",
        }
        return sums.get(cat, "")

    ir["issue_title"] = ir.apply(_title, axis=1)
    ir["why_it_matters"] = ir.apply(_why, axis=1)
    ir["recommended_next_step"] = ir.apply(_next_step, axis=1)
    ir["executive_summary"] = ir.apply(_exec, axis=1)
    ir["is_material"] = ir["estimated_impact"] >= materiality

    # Priority scoring
    sev_scores = {"HIGH": 300, "MEDIUM": 200, "LOW": 100}
    conf_scores = {"HIGH": 100, "MEDIUM": 50, "LOW": 0}
    mat_bonus = 500 if controller_mode else 200
    conf_mult = 3 if controller_mode else 1

    ir["priority_score"] = ir.apply(
        lambda r: round(
            sev_scores.get(r["severity"], 0)
            + conf_scores.get(r.get("confidence", "HIGH"), 0) * conf_mult
            + (mat_bonus if r["estimated_impact"] >= materiality else 0)
            + min(r["estimated_impact"] / 1000, 99), 2),
        axis=1,
    )

    ir = ir.sort_values("priority_score", ascending=False).reset_index(drop=True)
    ir.insert(0, "priority_rank", ir.index + 1)

    return ir


# ════════════════════════════════════════════════════════════════
# MODULE 7: ROOT CAUSE SUMMARY
# ════════════════════════════════════════════════════════════════

def build_root_cause_summary(investigation_report, materiality=100.0):
    """Aggregate actionable findings by category."""
    cols = [
        "root_cause_category", "finding_count", "material_finding_count",
        "total_impact", "material_impact", "highest_confidence",
        "high_confidence_count", "medium_confidence_count",
        "low_confidence_count", "top_example_issue",
    ]
    if investigation_report.empty:
        return pd.DataFrame(columns=cols)

    ir = investigation_report.copy()
    conf_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}
    rows = []
    for cat, grp in ir.groupby("root_cause_category"):
        material = grp[grp["estimated_impact"] >= materiality]
        hi_conf = max(grp["confidence"].unique(),
                      key=lambda c: conf_order.get(c, 0))
        top = grp.loc[grp["estimated_impact"].idxmax()]
        rows.append({
            "root_cause_category": cat,
            "finding_count": len(grp),
            "material_finding_count": len(material),
            "total_impact": round(grp["estimated_impact"].sum(), 2),
            "material_impact": round(material["estimated_impact"].sum(), 2),
            "highest_confidence": hi_conf,
            "high_confidence_count": int((grp["confidence"] == "HIGH").sum()),
            "medium_confidence_count": int((grp["confidence"] == "MEDIUM").sum()),
            "low_confidence_count": int((grp["confidence"] == "LOW").sum()),
            "top_example_issue": (
                f"{top.get('evidence_prepaid_item_id', 'N/A')} "
                f"(${top['estimated_impact']:,.2f})"
            ),
        })

    return (pd.DataFrame(rows, columns=cols)
            .sort_values("material_impact", ascending=False)
            .reset_index(drop=True))


# ════════════════════════════════════════════════════════════════
# MODULE 8: JOURNAL ENTRIES
# ════════════════════════════════════════════════════════════════

def generate_journal_entries(root_cause_report):
    """Corrective journal entries for actionable findings only."""
    if root_cause_report.empty:
        return pd.DataFrame()

    exclude = {"RECURRING_INVOICE_REVIEW"}
    actionable = root_cause_report[
        ~root_cause_report["root_cause_category"].isin(exclude)
    ].copy()
    actionable = actionable[~(
        (actionable["root_cause_category"] == "MISSING_ORIGINAL_BILL")
        & (actionable["confidence"] != "HIGH")
    )].copy()
    if actionable.empty:
        return pd.DataFrame()

    entries = []
    for _, row in actionable.iterrows():
        entries.append({
            "root_cause_id": row["root_cause_id"],
            "entity": row["entity"],
            "category": row["root_cause_category"],
            "severity": row["severity"],
            "estimated_impact": row["estimated_impact"],
            "evidence_prepaid_item_id": row["evidence_prepaid_item_id"],
            "suggested_journal_entry": row["suggested_journal_entry"],
            "recommended_action": row["recommended_action"],
        })

    return pd.DataFrame(entries)


# ════════════════════════════════════════════════════════════════
# MASTER: RUN_ANALYSIS
# ════════════════════════════════════════════════════════════════

def run_analysis(ledger_df, amortization_df, config=None):
    """Execute the full reconciliation workflow.

    Returns dict with all output keys required by app.py.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}

    # Dynamic materiality
    dataset_volume = ledger_df["amount"].apply(
        lambda x: abs(float(x)) if pd.notna(x) else 0
    ).sum()
    pct = cfg.get("materiality_percent", 0)
    if pct and dataset_volume > 0:
        cfg["materiality_threshold"] = round(dataset_volume * pct, 2)
    materiality = cfg.get("materiality_threshold", 100.0)

    # Module 1
    ledger, amortization, validation_info = validate_inputs(
        ledger_df, amortization_df, cfg)

    # Module 2
    ledger, category_counts, flagged = classify_transactions(ledger, cfg)

    # Module 3
    wf = build_amortization_waterfall(ledger, amortization)

    # Module 4A: Aggregate reconciliation (primary)
    agg_recon, reconciled_entities, latest_period_dt = aggregate_reconciliation(
        ledger, amortization, wf["all_periods"], materiality
    )

    # Module 4B: Period-level reconciliation (drill-down)
    recon = reconcile_balances(
        ledger, amortization,
        wf["expected_balance_flat"], wf["all_periods"], cfg,
    )

    # Module 5: Root Cause Analysis
    rca = perform_root_cause_analysis(
        ledger, amortization,
        wf["expected_balance_flat"], recon["ledger_bill_items"],
        wf["all_periods"], cfg, reconciled_entities, latest_period_dt,
    )

    # Module 6: Investigation Report
    investigation = build_investigation_report(
        rca["root_cause_report"], amortization, cfg
    )

    # Module 7: Root Cause Summary
    root_cause_summary = build_root_cause_summary(
        investigation, materiality
    )

    # Module 8: Journal Entries
    journal_entries = generate_journal_entries(rca["root_cause_report"])

    # Enrich validation_info
    validation_info["dataset_volume"] = round(dataset_volume, 2)
    validation_info["materiality_threshold_used"] = materiality
    validation_info["controller_mode"] = cfg.get("controller_mode", True)

    return {
        # Module 1
        "validation_info": validation_info,
        "ledger": ledger,
        # Module 2
        "category_counts": category_counts,
        "flagged_transactions": flagged,
        # Module 3
        "all_periods": wf["all_periods"],
        "item_metadata": wf["item_metadata"],
        "waterfall_amort": wf["waterfall_amort"],
        "waterfall_amort_with_total": wf["waterfall_amort_with_total"],
        "waterfall_balance": wf["waterfall_balance"],
        "expected_balance_flat": wf["expected_balance_flat"],
        # Module 4A
        "aggregate_reconciliation_summary": agg_recon,
        # Module 4B
        "ledger_bill_items": recon["ledger_bill_items"],
        "items_schedule_only": recon["items_schedule_only"],
        "reconciliation_summary": recon["reconciliation_summary"],
        "exceptions": recon["exceptions"],
        # Module 5
        "root_cause_report": rca["root_cause_report"],
        "amort_comparison": rca["amort_comparison"],
        # Module 6
        "investigation_report": investigation,
        "root_cause_summary": root_cause_summary,
        # Module 8
        "journal_entries": journal_entries,
    }
