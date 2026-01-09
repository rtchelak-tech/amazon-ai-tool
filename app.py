import streamlit as st
import pandas as pd
import plotly.express as px

# --- Page Configuration ---
st.set_page_config(page_title="FBA Command Center", layout="wide", initial_sidebar_state="expanded")

# --- Custom Styling ---
st.markdown("""
    <style>
    .main { background-color: #f9f9fb; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/a/a9/Amazon_logo.svg", width=100) 
    st.title("FBA Assistant 🤖")
    st.write("Upload reports to unlock modules.")
    st.divider()
    st.info("💡 **Quick Guide**")
    st.markdown("""
    **Tab 1: Inventory Health**
    *File:* `FBA Inventory`
    *New:* Stockout Alerts & Dead Stock.
    
    **Tab 2: Lost Money**
    *File:* `Reimbursements`
    *Goal:* Recovery Audit.
    """)
    st.caption("v2.2 - Health Upgrade")

st.title("🚀 Amazon FBA Command Center")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📦 Inventory Health", 
    "💸 Lost Money & Reimbursements", 
    "↩️ Returns Analysis", 
    "📉 True Inventory Tracker",
    "💰 Net Profit"
])

# ==========================================
# TAB 1: INVENTORY HEALTH (UPGRADED)
# ==========================================
with tab1:
    st.header("Inventory Health & Restock Alerts")
    st.markdown("Optimize your storage fees and prevent stockouts.")
    
    uploaded_inv = st.file_uploader("Upload 'FBA Inventory' (CSV)", type=['csv'], key="inv_upload")
    
    if uploaded_inv:
        # --- 1. LOAD & CLEAN ---
        try:
            df = pd.read_csv(uploaded_inv)
            # Standardize columns: lowercase, strip spaces, replace spaces with hyphens to match Amazon format
            df.columns = df.columns.str.strip().str.lower()
            
            # Helper to safely convert columns to numbers
            def safe_float(col):
                if col in df.columns:
                    return pd.to_numeric(df[col], errors='coerce').fillna(0)
                return 0

            # --- 2. EXTRACT METRICS ---
            # Identify columns (Amazon changes names often, so we check for variations)
            # Quantity
            if 'afn-fulfillable-quantity' in df.columns:
                df['qty'] = df['afn-fulfillable-quantity']
            elif 'available' in df.columns: # Sometimes it's just 'available'
                df['qty'] = df['available']
            else:
                df['qty'] = safe_float('available-quantity(sellable)')

            # Sales Velocity (30 Days)
            # Note: Health reports usually have 'units-shipped-last-30-days'
            df['sales_30'] = safe_float('units-shipped-last-30-days')
            
            # Financials
            df['price'] = safe_float('your-price')
            df['fees'] = safe_float('estimated-storage-cost-next-month')
            
            # Aging
            df['age_365'] = safe_float('inv-age-365-plus-days')
            df['age_181_330'] = safe_float('inv-age-181-to-330-days')
            
            # --- 3. CALCULATE NEW INSIGHTS ---
            
            # A. DAYS OF SUPPLY (DoS)
            # DoS = Current Stock / (Sales last 30 days / 30)
            # Avoid division by zero
            df['daily_velocity'] = df['sales_30'] / 30
            df['days_of_supply'] = df.apply(lambda x: x['qty'] / x['daily_velocity'] if x['daily_velocity'] > 0 else 999, axis=1)

            # B. POTENTIAL REVENUE
            df['potential_revenue'] = df['qty'] * df['price']

            # --- 4. DISPLAY TOP-LEVEL METRICS ---
            total_stock = df['qty'].sum()
            est_revenue = df['potential_revenue'].sum()
            total_fees = df['fees'].sum()
            
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Units in FBA", f"{int(total_stock):,}")
            m2.metric("Est. Revenue Value", f"${est_revenue:,.2f}")
            m3.metric("Est. Monthly Storage Fee", f"${total_fees:,.2f}", delta="Minimize This", delta_color="inverse")

            st.divider()

            # --- 5. ACTIONABLE ALERTS (THE NEW STUFF) ---
            
            c1, c2 = st.columns(2)
            
            with c1:
                st.subheader("🚨 Restock Alerts (Low Stock)")
                st.caption("Items with < 21 Days of Supply (High Sales Velocity)")
                
                # Filter: Velocity > 0 AND Days of Supply < 21
                restock_df = df[(df['sales_30'] > 0) & (df['days_of_supply'] < 21)].copy()
                restock_df = restock_df.sort_values('days_of_supply')
                
                if not restock_df.empty:
                    st.dataframe(
                        restock_df[['sku', 'qty', 'sales_30', 'days_of_supply']].head(10).style.format({'days_of_supply': "{:.1f}"}),
                        use_container_width=True
                    )
                else:
                    st.success("No immediate stockout risks found!")

            with c2:
                st.subheader("🐢 Dead Stock Candidates")
                st.caption("Items with > 10 units but ZERO sales in 30 days.")
                
                # Filter: Qty > 10 AND Sales_30 == 0
                dead_df = df[(df['qty'] > 10) & (df['sales_30'] == 0)].copy()
                dead_df = dead_df.sort_values('qty', ascending=False)
                
                if not dead_df.empty:
                    st.dataframe(dead_df[['sku', 'product-name', 'qty', 'fees']].head(10), use_container_width=True)
                else:
                    st.success("No dead stock found. Great job!")

            # --- 6. AGING INVENTORY VISUAL ---
            st.divider()
            st.subheader("⏳ Inventory Age Distribution")
            
            # We want to see how much stock is sitting in each age bucket
            age_cols = ['inv-age-0-to-90-days', 'inv-age-91-to-180-days', 'inv-age-181-to-330-days', 'inv-age-331-to-365-days', 'inv-age-365-plus-days']
            
            # Check which columns actually exist in the file
            present_age_cols = [c for c in age_cols if c in df.columns]
            
            if present_age_cols:
                # Sum them up for the chart
                age_sums = df[present_age_cols].sum().reset_index()
                age_sums.columns = ['Age Group', 'Units']
                
                fig = px.bar(age_sums, x='Age Group', y='Units', title="Inventory Units by Age Group", color='Age Group')
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("Inventory Age columns not found in this report. (Try downloading the 'FBA Inventory Health' report specifically).")

        except Exception as e:
            st.error(f"Error processing inventory file: {e}")
            st.write("Debug - Columns found:", df.columns.tolist())

    else:
        st.info("👋 Upload your **FBA Inventory** (or Inventory Health) CSV to see Stockout & Dead Stock analysis.")

# ==========================================
# TAB 2: LOST MONEY & REIMBURSEMENTS
# ==========================================
with tab2:
    st.header("Lost Inventory & Reimbursements")
    st.markdown("Analyze how much Amazon has paid you back vs. what is still missing.")
    
    c1, c2 = st.columns(2)
    inventory_upload = c1.file_uploader("1. Upload 'Inventory Ledger' (CSV)", type=['csv'], key="ledger_up")
    reimbursement_upload = c2.file_uploader("2. Upload 'Reimbursements' (CSV)", type=['csv'], key="reimb_up")
    
    # LOGIC 1: Process Reimbursements
    if reimbursement_upload:
        try:
            df_reim = pd.read_csv(reimbursement_upload)
            df_reim.columns = df_reim.columns.str.strip().str.lower()
            
            if 'approval-date' in df_reim.columns:
                df_reim['approval-date'] = pd.to_datetime(df_reim['approval-date'], errors='coerce')
            if 'amount-total' in df_reim.columns:
                df_reim['amount-total'] = pd.to_numeric(df_reim['amount-total'], errors='coerce').fillna(0)

            st.divider()
            st.subheader("✅ Money Recovered (from file)")
            
            total_recovered