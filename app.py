import streamlit as st
import pandas as pd
import plotly.express as px

# --- PAGE CONFIG ---
st.set_page_config(page_title="Amazon FBA Mission Control", layout="wide")

# --- CUSTOM STYLING ---
st.markdown("""
    <style>
    .mission-box {
        padding: 20px; 
        border-radius: 10px; 
        background-color: #f0f2f6; 
        border-left: 5px solid #ff9900;
        margin-bottom: 20px;
    }
    .file-req { font-weight: bold; color: #d63031; }
    </style>
""", unsafe_allow_html=True)

# --- SIDEBAR: MISSION SELECTOR ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/a/a9/Amazon_logo.svg", width=100)
    st.title("Mission Control 🚀")
    
    # This is the "Pre-defined" list of what the app can do
    selected_mission = st.radio(
        "Select Your Goal:",
        [
            "📦 Inventory Health Check",
            "💸 Lost Money Audit", 
            "↩️ Analyze Returns",
            "💰 Calculate True Profit"
        ]
    )
    
    st.divider()
    st.info("Select a goal above to see which reports are required.")

# --- MAIN APP LOGIC ---
st.title(f"{selected_mission}")

# ==========================================
# MISSION 1: INVENTORY HEALTH (1 File)
# ==========================================
if selected_mission == "📦 Inventory Health Check":
    # 1. EXPLAIN THE MISSION
    st.markdown("""
    <div class="mission-box">
        <b>Goal:</b> Identify Stockouts, Dead Stock, and Pricing Issues.<br>
        <b>Files Required:</b> <span class="file-req">1 Report (FBA Inventory Health)</span>
    </div>
    """, unsafe_allow_html=True)

    # 2. ASK FOR FILES
    uploaded_file = st.file_uploader("Upload 'FBA Inventory' CSV", type=['csv'])

    # 3. RUN ANALYSIS
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        df.columns = df.columns.str.strip().str.lower()
        
        # Simple Logic to prove it works
        st.success("Analysis Running...")
        
        # Check for Stockouts
        if 'units-shipped-last-30-days' in df.columns and 'afn-fulfillable-quantity' in df.columns:
            st.subheader("🚨 Stockout Risk (Items selling fast but low stock)")
            df['sales'] = pd.to_numeric(df['units-shipped-last-30-days'], errors='coerce').fillna(0)
            df['stock'] = pd.to_numeric(df['afn-fulfillable-quantity'], errors='coerce').fillna(0)
            
            # Risk = less than 10 units but sales > 5
            risk = df[(df['stock'] < 10) & (df['sales'] > 5)]
            st.dataframe(risk[['sku', 'product-name', 'stock', 'sales']])
        else:
            st.warning("Could not find 'units-shipped' or 'afn-fulfillable-quantity' columns.")

# ==========================================
# MISSION 2: LOST MONEY AUDIT (2 Files)
# ==========================================
elif selected_mission == "💸 Lost Money Audit":
    # 1. EXPLAIN THE MISSION
    st.markdown("""
    <div class="mission-box">
        <b>Goal:</b> Find items Amazon lost or damaged but never paid you for.<br>
        <b>Files Required:</b> <span class="file-req">2 Reports (Inventory Ledger + Reimbursements)</span>
    </div>
    """, unsafe_allow_html=True)
    
    # 2. ASK FOR FILES (Dual Uploader)
    c1, c2 = st.columns(2)
    file_ledger = c1.file_uploader("1. Inventory Ledger (Daily)", type=['csv'])
    file_reimb = c2.file_uploader("2. Reimbursements Report", type=['csv'])
    
    # 3. RUN ANALYSIS (Only if BOTH are present)
    if file_ledger and file_reimb:
        st.success("✅ Both files received! Starting Audit Comparison...")
        
        # Load both
        df_ledger = pd.read_csv(file_ledger)
        df_reimb = pd.read_csv(file_reimb)
        
        st.write(f"Scanning {len(df_ledger)} ledger events against {len(df_reimb)} reimbursement payments...")
        # (Insert your complex matching logic here)
        
    elif file_ledger or file_reimb:
        st.warning("⚠️ Waiting for the second file... I need both to compare.")

# ==========================================
# MISSION 3: RETURNS ANALYSIS (1 File)
# ==========================================
elif selected_mission == "↩️ Analyze Returns":
    st.markdown("""
    <div class="mission-box">
        <b>Goal:</b> Understand why customers are returning items (Defective vs Unwanted).<br>
        <b>Files Required:</b> <span class="file-req">1 Report (FBA Customer Returns)</span>
    </div>
    """, unsafe_allow_html=True)
    
    uploaded_file = st.file_uploader("Upload 'Customer Returns' CSV", type=['csv'])
    
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        df.columns = df.columns.str.strip().str.lower()
        
        if 'reason' in df.columns:
            st.subheader("Top Return Reasons")
            counts = df['reason'].value_counts()
            st.bar_chart(counts)
            
            st.subheader("Defective Items (Action Required)")
            defects = df[df['reason'].str.contains("Defective|Damaged", case=False, na=False)]
            st.dataframe(defects)

# ==========================================
# MISSION 4: PROFIT CALCULATOR (1 File)
# ==========================================
elif selected_mission == "💰 Calculate True Profit":
    st.markdown("""
    <div class="mission-box">
        <b>Goal:</b> See your actual profit after Amazon takes their cut (Ads, Storage, Commission).<br>
        <b>Files Required:</b> <span class="file-req">1 Report (Payments - All Statements V2)</span>
    </div>
    """, unsafe_allow_html=True)
    
    uploaded_file = st.file_uploader("Upload 'Settlement Report' CSV", type=['csv'])
    
    if uploaded_file:
        st.info("Profit Logic will run here...")