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

# --- SIDEBAR: The "Guidance" System ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/a/a9/Amazon_logo.svg", width=100) 
    st.title("FBA Assistant 🤖")
    st.write("Upload reports to unlock modules.")
    
    st.divider()
    
    # Dynamic Help Section
    st.info("💡 **Quick Guide**")
    st.markdown("""
    **1. Inventory Health**
    *File:* `FBA Inventory`
    *Goal:* Fix fees & excess stock.
    
    **2. Returns Analysis**
    *File:* `FBA Customer Returns`
    *Goal:* Find product defects.
    
    **3. True Inventory (Beta)**
    *Files:* `Inventory Ledger`, `Removals`
    *Goal:* Track lost units.
    """)
    
    st.divider()
    st.caption("v2.0 - Command Center Edition")

# --- MAIN APP: The "5-Tab Suite" ---
st.title("🚀 Amazon FBA Command Center")

# Create the Tabs for the different Modules
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📦 Inventory Health", 
    "💸 Lost Money & Reimbursements", 
    "↩️ Returns Analysis", 
    "📉 True Inventory Tracker",
    "💰 Net Profit"
])

# ==========================================
# MODULE 1: INVENTORY HEALTH (Fully Working)
# ==========================================
with tab1:
    st.header("Inventory Health & Storage Fees")
    uploaded_inv = st.file_uploader("Upload 'FBA Inventory Health' CSV", type=['csv'], key="inv_upload")
    
    if uploaded_inv:
        # Load & Clean Data
        df = pd.read_csv(uploaded_inv)
        numeric_cols = ['estimated-excess-quantity', 'your-price', 'estimated-storage-cost-next-month', 'inv-age-365-plus-days']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
        # Calculate Metrics
        excess_val = (df['estimated-excess-quantity'] * df['your-price']).sum() if 'estimated-excess-quantity' in df.columns else 0
        storage_cost = df['estimated-storage-cost-next-month'].sum() if 'estimated-storage-cost-next-month' in df.columns else 0
        aged_units = df['inv-age-365-plus-days'].sum() if 'inv-age-365-plus-days' in df.columns else 0

        # Display Metrics
        c1, c2, c3 = st.columns(3)
        c1.metric("Trapped Capital (Excess)", f"${excess_val:,.2f}", delta="Needs Liquidation", delta_color="inverse")
        c2.metric("Next Month Storage Fees", f"${storage_cost:,.2f}", delta="- Minimize This", delta_color="inverse")
        c3.metric("Aged Units (365+ Days)", f"{int(aged_units)}", delta="LTSF Risk", delta_color="inverse")

        # Visuals
        st.subheader("Where is your money stuck?")
        if 'estimated-excess-quantity' in df.columns:
            df['excess_val'] = df['estimated-excess-quantity'] * df['your-price']
            top_excess = df.sort_values(by='excess_val', ascending=False).head(10)
            fig = px.bar(top_excess, x='excess_val', y='sku', orientation='h', title="Top 10 SKUs by Excess Value", color='excess_val')
            st.plotly_chart(fig, use_container_width=True)
            
        # Action List
        st.subheader("📋 Recommended Actions")
        if 'recommended-action' in df.columns:
             st.dataframe(df[['sku', 'product-name', 'recommended-action', 'estimated-storage-cost-next-month']], use_container_width=True)
    else:
        st.info("👋 Upload your **FBA Inventory** file to see this data.")

# ==========================================
# MODULE 2: LOST MONEY (Placeholder)
# ==========================================
with tab2:
    st.header("Lost Inventory & Reimbursements")
    st.markdown("Find units Amazon lost/damaged but didn't pay you for.")
    
    c1, c2 = st.columns(2)
    reimb_file = c1.file_uploader("1. Upload 'Reimbursements' Report", type=['csv'], key="reimb")
    adj_file = c2.file_uploader("2. Upload 'Inventory Adjustments' Report", type=['csv'], key="adj")
    
    if reimb_file and adj_file:
        st.success("Files received! (Logic to match Lost vs. Paid would run here)")
        # This is where we would add the logic to compare the two files
    else:
        st.warning("Please upload both files to run the audit.")

# ==========================================
# MODULE 3: RETURNS ANALYSIS (Placeholder)
# ==========================================
with tab3:
    st.header("Voice of the Customer (Returns)")
    returns_file = st.file_uploader("Upload 'FBA Customer Returns' Report", type=['csv'], key="ret")
    
    if returns_file:
        st.write("Analyzing return reasons...")
        # Logic to scan 'customer-comments' column would go here
    else:
        st.info("Upload returns file to detect product defects.")

