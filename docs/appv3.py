"""
app.py
AI Month-End Close Reconciliation Assistant — Streamlit Frontend

Executive-first dashboard: KPIs, action items, charts, then detail tabs.
Run: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from reconciliation_engine import run_analysis, period_to_date


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
# STYLES
# ════════════════════════════════════════════════════════════════

st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    hr { margin: 1.4rem 0; border-color: #eaeaea; }

    /* KPI cards */
    div[data-testid="stMetric"] {
        background: #fff; border: 1px solid #e2e6ea; border-radius: 10px;
        padding: 14px 18px; box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
    div[data-testid="stMetric"] label {
        font-size: 0.74rem !important; color: #6c757d !important;
        text-transform: uppercase; letter-spacing: 0.03em;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        font-size: 1.45rem !important; font-weight: 700 !important;
    }

    /* Section labels */
    .sh {
        font-size: 0.95rem; font-weight: 700; color: #1a1a2e;
        padding-bottom: 0.35rem; border-bottom: 2px solid #1a1a2e;
        margin-bottom: 0.8rem; margin-top: 0.3rem;
        letter-spacing: 0.02em; text-transform: uppercase;
    }

    /* Executive summary card */
    .exec-card {
        background: #f7f9fc; border: 1px solid #d6dce5;
        border-left: 4px solid #1a1a2e; border-radius: 8px;
        padding: 20px 24px; margin-bottom: 4px;
    }
    .exec-card h4 {
        margin: 0 0 12px 0; font-size: 0.92rem; font-weight: 700;
        color: #1a1a2e; text-transform: uppercase; letter-spacing: 0.03em;
    }
    .exec-card ul {
        margin: 0; padding-left: 18px; list-style: none;
    }
    .exec-card li {
        font-size: 0.84rem; color: #333; line-height: 1.75;
        position: relative; padding-left: 4px;
    }
    .exec-card li::before {
        content: "›"; position: absolute; left: -14px;
        color: #1a1a2e; font-weight: 700;
    }
    .exec-card .focus {
        margin-top: 12px; padding-top: 10px; border-top: 1px solid #dde2e8;
        font-size: 0.82rem; color: #555; line-height: 1.6;
    }
    .exec-card .focus strong { color: #1a1a2e; }

    /* Compact action cards */
    .ac {
        background: #fff; border: 1px solid #e2e6ea; border-radius: 8px;
        padding: 16px 18px; box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        margin-bottom: 10px; height: 100%;
    }
    .ac .badge {
        display: inline-block; font-size: 0.65rem; font-weight: 700;
        padding: 2px 8px; border-radius: 3px; letter-spacing: 0.04em;
        margin-bottom: 6px; text-transform: uppercase;
    }
    .badge-high   { background: #f8d7da; color: #721c24; }
    .badge-medium { background: #fff3cd; color: #856404; }
    .badge-low    { background: #d4edda; color: #155724; }
    .ac .ac-title {
        font-size: 0.88rem; font-weight: 700; color: #1a1a2e;
        margin-bottom: 4px; line-height: 1.3;
    }
    .ac .ac-meta {
        font-size: 0.75rem; color: #6c757d; margin-bottom: 8px;
    }
    .ac .ac-action {
        font-size: 0.8rem; color: #333; line-height: 1.5;
    }
</style>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════
# PLOTLY DEFAULTS
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
PL = dict(
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter, Segoe UI, sans-serif", size=12, color="#333"),
    margin=dict(l=0, r=0, t=40, b=0),
    legend=dict(orientation="h", y=-0.18, x=0.5, xanchor="center"),
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
    ledger_file = st.file_uploader("Prepaid Expense Ledger (CSV)", type=["csv"])
    amort_file = st.file_uploader("Amortization Schedule (CSV)", type=["csv"])
    st.divider()
    both = ledger_file is not None and amort_file is not None
    run = st.button("▶  Run Analysis", type="primary",
                    use_container_width=True, disabled=not both)
    if not both:
        st.info("Upload both CSV files to enable analysis.", icon="📁")
    st.divider()
    st.caption("Built by Sarim Areeb")
    st.caption("Python · Pandas · Streamlit · Plotly")


# ════════════════════════════════════════════════════════════════
# EXECUTION
# ════════════════════════════════════════════════════════════════

if "results" not in st.session_state:
    st.session_state.results = None

if run and both:
    try:
        with st.spinner("Running reconciliation analysis..."):
            st.session_state.results = run_analysis(
                pd.read_csv(ledger_file), pd.read_csv(amort_file)
            )
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
""")
    st.stop()


# ════════════════════════════════════════════════════════════════
# EXTRACT RESULTS
# ════════════════════════════════════════════════════════════════

