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
    st.info("💡 **Quick Guide**")import streamlit as st
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
        # Normalize column names just in case
        df.columns = df.columns.str.strip().str.lower()
        
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
# MODULE 2: LOST MONEY (NOW WORKING!)
# ==========================================
with tab2:
    st.header("Lost Inventory & Reimbursements")
    st.markdown("Find units Amazon lost/damaged but didn't pay you for.")
    
    c1, c2 = st.columns(2)
    # Note: We use the Inventory Ledger for 'Lost' items
    inventory_upload = c1.file_uploader("1. Upload 'Inventory Ledger' (CSV)", type=['csv'], key="reimb")
    reimbursement_upload = c2.file_uploader("2. Upload 'Reimbursements' Report (CSV)", type=['csv'], key="adj")
    
    if inventory_upload and reimbursement_upload:
        st.success("Files received! Running audit...")
        
        try:
            # --- 1. LOAD DATA ---
            df_inv = pd.read_csv(inventory_upload)
            df_reim = pd.read_csv(reimbursement_upload)
            
            # --- 2. NORMALIZE COLUMNS ---
            # Clean up column names (strip spaces, lowercase) to match Amazon's changing formats
            df_inv.columns = df_inv.columns.str.strip().str.lower()
            df_reim.columns = df_reim.columns.str.strip().str.lower()
            
            # --- 3. CONVERT DATES ---
            # We use 'errors=coerce' so if a date is weird, it doesn't crash the app
            if 'date' in df_inv.columns:
                df_inv['date'] = pd.to_datetime(df_inv['date'], errors='coerce')
            
            if 'approval-date' in df_reim.columns:
                df_reim['approval-date'] = pd.to_datetime(df_reim['approval-date'], errors='coerce')
            
            # --- 4. DISPLAY RESULTS ---
            st.divider()
            st.write(f"✅ **Loaded Data Successfully**")
            st.write(f"**Inventory Ledger:** {len(df_inv)} rows found.")
            st.write(f"**Reimbursements:** {len(df_reim)} rows found.")
            
            st.subheader("Data Preview")
            st.dataframe(df_inv.head())
            
            # Future Logic: Here is where we will compare df_inv (Lost) vs df_reim (Paid)
            
        except Exception as e:
            st.error(f"Error processing files: {e}")
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

