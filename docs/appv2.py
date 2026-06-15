"""
app.py
AI Month-End Close Reconciliation Assistant — Streamlit Frontend

Executive-first dashboard that surfaces findings, materiality,
priority, and recommended actions before showing raw detail tables.

Run: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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
# GLOBAL STYLE
# ════════════════════════════════════════════════════════════════

st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    hr { margin: 1.5rem 0; border-color: #e0e0e0; }

    /* KPI metric cards */
    div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e2e6ea;
        border-radius: 10px;
        padding: 16px 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
    div[data-testid="stMetric"] label { font-size: 0.78rem !important; color: #6c757d !important; }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] { font-size: 1.5rem !important; }

    /* Section headers */
    .sh {
        font-size: 1.05rem; font-weight: 700; color: #1a1a2e;
        padding-bottom: 0.4rem; border-bottom: 2px solid #1a1a2e;
        margin-bottom: 0.9rem; margin-top: 0.5rem;
        letter-spacing: 0.01em;
    }

    /* Action cards */
    .action-card {
        background: #ffffff; border: 1px solid #e2e6ea;
        border-radius: 10px; padding: 20px 22px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.05);
        margin-bottom: 12px; height: 100%;
    }
    .action-card .sev-badge {
        display: inline-block; font-size: 0.7rem; font-weight: 700;
        padding: 3px 10px; border-radius: 4px; letter-spacing: 0.04em;
        margin-bottom: 8px;
    }
    .sev-high   { background: #f8d7da; color: #721c24; }
    .sev-medium { background: #fff3cd; color: #856404; }
    .sev-low    { background: #d4edda; color: #155724; }
    .action-card .ac-title { font-size: 0.95rem; font-weight: 700; color: #1a1a2e; margin-bottom: 6px; }
    .action-card .ac-meta  { font-size: 0.78rem; color: #6c757d; margin-bottom: 10px; }
    .action-card .ac-body  { font-size: 0.83rem; color: #333; line-height: 1.55; }
    .action-card .ac-evidence { font-size: 0.75rem; color: #888; margin-top: 8px; font-family: monospace; }

    /* Chart containers */
    .chart-wrap { background: #ffffff; border: 1px solid #e2e6ea; border-radius: 10px; padding: 6px; }

    /* Compact plotly */
    .stPlotlyChart { border-radius: 10px; }

    /* CFO box override */
    div[data-testid="stAlert"] p { line-height: 1.65; }
</style>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════
# PLOTLY THEME — consistent professional palette
# ════════════════════════════════════════════════════════════════

COLORS = {
    "DUPLICATE_BILL":          "#c0392b",
    "UNLINKED_ADDITION":       "#e67e22",
    "MISSING_ORIGINAL_BILL":   "#8e44ad",
    "MISSING_AMORTIZATION_JE": "#2980b9",
    "OVER_AMORTIZATION":       "#d35400",
    "UNDER_AMORTIZATION":      "#27ae60",
    "MANUAL_ADJUSTMENT":       "#7f8c8d",
}
SEVERITY_COLORS = {"HIGH": "#c0392b", "MEDIUM": "#e67e22", "LOW": "#27ae60"}
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter, Segoe UI, sans-serif", size=12, color="#333"),
    margin=dict(l=0, r=0, t=36, b=0),
    legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center"),
)


# ════════════════════════════════════════════════════════════════
# HEADER
# ════════════════════════════════════════════════════════════════

st.title("📊 AI Month-End Close Reconciliation Assistant")
st.caption(
    "Automated prepaid expense reconciliation — root cause analysis, "
    "management action items, and corrective journal entries."
)
st.divider()


# ════════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════════

with st.sidebar:
    st.header("Upload Data")
    st.caption("Both files must follow the required schema.")

    ledger_file = st.file_uploader(
        "Prepaid Expense Ledger (CSV)", type=["csv"],
        help="GL account detail with transaction_id, amount, running_balance, etc.",
    )
    amort_file = st.file_uploader(
        "Amortization Schedule (CSV)", type=["csv"],
        help="One row per item per period with scheduled_amortization.",
    )

    st.divider()
    both_uploaded = ledger_file is not None and amort_file is not None
    run_clicked = st.button("▶  Run Analysis", type="primary",
                            use_container_width=True, disabled=not both_uploaded)
    if not both_uploaded:
        st.info("Upload both CSV files to enable analysis.", icon="📁")
    st.divider()
    st.caption("Built by Sarim Areeb")
    st.caption("Python · Pandas · Streamlit · Plotly")


# ════════════════════════════════════════════════════════════════
# ANALYSIS EXECUTION
# ════════════════════════════════════════════════════════════════

if "results" not in st.session_state:
    st.session_state.results = None

if run_clicked and both_uploaded:
    try:
        with st.spinner("Running reconciliation analysis..."):
            ledger_df = pd.read_csv(ledger_file)
            amort_df = pd.read_csv(amort_file)
            st.session_state.results = run_analysis(ledger_df, amort_df)
        st.success("Analysis complete.", icon="✅")
    except ValueError as e:
        st.error(f"Validation error: {e}", icon="🚫")
        st.session_state.results = None
    except Exception as e:
        st.error(f"Unexpected error: {e}", icon="❌")
        st.session_state.results = None

results = st.session_state.results

if results is None:
    st.markdown("""