# ==========================================
# MODULE 4: TRUE INVENTORY (The Lifecycle)
# ==========================================
with tab4:
    st.header("True Inventory Lifecycle")
    st.markdown("Reconcile shipments, sales, and warehouse transfers.")
    ledger_file = st.file_uploader("Upload 'Inventory Ledger' (View: Daily)", type=['csv'], key="ledg")
    
    if ledger_file:
        st.write("Tracking lifecycle...")
        # Logic to map Inbound -> Sold -> Returned -> Removal would go here
    else:
        st.info("Upload the Daily Ledger to track 'Ghost' Inventory.")

# ==========================================
# MODULE 5: FINANCIALS (Placeholder)
# ==========================================
with tab5:
    st.header("Net Profit Calculator")
    settlement_file = st.file_uploader("Upload 'Settlement Report' (Flat File V2)", type=['csv'], key="fin")
    
    if settlement_file:
        st.write("Calculating true margins...")
        # Logic to subtract fees/refunds from sales would go here
    else:
        st.info("See your true pocket profit after all Amazon fees.")
        import pandas as pd

# --- CONFIGURATION ---
inventory_file = 'inventory_ledger.csv'      # Download for: Dec 1 - Dec 31
reimbursement_file = 'reimbursements.csv'    # Download for: Dec 1 - TODAY

# Define the period you want to AUDIT (The Inventory dates)
TARGET_MONTH_START = '2025-12-01'
TARGET_MONTH_END = '2025-12-31'

# --- STEP 1: LOAD DATA ---
df_inv = pd.read_csv(inventory_file)
df_reim = pd.read_csv(reimbursement_file)

# Normalize columns
df_inv.columns = df_inv.columns.str.strip().str.lower()
df_reim.columns = df_reim.columns.str.strip().str.lower()

# Convert to datetime
df_inv['date'] = pd.to_datetime(df_inv['date'])
df_reim['approval-date'] = pd.to_datetime(df_reim['approval-date'])

# --- STEP 2: SMART FILTERING ---

# 1. Filter Inventory STRICTLY to the target month
mask_inv = (df_inv['date'] >= TARGET_MONTH_START) & (df_inv['date'] <= TARGET_MONTH_END)
df_inv = df_inv.loc[mask_inv].copy()

# 2. Filter Reimbursements broadly (Start date -> Future)
# We only care that the reimbursement happened AFTER the target month started
mask_reim = (df_reim['approval-date'] >= TARGET_MONTH_START)
df_reim = df_reim.loc[mask_reim].copy()

print(f"Auditing Inventory from {TARGET_MONTH_START} to {TARGET_MONTH_END}")
print(f"Checking for Reimbursements from {TARGET_MONTH_START} to {df_reim['approval-date'].max().date()}")

# --- STEP 3: CALCULATE NET LOSS (INVENTORY) ---
for col in ['lost', 'damaged', 'found']:
    df_inv[col] = df_inv[col].fillna(0) if col in df_inv.columns else 0

inv_summary = df_inv.groupby('fnsku')[['lost', 'damaged', 'found']].sum().reset_index()
inv_summary['net_loss_units'] = (inv_summary['lost'] + inv_summary['damaged']) - inv_summary['found']
inv_summary = inv_summary[inv_summary['net_loss_units'] > 0]

# --- STEP 4: CALCULATE PAYMENTS (REIMBURSEMENTS) ---
reim_qty_col = 'quantity-reimbursed-total'
reim_amt_col = 'amount-total'
df_reim[reim_qty_col] = df_reim[reim_qty_col].fillna(0)
df_reim[reim_amt_col] = df_reim[reim_amt_col].fillna(0)

reim_summary = df_reim.groupby('fnsku')[[reim_qty_col, reim_amt_col]].sum().reset_index()

# Calculate average value per unit
reim_summary['avg_val_per_unit'] = reim_summary.apply(
    lambda x: x[reim_amt_col] / x[reim_qty_col] if x[reim_qty_col] > 0 else 0, axis=1
)
reim_summary.rename(columns={reim_qty_col: 'total_reimbursed_qty'}, inplace=True)

# --- STEP 5: COMPARE ---
final_report = pd.merge(inv_summary, reim_summary, on='fnsku', how='left')
final_report['total_reimbursed_qty'] = final_report['total_reimbursed_qty'].fillna(0)
final_report['avg_val_per_unit'] = final_report['avg_val_per_unit'].fillna(0)

# DISCREPANCY CALCULATION
final_report['units_owed'] = final_report['net_loss_units'] - final_report['total_reimbursed_qty']
final_report['est_money_owed'] = final_report['units_owed'] * final_report['avg_val_per_unit']

# Sort and Export
actionable_report = final_report[final_report['units_owed'] > 0].sort_values(by='units_owed', ascending=False)

print(f"\nFound {len(actionable_report)} FNSKUs with discrepancies.")
if not actionable_report.empty:
    print(actionable_report[['fnsku', 'net_loss_units', 'total_reimbursed_qty', 'units_owed', 'est_money_owed']].head())
    actionable_report.to_csv('december_reconciliation_results.csv', index=False)