recon      = results["reconciliation_summary"]
exceptions = results["exceptions"]
inv        = results["investigation_report"]
journal    = results["journal_entries"]
info       = results["validation_info"]

n_total      = len(recon)
n_reconciled = int((recon["status"] == "RECONCILED").sum())
n_exc        = len(exceptions)
rate         = (n_reconciled / n_total * 100) if n_total > 0 else 0.0
total_var    = recon["abs_variance"].sum()
n_findings   = len(inv)
n_high       = int((inv["severity"] == "HIGH").sum()) if not inv.empty else 0
corr_impact  = inv["estimated_impact"].sum() if not inv.empty else 0.0


# ════════════════════════════════════════════════════════════════
# 1 · EXECUTIVE DASHBOARD
# ════════════════════════════════════════════════════════════════

st.markdown('<div class="sh">Executive Dashboard</div>', unsafe_allow_html=True)

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Unreconciled Variance", f"${total_var:,.0f}")
c2.metric("Corrective Impact",     f"${corr_impact:,.0f}")
c3.metric("High-Risk Issues",      n_high)
c4.metric("Root Causes",           n_findings)
c5.metric("Exception Periods",     f"{n_exc}/{n_total}")
c6.metric("Success Rate",          f"{rate:.0f}%")

st.write("")  # 8px spacer

# ── Executive Close Summary ───────────────────────────────────
if not inv.empty:
    top = inv.loc[inv["estimated_impact"].idxmax()]
    largest_label = top["issue_title"]

    # Build concise management focus line from top 3 distinct actions
    action_verbs = []
    seen_cats = set()
    for _, r in inv.head(5).iterrows():
        cat = r["root_cause_category"]
        if cat in seen_cats:
            continue
        seen_cats.add(cat)
        short = {
            "DUPLICATE_BILL":          "Reverse duplicate invoice",
            "UNLINKED_ADDITION":       "Create schedule or reclassify unlinked prepaid",
            "MISSING_ORIGINAL_BILL":   "Locate missing original invoice",
            "MISSING_AMORTIZATION_JE": "Post missing amortization entries",
            "OVER_AMORTIZATION":       "Reverse excess amortization",
            "UNDER_AMORTIZATION":      "Post catch-up amortization",
            "MANUAL_ADJUSTMENT":       "Review manual adjustment documentation",
        }.get(cat, "Investigate")
        action_verbs.append(short)
        if len(action_verbs) == 3:
            break
    focus_text = ", ".join(action_verbs[:-1]) + f", and {action_verbs[-1]}" if len(action_verbs) > 1 else action_verbs[0] if action_verbs else "No actions required"
else:
    largest_label = "None"
    focus_text = "No corrective actions required"

entity_word = "entity" if info["entities"] == 1 else "entities"
summary_html = f"""
<div class="exec-card">
    <h4>Executive Close Summary</h4>
    <ul>
        <li><strong>{n_exc}</strong> of <strong>{n_total}</strong> entity-periods exceeded reconciliation tolerance</li>
        <li>Total unreconciled variance: <strong>${total_var:,.2f}</strong></li>
        <li>Corrective impact identified: <strong>${corr_impact:,.2f}</strong></li>
        <li>Largest issue: <strong>{largest_label}</strong></li>
        <li>{info['entities']} {entity_word} · {info['date_range_start']} through {info['date_range_end']}</li>
    </ul>
    <div class="focus"><strong>Recommended management focus:</strong> {focus_text}</div>
</div>
"""
st.markdown(summary_html, unsafe_allow_html=True)

st.divider()


# ════════════════════════════════════════════════════════════════
# 2 · MANAGEMENT ACTION SUMMARY
# ════════════════════════════════════════════════════════════════

st.markdown('<div class="sh">Management Action Summary</div>', unsafe_allow_html=True)

if inv.empty:
    st.success("No issues requiring management action.", icon="✅")