### How It Works
1. **Upload** your GL prepaid ledger and amortization schedule
2. **Click** "Run Analysis" to execute the full pipeline
3. **Review** KPIs, action items, charts, and detailed findings

The engine runs six detection rules — duplicate bills, missing JEs, over-amortization,
unlinked additions, manual adjustments, and orphan schedules — then translates each
finding into plain-English management actions with suggested corrective journal entries.
""")
    st.stop()


# ════════════════════════════════════════════════════════════════
# EXTRACT ALL RESULT OBJECTS
# ════════════════════════════════════════════════════════════════

recon     = results["reconciliation_summary"]
exceptions = results["exceptions"]
inv       = results["investigation_report"]
journal   = results["journal_entries"]
info      = results["validation_info"]

n_total      = len(recon)
n_reconciled = int((recon["status"] == "RECONCILED").sum())
n_exceptions = len(exceptions)
success_rate = (n_reconciled / n_total * 100) if n_total > 0 else 0.0
total_var    = recon["abs_variance"].sum()
n_findings   = len(inv)
n_high       = int((inv["severity"] == "HIGH").sum()) if not inv.empty else 0
n_medium     = int((inv["severity"] == "MEDIUM").sum()) if not inv.empty else 0
n_low        = int((inv["severity"] == "LOW").sum()) if not inv.empty else 0
corr_impact  = inv["estimated_impact"].sum() if not inv.empty else 0.0


# ════════════════════════════════════════════════════════════════
# 1 ·  EXECUTIVE DASHBOARD
# ════════════════════════════════════════════════════════════════

st.markdown('<div class="sh">Executive Dashboard</div>', unsafe_allow_html=True)

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Unreconciled Variance", f"${total_var:,.0f}")
c2.metric("Corrective Impact",     f"${corr_impact:,.0f}")
c3.metric("High-Risk Issues",      n_high)
c4.metric("Root Causes",           n_findings)
c5.metric("Exception Periods",     f"{n_exceptions}/{n_total}")
c6.metric("Success Rate",          f"{success_rate:.0f}%")

# ── CFO narrative ─────────────────────────────────────────────
if not inv.empty:
    top = inv.loc[inv["estimated_impact"].idxmax()]
    top_text = (f"The largest finding is **{top['issue_title']}** "
                f"in **{top['entity']}** (${top['estimated_impact']:,.2f}).")
    high_items = inv[inv["severity"] == "HIGH"]
    if not high_items.empty:
        top_cat = (high_items["root_cause_category"].value_counts()
                   .index[0].replace("_", " ").title())
        risk_text = f"Most frequent high-risk category: **{top_cat}**."
    else:
        risk_text = "No high-risk findings."
else:
    top_text = "No root cause findings generated."
    risk_text = ""

if n_exceptions == 0:
    narrative = ("All entity-period combinations reconcile within tolerance. "
                 "No corrective action is required.")
else:
    narrative = (
        f"**{n_exceptions}** of **{n_total}** entity-periods across "
        f"**{info['entities']}** entit{'y' if info['entities'] == 1 else 'ies'} "
        f"({info['date_range_start']} – {info['date_range_end']}) "
        f"exceed the reconciliation threshold. "
        f"Total unreconciled variance: **${total_var:,.2f}**. "
        f"Corrective entries, if posted, address **${corr_impact:,.2f}**. "
        f"{top_text} {risk_text}"
    )
st.info(narrative, icon="📋")
st.divider()


# ════════════════════════════════════════════════════════════════
# 2 ·  MANAGEMENT ACTION SUMMARY
# ════════════════════════════════════════════════════════════════

st.markdown('<div class="sh">Management Action Summary</div>', unsafe_allow_html=True)

if inv.empty:
    st.success("No issues requiring management action.", icon="✅")
else:
    # Show top 6 findings as styled HTML cards, 2 per row
    top_items = inv.head(6)
    rows_of_cards = [top_items.iloc[i:i+2] for i in range(0, len(top_items), 2)]

    for card_row in rows_of_cards:
        cols = st.columns(2)
        for idx, (_, item) in enumerate(card_row.iterrows()):
            sev = item["severity"]
            sev_class = f"sev-{sev.lower()}"
            icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(sev, "⚪")

            evidence = str(item.get("evidence_transactions", ""))
            ev_html = ""
            if evidence and evidence not in ("No JE found in ledger",
                                              "None found in ledger", "nan"):
                ev_html = f'<div class="ac-evidence">Evidence: {evidence}</div>'

            card_html = f"""
            <div class="action-card">
                <span class="sev-badge {sev_class}">{icon} {sev}</span>
                <div class="ac-title">#{item['priority_rank']}  {item['issue_title']}</div>
                <div class="ac-meta">{item['entity']}  ·  ${item['estimated_impact']:,.2f}</div>
                <div class="ac-body">{item['recommended_next_step']}</div>
                {ev_html}
            </div>
            """
            cols[idx].markdown(card_html, unsafe_allow_html=True)

st.divider()


# ════════════════════════════════════════════════════════════════
# 3 ·  ROOT CAUSE ANALYTICS
# ════════════════════════════════════════════════════════════════

st.markdown('<div class="sh">Root Cause Analytics</div>', unsafe_allow_html=True)

if inv.empty or n_findings == 0:
    st.info("No root cause data available for visualisation.", icon="ℹ️")
else:
    chart_col1, chart_col2 = st.columns(2)

    # ── Chart 1: Impact by root cause category ────────────────
    with chart_col1:
        cat_df = (
            inv.groupby("root_cause_category")["estimated_impact"]
            .sum().reset_index()
            .sort_values("estimated_impact", ascending=True)
        )
        cat_df["color"] = cat_df["root_cause_category"].map(COLORS).fillna("#95a5a6")
        cat_df["label"] = cat_df["root_cause_category"].str.replace("_", " ").str.title()

        fig1 = go.Figure(go.Bar(
            x=cat_df["estimated_impact"],
            y=cat_df["label"],
            orientation="h",
            marker_color=cat_df["color"],
            text=cat_df["estimated_impact"].apply(lambda v: f"${v:,.0f}"),
            textposition="outside",
            textfont=dict(size=11),
        ))
        fig1.update_layout(
            **PLOTLY_LAYOUT,
            title=dict(text="Financial Impact by Root Cause", font=dict(size=14)),
            xaxis=dict(title="", showgrid=True, gridcolor="#f0f0f0", zeroline=False,
                       tickprefix="$", tickformat=","),
            yaxis=dict(title=""),
            height=320,
            showlegend=False,
        )
        st.plotly_chart(fig1, use_container_width=True)

    # ── Chart 2: Impact by entity ─────────────────────────────
    with chart_col2:
        ent_df = (
            inv.groupby("entity")["estimated_impact"]
            .sum().reset_index()
            .sort_values("estimated_impact", ascending=True)
        )

        fig2 = go.Figure(go.Bar(
            x=ent_df["estimated_impact"],
            y=ent_df["entity"],
            orientation="h",
            marker_color="#2980b9",
            text=ent_df["estimated_impact"].apply(lambda v: f"${v:,.0f}"),
            textposition="outside",
            textfont=dict(size=11),
        ))
        fig2.update_layout(
            **PLOTLY_LAYOUT,
            title=dict(text="Financial Impact by Entity", font=dict(size=14)),
            xaxis=dict(title="", showgrid=True, gridcolor="#f0f0f0", zeroline=False,
                       tickprefix="$", tickformat=","),
            yaxis=dict(title=""),
            height=320,
            showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True)

    # ── Chart 3: Variance trend by accounting period ──────────
    from reconciliation_engine import period_to_date

    trend = recon.copy()
    trend["_sort"] = trend["accounting_period"].apply(period_to_date)
    trend = trend.sort_values(["entity", "_sort"])

    fig3 = px.bar(
        trend, x="accounting_period", y="variance", color="entity",
        barmode="group",
        text=trend["variance"].apply(lambda v: f"${v:,.0f}"),
        color_discrete_sequence=["#2980b9", "#e67e22", "#8e44ad", "#27ae60"],
    )
    fig3.update_layout(
        **PLOTLY_LAYOUT,
        title=dict(text="Variance by Accounting Period", font=dict(size=14)),
        xaxis=dict(title="", showgrid=False),
        yaxis=dict(title="Variance ($)", showgrid=True, gridcolor="#f0f0f0",
                   zeroline=True, zerolinecolor="#ccc", tickprefix="$", tickformat=","),
        height=340,
    )
    fig3.update_traces(textposition="outside", textfont_size=10)
    st.plotly_chart(fig3, use_container_width=True)

st.divider()


# ════════════════════════════════════════════════════════════════
# 4 ·  DETAILED TABLES (existing sections, pushed below)
# ════════════════════════════════════════════════════════════════

st.markdown('<div class="sh">Detailed Analysis</div>', unsafe_allow_html=True)

tab_validation, tab_recon, tab_exceptions, tab_investigation, tab_journal = st.tabs([
    "📁 Input Validation",
    "📊 Reconciliation",
    "⚠️ Exceptions",
    "🔍 Investigation Report",
    "📝 Journal Entries",
])


# ── Tab 1: Input Validation ──────────────────────────────────

with tab_validation:
    v1, v2, v3, v4 = st.columns(4)
    v1.metric("Ledger Rows", f"{info['ledger_rows']:,}")
    v2.metric("Schedule Rows", f"{info['amort_rows']:,}")
    v3.metric("Entities", info["entities"])
    v4.metric("Periods", info["periods"])

    st.write(f"**Date range:** {info['date_range_start']} → {info['date_range_end']}  ·  "
             f"**Ledger cols:** {info['ledger_cols']}  ·  **Schedule cols:** {info['amort_cols']}")

    st.write("**Transaction classification:**")
    counts = results["category_counts"]
    count_df = pd.DataFrame(
        [{"Category": k, "Count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]
    )
    st.dataframe(count_df, use_container_width=True, hide_index=True)

    flagged = results["flagged_transactions"]
    if not flagged.empty:
        st.write(f"**Flagged for review:** {len(flagged)} row(s)")
        st.dataframe(
            flagged[["transaction_id", "accounting_period", "entity",
                     "transaction_type", "document_number", "vendor_name",
                     "amount", "prepaid_item_id", "transaction_category"]]
            .style.format({"amount": "${:,.2f}"}),
            use_container_width=True, hide_index=True,
        )


# ── Tab 2: Reconciliation Summary ────────────────────────────

with tab_recon:
    def _hl_status(val):
        if val == "RECONCILED":
            return "background-color: #d4edda; color: #155724; font-weight: bold"
        if val == "EXCEPTION":
            return "background-color: #f8d7da; color: #721c24; font-weight: bold"
        return ""

    rcols = ["entity", "accounting_period", "expected_balance",
             "actual_balance", "variance", "status"]
    st.dataframe(
        recon[rcols].style
        .format({"expected_balance": "${:,.2f}", "actual_balance": "${:,.2f}", "variance": "${:,.2f}"})
        .map(_hl_status, subset=["status"]),
        use_container_width=True, hide_index=True,
    )


# ── Tab 3: Exceptions ────────────────────────────────────────

with tab_exceptions:
    if exceptions.empty:
        st.success("All periods reconcile cleanly.", icon="✅")
    else:
        st.warning(f"{n_exceptions} exception period(s) · ${total_var:,.2f} total variance", icon="⚠️")
        st.dataframe(
            exceptions[rcols].style
            .format({"expected_balance": "${:,.2f}", "actual_balance": "${:,.2f}", "variance": "${:,.2f}"})
            .map(_hl_status, subset=["status"]),
            use_container_width=True, hide_index=True,
        )


# ── Tab 4: Investigation Report ──────────────────────────────

with tab_investigation:
    if inv.empty:
        st.info("No root causes identified.", icon="ℹ️")
    else:
        def _hl_sev(val):
            if val == "HIGH":   return "background-color: #f8d7da; font-weight: bold; color: #721c24"
            if val == "MEDIUM": return "background-color: #fff3cd; font-weight: bold; color: #856404"
            if val == "LOW":    return "background-color: #d4edda; color: #155724"
            return ""

        inv_cols = ["priority_rank", "issue_title", "entity", "severity",
                    "estimated_impact", "recommended_next_step"]
        st.dataframe(
            inv[inv_cols].style
            .format({"estimated_impact": "${:,.2f}"})
            .map(_hl_sev, subset=["severity"]),
            use_container_width=True, hide_index=True,
        )

        st.markdown("#### Detailed Findings")
        for _, row in inv.iterrows():
            sev_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(row["severity"], "⚪")
            with st.expander(
                f"{sev_icon}  #{row['priority_rank']}  {row['issue_title']}  —  "
                f"{row['entity']}  ·  ${row['estimated_impact']:,.2f}"
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


# ── Tab 5: Journal Entries ────────────────────────────────────

with tab_journal:
    if journal.empty:
        st.info("No corrective journal entries to suggest.", icon="ℹ️")
    else:
        st.write(f"{len(journal)} suggested entries · ${journal['estimated_impact'].sum():,.2f} total impact")

        je_cols = ["root_cause_id", "entity", "category", "severity",
                   "estimated_impact", "evidence_prepaid_item_id"]

        def _hl_je_sev(val):
            if val == "HIGH":   return "background-color: #f8d7da; font-weight: bold; color: #721c24"
            if val == "MEDIUM": return "background-color: #fff3cd; font-weight: bold; color: #856404"
            if val == "LOW":    return "background-color: #d4edda; color: #155724"
            return ""

        st.dataframe(
            journal[je_cols].style
            .format({"estimated_impact": "${:,.2f}"})
            .map(_hl_je_sev, subset=["severity"]),
            use_container_width=True, hide_index=True,
        )

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
    "Python · Pandas · Streamlit · Plotly  ·  "
    "Backend: reconciliation_engine.py"
)
