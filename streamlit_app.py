import streamlit as st
import pandas as pd
import plotly.express as px
import pdfplumber
import re
from ai_logic import classify_transactions_batch
from datetime import datetime
from telemetry import check_db, log_manual_category_override
from config import REQUIRED_COLUMNS

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

st.set_page_config(page_title="SG Spend Tracker", page_icon="💳", layout="wide")

def extract_pdf_text(file) -> str:
    text = ""
    with pdfplumber.open(file) as pdf:
        for p in pdf.pages:
            text += p.extract_text() or ""
    return text

def extract_pdf_tables(file):
    import re
    text = extract_pdf_text(file)
    lines = text.split('\n')
    
    all_rows = [["Date", "Description", "Amount"]]
    date_regex = r"^(\d{2}\s[A-Z]{3})\s"
    
    current_tx = None

    for line in lines:
        clean_line = line.strip()
        
        # 1. Start a New Transaction
        date_match = re.match(date_regex, clean_line)
        if date_match:
            if current_tx: all_rows.append(current_tx)
            
            nums = re.findall(r"(\d[\d,.]*\.\d{2})", clean_line)
            tx_date = date_match.group(1)
            # Basic cleaning
            desc = clean_line[len(tx_date):].strip()
            desc = re.sub(r"^\d{2}\s[A-Z]{3}\s", "", desc)
            for n in nums: desc = desc.replace(n, "").strip()

            current_tx = [tx_date, desc, nums[0] if nums else "0.00"]
            continue

        # 2. Append to Description ONLY if it looks safe
        if current_tx:
            # STOP if the description gets too long (most merchants are < 100 chars)
            # OR if we hit common footer words
            if len(current_tx[1]) > 150 or any(x in clean_line.upper() for x in ["PAGE", "CHECK YOUR", "TOTAL"]):
                all_rows.append(current_tx)
                current_tx = None
            else:
                # Only add the line if it's not a random number/junk
                if not re.match(r"^\d{5,}$", clean_line):
                    current_tx[1] = f"{current_tx[1]} {clean_line}".strip()

    if current_tx: all_rows.append(current_tx)
    return all_rows

def detect_bank(text: str) -> str:
    t = text.lower()
    if "development bank of singapore" in t or "dbs bank" in t:
        return "DBS"
    if "oversea-chinese banking corporation" in t or "ocbc" in t:
        return "OCBC"
    if "united overseas bank" in t or "uob" in t:
        return "UOB"
    return "UNKNOWN"

