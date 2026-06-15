"""
reconciliation_engine.py
AI Month-End Close Reconciliation Assistant — Backend Engine

Converts two accounting CSV exports (GL ledger + amortization schedule) into
a complete prepaid expense reconciliation with root cause analysis and
business-friendly investigation findings.

Usage:
    from reconciliation_engine import run_analysis

    results = run_analysis(ledger_df, amortization_df)
    # results is a dict with all output dataframes and metadata
"""

import pandas as pd
from datetime import datetime


# ════════════════════════════════════════════════════════════════
# DEFAULT CONFIGURATION
# ════════════════════════════════════════════════════════════════
# These defaults are used when no config dict is passed to
# run_analysis(). Override any of them by passing a config dict.

DEFAULT_CONFIG = {
    "reconciliation_threshold": 1.00,
    "amort_tolerance": 1.00,
    "txn_type_map": {
        "Bill": "Bill",
        "Bill Credit": "Bill Credit",
        "Journal Entry": "Journal Entry",
    },
    "amortization_keywords": [
        "amortization", "amortisation",
        "prepaid expense recognition", "monthly expense",
        "prepaid recognition",
    ],
    "manual_adjustment_keywords": [
        "reclassif", "correction", "adjustment", "reclass",
        "write-off", "write off", "reversal", "true-up", "true up",
    ],
}

REQUIRED_LEDGER_COLS = [
    "transaction_id", "transaction_date", "accounting_period",
    "entity", "transaction_type", "document_number", "vendor_name",
    "description", "amount", "running_balance", "prepaid_item_id",
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
    "impacted_periods", "estimated_impact", "evidence_transactions",
    "evidence_prepaid_item_id", "explanation_workpaper",
    "management_summary", "recommended_action", "suggested_journal_entry",
]


# ════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ════════════════════════════════════════════════════════════════

def period_to_date(period_str):
    """Parse an accounting period string into a datetime for sorting.

    Supports: 'Oct 2025', 'October 2025', '2025-10', '10/2025', '10-2025'.
    """
    for fmt in ["%b %Y", "%B %Y", "%Y-%m", "%m/%Y", "%m-%Y"]:
        try:
            return datetime.strptime(str(period_str).strip(), fmt)
        except ValueError:
            continue
    raise ValueError(
        f"Cannot parse period '{period_str}'. "
        f"Supported formats: 'Oct 2025', 'October 2025', '2025-10', '10/2025'."
    )


def _periods_from(start_period, all_periods):
    """Return a comma-separated string of all periods >= start_period."""
    start_dt = period_to_date(start_period)
    return ", ".join(p for p in all_periods if period_to_date(p) >= start_dt)


def _sort_by_period(df, period_col="accounting_period", group_cols=None):
    """Sort a dataframe chronologically by accounting period within groups."""
    df = df.copy()
    df["_sort"] = df[period_col].apply(period_to_date)
    sort_cols = (group_cols or []) + ["_sort"]
    return df.sort_values(sort_cols).drop(columns="_sort").reset_index(drop=True)


def _get_vendor_label(item_id, amortization_df):
    """Look up a short vendor label from the amortization data."""
    if "NONE" in str(item_id) or pd.isna(item_id):
        return "Prepaid Expense"
    match = amortization_df.loc[
        amortization_df["prepaid_item_id"] == item_id, "vendor_name"
    ]
    if not match.empty:
        return match.iloc[0].split()[0]
    return str(item_id).split("-")[0].title()


# ════════════════════════════════════════════════════════════════
# MODULE 1: VALIDATE INPUTS
# ════════════════════════════════════════════════════════════════

def validate_inputs(ledger_df, amortization_df, config):
    """Validate schemas and normalise transaction types.

    Returns:
        tuple: (ledger, amortization, validation_info)
    """
    ledger = ledger_df.copy()
    amortization = amortization_df.copy()

    # Schema check
    missing_ledger = [c for c in REQUIRED_LEDGER_COLS if c not in ledger.columns]
    missing_amort = [c for c in REQUIRED_AMORT_COLS if c not in amortization.columns]

    if missing_ledger:
        raise ValueError(f"Ledger missing required columns: {missing_ledger}")
    if missing_amort:
        raise ValueError(f"Amortization schedule missing required columns: {missing_amort}")

    # Normalise transaction types via config map
    txn_map = config["txn_type_map"]
    ledger["transaction_type"] = (
        ledger["transaction_type"].map(txn_map).fillna(ledger["transaction_type"])
    )

    validation_info = {
        "ledger_rows": len(ledger),
        "ledger_cols": len(ledger.columns),
        "amort_rows": len(amortization),
        "amort_cols": len(amortization.columns),
        "entities": ledger["entity"].nunique(),
        "periods": ledger["accounting_period"].nunique(),
        "date_range_start": ledger["accounting_period"].iloc[0],
        "date_range_end": ledger["accounting_period"].iloc[-1],
    }

    return ledger, amortization, validation_info