else:
    top_items = inv.head(6)

    # Short action labels per category (no long paragraphs)
    def _short_action(row):
        cat = row["root_cause_category"]
        item = str(row.get("evidence_prepaid_item_id", ""))
        txns = str(row.get("evidence_transactions", ""))
        short_actions = {
            "DUPLICATE_BILL":          f"Confirm with AP and reverse duplicate posting" + (f" ({txns})" if txns not in ("nan", "") else ""),
            "UNLINKED_ADDITION":       "Create amortization schedule or reclassify to expense",
            "MISSING_ORIGINAL_BILL":   f"Locate original invoice for {item} in AP records",
            "MISSING_AMORTIZATION_JE": f"Post catch-up amortization entries for {item}",
            "OVER_AMORTIZATION":       f"Review and reverse excess amortization on {item}",
            "UNDER_AMORTIZATION":      f"Post catch-up entry for shortfall on {item}",
            "MANUAL_ADJUSTMENT":       f"Obtain documentation and approval" + (f" for {txns}" if txns not in ("nan", "", "No JE found in ledger", "None found in ledger") else ""),
        }
        return short_actions.get(cat, "Investigate and document findings")

    rows_of_cards = [top_items.iloc[i:i+3] for i in range(0, len(top_items), 3)]

    for card_row in rows_of_cards:
        cols = st.columns(3)
        for idx, (_, item) in enumerate(card_row.iterrows()):
            sev = item["severity"]
            badge_cls = f"badge-{sev.lower()}"
            icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(sev, "⚪")
            action = _short_action(item)

            html = f"""
            <div class="ac">
                <span class="badge {badge_cls}">{icon} {sev}</span>
                <div class="ac-title">{item['issue_title']}</div>
                <div class="ac-meta">{item['entity']}  ·  ${item['estimated_impact']:,.2f}</div>
                <div class="ac-action">{action}</div>
            </div>
            """
            cols[idx].markdown(html, unsafe_allow_html=True)

st.divider()


# ════════════════════════════════════════════════════════════════
# 3 · ROOT CAUSE ANALYTICS
# ════════════════════════════════════════════════════════════════

st.markdown('<div class="sh">Root Cause Analytics</div>', unsafe_allow_html=True)

if inv.empty or n_findings == 0:
    st.info("No root cause data available for charts.", icon="ℹ️")
else:
    col_chart1, col_chart2 = st.columns(2)

    # ── Chart 1: Impact by Root Cause Category ────────────────
    with col_chart1:
        cat_df = (
            inv.groupby("root_cause_category")["estimated_impact"]
            .sum().reset_index()
            .sort_values("estimated_impact", ascending=True)
        )
        cat_df["color"] = cat_df["root_cause_category"].map(COLORS).fillna("#95a5a6")
        cat_df["label"] = cat_df["root_cause_category"].str.replace("_", " ").str.title()

        fig1 = go.Figure(go.Bar(
            x=cat_df["estimated_impact"], y=cat_df["label"],
            orientation="h", marker_color=cat_df["color"],
            text=cat_df["estimated_impact"].apply(lambda v: f"${v:,.0f}"),
            textposition="outside", textfont=dict(size=11),
        ))
        fig1.update_layout(
            **PL, title=dict(text="Financial Impact by Root Cause", font=dict(size=13)),
            xaxis=dict(title="", showgrid=True, gridcolor="#f0f0f0",
                       zeroline=False, tickprefix="$", tickformat=","),
            yaxis=dict(title=""),
            height=300, showlegend=False,
        )
        st.plotly_chart(fig1, use_container_width=True)

    # ── Chart 2: Impact by Entity ─────────────────────────────
    with col_chart2:
        ent_df = (
            inv.groupby("entity")["estimated_impact"]
            .sum().reset_index()
            .sort_values("estimated_impact", ascending=True)
        )
        fig2 = go.Figure(go.Bar(
            x=ent_df["estimated_impact"], y=ent_df["entity"],
            orientation="h", marker_color="#2980b9",
            text=ent_df["estimated_impact"].apply(lambda v: f"${v:,.0f}"),
            textposition="outside", textfont=dict(size=11),
        ))
        fig2.update_layout(
            **PL, title=dict(text="Financial Impact by Entity", font=dict(size=13)),
            xaxis=dict(title="", showgrid=True, gridcolor="#f0f0f0",
                       zeroline=False, tickprefix="$", tickformat=","),
            yaxis=dict(title=""),
            height=300, showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True)

    # ── Chart 3: Unreconciled Variance Trend ──────────────────
    trend = (
        recon.copy()
        .assign(_sort=lambda d: d["accounting_period"].apply(period_to_date))
        .groupby(["accounting_period", "_sort"])["abs_variance"]
        .sum().reset_index()
        .sort_values("_sort")
    )

    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(
        x=trend["accounting_period"], y=trend["abs_variance"],
        mode="lines+markers+text",
        line=dict(color="#1a1a2e", width=2.5),
        marker=dict(size=8, color="#1a1a2e"),
        text=trend["abs_variance"].apply(lambda v: f"${v:,.0f}"),
        textposition="top center", textfont=dict(size=10, color="#555"),
        hovertemplate="<b>%{x}</b><br>Variance: $%{y:,.2f}<extra></extra>",
    ))
    fig3.update_layout(
        **PL,
        title=dict(text="Unreconciled Variance Trend", font=dict(size=13)),
        xaxis=dict(title="", showgrid=False),
        yaxis=dict(title="", showgrid=True, gridcolor="#f0f0f0",
                   zeroline=True, zerolinecolor="#e0e0e0",
                   tickprefix="$", tickformat=","),
        height=300, showlegend=False,
    )
    st.plotly_chart(fig3, use_container_width=True)