def clean_amount(series):
    return (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("sgd", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.strip()
        .apply(lambda x: re.sub(r"[^\d\-.]", "", x))
        .astype(float, errors="ignore")
    )

# ----------------------------
# DB HEALTH CHECK (ONCE)
# ----------------------------
if "db_ok" not in st.session_state:
    # 1. Initialize DB at the start
    ok, err = check_db()
    if not ok:
        st.error(f"DB Error: {err}")


# 1. Initialize Master Data
if "master_df" not in st.session_state:
    # Ensure Date column is datetime type for sorting
    st.session_state.master_df = pd.DataFrame(columns = REQUIRED_COLUMNS)

st.title("💳 SG Multi-Month Spend Tracker")

# --- THE UPDATED EDIT DIALOG FUNCTION ---
@st.dialog("Edit Transaction")
def edit_transaction_dialog(index, row):
    st.write(f"Editing entry for **{row['Description']}**")
    
    # Original values (IMPORTANT for comparison)
    old_category = row["Category"]

    # 1. Input Fields
    new_desc = st.text_input("Description", value=row['Description'])
    new_amt = st.number_input("Amount (SGD)", value=float(row['Amount']), min_value=0.0)
    new_date = st.date_input("Date", value=pd.to_datetime(row['Date']))
    
    # 2. Category Dropdown (Pre-select the current category)
    categories = ["Food & Dining", "Transport", "Groceries", "Shopping", "Bills", "Others"]
    # Handle case where current category might not be in the list
    current_cat_index = categories.index(row['Category']) if row['Category'] in categories else 5
    new_cat = st.selectbox("Category", options=categories, index=current_cat_index)
    
    st.divider()
    
    col_save, col_ai, col_can = st.columns(3)
    
    with col_save:
        if st.button("💾 Save", type="primary", use_container_width=True):

            # Update main data
            st.session_state.master_df.at[index, 'Description'] = new_desc
            st.session_state.master_df.at[index, 'Amount'] = new_amt
            st.session_state.master_df.at[index, 'Category'] = new_cat
            st.session_state.master_df.at[index, 'Date'] = pd.to_datetime(new_date)

            # ✅ TELEMETRY: ONLY IF USER CHANGED CATEGORY
            if new_cat != old_category:
                log_manual_category_override(
                    description=new_desc,
                    amount=new_amt,
                    old_category=old_category,
                    new_category=new_cat,
                    source="manual_edit"
                )

            st.success("Updated!")
            st.rerun()

    with col_ai:
        if st.button("🤖 AI Fix", use_container_width=True):
            with st.spinner("AI thinking..."):
                # 1. Get the suggestion
                ai_suggested_cat = classify_transactions_batch([new_desc])[0]
                
                # 2. Update the session state immediately
                st.session_state.master_df.at[index, 'Description'] = new_desc
                st.session_state.master_df.at[index, 'Amount'] = new_amt
                st.session_state.master_df.at[index, 'Category'] = ai_suggested_cat
                st.session_state.master_df.at[index, 'Date'] = pd.to_datetime(new_date)
                
                # 3. Success toast (optional, will show briefly before rerun)
                st.toast(f"Updated to {ai_suggested_cat}!", icon="✅")
                
                # 4. Instant refresh
                st.rerun()

    with col_can:
        if st.button("Cancel", use_container_width=True):
            st.rerun()

# 2. Sidebar Settings
with st.sidebar:
    st.header("📅 Settings")
    default_month = st.selectbox("Current Month", ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], index=datetime.now().month - 1)
    default_year = st.selectbox("Current Year", [2024, 2025, 2026], index=2)
    if st.button("🗑️ Reset Everything"):
        st.session_state.master_df = pd.DataFrame(columns=["Date", "Month", "Year", "Description", "Amount", "Category"])
        st.rerun()

# 3. Summary Section (Charts & Metrics)
if not st.session_state.master_df.empty:
    # Always ensure master_df is sorted by Date (Newest at top)
    st.session_state.master_df['Date'] = pd.to_datetime(st.session_state.master_df['Date'])
    m_df = st.session_state.master_df.sort_values(by="Date", ascending=False)
    
    col_met, col_ch = st.columns([1, 2])
    with col_met:
        st.metric("Total Spend", f"S${m_df['Amount'].sum():,.2f}")
        st.write("### Category Summary")
        summary = m_df.groupby('Category')['Amount'].sum().reset_index()
        st.dataframe(summary.set_index('Category'), use_container_width=True)

    with col_ch:
        fig = px.pie(m_df, values='Amount', names='Category', hole=0.4, 
                     title="Spending Breakdown", color_discrete_sequence=px.colors.qualitative.Pastel)
        st.plotly_chart(fig, use_container_width=True)
    st.divider()

# 4. Entry Tabs
tab1, tab2 = st.tabs(["📂 Batch Upload (CSV)", "✍️ Manual Entry"])

# ----------------------------
# RESET FLAG (MUST BE BEFORE UPLOADER)
# ----------------------------
if st.session_state.get("clear_pdf_uploader"):
    st.session_state.pop("pdf_uploader", None)
    st.session_state["clear_pdf_uploader"] = False

