import streamlit as st
import pandas as pd
import plotly.express as px

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="FBA Command Center", layout="wide", initial_sidebar_state="expanded")

# --- CUSTOM STYLING ---
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
    *Insights:* Stockouts, Dead Stock, Pricing.
    
    **Tab 2: Lost Money**
    *File:* `Reimbursements`
    *Insights:* Recovery Audit.
    """)
    st.caption("v2.3 - Full Suite")

# --- MAIN APP ---
st.title("🚀 Amazon FBA Command Center")

# Create the Tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📦 Inventory Health", 
    "💸 Lost Money & Reimbursements", 
    "↩️ Returns Analysis", 
    "📉 True Inventory Tracker",
    "💰 Net Profit"
])

# ==========================================
# TAB 1: INVENTORY HEALTH (SUPERCHARGED)
# ==========================================
with tab1:
    st.header("Inventory Health & Market Analysis")
    st.markdown("Deep dive into Stockouts, Pricing, and Amazon's Recommendations.")
    
    uploaded_inv = st.file_uploader("Upload 'FBA Inventory' (CSV)", type=['csv'], key="inv_upload")
    
    if uploaded_inv:
        try:
            # --- 1. LOAD & CLEAN ---
            df = pd.read_csv(uploaded_inv)
            # Standardize columns: lowercase, strip spaces
            df.columns = df.columns.str.strip().str.lower()
            
            # Helper: Safely convert to number
            def safe_float(col):
                if col in df.columns:
                    return pd.to_numeric(df[col], errors='coerce').fillna(0)
                return 0

            # --- 2. MAP COLUMNS ---
            # We map standard columns to easy variable names
            df['qty'] = df['afn-fulfillable-quantity'] if 'afn-fulfillable-quantity' in df.columns else safe_float('available-quantity(sellable)')
            df['sales_30'] = safe_float('units-shipped-last-30-days')
            df['price'] = safe_float('your-price')
            df['competitor_price'] = safe_float('lowest-price-new-plus-shipping')
            df['fees'] = safe_float('estimated-storage-cost-next-month')
            
            # --- 3. CALCULATE METRICS ---
            total_stock = df['qty'].sum()
            est_revenue = (df['qty'] * df['price']).sum()
            
            # A. Stockout Risk (Days of Supply)
            df['daily_velocity'] = df['sales_30'] / 30
            df['days_of_supply'] = df.apply(lambda x: x['qty'] / x['daily_velocity'] if x['daily_velocity'] > 0 else 999, axis=1)

            # --- 4. DISPLAY TOP STATS ---
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Units", f"{int(total_stock):,}")
            m2.metric("Est. Revenue Value", f"${est_revenue:,.2f}")
            m3.metric("Monthly Storage Fees", f"${df['fees'].sum():,.2f}", delta="Minimize This", delta_color="inverse")

            st.divider()

            # --- 5. STOCKOUTS & DEAD STOCK ---
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("🚨 Stockout Risk")
                st.caption("Items with < 21 Days of Supply")
                restock_df = df[(df['sales_30'] > 0) & (df['days_of_supply'] < 21)].sort_values('days_of_supply')
                if not restock_df.empty:
                    st.dataframe(restock_df[['sku', 'qty', 'sales_30', 'days_of_supply']].head(10).style.format({'days_of_supply': "{:.1f}"}), use_container_width=True)
                else:
                    st.success("No immediate stockout risks!")

            with c2:
                st.subheader("🐢 Dead Stock")
                st.caption("Qty > 10 but ZERO sales in 30 days")
                dead_df = df[(df['qty'] > 10) & (df['sales_30'] == 0)].sort_values('qty', ascending=False)
                if not dead_df.empty:
                    st.dataframe(dead_df[['sku', 'product-name', 'qty', 'fees']].head(10), use_container_width=True)
                else:
                    st.success("No dead stock found!")

            st.divider()

            # --- 6. THE 80/20 RULE (PARETO) ---
            st.subheader("🏆 The 'Hero' Products (80/20 Rule)")
            if df['sales_30'].sum() > 0:
                sorted_df = df.sort_values(by='sales_30', ascending=False)
                sorted_df['cumulative_sales'] = sorted_df['sales_30'].cumsum()
                sorted_df['cumulative_perc'] = 100 * sorted_df['cumulative_sales'] / sorted_df['sales_30'].sum()
                top_performers = sorted_df[sorted_df['cumulative_perc'] <= 80]
                
                c_pie, c_stat = st.columns([1, 2])
                with c_pie:
                    sales_data = pd.DataFrame({
                        'Type': ['Hero Products (80% Vol)', 'Others (20% Vol)'],
                        'Sales': [top_performers['sales_30'].sum(), df['sales_30'].sum() - top_performers['sales_30'].sum()]
                    })
                    fig_pie = px.pie(sales_data, values='Sales', names='Type', hole=0.4)
                    st.plotly_chart(fig_pie, use_container_width=True)
                with c_stat:
                    st.write(f"**{len(top_performers)} SKUs** are generating 80% of your sales volume.")
                    st.dataframe(top_performers[['sku', 'product-name', 'sales_30', 'price']].head(5), use_container_width=True)

            # --- 7. PRICE WAR ---
            st.subheader("🏷️ Price Competitiveness")
            if 'competitor_price' in df.columns and df['competitor_price'].sum() > 0:
                df['price_diff'] = df['price'] - df['competitor_price']
                overpriced = df[(df['qty'] > 0) & (df['price_diff'] > 0)].sort_values('price_diff', ascending=False)
                if not overpriced.empty:
                    st.warning(f"⚠️ You are priced higher on **{len(overpriced)} products**.")
                    st.dataframe(overpriced[['sku', 'price', 'competitor_price', 'price_diff']].head(5), use_container_width=True)
                else:
                    st.success("✅ Your pricing is competitive!")
            else:
                st.info("Pricing columns not detected (Need 'lowest-price-new-plus-shipping').")

        except Exception as e:
            st.error(f"Error processing inventory file: {e}")

    else:
        st.info("👋 Upload your **FBA Inventory Health** CSV to unlock Price Wars & 80/20 Analysis.")

# ==========================================
# TAB 2: LOST MONEY & REIMBURSEMENTS
# ==========================================
with tab2:
    st.header("Lost Inventory & Reimbursements")
    st.markdown("Analyze how much Amazon has paid you back vs. what is still missing.")
    
    c1, c2 = st.columns(2)
    inventory_upload = c1.file_uploader("1. Upload 'Inventory Ledger' (CSV)", type=['csv'], key="ledger_up")
    reimbursement_upload = c2.file_uploader("2. Upload 'Reimbursements' (CSV)", type=['csv'], key="reimb_up")
    
    # LOGIC: Process Reimbursements
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
            
            total_recovered = df_reim['amount-total'].sum()
            
            m1, m2 = st.columns(2)
            m1.metric("Total Reimbursed", f"${total_recovered:,.2f}")
            m2.metric("Total Cases/Rows", f"{len(df_reim)}")

            if 'reason' in df_reim.columns:
                reason_counts = df_reim.groupby('reason')['amount-total'].sum().reset_index()
                fig_reim = px.bar(reason_counts, x='reason', y='amount-total', title="Reimbursements by Reason", color='amount-total')
                st.plotly_chart(fig_reim, use_container_width=True)
                
            st.dataframe(df_reim.head())
            
        except Exception as e:
            st.error(f"Error reading Reimbursements file: {e}")

    if inventory_upload and reimbursement_upload:
        st.info("🔄 Comparison Logic: Upload 'Inventory Ledger' to match lost units against these payments.")

# ==========================================
# TAB 3: RETURNS (Placeholder)
# ==========================================
with tab3:
    st.header("Voice of the Customer (Returns)")
    st.info("Coming soon: Upload 'FBA Customer Returns' to see return reasons.")

# ==========================================
# TAB 4: TRUE INVENTORY (Placeholder)
# ==========================================
with tab4:
    st.header("True Inventory Lifecycle")
    st.info("Coming soon: Upload 'Inventory Ledger' to track lost units.")

# ==========================================
# TAB 5: NET PROFIT (Placeholder)
# ==========================================
with tab5:
    st.header("Net Profit Calculator")
    st.info("Coming soon: Upload 'Settlement Report' to see true margins.")