st.divider()


# ════════════════════════════════════════════════════════════════
# 4 · DETAILED TABLES (tabs)
# ════════════════════════════════════════════════════════════════

st.markdown('<div class="sh">Detailed Analysis</div>', unsafe_allow_html=True)

tab_val, tab_rec, tab_exc, tab_inv, tab_je = st.tabs([
    "📁 Input Validation",
    "📊 Reconciliation",
    "⚠️ Exceptions",
    "🔍 Investigation Report",
    "📝 Journal Entries",
])


# ── Tab: Input Validation ─────────────────────────────────────

with tab_val:
    v1, v2, v3, v4 = st.columns(4)
    v1.metric("Ledger Rows",   f"{info['ledger_rows']:,}")
    v2.metric("Schedule Rows", f"{info['amort_rows']:,}")
    v3.metric("Entities",      info["entities"])
    v4.metric("Periods",       info["periods"])

    st.write(f"**Date range:** {info['date_range_start']} → {info['date_range_end']}  ·  "
             f"**Ledger cols:** {info['ledger_cols']}  ·  **Schedule cols:** {info['amort_cols']}")

    st.write("**Transaction classification:**")
    counts = results["category_counts"]
    st.dataframe(
        pd.DataFrame([{"Category": k, "Count": v}
                       for k, v in sorted(counts.items(), key=lambda x: -x[1])]),
        use_container_width=True, hide_index=True,
    )

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


# ── Tab: Reconciliation ──────────────────────────────────────

with tab_rec:
    def _hl_status(val):
        if val == "RECONCILED": return "background-color: #d4edda; color: #155724; font-weight: bold"
        if val == "EXCEPTION":  return "background-color: #f8d7da; color: #721c24; font-weight: bold"
        return ""

    rcols = ["entity", "accounting_period", "expected_balance",
             "actual_balance", "variance", "status"]
    st.dataframe(
        recon[rcols].style
        .format({"expected_balance": "${:,.2f}", "actual_balance": "${:,.2f}", "variance": "${:,.2f}"})
        .map(_hl_status, subset=["status"]),
        use_container_width=True, hide_index=True,
    )


# ── Tab: Exceptions ──────────────────────────────────────────

with tab_exc:
    if exceptions.empty:
        st.success("All periods reconcile cleanly.", icon="✅")
    else:
        st.warning(f"{n_exc} exception period(s) · ${total_var:,.2f} total variance", icon="⚠️")
        st.dataframe(
            exceptions[rcols].style
            .format({"expected_balance": "${:,.2f}", "actual_balance": "${:,.2f}", "variance": "${:,.2f}"})
            .map(_hl_status, subset=["status"]),
            use_container_width=True, hide_index=True,
        )


# ── Tab: Investigation Report ─────────────────────────────────

with tab_inv:
    if inv.empty:
        st.info("No root causes identified.", icon="ℹ️")
    else:
        def _hl_sev(val):
            if val == "HIGH":   return "background-color: #f8d7da; font-weight: bold; color: #721c24"
            if val == "MEDIUM": return "background-color: #fff3cd; font-weight: bold; color: #856404"
            if val == "LOW":    return "background-color: #d4edda; color: #155724"
            return ""

        st.dataframe(
            inv[["priority_rank", "issue_title", "entity", "severity",
                 "estimated_impact", "recommended_next_step"]].style
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
                st.markdown("**Why this matters**")
                st.markdown(row["why_it_matters"])
                st.markdown("**Recommended next step**")
                st.markdown(row["recommended_next_step"])
                st.markdown("**Executive summary**")
                st.markdown(row["executive_summary"])


# ── Tab: Journal Entries ──────────────────────────────────────

with tab_je:
    if journal.empty:
        st.info("No corrective journal entries to suggest.", icon="ℹ️")
    else:
        st.write(f"{len(journal)} suggested entries · "
                 f"${journal['estimated_impact'].sum():,.2f} total impact")

        def _hl_je(val):
            if val == "HIGH":   return "background-color: #f8d7da; font-weight: bold; color: #721c24"
            if val == "MEDIUM": return "background-color: #fff3cd; font-weight: bold; color: #856404"
            if val == "LOW":    return "background-color: #d4edda; color: #155724"
            return ""

        st.dataframe(
            journal[["root_cause_id", "entity", "category", "severity",
                      "estimated_impact", "evidence_prepaid_item_id"]].style
            .format({"estimated_impact": "${:,.2f}"})
            .map(_hl_je, subset=["severity"]),
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
