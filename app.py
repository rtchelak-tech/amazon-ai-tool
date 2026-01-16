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
        df = pd.read_csv(uploaded_file, encoding="latin-1")
    return df

def detect_report_type(df: pd.DataFrame) -> str:
    cols = set(df.columns)
    # Reimbursements report heuristics
    if "reimbursement-id" in cols and "approval-date" in cols and "reason" in cols:
        return "reimbursements"
    # Inventory Ledger (Daily) heuristics
    if "fnsku" in cols and "starting warehouse balance" in cols and "ending warehouse balance" in cols:
        return "ledger_daily"
    # Inventory Health heuristics
    if "estimated-excess-quantity" in cols and "estimated-storage-cost-next-month" in cols:
        return "inventory_health"
    # Customer Returns heuristics (common)
    if "return-reason" in cols or "customer-comments" in cols:
        return "customer_returns"
    # Settlement
    if "settlement-id" in cols or "amount-type" in cols:
        return "settlement"
    return "unknown"

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

def normalize_reimbursements(df_reim: pd.DataFrame) -> pd.DataFrame:
    df = clean_columns(df_reim)

    required = ["approval-date", "reason"]
    if not require_columns(df, required, "Reimbursements Report"):
        return pd.DataFrame()

    # Key columns often present
    for col in ["fnsku", "sku", "asin", "product-name", "reimbursement-id", "case-id", "amazon-order-id", "condition", "currency-unit"]:
        if col not in df.columns:
            df[col] = ""

    df["approval-date"] = pd.to_datetime(df["approval-date"], errors="coerce")

    # Map reason -> event_type (we only use warehouse/inbound loss types in this tab)
    df["reason_norm"] = df["reason"].astype(str).str.strip().str.lower()
    df["event_type"] = df["reason_norm"].map(REASON_MAP)

    # Quantity columns vary; sum anything that starts with quantity-reimbursed
    qty_cols = [c for c in df.columns if c.startswith("quantity-reimbursed")]
    if qty_cols:
        df["qty_reimbursed"] = df[qty_cols].apply(to_number)
        df["qty_reimbursed"] = df[qty_cols].apply(lambda row: row.sum(), axis=1)
    else:
        # Fallback if Amazon changes it (rare)
        df["qty_reimbursed"] = 0

    # Amount columns
    if "amount-total" in df.columns:
        df["amount_total"] = to_number(df["amount-total"])
    else:
        df["amount_total"] = 0

    if "amount-per-unit" in df.columns:
        df["amount_per_unit"] = to_number(df["amount-per-unit"])
    else:
        df["amount_per_unit"] = 0

    # Filter to only event_types we audit (lost/damage/dispose/unknown if present)
    audited = df[df["event_type"].isin(["lost", "damage", "dispose"])].copy()

    # Keep only meaningful rows
    audited = audited[audited["qty_reimbursed"] != 0]

    return audited

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
                    .apply(lambda g: pd.Series({
                        "avg_reim_per_unit": (g["amount_total"].sum() / g["qty_reimbursed"].sum()) if g["qty_reimbursed"].sum() else 0
                    }))
                    .reset_index(drop=True))
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

**4. True Inventory (Beta)**
*Files:* `Inventory Ledger`, (optional later: Removals)
*Goal:* Track ghost units.

**5. Net Profit**
*File:* `Settlement Flat File V2`
*Goal:* True pocket profit (later).
""")
    st.divider()
    st.caption("v2.1 - Audit Engine Edition")

# =========================
# Main UI Tabs
# =========================
st.title("🚀 Amazon FBA Command Center (US)")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📦 Inventory Health",
    "💸 Lost Money & Reimbursements",
    "↩️ Returns Analysis",
    "📉 True Inventory Tracker",
    "💰 Net Profit"
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
# TAB 4: TRUE INVENTORY (placeholder)
# ==========================================
with tab4:
    st.header("True Inventory Lifecycle (Beta)")
    st.markdown("Next step: reconcile inbound → sales → returns → removals → adjustments using ledger + other reports.")
    st.info("This tab is intentionally left as Beta until we confirm which additional Amazon reports you’ll use (Removals, Manage FBA Inventory snapshot, etc.).")

# ==========================================
# TAB 5: NET PROFIT (placeholder)
# ==========================================
with tab5:
    st.header("Net Profit Calculator (Beta)")
    st.markdown("Next step: parse Settlement Flat File V2, aggregate sales/refunds/fees, and optionally merge COGS.")
    st.info("Upload support will be added after we confirm your exact Settlement file columns and whether you want true net (with COGS + ads) or Amazon-only margin.")
