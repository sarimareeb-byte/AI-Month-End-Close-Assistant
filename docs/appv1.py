"""
app.py
AI Month-End Close Reconciliation Assistant — Streamlit Frontend

Connects to reconciliation_engine.py and renders results in a
clean, professional dashboard layout.

Run: streamlit run app.py
"""

import streamlit as st
import pandas as pd
from reconciliation_engine import run_analysis


# ════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="AI Month-End Close Assistant",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ════════════════════════════════════════════════════════════════
# CUSTOM CSS — minimal, professional styling
# ════════════════════════════════════════════════════════════════

st.markdown("""
<style>
    /* Tighten top padding */
    .block-container { padding-top: 2rem; }

    /* Section dividers */
    hr { margin: 2rem 0; border-color: #e0e0e0; }

    /* Metric cards */
    div[data-testid="stMetric"] {
        background: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 8px;
        padding: 12px 16px;
    }

    /* Upload area labels */
    .upload-label {
        font-size: 0.85rem;
        font-weight: 600;
        color: #495057;
        margin-bottom: 0.25rem;
    }

    /* Section headers */
    .section-header {
        font-size: 1.1rem;
        font-weight: 700;
        color: #1a1a2e;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #1a1a2e;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════
# HEADER
# ════════════════════════════════════════════════════════════════

st.title("📊 AI Month-End Close Reconciliation Assistant")
st.caption(
    "Upload a GL prepaid ledger and an amortization schedule. "
    "The tool classifies every transaction, builds waterfall schedules, "
    "reconciles expected vs actual balances, identifies root causes, "
    "and surfaces plain-English findings ranked by financial impact."
)

st.divider()


# ════════════════════════════════════════════════════════════════
# SIDEBAR — FILE UPLOADS + RUN BUTTON
# ════════════════════════════════════════════════════════════════

with st.sidebar:
    st.header("Upload Data")
    st.caption("Both files must follow the required column schema.")

    ledger_file = st.file_uploader(
        "Prepaid Expense Ledger (CSV)",
        type=["csv"],
        help="GL account detail export with transaction_id, amount, running_balance, etc.",
    )

    amort_file = st.file_uploader(
        "Amortization Schedule (CSV)",
        type=["csv"],
        help="One row per item per period with scheduled_amortization and expected_ending_balance.",
    )

    st.divider()

    # Run button — only enabled when both files are uploaded
    both_uploaded = ledger_file is not None and amort_file is not None

    run_clicked = st.button(
        "▶  Run Analysis",
        type="primary",
        use_container_width=True,
        disabled=not both_uploaded,
    )

    if not both_uploaded:
        st.info("Upload both CSV files to enable analysis.", icon="📁")

    st.divider()
    st.caption("Built by Sarim Areeb")
    st.caption("Python · Pandas · Streamlit")


# ════════════════════════════════════════════════════════════════
# ANALYSIS EXECUTION
# ════════════════════════════════════════════════════════════════

# Use session state to persist results across reruns
if "results" not in st.session_state:
    st.session_state.results = None

if run_clicked and both_uploaded:
    try:
        with st.spinner("Running reconciliation analysis..."):
            ledger_df = pd.read_csv(ledger_file)
            amort_df = pd.read_csv(amort_file)
            results = run_analysis(ledger_df, amort_df)
            st.session_state.results = results

        st.success("Analysis complete.", icon="✅")

    except ValueError as e:
        st.error(f"Validation error: {e}", icon="🚫")
        st.session_state.results = None

    except Exception as e:
        st.error(f"Unexpected error: {e}", icon="❌")
        st.session_state.results = None


# ════════════════════════════════════════════════════════════════
# RESULTS DISPLAY
# ════════════════════════════════════════════════════════════════

results = st.session_state.results

if results is None:
    # Empty state — show instructions
    st.markdown(
        """
        ### How It Works

        1. **Upload** your GL prepaid ledger and amortization schedule using the sidebar
        2. **Click** "Run Analysis" to execute the full reconciliation pipeline
        3. **Review** the results across five sections below

        The tool runs six detection rules to identify duplicate bills, missing
        journal entries, over-amortization, unlinked prepaid additions, manual
        adjustments, and orphan amortization schedules — then translates each
        finding into a plain-English investigation report with suggested
        corrective journal entries.
        """
    )
    st.stop()


# ── SECTION 1: Input Validation Summary ──────────────────────

st.markdown('<div class="section-header">Section 1 · Input Validation Summary</div>', unsafe_allow_html=True)

info = results["validation_info"]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Ledger Rows", f"{info['ledger_rows']:,}")
col2.metric("Schedule Rows", f"{info['amort_rows']:,}")
col3.metric("Entities", info["entities"])
col4.metric("Periods", info["periods"])

with st.expander("View date range and column counts"):
    st.write(f"**Date range:** {info['date_range_start']} → {info['date_range_end']}")
    st.write(f"**Ledger columns:** {info['ledger_cols']}  ·  **Schedule columns:** {info['amort_cols']}")

    # Category counts
    st.write("**Transaction classification:**")
    counts = results["category_counts"]
    count_df = pd.DataFrame(
        [{"Category": k, "Count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]
    )
    st.dataframe(count_df, use_container_width=True, hide_index=True)

    # Flagged rows
    flagged = results["flagged_transactions"]
    if not flagged.empty:
        st.write(f"**Flagged for review:** {len(flagged)} row(s)")
        st.dataframe(
            flagged[["transaction_id", "accounting_period", "entity",
                     "transaction_type", "document_number", "vendor_name",
                     "amount", "prepaid_item_id", "transaction_category"]]
            .style.format({"amount": "${:,.2f}"}),
            use_container_width=True,
            hide_index=True,
        )

st.divider()


# ── SECTION 2: Reconciliation Summary ────────────────────────

st.markdown('<div class="section-header">Section 2 · Reconciliation Summary</div>', unsafe_allow_html=True)

recon = results["reconciliation_summary"]
exceptions = results["exceptions"]

# Quick stats
r_total = len(recon)
r_clean = (recon["status"] == "RECONCILED").sum()
r_exc = len(exceptions)
r_rate = (r_clean / r_total * 100) if r_total > 0 else 0
r_var = recon["abs_variance"].sum()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Periods", r_total)
col2.metric("Reconciled", r_clean)
col3.metric("Exceptions", r_exc)
col4.metric("Total Variance", f"${r_var:,.2f}")

# Color-coded status column
def _highlight_status(val):
    if val == "RECONCILED":
        return "background-color: #d4edda; color: #155724; font-weight: bold"
    if val == "EXCEPTION":
        return "background-color: #f8d7da; color: #721c24; font-weight: bold"
    return ""

display_cols = ["entity", "accounting_period", "expected_balance",
                "actual_balance", "variance", "status"]

styled_recon = (
    recon[display_cols]
    .style
    .format({
        "expected_balance": "${:,.2f}",
        "actual_balance": "${:,.2f}",
        "variance": "${:,.2f}",
    })
    .map(_highlight_status, subset=["status"])
)

st.dataframe(styled_recon, use_container_width=True, hide_index=True)

st.divider()


# ── SECTION 3: Exceptions ────────────────────────────────────

st.markdown('<div class="section-header">Section 3 · Exceptions</div>', unsafe_allow_html=True)

if exceptions.empty:
    st.success("No exceptions found. All periods reconcile cleanly.", icon="✅")
else:
    st.warning(
        f"{len(exceptions)} period(s) require investigation. "
        f"Total unreconciled variance: ${r_var:,.2f}",
        icon="⚠️",
    )

    styled_exc = (
        exceptions[display_cols]
        .style
        .format({
            "expected_balance": "${:,.2f}",
            "actual_balance": "${:,.2f}",
            "variance": "${:,.2f}",
        })
        .map(_highlight_status, subset=["status"])
    )

    st.dataframe(styled_exc, use_container_width=True, hide_index=True)

st.divider()


# ── SECTION 4: Investigation Report ──────────────────────────

st.markdown('<div class="section-header">Section 4 · Investigation Report</div>', unsafe_allow_html=True)

investigation = results["investigation_report"]

if investigation.empty:
    st.info("No root causes identified.", icon="ℹ️")
else:
    # Summary stats
    total_issues = len(investigation)
    high_count = (investigation["severity"] == "HIGH").sum()
    total_impact = investigation["estimated_impact"].sum()

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Issues", total_issues)
    col2.metric("High Priority", high_count)
    col3.metric("Total Impact", f"${total_impact:,.2f}")

    # Severity styling
    def _highlight_severity(val):
        if val == "HIGH":
            return "background-color: #f8d7da; font-weight: bold; color: #721c24"
        if val == "MEDIUM":
            return "background-color: #fff3cd; font-weight: bold; color: #856404"
        if val == "LOW":
            return "background-color: #d4edda; color: #155724"
        return ""

    inv_display_cols = [
        "priority_rank", "issue_title", "entity", "severity",
        "estimated_impact", "recommended_next_step",
    ]

    styled_inv = (
        investigation[inv_display_cols]
        .style
        .format({"estimated_impact": "${:,.2f}"})
        .map(_highlight_severity, subset=["severity"])
    )

    st.dataframe(styled_inv, use_container_width=True, hide_index=True)

    # Expandable detail cards for each finding
    st.markdown("#### Detailed Findings")

    for _, row in investigation.iterrows():
        severity_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(row["severity"], "⚪")

        with st.expander(
            f"{severity_icon}  #{row['priority_rank']}  {row['issue_title']}  "
            f"—  {row['entity']}  ·  ${row['estimated_impact']:,.2f}"
        ):
            st.markdown(f"**Severity:** {row['severity']}  ·  "
                        f"**Impact:** ${row['estimated_impact']:,.2f}  ·  "
                        f"**Entity:** {row['entity']}")

            st.markdown(f"**Periods affected:** {row['impacted_periods']}")
            st.markdown(f"**Evidence:** {row['evidence_transactions']}")

            st.markdown("---")
            st.markdown(f"**Why this matters**")
            st.markdown(row["why_it_matters"])

            st.markdown(f"**Recommended next step**")
            st.markdown(row["recommended_next_step"])

            st.markdown(f"**Executive summary**")
            st.markdown(row["executive_summary"])

st.divider()


# ── SECTION 5: Suggested Journal Entries ─────────────────────

st.markdown('<div class="section-header">Section 5 · Suggested Journal Entries</div>', unsafe_allow_html=True)

journal = results["journal_entries"]

if journal.empty:
    st.info("No corrective journal entries to suggest.", icon="ℹ️")
else:
    # Summary
    st.write(f"{len(journal)} suggested corrective entries totalling "
             f"${journal['estimated_impact'].sum():,.2f}")

    # Display table
    je_display_cols = [
        "root_cause_id", "entity", "category", "severity",
        "estimated_impact", "evidence_prepaid_item_id",
    ]

    def _highlight_je_severity(val):
        if val == "HIGH":
            return "background-color: #f8d7da; font-weight: bold; color: #721c24"
        if val == "MEDIUM":
            return "background-color: #fff3cd; font-weight: bold; color: #856404"
        if val == "LOW":
            return "background-color: #d4edda; color: #155724"
        return ""

    styled_je = (
        journal[je_display_cols]
        .style
        .format({"estimated_impact": "${:,.2f}"})
        .map(_highlight_je_severity, subset=["severity"])
    )

    st.dataframe(styled_je, use_container_width=True, hide_index=True)

    # Expandable JE detail
    st.markdown("#### Entry Details")

    for _, row in journal.iterrows():
        with st.expander(
            f"{row['root_cause_id']}  ·  {row['category']}  ·  "
            f"{row['entity']}  ·  ${row['estimated_impact']:,.2f}"
        ):
            st.markdown(f"**Item:** {row['evidence_prepaid_item_id']}")
            st.markdown("**Suggested journal entry:**")
            st.code(row["suggested_journal_entry"], language=None)
            st.markdown("**Recommended action:**")
            st.markdown(row["recommended_action"])


# ════════════════════════════════════════════════════════════════
# FOOTER
# ════════════════════════════════════════════════════════════════

st.divider()
st.caption(
    "AI Month-End Close Reconciliation Assistant  ·  "
    "Built by Sarim Areeb  ·  "
    "Python · Pandas · Streamlit  ·  "
    "Backend: reconciliation_engine.py"
)