# ════════════════════════════════════════════════════════════════
# MODULE 2: CLASSIFY TRANSACTIONS
# ════════════════════════════════════════════════════════════════

def classify_transactions(ledger, config):
    """Classify every ledger row into one of seven accounting categories.

    Returns:
        tuple: (ledger_with_categories, category_counts_dict, flagged_rows_df)
    """
    amort_kw = config["amortization_keywords"]
    manual_kw = config["manual_adjustment_keywords"]

    ledger = ledger.copy()

    # Pre-compute duplicate detection across all rows
    dup_counts = (
        ledger
        .groupby(["entity", "document_number", "transaction_type"])["transaction_id"]
        .transform("count")
    )
    is_dup = (
        (ledger["transaction_type"] == "Bill")
        & (ledger["amount"] > 0)
        & (dup_counts > 1)
    )

    def _classify(row, is_dup_flag):
        txn_type = row["transaction_type"]
        amount = row["amount"]
        desc = str(row["description"]).lower()
        item_id = str(row["prepaid_item_id"]).strip()
        has_id = item_id not in ("", "nan", "none")
        is_amort = any(kw in desc for kw in amort_kw)
        is_manual = any(kw in desc for kw in manual_kw)

        if is_dup_flag:
            return "POTENTIAL_DUPLICATE"
        if txn_type == "Bill" and amount > 0 and not has_id:
            return "UNLINKED_ADDITION"
        if txn_type == "Bill" and amount > 0 and has_id:
            return "PREPAID_ADDITION"
        if txn_type == "Bill Credit" and amount < 0:
            return "BILL_CREDIT_REVERSAL"
        if txn_type == "Journal Entry" and amount < 0 and is_amort:
            return "AMORTIZATION_ENTRY"
        if txn_type == "Journal Entry" and amount < 0 and is_manual:
            return "MANUAL_ADJUSTMENT"
        return "OTHER"

    ledger["transaction_category"] = ledger.apply(
        lambda row: _classify(row, is_dup.loc[row.name]), axis=1
    )

    category_counts = ledger["transaction_category"].value_counts().to_dict()

    review_categories = [
        "POTENTIAL_DUPLICATE", "UNLINKED_ADDITION",
        "MANUAL_ADJUSTMENT", "OTHER",
    ]
    flagged = ledger[ledger["transaction_category"].isin(review_categories)].copy()

    return ledger, category_counts, flagged


# ════════════════════════════════════════════════════════════════
# MODULE 3: BUILD AMORTIZATION WATERFALL
# ════════════════════════════════════════════════════════════════

def build_amortization_waterfall(ledger, amortization):
    """Build waterfall pivot tables and flat expected balance table.

    Returns:
        dict with keys:
            all_periods, item_metadata, waterfall_amort,
            waterfall_amort_with_total, waterfall_balance,
            expected_balance_flat
    """
    # Period list — union of both files, sorted chronologically
    all_periods = sorted(
        set(amortization["accounting_period"].unique())
        | set(ledger["accounting_period"].unique()),
        key=period_to_date,
    )

    # Item metadata lookup
    item_metadata = (
        amortization
        .drop_duplicates(subset="prepaid_item_id")
        [["prepaid_item_id", "entity", "vendor_name", "description",
          "original_amount", "start_date", "end_date", "total_periods",
          "source_document"]]
        .set_index("prepaid_item_id")
    )

    # Waterfall — amortization amounts
    waterfall_amort = amortization.pivot_table(
        index="prepaid_item_id", columns="accounting_period",
        values="scheduled_amortization", aggfunc="sum", fill_value=0,
    )
    # Reorder to calendar order; only include periods that exist in pivot
    available_periods = [p for p in all_periods if p in waterfall_amort.columns]
    waterfall_amort = waterfall_amort[available_periods]

    total_amort_row = waterfall_amort.sum(axis=0).rename("── TOTAL AMORTIZATION")
    waterfall_amort_with_total = pd.concat(
        [waterfall_amort, total_amort_row.to_frame().T]
    )

    # Waterfall — expected ending balances
    waterfall_balance = amortization.pivot_table(
        index="prepaid_item_id", columns="accounting_period",
        values="expected_ending_balance", aggfunc="last", fill_value=None,
    )
    available_balance_periods = [p for p in all_periods if p in waterfall_balance.columns]
    waterfall_balance = waterfall_balance[available_balance_periods]

    # Flat expected balance table (input for reconciliation)
    expected_balance_flat = (
        amortization[[
            "prepaid_item_id", "entity", "vendor_name", "accounting_period",
            "period_number", "scheduled_amortization", "expected_ending_balance",
            "status",
        ]]
        .copy()
        .sort_values(["entity", "prepaid_item_id", "period_number"])
        .reset_index(drop=True)
    )

    return {
        "all_periods": all_periods,
        "item_metadata": item_metadata,
        "waterfall_amort": waterfall_amort,
        "waterfall_amort_with_total": waterfall_amort_with_total,
        "waterfall_balance": waterfall_balance,
        "expected_balance_flat": expected_balance_flat,
    }


