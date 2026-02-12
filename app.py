import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta

# =========================
# Page Config + Styling
# =========================
st.set_page_config(page_title="FBA Command Center", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
.main { background-color: #f9f9fb; }
.stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
.small-note { color: #666; font-size: 0.9rem; }
</style>
""", unsafe_allow_html=True)

# =========================
# Helpers: cleaning + parsing
# =========================
def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace("\ufeff", "", regex=False)
    )
    return df

def to_number(s: pd.Series) -> pd.Series:
    # Handles $, commas, blanks, etc.
    return (
        s.astype(str)
        .str.replace("$", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.replace("—", "", regex=False)
        .str.replace("nan", "", regex=False)
        .str.strip()
        .replace("", "0")
        .pipe(pd.to_numeric, errors="coerce")
        .fillna(0)
    )

def require_columns(df: pd.DataFrame, required: list[str], label: str) -> bool:
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.error(f"❌ {label}: Missing required columns: {missing}")
        st.caption("Tip: Amazon sometimes changes headers. If your file is different, paste the header row here and we’ll adapt the mapper.")
        return False
    return True

@st.cache_data(show_spinner=False)
def load_csv(uploaded_file) -> pd.DataFrame:
    # Try common encodings safely
    try:
        df = pd.read_csv(uploaded_file)
    except UnicodeDecodeError:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file, encoding="latin-1")
    return df

# =========================
# Tab 2: Lost Money Engine
# =========================
LOSS_COLUMNS_LEDGER = {
    "lost": "lost",
    "damage": "damage",
    "dispose": "dispose",
    "unknown event": "unknown",
}

REASON_MAP = {
    "lost_warehouse": "lost",
    "lost_inbound": "lost",            # inbound issues (optional in v1 audit)
    "damaged_warehouse": "damage",
    "disposed_warehouse": "dispose",
    "found_warehouse": "found",        # usually not part of owed; included for completeness
}

def normalize_ledger_daily(df_ledger: pd.DataFrame) -> pd.DataFrame:
    df = clean_columns(df_ledger)

    # Required minimum columns
    required = ["date", "fnsku", "msku"]
    if not require_columns(df, required, "Inventory Ledger (Daily)"):
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # Ensure loss-related columns exist and are numeric
    for col in LOSS_COLUMNS_LEDGER.keys():
        if col in df.columns:
            df[col] = to_number(df[col])
        else:
            df[col] = 0

    # Standardize key fields
    if "asin" not in df.columns:
        df["asin"] = ""
    if "title" not in df.columns:
        df["title"] = ""
    if "disposition" not in df.columns:
        df["disposition"] = ""

    return df

def extract_ledger_losses(df_ledger_norm: pd.DataFrame) -> pd.DataFrame:
    if df_ledger_norm.empty:
        return df_ledger_norm

    out = []
    base_cols = ["date", "fnsku", "msku", "asin", "title", "disposition"]

    for col, event in LOSS_COLUMNS_LEDGER.items():
        tmp = df_ledger_norm.copy()
        tmp = tmp[tmp[col] != 0]
        if tmp.empty:
            continue
        tmp["event_type"] = event
        tmp["qty_lost"] = tmp[col].abs()
        out.append(tmp[base_cols + ["event_type", "qty_lost"]])

    if not out:
        return pd.DataFrame(columns=base_cols + ["event_type", "qty_lost"])

    losses = pd.concat(out, ignore_index=True)
    losses["qty_lost"] = to_number(losses["qty_lost"])
    return losses

def build_lost_money_audit(ledger_losses: pd.DataFrame, reim_norm: pd.DataFrame, min_age_days: int = 45):
    """
    Returns:
      summary_df, owed_df, evidence_df
    """
    if ledger_losses.empty:
        return (pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    # Aggregate ledger losses by FNSKU + event_type
    ledger_agg = (ledger_losses
                  .groupby(["fnsku", "msku", "asin", "title", "event_type"], as_index=False)
                  .agg(
                      qty_lost=("qty_lost", "sum"),
                      oldest_loss_date=("date", "min"),
                      newest_loss_date=("date", "max")
                  ))

    # Aggregate reimbursements by FNSKU + event_type
    if reim_norm.empty:
        reim_agg = pd.DataFrame(columns=["fnsku", "event_type", "qty_reimbursed", "amount_reimbursed"])
    else:
        reim_agg = (reim_norm
                    .groupby(["fnsku", "event_type"], as_index=False)
                    .agg(
                        qty_reimbursed=("qty_reimbursed", "sum"),
                        amount_reimbursed=("amount_total", "sum")
                    ))

    audit = ledger_agg.merge(reim_agg, on=["fnsku", "event_type"], how="left")
    audit["qty_reimbursed"] = audit["qty_reimbursed"].fillna(0)
    audit["amount_reimbursed"] = audit["amount_reimbursed"].fillna(0)

    audit["qty_owed"] = audit["qty_lost"] - audit["qty_reimbursed"]

    # Age filter (avoid false positives due to Amazon delay)
    cutoff = pd.Timestamp(datetime.now() - timedelta(days=min_age_days))
    audit["is_old_enough"] = audit["oldest_loss_date"] <= cutoff

    owed = audit[(audit["qty_owed"] > 0) & (audit["is_old_enough"])].copy()

    # Estimate $ owed (conservative):
    # If reimbursements include amount_per_unit for same fnsku/event, use avg reimbursed $/unit,
    # else leave blank (0) to avoid misleading numbers.
    if not reim_norm.empty:
        per_unit = (reim_norm[reim_norm["qty_reimbursed"] > 0]
                    .groupby(["fnsku", "event_type"], as_index=False)
                    .agg(
                        _total_amount=("amount_total", "sum"),
                        _total_qty=("qty_reimbursed", "sum"),
                    ))
        per_unit["avg_reim_per_unit"] = per_unit.apply(
            lambda r: r["_total_amount"] / r["_total_qty"] if r["_total_qty"] else 0, axis=1
        )
        per_unit = per_unit.drop(columns=["_total_amount", "_total_qty"])
        owed = owed.merge(per_unit, on=["fnsku", "event_type"], how="left")
        owed["avg_reim_per_unit"] = owed["avg_reim_per_unit"].fillna(0)
        owed["est_amount_owed"] = owed["qty_owed"] * owed["avg_reim_per_unit"]
    else:
        owed["avg_reim_per_unit"] = 0
        owed["est_amount_owed"] = 0

    # Evidence rows (ledger detail that contributes to owed cases)
    if owed.empty:
        evidence = pd.DataFrame()
    else:
        key = owed[["fnsku", "event_type"]].drop_duplicates()
        evidence = ledger_losses.merge(key, on=["fnsku", "event_type"], how="inner").sort_values(["fnsku", "date"])

    # Summary
    summary = pd.DataFrame([{
        "ledger_loss_units": float(ledger_losses["qty_lost"].sum()),
        "reimbursed_units": float(reim_norm["qty_reimbursed"].sum()) if not reim_norm.empty else 0.0,
        "owed_units_old_enough": float(owed["qty_owed"].sum()) if not owed.empty else 0.0,
        "est_amount_owed": float(owed["est_amount_owed"].sum()) if "est_amount_owed" in owed.columns else 0.0,
        "min_age_days_used": min_age_days,
    }])

    return summary, owed, evidence

def df_to_csv_download(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")

# =========================
# Sidebar
# =========================
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/a/a9/Amazon_logo.svg", width=100)
    st.title("FBA Assistant 🤖")
    st.write("Upload reports to unlock modules (US-only).")
    st.divider()
    st.info("💡 **Quick Guide**")
    st.markdown("""
**1. Inventory Health**
*File:* `FBA Inventory Health`
*Goal:* Fix fees & excess stock.

**2. Lost Money & Reimbursements**
*Files:* `Inventory Ledger (Daily)`, `Reimbursements`
*Goal:* Find warehouse losses not reimbursed.

**3. Returns Analysis**
*File:* `FBA Customer Returns`
*Goal:* Detect defect patterns.

**4. Inventory Snapshot**
*File:* `Manage FBA Inventory`
*Goal:* See where every unit sits, find ghost units.

**5. Net Profit**
*File:* `Settlement Flat File V2`
*Goal:* True pocket profit after all fees.

**6. Business & Traffic**
*File:* `Detail Page Sales and Traffic`
*Goal:* Conversion rates, Buy Box problems.

**7. Removal Orders**
*File:* `Removal Order Detail`
*Goal:* Track removals, disposals, stuck orders.

**8. Restocking**
*File:* `FBA Inventory Health`
*Goal:* Reorder points, stockout dates, velocity trends.
""")
    st.divider()
    st.caption("v3.1 - Restocking Intelligence")

# =========================
# Main UI Tabs
# =========================
st.title("🚀 Amazon FBA Command Center (US)")

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "📦 Inventory Health",
    "💸 Lost Money & Reimbursements",
    "↩️ Returns Analysis",
    "📊 Inventory Snapshot",
    "💰 Net Profit",
    "🔍 Business & Traffic",
    "🚚 Removal Orders",
    "🔄 Restocking",
])

# ==========================================
# TAB 1: INVENTORY HEALTH
# ==========================================
with tab1:
    st.header("Inventory Health & Storage Fees")
    uploaded_inv = st.file_uploader("Upload 'FBA Inventory Health' CSV", type=["csv"], key="inv_upload")

    if uploaded_inv:
        df = clean_columns(load_csv(uploaded_inv))

        # Numeric columns (if present)
        numeric_cols = [
            "estimated-excess-quantity",
            "your-price",
            "estimated-storage-cost-next-month",
            "inv-age-365-plus-days"
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = to_number(df[col])
            else:
                df[col] = 0

        # Safe compute
        excess_val = (df["estimated-excess-quantity"] * df["your-price"]).sum()
        storage_cost = df["estimated-storage-cost-next-month"].sum()
        aged_units = df["inv-age-365-plus-days"].sum()

        c1, c2, c3 = st.columns(3)
        c1.metric("Trapped Capital (Excess)", f"${excess_val:,.2f}", delta="Needs Liquidation", delta_color="inverse")
        c2.metric("Next Month Storage Fees", f"${storage_cost:,.2f}", delta="- Minimize This", delta_color="inverse")
        c3.metric("Aged Units (365+ Days)", f"{int(aged_units)}", delta="LTSF Risk", delta_color="inverse")

        st.subheader("Where is your money stuck?")
        if "sku" in df.columns:
            df["excess_val"] = df["estimated-excess-quantity"] * df["your-price"]
            top_excess = df.sort_values(by="excess_val", ascending=False).head(10)
            fig = px.bar(top_excess, x="excess_val", y="sku", orientation="h",
                         title="Top 10 SKUs by Excess Value", color="excess_val")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No SKU column detected in this file export.")

        st.subheader("📋 Recommended Actions")
        cols_needed = ["sku", "product-name", "recommended-action", "estimated-storage-cost-next-month"]
        existing = [c for c in cols_needed if c in df.columns]
        if len(existing) >= 2:
            st.dataframe(df[existing], use_container_width=True)
        else:
            st.info("This export doesn’t include 'recommended-action' fields. Different Inventory Health export versions vary.")
    else:
        st.info("👋 Upload your **FBA Inventory Health** file to see this data.")

# ==========================================
# TAB 2: LOST MONEY & REIMBURSEMENTS (FULL)
# ==========================================
with tab2:
    st.header("Lost Inventory & Reimbursements (Warehouse Audit)")
    st.markdown("This compares **Inventory Ledger losses** vs **Reimbursements paid** to find **units likely still owed**.")

    cA, cB, cC = st.columns([1, 1, 1])
    ledger_upload = cA.file_uploader("1) Upload 'Inventory Ledger' (Daily) CSV", type=["csv"], key="ledger_upload")
    reimb_upload = cB.file_uploader("2) Upload 'Reimbursements' CSV", type=["csv"], key="reimb_upload")
    min_age_days = cC.number_input(
        "Delay window (days)",
        min_value=0, max_value=180, value=45, step=5,
        help="Amazon often reimburses with a delay. We avoid flagging recent losses."
    )

    # --- Local override: FIXED reimbursement normalizer (prevents ValueError) ---
    def normalize_reimbursements_fixed(df_reim: pd.DataFrame) -> pd.DataFrame:
        df = clean_columns(df_reim)

        required = ["approval-date", "reason"]
        if not require_columns(df, required, "Reimbursements Report"):
            return pd.DataFrame()

        # Ensure common columns exist (Amazon exports vary)
        for col in [
            "fnsku", "sku", "asin", "product-name", "reimbursement-id", "case-id",
            "amazon-order-id", "condition", "currency-unit", "amount-total", "amount-per-unit"
        ]:
            if col not in df.columns:
                df[col] = ""

        df["approval-date"] = pd.to_datetime(df["approval-date"], errors="coerce")

        # Map reason -> event_type for our audit (lost/damage/dispose)
        df["reason_norm"] = df["reason"].astype(str).str.strip().str.lower()
        df["event_type"] = df["reason_norm"].map(REASON_MAP)

        # Quantity reimbursed: sum any columns that start with "quantity-reimbursed"
        qty_cols = [c for c in df.columns if c.startswith("quantity-reimbursed")]

        if qty_cols:
            # Convert each qty column to numeric safely, then sum across columns per row
            qty_df = df[qty_cols].apply(lambda col: to_number(col))
            df["qty_reimbursed"] = qty_df.sum(axis=1)
        else:
            df["qty_reimbursed"] = 0

        # Amount fields
        df["amount_total"] = to_number(df["amount-total"]) if "amount-total" in df.columns else 0
        df["amount_per_unit"] = to_number(df["amount-per-unit"]) if "amount-per-unit" in df.columns else 0

        # Keep only reimbursable warehouse loss types (this tab)
        audited = df[df["event_type"].isin(["lost", "damage", "dispose"])].copy()
        audited = audited[audited["qty_reimbursed"] != 0]

        return audited

    if ledger_upload and reimb_upload:
        with st.spinner("Loading and auditing..."):
            df_ledger_raw = load_csv(ledger_upload)
            df_reim_raw = load_csv(reimb_upload)

            df_ledger = normalize_ledger_daily(df_ledger_raw)

            # Use the FIXED normalizer here
            df_reim = normalize_reimbursements_fixed(df_reim_raw)

            ledger_losses = extract_ledger_losses(df_ledger)

            summary, owed, evidence = build_lost_money_audit(
                ledger_losses=ledger_losses,
                reim_norm=df_reim,
                min_age_days=int(min_age_days)
            )

        if df_ledger.empty:
            st.error("Ledger failed validation — check that you uploaded the Daily Inventory Ledger export.")
        elif ledger_losses.empty:
            st.warning("Ledger loaded but no loss-related rows were found (lost/damage/dispose/unknown).")
        else:
            st.success("✅ Audit complete.")

            # KPIs
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Ledger Loss Units", f"{summary.loc[0,'ledger_loss_units']:.0f}")
            k2.metric("Reimbursed Units", f"{summary.loc[0,'reimbursed_units']:.0f}")
            k3.metric("Units Likely Owed", f"{summary.loc[0,'owed_units_old_enough']:.0f}")
            k4.metric("Est. $ Owed (conservative)", f"${summary.loc[0,'est_amount_owed']:,.2f}")

            st.caption(
                f"Using delay window: {int(min_age_days)} days. "
                "Est. $ uses average reimbursed $/unit when available; otherwise stays $0 to avoid misleading numbers."
            )

            st.divider()

            # Charts
            st.subheader("Losses by Type (Ledger)")
            loss_by_type = (
                ledger_losses.groupby("event_type", as_index=False)["qty_lost"]
                .sum()
                .sort_values("qty_lost", ascending=False)
            )
            fig1 = px.bar(loss_by_type, x="event_type", y="qty_lost", title="Ledger Loss Units by Event Type")
            st.plotly_chart(fig1, use_container_width=True)

            if not owed.empty:
                st.subheader("🚨 Likely Owed by Amazon (Old Enough)")
                owed_view = owed.copy().sort_values(["est_amount_owed", "qty_owed"], ascending=False)

                show_cols = [
                    "fnsku", "msku", "asin", "event_type",
                    "qty_lost", "qty_reimbursed", "qty_owed",
                    "avg_reim_per_unit", "est_amount_owed",
                    "oldest_loss_date", "newest_loss_date",
                    "title"
                ]
                show_cols = [c for c in show_cols if c in owed_view.columns]

                st.dataframe(owed_view[show_cols], use_container_width=True, height=420)

                d1, d2 = st.columns(2)
                d1.download_button(
                    "⬇️ Download Likely Owed (CSV)",
                    data=df_to_csv_download(owed_view),
                    file_name="likely_owed_reimbursements.csv",
                    mime="text/csv"
                )

                if not evidence.empty:
                    d2.download_button(
                        "⬇️ Download Evidence Rows (CSV)",
                        data=df_to_csv_download(evidence),
                        file_name="ledger_evidence_rows.csv",
                        mime="text/csv"
                    )

                st.subheader("Evidence Preview (Ledger rows behind owed cases)")
                st.dataframe(evidence.head(200), use_container_width=True)
            else:
                st.info("No owed cases found (after applying delay window + netting vs reimbursements).")

            with st.expander("🔎 Debug: normalized previews"):
                st.write("Ledger (normalized) preview")
                st.dataframe(df_ledger.head(25), use_container_width=True)
                st.write("Ledger losses extracted preview")
                st.dataframe(ledger_losses.head(25), use_container_width=True)
                st.write("Reimbursements (audited subset) preview")
                st.dataframe(df_reim.head(25), use_container_width=True)

    else:
        st.info("Upload both **Inventory Ledger (Daily)** and **Reimbursements** to run the audit.")

# ==========================================
# TAB 3: RETURNS ANALYSIS (starter)
# ==========================================
with tab3:
    st.header("Voice of the Customer (Returns)")
    returns_file = st.file_uploader("Upload 'FBA Customer Returns' Report (CSV)", type=["csv"], key="returns_upload")

    if returns_file:
        df = clean_columns(load_csv(returns_file))
        st.success("Returns file loaded.")

        # Try to find comment + reason columns
        comment_col = "customer-comments" if "customer-comments" in df.columns else None
        reason_col = "return-reason" if "return-reason" in df.columns else None

        if reason_col:
            st.subheader("Top Return Reasons")
            top_reasons = df[reason_col].astype(str).value_counts().head(15).reset_index()
            top_reasons.columns = ["return_reason", "count"]
            fig = px.bar(top_reasons, x="count", y="return_reason", orientation="h", title="Top Return Reasons")
            st.plotly_chart(fig, use_container_width=True)

        if comment_col:
            st.subheader("Defect Keyword Scan (basic)")
            keywords = ["broken", "stopped", "won't", "doesn't", "leak", "missing", "defect", "dead", "bad", "failed"]
            comments = df[comment_col].astype(str).str.lower()
            hits = {k: int(comments.str.contains(k, na=False).sum()) for k in keywords}
            hit_df = pd.DataFrame({"keyword": list(hits.keys()), "mentions": list(hits.values())}).sort_values("mentions", ascending=False)
            fig2 = px.bar(hit_df, x="mentions", y="keyword", orientation="h", title="Customer Comment Keyword Mentions")
            st.plotly_chart(fig2, use_container_width=True)

        st.subheader("Preview")
        st.dataframe(df.head(50), use_container_width=True)

    else:
        st.info("Upload returns file to detect defects and trends.")

# ==========================================
# TAB 4: INVENTORY SNAPSHOT (Manage FBA Inventory)
# ==========================================
with tab4:
    st.header("Inventory Snapshot (Manage FBA Inventory)")
    st.markdown("Upload your **Manage FBA Inventory** report to see where every unit sits right now.")

    inv_snap_file = st.file_uploader("Upload 'Manage FBA Inventory' CSV/TXT", type=["csv", "txt"], key="inv_snap_upload")

    if inv_snap_file:
        df = clean_columns(load_csv(inv_snap_file))

        qty_cols = [
            "afn-fulfillable-quantity", "afn-unsellable-quantity",
            "afn-reserved-quantity", "afn-total-quantity",
            "afn-inbound-working-quantity", "afn-inbound-shipped-quantity",
            "afn-inbound-receiving-quantity", "afn-researching-quantity",
            "your-price",
        ]
        for col in qty_cols:
            if col in df.columns:
                df[col] = to_number(df[col])
            else:
                df[col] = 0

        total_fulfillable = df["afn-fulfillable-quantity"].sum()
        total_unsellable = df["afn-unsellable-quantity"].sum()
        total_reserved = df["afn-reserved-quantity"].sum()
        total_warehouse = df["afn-total-quantity"].sum()
        total_researching = df["afn-researching-quantity"].sum()
        inbound_pipeline = (
            df["afn-inbound-working-quantity"].sum()
            + df["afn-inbound-shipped-quantity"].sum()
            + df["afn-inbound-receiving-quantity"].sum()
        )

        # KPIs
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Fulfillable Units", f"{int(total_fulfillable):,}")
        k2.metric("Reserved Units", f"{int(total_reserved):,}")
        k3.metric("Unsellable Units", f"{int(total_unsellable):,}", delta="Needs Removal", delta_color="inverse")
        k4.metric("Inbound Pipeline", f"{int(inbound_pipeline):,}")

        k5, k6 = st.columns(2)
        k5.metric("Total Warehouse Units", f"{int(total_warehouse):,}")
        if total_researching > 0:
            k6.metric("Under Research (Ghost Units)", f"{int(total_researching):,}", delta="Potential Reimbursement", delta_color="inverse")
        else:
            k6.metric("Under Research", "0")

        st.divider()

        # Inventory breakdown chart
        st.subheader("Inventory State Breakdown")
        state_data = pd.DataFrame({
            "State": ["Fulfillable", "Reserved", "Unsellable", "Researching"],
            "Units": [total_fulfillable, total_reserved, total_unsellable, total_researching],
        })
        state_data = state_data[state_data["Units"] > 0]
        if not state_data.empty:
            fig_pie = px.pie(state_data, names="State", values="Units", title="Warehouse Inventory by State")
            st.plotly_chart(fig_pie, use_container_width=True)

        # Inbound pipeline breakdown
        st.subheader("Inbound Pipeline")
        inbound_data = pd.DataFrame({
            "Stage": ["Working (Prep)", "Shipped (In Transit)", "Receiving (At FC)"],
            "Units": [
                df["afn-inbound-working-quantity"].sum(),
                df["afn-inbound-shipped-quantity"].sum(),
                df["afn-inbound-receiving-quantity"].sum(),
            ],
        })
        fig_inbound = px.bar(inbound_data, x="Units", y="Stage", orientation="h", title="Inbound Shipment Pipeline")
        st.plotly_chart(fig_inbound, use_container_width=True)

        # Top SKUs by total inventory value
        if "sku" in df.columns:
            df["inv_value"] = df["afn-total-quantity"] * df["your-price"]
            top_inv = df.sort_values("inv_value", ascending=False).head(15)
            st.subheader("Top 15 SKUs by Estimated Inventory Value")
            fig_top = px.bar(top_inv, x="inv_value", y="sku", orientation="h",
                             title="Inventory Value ($)", color="inv_value")
            st.plotly_chart(fig_top, use_container_width=True)

        # Unsellable items needing removal
        unsellable = df[df["afn-unsellable-quantity"] > 0].copy()
        if not unsellable.empty:
            st.subheader("Unsellable Inventory (Removal Candidates)")
            show = ["sku", "fnsku", "asin", "product-name", "afn-unsellable-quantity", "your-price"]
            show = [c for c in show if c in unsellable.columns]
            unsellable = unsellable.sort_values("afn-unsellable-quantity", ascending=False)
            st.dataframe(unsellable[show], use_container_width=True)
            st.download_button(
                "⬇️ Download Unsellable Items (CSV)",
                data=df_to_csv_download(unsellable[show]),
                file_name="unsellable_inventory.csv",
                mime="text/csv",
            )

        # Ghost units under research
        researching = df[df["afn-researching-quantity"] > 0].copy()
        if not researching.empty:
            st.subheader("Ghost Units (Under Research)")
            st.caption("These units are under investigation by Amazon. If unresolved, they may qualify for reimbursement.")
            show_r = ["sku", "fnsku", "asin", "product-name", "afn-researching-quantity"]
            show_r = [c for c in show_r if c in researching.columns]
            st.dataframe(researching[show_r], use_container_width=True)

        with st.expander("Full Inventory Data"):
            st.dataframe(df.head(100), use_container_width=True)

    else:
        st.info("Upload your **Manage FBA Inventory** report to see inventory breakdown by state, inbound pipeline, and ghost units.")

# ==========================================
# TAB 5: NET PROFIT (Settlement Flat File V2)
# ==========================================
with tab5:
    st.header("Net Profit Calculator (Settlement V2)")
    st.markdown("Upload your **Settlement Flat File V2** to see exactly where every dollar went.")

    settle_file = st.file_uploader("Upload 'Settlement Flat File V2' CSV/TXT", type=["csv", "txt"], key="settle_upload")

    if settle_file:
        df = clean_columns(load_csv(settle_file))

        # Settlement V2 uses: amount-type, amount-description, amount
        needed = ["amount-type", "amount-description", "amount"]
        has_core = all(c in df.columns for c in needed)

        if not has_core:
            st.error(f"Missing required columns. Expected: {needed}. Found: {list(df.columns[:15])}")
        else:
            df["amount"] = to_number(df["amount"])

            if "posted-date-time" in df.columns:
                df["posted-date-time"] = pd.to_datetime(df["posted-date-time"], errors="coerce")
            elif "posted-date" in df.columns:
                df["posted-date-time"] = pd.to_datetime(df["posted-date"], errors="coerce")

            if "transaction-type" not in df.columns:
                df["transaction-type"] = ""
            if "sku" not in df.columns:
                df["sku"] = ""
            if "quantity-purchased" not in df.columns:
                df["quantity-purchased"] = 0
            else:
                df["quantity-purchased"] = to_number(df["quantity-purchased"])

            # --- Aggregate by amount-type ---
            by_type = df.groupby("amount-type", as_index=False)["amount"].sum().sort_values("amount")

            product_sales = df[df["amount-description"].str.lower().str.strip() == "principal"]["amount"].sum()
            total_fees = df[df["amount-type"].str.lower().str.strip() == "itemfees"]["amount"].sum()
            total_promos = df[df["amount-type"].str.lower().str.strip() == "promotion"]["amount"].sum()
            refund_rows = df[df["transaction-type"].str.lower().str.strip() == "refund"]
            total_refunds = refund_rows["amount"].sum()
            net_proceeds = df["amount"].sum()

            # KPIs
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Product Sales (Principal)", f"${product_sales:,.2f}")
            k2.metric("Amazon Fees", f"${total_fees:,.2f}", delta="Cost", delta_color="inverse")
            k3.metric("Refunds", f"${total_refunds:,.2f}", delta="Cost", delta_color="inverse")
            k4.metric("Net Proceeds", f"${net_proceeds:,.2f}",
                       delta=f"{(net_proceeds / product_sales * 100):.1f}% margin" if product_sales else "N/A")

            k5, k6 = st.columns(2)
            k5.metric("Promotions / Discounts", f"${total_promos:,.2f}")
            units_sold = df[
                (df["transaction-type"].str.lower().str.strip() == "order")
                & (df["amount-description"].str.lower().str.strip() == "principal")
            ]["quantity-purchased"].sum()
            k6.metric("Units Sold", f"{int(units_sold):,}")

            st.divider()

            # Fee breakdown chart
            st.subheader("Where Does Your Money Go?")
            by_desc = (
                df.groupby("amount-description", as_index=False)["amount"]
                .sum()
                .sort_values("amount")
            )
            # Show top expense categories (negative amounts = costs)
            expenses = by_desc[by_desc["amount"] < 0].copy()
            expenses["amount_abs"] = expenses["amount"].abs()
            expenses = expenses.sort_values("amount_abs", ascending=False).head(12)
            if not expenses.empty:
                fig_fees = px.bar(expenses, x="amount_abs", y="amount-description", orientation="h",
                                  title="Top Fee Categories (Absolute $)", color="amount_abs")
                st.plotly_chart(fig_fees, use_container_width=True)

            # Amount-type breakdown (pie)
            by_type_abs = by_type.copy()
            by_type_abs["amount_abs"] = by_type_abs["amount"].abs()
            by_type_abs = by_type_abs[by_type_abs["amount_abs"] > 0]
            if not by_type_abs.empty:
                fig_pie = px.pie(by_type_abs, names="amount-type", values="amount_abs",
                                 title="Settlement Breakdown by Amount Type")
                st.plotly_chart(fig_pie, use_container_width=True)

            # Daily revenue trend
            if "posted-date-time" in df.columns and df["posted-date-time"].notna().any():
                st.subheader("Daily Net Revenue Trend")
                daily = (
                    df.dropna(subset=["posted-date-time"])
                    .assign(date=lambda x: x["posted-date-time"].dt.date)
                    .groupby("date", as_index=False)["amount"]
                    .sum()
                    .sort_values("date")
                )
                if len(daily) > 1:
                    fig_trend = px.line(daily, x="date", y="amount", title="Daily Net Amount")
                    st.plotly_chart(fig_trend, use_container_width=True)

            # Per-SKU profitability
            if df["sku"].astype(str).str.strip().replace("", pd.NA).notna().any():
                st.subheader("Per-SKU Profitability")
                sku_profit = (
                    df[df["sku"].astype(str).str.strip() != ""]
                    .groupby("sku", as_index=False)
                    .agg(
                        revenue=("amount", lambda x: x[df.loc[x.index, "amount-description"].str.lower().str.strip() == "principal"].sum()),
                        total_amount=("amount", "sum"),
                        units=("quantity-purchased", "sum"),
                    )
                )
                sku_profit["fees_and_other"] = sku_profit["total_amount"] - sku_profit["revenue"]
                sku_profit["margin_%"] = (sku_profit["total_amount"] / sku_profit["revenue"] * 100).where(sku_profit["revenue"] != 0, 0).round(1)
                sku_profit = sku_profit.sort_values("total_amount", ascending=False)
                st.dataframe(sku_profit.head(50), use_container_width=True)

                st.download_button(
                    "⬇️ Download Per-SKU Profitability (CSV)",
                    data=df_to_csv_download(sku_profit),
                    file_name="sku_profitability.csv",
                    mime="text/csv",
                )

            with st.expander("Raw Settlement Data Preview"):
                st.dataframe(df.head(100), use_container_width=True)

    else:
        st.info("Upload your **Settlement Flat File V2** to see product sales, fees, refunds, and net proceeds broken down by SKU.")

# ==========================================
# TAB 6: BUSINESS & TRAFFIC ANALYTICS
# ==========================================
with tab6:
    st.header("Business & Traffic Analytics")
    st.markdown("Upload your **Detail Page Sales and Traffic by Child Item** report to find conversion and Buy Box problems.")

    biz_file = st.file_uploader("Upload 'Business Report' CSV (Detail Page Sales & Traffic)", type=["csv"], key="biz_upload")

    if biz_file:
        df = clean_columns(load_csv(biz_file))

        # Business report columns use mixed case with spaces; after clean_columns they're lowercase
        # Map common variations to standardized names
        col_map = {}
        for c in df.columns:
            if "child" in c and "asin" in c:
                col_map[c] = "child_asin"
            elif "parent" in c and "asin" in c:
                col_map[c] = "parent_asin"
            elif c == "sessions - total" or c == "sessions":
                col_map[c] = "sessions"
            elif c == "page views - total" or c == "page views":
                col_map[c] = "page_views"
            elif c == "buy box percentage" or c == "buy box percentage - b2b":
                if "buy_box_pct" not in col_map.values():
                    col_map[c] = "buy_box_pct"
            elif c == "unit session percentage" or c == "unit session percentage - total":
                col_map[c] = "conversion_rate"
            elif c == "units ordered" or c == "units ordered - total":
                if "units_ordered" not in col_map.values():
                    col_map[c] = "units_ordered"
            elif c == "ordered product sales" or c == "ordered product sales - total":
                if "ordered_sales" not in col_map.values():
                    col_map[c] = "ordered_sales"
        df = df.rename(columns=col_map)

        # Also handle SKU and title
        if "title" not in df.columns:
            df["title"] = ""
        if "sku" not in df.columns:
            df["sku"] = ""

        for nc in ["sessions", "page_views", "units_ordered"]:
            if nc in df.columns:
                df[nc] = to_number(df[nc])
            else:
                df[nc] = 0

        if "ordered_sales" in df.columns:
            df["ordered_sales"] = to_number(df["ordered_sales"])
        else:
            df["ordered_sales"] = 0

        # Percentages come as "12.34%" or "12.34" — normalize
        for pct_col in ["buy_box_pct", "conversion_rate"]:
            if pct_col in df.columns:
                df[pct_col] = (
                    df[pct_col].astype(str)
                    .str.replace("%", "", regex=False)
                    .str.replace(",", "", regex=False)
                    .str.strip()
                    .replace("", "0")
                    .pipe(pd.to_numeric, errors="coerce")
                    .fillna(0)
                )
            else:
                df[pct_col] = 0

        total_sessions = df["sessions"].sum()
        total_units = df["units_ordered"].sum()
        total_sales = df["ordered_sales"].sum()
        avg_conversion = (total_units / total_sessions * 100) if total_sessions else 0
        avg_buybox = df.loc[df["sessions"] > 0, "buy_box_pct"].mean() if (df["sessions"] > 0).any() else 0

        # KPIs
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Sessions", f"{int(total_sessions):,}")
        k2.metric("Units Ordered", f"{int(total_units):,}")
        k3.metric("Overall Conversion Rate", f"{avg_conversion:.2f}%")
        k4.metric("Avg Buy Box %", f"{avg_buybox:.1f}%",
                   delta="Low" if avg_buybox < 80 else "Good", delta_color="inverse" if avg_buybox < 80 else "normal")

        st.metric("Ordered Product Sales", f"${total_sales:,.2f}")

        st.divider()

        # Top ASINs by sessions
        asin_col = "child_asin" if "child_asin" in df.columns else "sku"
        st.subheader("Top ASINs by Sessions")
        top_sessions = df.sort_values("sessions", ascending=False).head(15)
        fig_sess = px.bar(top_sessions, x="sessions", y=asin_col, orientation="h",
                          title="Top 15 Products by Sessions", color="sessions")
        st.plotly_chart(fig_sess, use_container_width=True)

        # Conversion rate distribution
        has_traffic = df[df["sessions"] >= 10].copy()
        if not has_traffic.empty:
            st.subheader("Conversion Rate Distribution (Products with 10+ Sessions)")
            fig_conv = px.histogram(has_traffic, x="conversion_rate", nbins=20,
                                    title="Conversion Rate Distribution (%)")
            st.plotly_chart(fig_conv, use_container_width=True)

        # Low-conversion high-traffic opportunities
        st.subheader("Listing Optimization Opportunities")
        st.caption("High traffic + low conversion = listing needs work (images, copy, price, reviews).")
        if not has_traffic.empty:
            opportunities = has_traffic.sort_values("conversion_rate", ascending=True).head(15)
            show_opp = [asin_col, "title", "sessions", "units_ordered", "conversion_rate", "buy_box_pct", "ordered_sales"]
            show_opp = [c for c in show_opp if c in opportunities.columns]
            st.dataframe(opportunities[show_opp], use_container_width=True)

        # Buy Box losers
        bb_problems = df[(df["sessions"] >= 10) & (df["buy_box_pct"] < 80)].copy()
        if not bb_problems.empty:
            st.subheader("Buy Box Problems (< 80%)")
            st.caption("Losing the Buy Box means losing sales even with traffic. Check pricing, seller metrics, or FBA enrollment.")
            bb_problems = bb_problems.sort_values("buy_box_pct", ascending=True)
            show_bb = [asin_col, "title", "sessions", "buy_box_pct", "units_ordered", "ordered_sales"]
            show_bb = [c for c in show_bb if c in bb_problems.columns]
            st.dataframe(bb_problems[show_bb].head(20), use_container_width=True)
        else:
            st.success("No Buy Box issues detected (all products with traffic are above 80%).")

        # Revenue vs conversion scatter
        if not has_traffic.empty and len(has_traffic) >= 3:
            st.subheader("Sessions vs Conversion (Bubble = Revenue)")
            fig_scatter = px.scatter(
                has_traffic, x="sessions", y="conversion_rate",
                size="ordered_sales", hover_name=asin_col,
                title="Traffic vs Conversion (bubble size = revenue)",
                labels={"sessions": "Sessions", "conversion_rate": "Conversion Rate (%)"},
            )
            st.plotly_chart(fig_scatter, use_container_width=True)

        with st.expander("Full Business Report Data"):
            st.dataframe(df.head(100), use_container_width=True)

    else:
        st.info("Upload your **Detail Page Sales and Traffic** report to analyze conversion rates, Buy Box ownership, and find listing optimization opportunities.")

# ==========================================
# TAB 7: REMOVAL ORDERS
# ==========================================
with tab7:
    st.header("Removal Order Tracking")
    st.markdown("Upload your **Removal Order Detail** report to track removals, disposals, and associated costs.")

    removal_file = st.file_uploader("Upload 'Removal Order Detail' CSV/TXT", type=["csv", "txt"], key="removal_upload")

    if removal_file:
        df = clean_columns(load_csv(removal_file))

        qty_fields = [
            "requested-quantity", "cancelled-quantity", "disposed-quantity",
            "shipped-quantity", "in-process-quantity",
        ]
        for col in qty_fields:
            if col in df.columns:
                df[col] = to_number(df[col])
            else:
                df[col] = 0

        if "removal-fee" in df.columns:
            df["removal-fee"] = to_number(df["removal-fee"])
        else:
            df["removal-fee"] = 0

        if "request-date" in df.columns:
            df["request-date"] = pd.to_datetime(df["request-date"], errors="coerce")
        if "order-type" not in df.columns:
            df["order-type"] = "Unknown"
        if "order-status" not in df.columns:
            df["order-status"] = ""
        if "disposition" not in df.columns:
            df["disposition"] = ""
        if "sku" not in df.columns:
            df["sku"] = ""

        total_requested = df["requested-quantity"].sum()
        total_shipped = df["shipped-quantity"].sum()
        total_disposed = df["disposed-quantity"].sum()
        total_cancelled = df["cancelled-quantity"].sum()
        total_in_process = df["in-process-quantity"].sum()
        total_fees = df["removal-fee"].sum()

        # Remaining = requested but not yet accounted for
        total_remaining = total_requested - (total_shipped + total_disposed + total_cancelled)

        # KPIs
        k1, k2, k3 = st.columns(3)
        k1.metric("Total Requested", f"{int(total_requested):,}")
        k2.metric("Shipped Back", f"{int(total_shipped):,}")
        k3.metric("Disposed", f"{int(total_disposed):,}")

        k4, k5, k6 = st.columns(3)
        k4.metric("Cancelled", f"{int(total_cancelled):,}", delta="Stock returned to FBA", delta_color="normal")
        k5.metric("Still In Process", f"{int(total_in_process):,}")
        k6.metric("Total Removal Fees", f"${total_fees:,.2f}", delta="Cost", delta_color="inverse")

        if total_remaining > 0:
            st.warning(f"**{int(total_remaining):,} units** requested but not yet shipped, disposed, or cancelled. These may be stuck.")

        st.divider()

        # Removal type breakdown
        st.subheader("Removals by Order Type")
        by_type = df.groupby("order-type", as_index=False)["requested-quantity"].sum().sort_values("requested-quantity", ascending=False)
        if not by_type.empty:
            fig_type = px.pie(by_type, names="order-type", values="requested-quantity", title="Removal Orders by Type")
            st.plotly_chart(fig_type, use_container_width=True)

        # Status breakdown
        st.subheader("Order Status Breakdown")
        by_status = df.groupby("order-status", as_index=False)["requested-quantity"].sum().sort_values("requested-quantity", ascending=False)
        if not by_status.empty:
            fig_status = px.bar(by_status, x="requested-quantity", y="order-status", orientation="h",
                                title="Units by Order Status")
            st.plotly_chart(fig_status, use_container_width=True)

        # Disposition breakdown (Sellable vs Unsellable)
        by_disp = df.groupby("disposition", as_index=False)["requested-quantity"].sum()
        if not by_disp.empty and len(by_disp) > 1:
            st.subheader("Disposition (Sellable vs Unsellable)")
            fig_disp = px.pie(by_disp, names="disposition", values="requested-quantity", title="Removed Inventory Condition")
            st.plotly_chart(fig_disp, use_container_width=True)

        # Top SKUs by removal volume
        if df["sku"].astype(str).str.strip().replace("", pd.NA).notna().any():
            st.subheader("Top SKUs by Removal Volume")
            sku_removals = (
                df[df["sku"].astype(str).str.strip() != ""]
                .groupby("sku", as_index=False)
                .agg(
                    requested=("requested-quantity", "sum"),
                    shipped=("shipped-quantity", "sum"),
                    disposed=("disposed-quantity", "sum"),
                    cancelled=("cancelled-quantity", "sum"),
                    fees=("removal-fee", "sum"),
                )
                .sort_values("requested", ascending=False)
            )
            st.dataframe(sku_removals.head(25), use_container_width=True)

            st.download_button(
                "⬇️ Download Removal Summary by SKU (CSV)",
                data=df_to_csv_download(sku_removals),
                file_name="removal_summary_by_sku.csv",
                mime="text/csv",
            )

        # Removal trend over time
        if "request-date" in df.columns and df["request-date"].notna().any():
            st.subheader("Removal Trend Over Time")
            monthly = (
                df.dropna(subset=["request-date"])
                .assign(month=lambda x: x["request-date"].dt.to_period("M").astype(str))
                .groupby("month", as_index=False)["requested-quantity"]
                .sum()
                .sort_values("month")
            )
            if len(monthly) > 1:
                fig_trend = px.bar(monthly, x="month", y="requested-quantity", title="Monthly Removal Requests")
                st.plotly_chart(fig_trend, use_container_width=True)

        with st.expander("Full Removal Order Data"):
            st.dataframe(df.head(100), use_container_width=True)

    else:
        st.info("Upload your **Removal Order Detail** report to track removal costs, disposition, and identify stuck orders.")

# ==========================================
# TAB 8: RESTOCKING INTELLIGENCE
# ==========================================
with tab8:
    st.header("Restocking Intelligence")
    st.markdown("""
Upload your **FBA Inventory Health** report (same file as Tab 1).
Uses 30-day and 90-day sales velocity to calculate reorder points, days of supply, and stockout dates.
*Amazon provides 30 & 90-day windows — we estimate 60-day from those.*
""")

    # --- Seller-configurable parameters ---
    st.subheader("Settings")
    cfg1, cfg2, cfg3 = st.columns(3)
    with cfg1:
        lead_time = st.number_input("Lead Time (days)", min_value=1, max_value=180, value=30,
                                     help="Days from placing a PO to units being available at FBA (include manufacturing + shipping + check-in).")
    with cfg2:
        safety_days = st.number_input("Safety Stock (days)", min_value=0, max_value=90, value=14,
                                       help="Extra buffer days to absorb demand spikes and shipping delays.")
    with cfg3:
        target_dos = st.number_input("Target Days of Supply", min_value=14, max_value=365, value=60,
                                      help="How many days of inventory you want on hand after restock arrives.")

    st.divider()

    restock_file = st.file_uploader("Upload 'FBA Inventory Health' CSV", type=["csv"], key="restock_upload")

    if restock_file:
        df = clean_columns(load_csv(restock_file))

        # --- Map columns (Inventory Health report) ---
        # Amazon provides: 24hrs, 7d, 30d, 90d — NO 60-day column
        numeric_fields = [
            "available", "afn-fulfillable-quantity",
            "units-shipped-last-24-hrs",
            "units-shipped-last-7-days",
            "units-shipped-last-30-days",
            "units-shipped-last-90-days",
            "your-price",
            "afn-inbound-working-quantity",
            "afn-inbound-shipped-quantity",
            "afn-inbound-receiving-quantity",
            "afn-reserved-quantity",
            "inv-age-0-to-90-days",
            "inv-age-91-to-180-days",
            "inv-age-181-to-270-days",
            "inv-age-271-to-365-days",
            "inv-age-365-plus-days",
        ]

        # Also handle 'sales-shipped-last-*' variant column names
        sales_variant_map = {
            "sales-shipped-last-24-hrs": "units-shipped-last-24-hrs",
            "sales-shipped-last-7-days": "units-shipped-last-7-days",
            "sales-shipped-last-30-days": "units-shipped-last-30-days",
            "sales-shipped-last-90-days": "units-shipped-last-90-days",
        }
        for variant, canonical in sales_variant_map.items():
            if variant in df.columns and canonical not in df.columns:
                df[canonical] = df[variant]

        for col in numeric_fields:
            if col in df.columns:
                df[col] = to_number(df[col])
            else:
                df[col] = 0

        # Show detected columns for debugging
        velocity_cols_found = [c for c in df.columns if "shipped" in c or "sales-shipped" in c]
        with st.expander("Detected velocity columns"):
            st.write(velocity_cols_found if velocity_cols_found else "None found — check your report has units-shipped or sales-shipped columns")

        # Current fulfillable stock — try 'available' first (common), then 'afn-fulfillable-quantity'
        if df["available"].sum() > 0:
            df["current_stock"] = df["available"]
        else:
            df["current_stock"] = df["afn-fulfillable-quantity"]

        # Inbound pipeline (units not yet checked in)
        df["inbound_total"] = (
            df["afn-inbound-working-quantity"]
            + df["afn-inbound-shipped-quantity"]
            + df["afn-inbound-receiving-quantity"]
        )

        # Total available = on-hand + inbound
        df["total_available"] = df["current_stock"] + df["inbound_total"]

        # --- Velocity calculations ---
        # Amazon gives 30d and 90d. We derive:
        #   velocity_30d = units last 30 days / 30
        #   velocity_90d = units last 90 days / 90
        #   velocity_60d_est = (units last 90 days - units last 30 days) / 60
        #     (the "back half" — days 31-90 average — contrasts with recent 30d)
        df["velocity_30d"] = df["units-shipped-last-30-days"] / 30
        df["velocity_90d"] = df["units-shipped-last-90-days"] / 90
        units_days_31_to_90 = (df["units-shipped-last-90-days"] - df["units-shipped-last-30-days"]).clip(lower=0)
        df["velocity_60d_est"] = units_days_31_to_90 / 60

        # Trend indicator: compare recent 30-day vs older 31-90 day period
        # If 30d velocity > 31-90d velocity by 15%+ → accelerating
        # If 30d velocity < 31-90d velocity by 15%+ → decelerating
        def velocity_trend(row):
            v30 = row["velocity_30d"]
            v_older = row["velocity_60d_est"]
            if v_older == 0 and v30 == 0:
                return "No Sales"
            if v_older == 0:
                return "New Momentum"
            ratio = v30 / v_older
            if ratio >= 1.15:
                return "Accelerating"
            elif ratio <= 0.85:
                return "Decelerating"
            return "Stable"

        df["trend"] = df.apply(velocity_trend, axis=1)

        # --- Core restocking math (use 30-day velocity as primary) ---
        df["days_of_supply"] = df.apply(
            lambda r: r["total_available"] / r["velocity_30d"] if r["velocity_30d"] > 0 else 9999, axis=1
        )
        df["days_of_supply"] = df["days_of_supply"].clip(upper=9999)

        df["reorder_point_units"] = (lead_time + safety_days) * df["velocity_30d"]
        df["reorder_qty"] = (
            (target_dos * df["velocity_30d"]) - df["total_available"]
        ).clip(lower=0).round(0).astype(int)

        df["stockout_date"] = df.apply(
            lambda r: (datetime.now() + timedelta(days=int(r["days_of_supply"]))).strftime("%Y-%m-%d")
            if r["velocity_30d"] > 0 and r["days_of_supply"] < 9999
            else "N/A",
            axis=1,
        )

        df["reorder_cost"] = df["reorder_qty"] * df["your-price"]

        # --- Urgency status ---
        def urgency(row):
            dos = row["days_of_supply"]
            if row["current_stock"] == 0 and row["velocity_30d"] > 0:
                return "OUT OF STOCK"
            if dos <= lead_time:
                return "CRITICAL"
            if dos <= lead_time + safety_days:
                return "LOW"
            if dos > target_dos * 2:
                return "OVERSTOCK"
            return "OK"

        df["status"] = df.apply(urgency, axis=1)

        # --- Filter to products with actual sales ---
        has_30 = df["units-shipped-last-30-days"] > 0
        has_90 = df["units-shipped-last-90-days"] > 0
        active = df[has_30 | has_90].copy()

        if active.empty:
            st.warning("No products with sales found. Check that your report has 'units-shipped-last-30-days' or 'units-shipped-last-90-days' columns.")
            st.write("Columns in your file:", list(df.columns))
        else:
            # --- KPIs ---
            oos_count = (active["status"] == "OUT OF STOCK").sum()
            critical_count = (active["status"] == "CRITICAL").sum()
            low_count = (active["status"] == "LOW").sum()
            ok_count = (active["status"] == "OK").sum()
            over_count = (active["status"] == "OVERSTOCK").sum()

            total_reorder_units = active["reorder_qty"].sum()
            total_reorder_cost = active["reorder_cost"].sum()

            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Out of Stock", int(oos_count))
            k2.metric("Critical", int(critical_count))
            k3.metric("Low Stock", int(low_count))
            k4.metric("OK", int(ok_count))
            k5.metric("Overstock", int(over_count))

            k6, k7 = st.columns(2)
            k6.metric("Total Reorder Units Needed", f"{int(total_reorder_units):,}")
            k7.metric("Estimated Reorder Cost (at sell price)", f"${total_reorder_cost:,.2f}")

            st.divider()

            # --- Urgency distribution chart ---
            st.subheader("Inventory Status Distribution")
            status_counts = active["status"].value_counts().reset_index()
            status_counts.columns = ["Status", "SKUs"]
            color_map = {
                "OUT OF STOCK": "#d32f2f",
                "CRITICAL": "#f57c00",
                "LOW": "#fbc02d",
                "OK": "#388e3c",
                "OVERSTOCK": "#1565c0",
            }
            fig_status = px.bar(
                status_counts, x="Status", y="SKUs", color="Status",
                color_discrete_map=color_map,
                title="SKU Count by Restocking Urgency",
            )
            st.plotly_chart(fig_status, use_container_width=True)

            # --- Days of supply distribution ---
            reasonable = active[active["days_of_supply"] < 365].copy()
            if not reasonable.empty:
                st.subheader("Days of Supply Distribution")
                fig_dos = px.histogram(
                    reasonable, x="days_of_supply", nbins=30,
                    title="Days of Supply Across Active SKUs",
                    labels={"days_of_supply": "Days of Supply"},
                )
                fig_dos.add_vline(x=lead_time, line_dash="dash", line_color="red",
                                  annotation_text=f"Lead Time ({lead_time}d)")
                fig_dos.add_vline(x=lead_time + safety_days, line_dash="dash", line_color="orange",
                                  annotation_text=f"Reorder Point ({lead_time + safety_days}d)")
                st.plotly_chart(fig_dos, use_container_width=True)

            # --- Velocity comparison: Recent 30d vs Older 31-90d ---
            st.subheader("Sales Velocity: Recent 30 Days vs Prior Period (Days 31-90)")
            st.caption("Products above the diagonal are accelerating (selling faster recently). Below = decelerating.")
            top_velocity = active.nlargest(50, "velocity_30d")
            name_col = "sku" if "sku" in top_velocity.columns else "asin"
            fig_scatter = px.scatter(
                top_velocity, x="velocity_60d_est", y="velocity_30d",
                hover_name=name_col, color="trend",
                color_discrete_map={
                    "Accelerating": "#388e3c",
                    "Decelerating": "#d32f2f",
                    "Stable": "#757575",
                    "New Momentum": "#1565c0",
                    "No Sales": "#bdbdbd",
                },
                title="Daily Velocity (units/day): Last 30d vs Days 31-90",
                labels={"velocity_60d_est": "Days 31-90 Avg (units/day)", "velocity_30d": "Last 30-Day Avg (units/day)"},
            )
            # Add diagonal reference line
            max_vel = max(top_velocity["velocity_30d"].max(), top_velocity["velocity_60d_est"].max(), 1)
            fig_scatter.add_shape(type="line", x0=0, y0=0, x1=max_vel, y1=max_vel,
                                  line=dict(color="gray", dash="dot"))
            st.plotly_chart(fig_scatter, use_container_width=True)

            # --- Priority reorder list ---
            st.subheader("Reorder Priority List")
            st.caption("Sorted by urgency, then days of supply (lowest first).")

            status_order = {"OUT OF STOCK": 0, "CRITICAL": 1, "LOW": 2, "OK": 3, "OVERSTOCK": 4}
            active["_status_rank"] = active["status"].map(status_order)
            reorder_list = active.sort_values(["_status_rank", "days_of_supply"], ascending=[True, True])

            display_cols = [
                "sku", "asin", "product-name",
                "status", "trend",
                "current_stock", "inbound_total", "total_available",
                "velocity_30d", "velocity_90d",
                "days_of_supply", "stockout_date",
                "reorder_qty", "reorder_cost", "your-price",
            ]
            display_cols = [c for c in display_cols if c in reorder_list.columns]

            # Round numeric display columns
            for rc in ["velocity_30d", "velocity_90d", "velocity_60d_est", "days_of_supply", "reorder_cost"]:
                if rc in reorder_list.columns:
                    reorder_list[rc] = reorder_list[rc].round(1)

            # Status filter
            filter_status = st.multiselect(
                "Filter by status",
                options=["OUT OF STOCK", "CRITICAL", "LOW", "OK", "OVERSTOCK"],
                default=["OUT OF STOCK", "CRITICAL", "LOW"],
            )
            filtered = reorder_list[reorder_list["status"].isin(filter_status)] if filter_status else reorder_list

            st.dataframe(filtered[display_cols], use_container_width=True)

            st.download_button(
                "⬇️ Download Full Reorder List (CSV)",
                data=df_to_csv_download(reorder_list[display_cols]),
                file_name="restock_priority_list.csv",
                mime="text/csv",
            )

            # --- Overstock alert ---
            overstock = active[active["status"] == "OVERSTOCK"].copy()
            if not overstock.empty:
                with st.expander(f"Overstock Alert ({len(overstock)} SKUs with > {target_dos * 2} days supply)"):
                    st.caption("Consider running a sale, creating a removal order, or pausing reorders for these.")
                    over_cols = ["sku", "asin", "product-name", "current_stock", "days_of_supply", "velocity_30d", "your-price"]
                    over_cols = [c for c in over_cols if c in overstock.columns]
                    st.dataframe(overstock[over_cols].sort_values("days_of_supply", ascending=False), use_container_width=True)

    else:
        st.info("""
Upload your **FBA Inventory Health** report (same file used in the Inventory Health tab).

**Report needed:** `FBA Inventory Health` from Seller Central > Reports > Fulfillment > Inventory

Amazon provides 30-day and 90-day sales windows. This tab uses both to calculate:
- **Days of Supply** — how long current stock will last
- **Reorder Point** — when to place your next order
- **Reorder Quantity** — how many units to order
- **Stockout Date** — when you'll run out
- **Velocity Trend** — compares last 30 days vs days 31-90 to detect acceleration

Configure your lead time, safety stock, and target days of supply above.
""")