with tab1:
    uploaded_file = st.file_uploader(
        "Upload OCBC Statement",
        type=["pdf"],
        key=f"pdf_uploader_{st.session_state.uploader_key}"   # ✅ dynamic key
    )

    if uploaded_file:
        with st.spinner("Processing Transactions..."):
            clean_data = extract_pdf_tables(uploaded_file)
            df = pd.DataFrame(clean_data[1:], columns=clean_data[0])

            if 'Balance' in df.columns:
                df = df.drop(columns=['Balance'])

            df['Amount'] = pd.to_numeric(
                df['Amount'].astype(str).str.replace(',', ''),
                errors='coerce'
            )
            df = df[df['Amount'] > 0].dropna(subset=['Amount'])

            df['Amount'] = df['Amount'].apply(lambda x: f"SGD {x:,.2f}")

        # ===== PREVIEW =====
        st.subheader("🔍 Cleaned Transaction Preview")
        st.dataframe(
            df,
            column_config={
                "Date": st.column_config.TextColumn("Date", width="small"),
                "Description": st.column_config.TextColumn("Description", width="large"),
                "Amount": st.column_config.TextColumn("Amount")
            },
            use_container_width=True,
            hide_index=True
        )

        # ===== PROCESSING =====
        if st.button("🚀 Add to Master Tracker"):
            with st.spinner("Finalizing data..."):
                work_df = df.copy()

                work_df['Amount'] = pd.to_numeric(
                    work_df['Amount'].str.replace('SGD ', '').str.replace(',', '')
                )

                descs = work_df['Description'].tolist()
                cats = classify_transactions_batch(descs)

                new_rows = pd.DataFrame({
                    "Date": pd.to_datetime(
                        work_df['Date'] + f" {default_year}",
                        format='%d %b %Y'
                    ),
                    "Description": descs,
                    "Amount": work_df['Amount'],
                    "Category": cats,
                    "Month": default_month,
                    "Year": default_year
                })

                st.session_state.master_df = pd.concat(
                    [st.session_state.master_df, new_rows],
                    ignore_index=True
                )

                # ✅ RESET uploader (THIS IS THE CORRECT WAY)
                st.session_state.uploader_key += 1

                st.success(f"Successfully added {len(new_rows)} transactions!")
                st.rerun()


with tab2:
    with st.form("manual_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            m_desc = st.text_input("Merchant")
            m_amt = st.number_input("Amount", min_value=0.0, step=0.1)
        with col2:
            m_date = st.date_input("Date (Optional)", value=datetime.now())
            m_cat = st.selectbox("Category", ["Auto-Detect", "Food & Dining", "Transport", "Groceries", "Shopping", "Bills", "Others"])
        
        if st.form_submit_button("➕ Add Transaction"):
            # 2. VALIDATION: Check if merchant is empty or amount is 0
            if not m_desc.strip():
                st.error("Please enter a Merchant name.")
            elif m_amt <= 0:
                st.error("Amount must be greater than 0.00.")
            else:
                cat = m_cat if m_cat != "Auto-Detect" else classify_transactions_batch([m_desc])[0]
                new_row = pd.DataFrame({
                    "Date": [pd.to_datetime(m_date)], 
                    "Month": [m_date.strftime("%b")],
                    "Year": [m_date.year], 
                    "Description": [m_desc], 
                    "Amount": [m_amt], 
                    "Category": [cat]
                })
                st.session_state.master_df = pd.concat([st.session_state.master_df, new_row], ignore_index=True)
                st.rerun()

# 5. Sorted History with Edit/Delete
if not st.session_state.master_df.empty:
    st.subheader("📝 Transaction History")
    # Sort and display
    sorted_df = st.session_state.master_df.sort_values(by="Date", ascending=False)
    
    for index, row in sorted_df.iterrows():
        with st.container():
            c1, c2, c3, c4, c5, c6 = st.columns([1.5, 2, 4, 1.5, 1, 1])
            with c1: st.write(f"*{row['Date'].strftime('%d %b %y')}*")
            with c2: st.write(f"**{row['Category']}**")
            with c3: st.write(f"{row['Description']}")
            with c4: st.write(f"S$ {row['Amount']:.2f}")
            with c5:
                if st.button("✏️", key=f"ed_{index}"):
                    edit_transaction_dialog(index, row)
            with c6:
                if st.button("🗑️", key=f"dl_{index}"):
                    st.session_state.master_df = st.session_state.master_df.drop(index)
                    st.rerun()
            st.write("---")