# ════════════════════════════════════════════════════════════════
# MODULE 4: RECONCILE BALANCES
# ════════════════════════════════════════════════════════════════

def reconcile_balances(ledger, amortization, expected_balance_flat,
                       all_periods, config):
    """Compare expected vs actual prepaid balances per entity-period.

    Returns:
        dict with keys:
            ledger_bill_items, items_schedule_only,
            reconciliation_summary, exceptions
    """
    threshold = config["reconciliation_threshold"]

    # Items with Bills in the ledger
    ledger_bill_items = set(
        ledger.loc[ledger["transaction_type"] == "Bill", "prepaid_item_id"]
        .dropna().astype(str).str.strip().unique()
    )

    items_schedule_only = (
        set(amortization["prepaid_item_id"].unique()) - ledger_bill_items
    )

    # Expected balance: only items with a Bill in the ledger
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

    # Actual balance: last running_balance per entity-period
    actual = (
        ledger.sort_values("transaction_date")
        .groupby(["entity", "accounting_period"])["running_balance"]
        .last().reset_index()
        .rename(columns={"running_balance": "actual_balance"})
    )
    actual = _sort_by_period(actual, group_cols=["entity"])

    # Merge and compute variance
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
                                ledger_bill_items, all_periods, config):
    """Identify specific accounting events causing each exception.

    Returns:
        dict with keys: root_cause_report, amort_comparison
    """
    amort_tol = config["amort_tolerance"]
    findings = []
    counter = [0]  # mutable counter inside closure

    def _next_id():
        counter[0] += 1
        return f"RC-{counter[0]:03d}"

    # ── Rule 1: Duplicate Bill ────────────────────────────────
    bills = ledger[ledger["transaction_type"] == "Bill"].copy()
    doc_counts = (
        bills.groupby(["entity", "document_number"])
        .agg(
            count=("transaction_id", "count"),
            transaction_ids=("transaction_id", lambda x: ", ".join(x.tolist())),
            amounts=("amount", lambda x: x.tolist()),
            periods=("accounting_period", lambda x: sorted(
                x.unique().tolist(), key=period_to_date)),
            prepaid_ids=("prepaid_item_id", lambda x: ", ".join(
                x.dropna().astype(str).unique().tolist())),
            vendor=("vendor_name", "first"),
        )
        .reset_index()
    )

    for _, dup in doc_counts[doc_counts["count"] > 1].iterrows():
        inv_amt = dup["amounts"][0]
        impact = inv_amt * (dup["count"] - 1)
        dup_start = dup["periods"][-1]
        findings.append({
            "root_cause_id": _next_id(), "entity": dup["entity"],
            "root_cause_category": "DUPLICATE_BILL", "severity": "HIGH",
            "impacted_periods": _periods_from(dup_start, all_periods),
            "estimated_impact": round(impact, 2),
            "evidence_transactions": dup["transaction_ids"],
            "evidence_prepaid_item_id": dup["prepaid_ids"],
            "explanation_workpaper": (
                f"Document {dup['document_number']} ({dup['vendor']}) "
                f"posted {dup['count']}x in {dup['entity']}. "
                f"IDs: {dup['transaction_ids']}. "
                f"Excess: ${impact:,.2f} from {dup_start} onward."
            ),
            "management_summary": (
                f"Invoice {dup['document_number']} from {dup['vendor']} "
                f"was recorded twice in {dup['entity']}, overstating "
                f"prepaid assets by ${impact:,.2f} from {dup_start} onward."
            ),
            "recommended_action": (
                f"1. Confirm with AP whether two invoices were received "
                f"for {dup['document_number']}.\n"
                f"2. Reverse the duplicate posting if confirmed.\n"
                f"3. Recover payment from vendor if duplicate payment was made."
            ),
            "suggested_journal_entry": (
                f"Dr  Accounts Payable   ${impact:>12,.2f}\n"
                f"Cr  Prepaid Expenses   ${impact:>12,.2f}\n"
                f"Memo: Reversal of duplicate {dup['document_number']}"
            ),
        })

    # ── Rule 2: Unlinked Addition ─────────────────────────────
    for _, row in ledger[ledger["transaction_category"] == "UNLINKED_ADDITION"].iterrows():
        amt = abs(row["amount"])
        findings.append({
            "root_cause_id": _next_id(), "entity": row["entity"],
            "root_cause_category": "UNLINKED_ADDITION", "severity": "HIGH",
            "impacted_periods": _periods_from(row["accounting_period"], all_periods),
            "estimated_impact": round(amt, 2),
            "evidence_transactions": row["transaction_id"],
            "evidence_prepaid_item_id": "NONE — no prepaid_item_id assigned",
            "explanation_workpaper": (
                f"{row['transaction_id']} ({row['vendor_name']}, "
                f"{row['accounting_period']}) posted ${amt:,.2f} to prepaid "
                f"in {row['entity']} with no prepaid_item_id. "
                f"Balance will never amortize."
            ),
            "management_summary": (
                f"${amt:,.2f} to {row['vendor_name']} in {row['entity']} "
                f"({row['accounting_period']}) has no amortization schedule "
                f"— the balance overstates assets indefinitely."
            ),
            "recommended_action": (
                f"1. Determine if payment qualifies as prepaid.\n"
                f"2. If yes: create amortization schedule and assign prepaid_item_id.\n"
                f"3. If no: reclassify to the appropriate expense account."
            ),
            "suggested_journal_entry": (
                f"If reclassify:\n"
                f"  Dr  [Expense Account]   ${amt:>12,.2f}\n"
                f"  Cr  Prepaid Expenses    ${amt:>12,.2f}\n"
                f"  Memo: Reclassification of {row['document_number']}"
            ),
        })

    # ── Rule 3: Manual Adjustment ─────────────────────────────
    for _, row in ledger[ledger["transaction_category"] == "MANUAL_ADJUSTMENT"].iterrows():
        amt = abs(row["amount"])
        findings.append({
            "root_cause_id": _next_id(), "entity": row["entity"],
            "root_cause_category": "MANUAL_ADJUSTMENT", "severity": "MEDIUM",
            "impacted_periods": _periods_from(row["accounting_period"], all_periods),
            "estimated_impact": round(amt, 2),
            "evidence_transactions": row["transaction_id"],
            "evidence_prepaid_item_id": str(row["prepaid_item_id"]),
            "explanation_workpaper": (
                f"{row['transaction_id']} ({row['document_number']}, "
                f"{row['accounting_period']}) — ${amt:,.2f} JE in "
                f"{row['entity']} outside scheduled amortization. "
                f"Desc: '{row['description']}'."
            ),
            "management_summary": (
                f"A ${amt:,.2f} manual JE ({row['document_number']}) in "
                f"{row['entity']} adjusted the prepaid balance outside the "
                f"normal process. Balance impact carries forward."
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

    # ── Rule 4: Missing Original Bill ─────────────────────────
    scheduled_items = set(amortization["prepaid_item_id"].unique())
    orphan_schedules = scheduled_items - ledger_bill_items

    for item_id in sorted(orphan_schedules):
        s = amortization[amortization["prepaid_item_id"] == item_id].iloc[0]
        item_periods = sorted(
            amortization[amortization["prepaid_item_id"] == item_id]
            ["accounting_period"].unique().tolist(),
            key=period_to_date,
        )
        findings.append({
            "root_cause_id": _next_id(), "entity": s["entity"],
            "root_cause_category": "MISSING_ORIGINAL_BILL", "severity": "HIGH",
            "impacted_periods": ", ".join(item_periods),
            "estimated_impact": round(s["original_amount"], 2),
            "evidence_transactions": "None found in ledger",
            "evidence_prepaid_item_id": item_id,
            "explanation_workpaper": (
                f"Schedule {s.get('schedule_id', 'N/A')} for {item_id} "
                f"({s['vendor_name']}, ${s['original_amount']:,.2f}) in "
                f"{s['entity']} has no originating Bill. "
                f"Ref: {s['source_document']}."
            ),
            "management_summary": (
                f"${s['original_amount']:,.2f} amortization schedule for "
                f"{s['vendor_name']} in {s['entity']} has no corresponding "
                f"Bill — the original payment may be miscoded."
            ),
            "recommended_action": (
                f"1. Locate {s['source_document']} in AP.\n"
                f"2. If miscoded, recode to prepaid.\n"
                f"3. If schedule is an error, cancel it and reverse any "
                f"JEs already posted."
            ),
            "suggested_journal_entry": (
                f"If Bill was expensed incorrectly:\n"
                f"  Dr  Prepaid Expenses   ${s['original_amount']:>12,.2f}\n"
                f"  Cr  [Expense Account]  ${s['original_amount']:>12,.2f}\n"
                f"  Memo: Reclassification of {s['source_document']}"
            ),
        })

    # ── Rule 5: Missing Amortization JE (consolidated) ────────
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

    amort_comparison = pd.merge(
        sched_amort, actual_amort,
        on=["entity", "prepaid_item_id", "accounting_period"], how="left",
    )
    amort_comparison["actual_amortization"] = (
        amort_comparison["actual_amortization"].fillna(0)
    )

    missing_je = amort_comparison[
        (amort_comparison["scheduled_amortization"] > 0)
        & (amort_comparison["actual_amortization"] == 0)
    ].copy()

    missing_grouped = (
        missing_je.groupby(["entity", "prepaid_item_id"])
        .agg(
            total_impact=("scheduled_amortization", "sum"),
            all_missing_periods=(
                "accounting_period",
                lambda x: sorted(x.tolist(), key=period_to_date),
            ),
            first_missed=(
                "accounting_period",
                lambda x: sorted(x.tolist(), key=period_to_date)[0],
            ),
        )
        .reset_index()
    )

    for _, row in missing_grouped.iterrows():
        vendor = amortization.loc[
            amortization["prepaid_item_id"] == row["prepaid_item_id"],
            "vendor_name",
        ].iloc[0]
        missed_str = ", ".join(row["all_missing_periods"])
        n_periods = len(row["all_missing_periods"])
        findings.append({
            "root_cause_id": _next_id(), "entity": row["entity"],
            "root_cause_category": "MISSING_AMORTIZATION_JE", "severity": "MEDIUM",
            "impacted_periods": _periods_from(row["first_missed"], all_periods),
            "estimated_impact": round(row["total_impact"], 2),
            "evidence_transactions": "No JE found in ledger",
            "evidence_prepaid_item_id": row["prepaid_item_id"],
            "explanation_workpaper": (
                f"{row['prepaid_item_id']} ({vendor}) in {row['entity']} "
                f"required JEs in {n_periods} period(s): {missed_str}. "
                f"Total missed: ${row['total_impact']:,.2f}."
            ),
            "management_summary": (
                f"Amortization for {vendor} ({row['prepaid_item_id']}) in "
                f"{row['entity']} was not posted in {n_periods} period(s), "
                f"totalling ${row['total_impact']:,.2f} of unrecognised expense."
            ),
            "recommended_action": (
                f"Post {n_periods} catch-up amortization entries for "
                f"{row['prepaid_item_id']} covering: {missed_str}."
            ),
            "suggested_journal_entry": (
                f"Dr  {vendor} Expense    ${row['total_impact']:>12,.2f}\n"
                f"Cr  Prepaid Expenses  ${row['total_impact']:>12,.2f}\n"
                f"Memo: Catch-up amortization — {n_periods} missed "
                f"period(s): {missed_str}"
            ),
        })

    # ── Rule 6: Over / Under Amortization ─────────────────────
    over = amort_comparison[
        (amort_comparison["actual_amortization"] > 0)
        & (amort_comparison["actual_amortization"]
           > amort_comparison["scheduled_amortization"] + amort_tol)
    ].copy()

    under = amort_comparison[
        (amort_comparison["actual_amortization"] > 0)
        & (amort_comparison["actual_amortization"]
           < amort_comparison["scheduled_amortization"] - amort_tol)
    ].copy()

    for _, row in over.iterrows():
        excess = row["actual_amortization"] - row["scheduled_amortization"]
        vendor = amortization.loc[
            amortization["prepaid_item_id"] == row["prepaid_item_id"],
            "vendor_name",
        ].iloc[0]
        ev_txns = ledger.loc[
            (ledger["transaction_category"] == "AMORTIZATION_ENTRY")
            & (ledger["prepaid_item_id"] == row["prepaid_item_id"])
            & (ledger["accounting_period"] == row["accounting_period"]),
            "transaction_id",
        ].tolist()
        findings.append({
            "root_cause_id": _next_id(), "entity": row["entity"],
            "root_cause_category": "OVER_AMORTIZATION", "severity": "MEDIUM",
            "impacted_periods": _periods_from(row["accounting_period"], all_periods),
            "estimated_impact": round(excess, 2),
            "evidence_transactions": ", ".join(ev_txns),
            "evidence_prepaid_item_id": row["prepaid_item_id"],
            "explanation_workpaper": (
                f"{row['prepaid_item_id']} ({vendor}) in {row['entity']} "
                f"posted ${row['actual_amortization']:,.2f} vs scheduled "
                f"${row['scheduled_amortization']:,.2f} in "
                f"{row['accounting_period']}. Excess: ${excess:,.2f}."
            ),
            "management_summary": (
                f"{vendor} ({row['prepaid_item_id']}) in {row['entity']} was "
                f"over-amortized by ${excess:,.2f} in "
                f"{row['accounting_period']} — prepaid balance is understated."
            ),
            "recommended_action": (
                f"1. Review JEs {', '.join(ev_txns)}.\n"
                f"2. Confirm if duplicate amortization run occurred.\n"
                f"3. Reverse excess if confirmed."
            ),
            "suggested_journal_entry": (
                f"Dr  Prepaid Expenses  ${excess:>12,.2f}\n"
                f"Cr  {vendor} Expense   ${excess:>12,.2f}\n"
                f"Memo: Reversal of excess amortization — "
                f"{row['prepaid_item_id']} {row['accounting_period']}"
            ),
        })

    for _, row in under.iterrows():
        shortfall = row["scheduled_amortization"] - row["actual_amortization"]
        vendor = amortization.loc[
            amortization["prepaid_item_id"] == row["prepaid_item_id"],
            "vendor_name",
        ].iloc[0]
        ev_txns = ledger.loc[
            (ledger["transaction_category"] == "AMORTIZATION_ENTRY")
            & (ledger["prepaid_item_id"] == row["prepaid_item_id"])
            & (ledger["accounting_period"] == row["accounting_period"]),
            "transaction_id",
        ].tolist()
        findings.append({
            "root_cause_id": _next_id(), "entity": row["entity"],
            "root_cause_category": "UNDER_AMORTIZATION", "severity": "LOW",
            "impacted_periods": _periods_from(row["accounting_period"], all_periods),
            "estimated_impact": round(shortfall, 2),
            "evidence_transactions": (
                ", ".join(ev_txns) if ev_txns else "Partial JE only"
            ),
            "evidence_prepaid_item_id": row["prepaid_item_id"],
            "explanation_workpaper": (
                f"{row['prepaid_item_id']} ({vendor}) in {row['entity']} "
                f"posted ${row['actual_amortization']:,.2f} vs scheduled "
                f"${row['scheduled_amortization']:,.2f}. "
                f"Shortfall: ${shortfall:,.2f}."
            ),
            "management_summary": (
                f"{vendor} ({row['prepaid_item_id']}) in {row['entity']} was "
                f"partially amortized in {row['accounting_period']} — "
                f"${shortfall:,.2f} shortfall overstates prepaid assets."
            ),
            "recommended_action": (
                f"Post catch-up amortization of ${shortfall:,.2f} for "
                f"{row['prepaid_item_id']} in {row['entity']}."
            ),
            "suggested_journal_entry": (
                f"Dr  {vendor} Expense    ${shortfall:>12,.2f}\n"
                f"Cr  Prepaid Expenses  ${shortfall:>12,.2f}\n"
                f"Memo: Catch-up amortization shortfall — "
                f"{row['prepaid_item_id']} {row['accounting_period']}"
            ),
        })

    # ── Assemble ──────────────────────────────────────────────
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

def build_investigation_report(root_cause_report, amortization):
    """Transform technical root causes into business-friendly findings.

    Returns:
        pd.DataFrame: investigation_report with priority ranking
    """
    if root_cause_report.empty:
        return pd.DataFrame()

    ir = root_cause_report[[
        "root_cause_id", "entity", "root_cause_category", "severity",
        "impacted_periods", "estimated_impact", "evidence_transactions",
        "evidence_prepaid_item_id",
    ]].copy()

    # ── Issue title ───────────────────────────────────────────
    def _title(row):
        vl = _get_vendor_label(row["evidence_prepaid_item_id"], amortization)
        return {
            "DUPLICATE_BILL":          f"Duplicate {vl} Invoice Detected",
            "UNLINKED_ADDITION":       "Prepaid Expense Recorded Without a Schedule",
            "MISSING_ORIGINAL_BILL":   "Amortization Schedule Exists Without Original Invoice",
            "MISSING_AMORTIZATION_JE": "Required Monthly Amortization Was Not Posted",
            "OVER_AMORTIZATION":       "Expense Recognized Faster Than Scheduled",
            "UNDER_AMORTIZATION":      "Amortization Posting Was Incomplete",
            "MANUAL_ADJUSTMENT":       "Manual Adjustment Requires Review",
        }.get(row["root_cause_category"], f"Unclassified — {row['root_cause_category']}")

    # ── Why it matters ────────────────────────────────────────
    def _why(row):
        cat, impact, entity = row["root_cause_category"], row["estimated_impact"], row["entity"]
        pl = [p.strip() for p in row["impacted_periods"].split(",")]
        phrase = f"in {pl[0]}" if len(pl) == 1 else f"from {pl[0]} through {pl[-1]}"
        msgs = {
            "DUPLICATE_BILL": f"This invoice appears to have been recorded twice in {entity}. Prepaid expenses are likely overstated by approximately ${impact:,.2f} {phrase}. The error will carry forward each period until reversed.",
            "UNLINKED_ADDITION": f"A payment of ${impact:,.2f} was posted to the prepaid account in {entity} but has no amortization schedule. The expense can never be recognised — the balance will overstate assets {phrase}.",
            "MISSING_ORIGINAL_BILL": f"An amortization schedule worth ${impact:,.2f} exists in {entity} but the original invoice was never posted. The schedule may be amortizing a balance that does not exist on the books.",
            "MISSING_AMORTIZATION_JE": f"The monthly journal entry recognising prepaid expense was not posted for this item in {entity} {phrase}. ${impact:,.2f} of expense has been deferred, understating costs and overstating prepaid assets.",
            "OVER_AMORTIZATION": f"More expense was recognised than scheduled in {entity} {phrase}. The ${impact:,.2f} excess understates the prepaid balance and pulls expenses forward.",
            "UNDER_AMORTIZATION": f"The amortization JE in {entity} {phrase} was posted for less than scheduled. The ${impact:,.2f} shortfall leaves the prepaid balance higher than it should be.",
            "MANUAL_ADJUSTMENT": f"A ${impact:,.2f} manual JE was posted to prepaid in {entity} {phrase} outside the normal process. Each manual adjustment requires documented approval.",
        }
        return msgs.get(cat, f"An unclassified issue of ${impact:,.2f} in {entity} {phrase} requires investigation.")

    # ── Recommended next step ─────────────────────────────────
    def _next(row):
        cat = row["root_cause_category"]
        impact = row["estimated_impact"]
        item_id = str(row["evidence_prepaid_item_id"])
        txns = str(row["evidence_transactions"])
        txn_ref = txns if txns not in ("No JE found in ledger", "None found in ledger", "nan") else None
        ref = f"Review {txn_ref} and " if txn_ref else "Locate both postings and "
        steps = {
            "DUPLICATE_BILL": f"{ref}confirm whether two separate invoices were received. Reverse the duplicate and recover the overpayment from the vendor if applicable.",
            "UNLINKED_ADDITION": "Locate the transaction and determine whether it qualifies as a prepaid. If yes, create a schedule. If no, reclassify to the appropriate expense account.",
            "MISSING_ORIGINAL_BILL": f"Search AP records for the original invoice for {item_id}. Recode to prepaid if it was expensed directly. Cancel the schedule if it was created in error.",
            "MISSING_AMORTIZATION_JE": f"Post the missing amortization JE for {item_id}. If the period is closed, record a catch-up entry in the current period with a reference to the missed month(s).",
            "OVER_AMORTIZATION": f"{'Review ' + txn_ref + '. ' if txn_ref else ''}Compare the posted amount against the schedule for {item_id}. Reverse the excess ${impact:,.2f} if a duplicate run is confirmed.",
            "UNDER_AMORTIZATION": f"Post a catch-up amortization of ${impact:,.2f} for {item_id}. Investigate whether the partial posting was intentional or a system error.",
            "MANUAL_ADJUSTMENT": f"{'Obtain documentation for ' + txn_ref + '. ' if txn_ref else ''}Verify approval and confirm whether the amortization schedule needs updating.",
        }
        return steps.get(cat, "Investigate and document findings with supporting evidence.")

    # ── Executive summary ─────────────────────────────────────
    def _exec(row):
        cat, impact, entity = row["root_cause_category"], row["estimated_impact"], row["entity"]
        vl = _get_vendor_label(row["evidence_prepaid_item_id"], amortization)
        item_id = str(row["evidence_prepaid_item_id"])
        sums = {
            "DUPLICATE_BILL": f"A duplicate {vl} invoice in {entity} is likely causing a ${impact:,.2f} overstatement of prepaid expenses.",
            "UNLINKED_ADDITION": f"A ${impact:,.2f} prepaid payment in {entity} has no amortization schedule and will never be recognised as an expense without intervention.",
            "MISSING_ORIGINAL_BILL": f"An amortization schedule for ${impact:,.2f} in {entity} ({item_id}) has no corresponding invoice, suggesting a miscoding or setup error.",
            "MISSING_AMORTIZATION_JE": f"${impact:,.2f} of prepaid expense in {entity} ({item_id}) has not been recognised because required amortization entries were not posted.",
            "OVER_AMORTIZATION": f"The {vl} prepaid in {entity} was expensed ${impact:,.2f} faster than scheduled, understating the prepaid asset balance.",
            "UNDER_AMORTIZATION": f"The {vl} prepaid in {entity} was only partially amortized, leaving ${impact:,.2f} of expense unrecognised.",
            "MANUAL_ADJUSTMENT": f"A ${impact:,.2f} manual adjustment in {entity} changed the prepaid balance outside the normal process and requires documented justification.",
        }
        return sums.get(cat, f"An unclassified issue of ${impact:,.2f} in {entity} requires investigation.")

    # ── Priority score ────────────────────────────────────────
    sev_scores = {"HIGH": 300, "MEDIUM": 200, "LOW": 100}

    ir["issue_title"] = ir.apply(_title, axis=1)
    ir["why_it_matters"] = ir.apply(_why, axis=1)
    ir["recommended_next_step"] = ir.apply(_next, axis=1)
    ir["executive_summary"] = ir.apply(_exec, axis=1)
    ir["priority_score"] = ir.apply(
        lambda r: round(sev_scores.get(r["severity"], 0)
                        + min(r["estimated_impact"] / 1000, 99), 2),
        axis=1,
    )

    ir = ir.sort_values("priority_score", ascending=False).reset_index(drop=True)
    ir.insert(0, "priority_rank", ir.index + 1)

    return ir


# ════════════════════════════════════════════════════════════════
# MODULE 7: JOURNAL ENTRIES
# ════════════════════════════════════════════════════════════════

def generate_journal_entries(root_cause_report):
    """Extract and structure suggested corrective journal entries.

    Returns:
        pd.DataFrame with one row per suggested JE
    """
    if root_cause_report.empty:
        return pd.DataFrame()

    entries = []
    for _, row in root_cause_report.iterrows():
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
# MASTER FUNCTION: RUN_ANALYSIS
# ════════════════════════════════════════════════════════════════

def run_analysis(ledger_df, amortization_df, config=None):
    """Execute the full reconciliation workflow end to end.

    Parameters:
        ledger_df       : pd.DataFrame — raw GL ledger export
        amortization_df : pd.DataFrame — raw amortization schedule export
        config          : dict (optional) — override any DEFAULT_CONFIG key

    Returns:
        dict with all output dataframes and metadata:
            validation_info          : dict of input file stats
            ledger                   : classified ledger
            category_counts          : dict of classification counts
            flagged_transactions     : df of rows requiring review
            all_periods              : list of sorted period strings
            item_metadata            : df of prepaid item details
            waterfall_amort          : pivot of amortization amounts
            waterfall_amort_with_total : same with total row
            waterfall_balance        : pivot of expected ending balances
            expected_balance_flat    : flat table for reconciliation
            ledger_bill_items        : set of item IDs with Bills
            items_schedule_only      : set of items with no Bill
            reconciliation_summary   : full recon table
            exceptions               : filtered exception rows
            root_cause_report        : one row per root cause
            amort_comparison         : scheduled vs actual detail
            investigation_report     : business-friendly findings
            journal_entries          : structured corrective JEs
    """
    # Merge user config with defaults
    cfg = {**DEFAULT_CONFIG, **(config or {})}

    # Module 1: Validate
    ledger, amortization, validation_info = validate_inputs(
        ledger_df, amortization_df, cfg
    )

    # Module 2: Classify
    ledger, category_counts, flagged = classify_transactions(ledger, cfg)

    # Module 3: Waterfall
    wf = build_amortization_waterfall(ledger, amortization)

    # Module 4: Reconcile
    recon = reconcile_balances(
        ledger, amortization,
        wf["expected_balance_flat"], wf["all_periods"], cfg,
    )

    # Module 5: Root Cause Analysis
    rca = perform_root_cause_analysis(
        ledger, amortization,
        wf["expected_balance_flat"], recon["ledger_bill_items"],
        wf["all_periods"], cfg,
    )

    # Module 6: Investigation Report
    investigation = build_investigation_report(
        rca["root_cause_report"], amortization
    )

    # Module 7: Journal Entries
    journal_entries = generate_journal_entries(rca["root_cause_report"])

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
        # Module 4
        "ledger_bill_items": recon["ledger_bill_items"],
        "items_schedule_only": recon["items_schedule_only"],
        "reconciliation_summary": recon["reconciliation_summary"],
        "exceptions": recon["exceptions"],
        # Module 5
        "root_cause_report": rca["root_cause_report"],
        "amort_comparison": rca["amort_comparison"],
        # Module 6
        "investigation_report": investigation,
        # Module 7
        "journal_entries": journal_entries,
    }
