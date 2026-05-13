import streamlit as st
import pandas as pd
import plotly.express as px
import pdfplumber
import re
from ai_logic import classify_transactions_batch
from datetime import datetime
from telemetry import check_db, log_manual_category_override
from config import REQUIRED_COLUMNS

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
    
    all_rows = []
    # Headers stay for the DataFrame structure
    all_rows.append(["Date", "Description", "Amount", "Balance"])

    date_regex = r"^(\d{2}\s[A-Z]{3})\s"
    # List of keywords that mean "this is a footer or bank info, not a spend"
    noise_keywords = [
        "STATEMENT OF ACCOUNT", "OCBC Bank", "Page", "Account No", 
        "BALANCE B/F", "BALANCE C/F", "Total Withdrawals", "Deposit Insurance",
        "Co. Reg. No", "Singapore dollar deposits", "65 Chulia Street"
    ]
    
    current_tx = None

    for line in lines:
        line = line.strip()
        # Skip if line is empty or matches known noise
        if not line or any(k in line for k in noise_keywords):
            continue

        date_match = re.match(date_regex, line)

        if date_match:
            if current_tx:
                all_rows.append(current_tx)
            
            # Extract numbers
            nums = re.findall(r"(\d[\d,.]*\.\d{2})", line)
            tx_date = date_match.group(1)
            
            # Clean up the initial description line
            desc_start = line[len(tx_date):].strip()
            # Remove the transaction value date (OCBC repeats the date twice)
            desc_start = re.sub(r"^\d{2}\s[A-Z]{3}\s", "", desc_start)
            
            for n in nums:
                desc_start = desc_start.replace(n, "").strip()

            current_tx = [
                tx_date, 
                desc_start, 
                nums[0] if len(nums) > 1 else (nums[0] if len(nums) == 1 else "0.00"),
                nums[-1] if nums else "0.00"
            ]

        elif current_tx:
            # If the line is an ID number (like 23063506), it's noise for the AI
            # We only append it if it looks like a merchant name (mostly letters)
            if not re.match(r"^\d{5,}$", line): 
                current_tx[1] = f"{current_tx[1]} {line}".strip()

    if current_tx:
        all_rows.append(current_tx)
        
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


with tab1:
    uploaded_file = st.file_uploader("Upload OCBC Statement", type=["pdf"])

    if uploaded_file:
        with st.spinner("Processing Transactions..."):
            # 1. Extract and Filter
            clean_data = extract_pdf_tables(uploaded_file)
            
            # 2. Convert to DataFrame
            df = pd.DataFrame(clean_data[1:], columns=clean_data[0])

            # 3. Drop Balance column immediately to avoid confusion
            if 'Balance' in df.columns:
                df = df.drop(columns=['Balance'])

            # 4. Clean numeric data
            # Strip commas and convert to float for logic
            df['Amount'] = pd.to_numeric(df['Amount'].astype(str).str.replace(',', ''), errors='coerce')
            
            # Remove zeros/NaNs (like balance forward lines)
            df = df[df['Amount'] > 0].dropna(subset=['Amount'])

            # 5. Format for UI: Add SGD and force Left Alignment
            # We convert to string here to ensure it aligns left in the table
            df['Amount'] = df['Amount'].apply(lambda x: f"SGD {x:,.2f}")

        # ===== PREVIEW & MAPPING =====
        st.subheader("Final Data for AI Processing")
        
        # Display clean version without Balance
        st.dataframe(
            df,
            column_config={
                "Date": st.column_config.TextColumn("Date", width="small"),
                "Description": st.column_config.TextColumn("Description", width="large"),
                "Amount": st.column_config.TextColumn("Amount") # Left Aligned
            },
            use_container_width=True,
            hide_index=True
        )

        # c_desc = st.selectbox("Description Column", df.columns, index=1)
        # c_amt  = st.selectbox("Amount Column (Withdrawal)", df.columns, index=2)
        # c_date = st.selectbox("Date Column", ["<None>"] + list(df.columns), index=1)

        if st.button("🚀 Process & Add Transactions"):
            work = df.copy()

            # Amount cleaning
            work[c_amt] = clean_amount(work[c_amt])

            # Date handling
            if c_date != "<None>":
                work["__date"] = pd.to_datetime(work[c_date], errors="coerce")
            else:
                work["__date"] = pd.Timestamp.today()

            # Validation
            work = work[
                (work[c_amt] > 0) &
                work[c_desc].notna() &
                (work[c_desc].astype(str).str.strip() != "")
            ]

            if work.empty:
                st.error("No valid transactions after cleaning.")
                st.stop()

            # ===== AI CATEGORY =====
            with st.spinner(f"AI categorizing {len(work)} rows…"):
                descs = work[c_desc].astype(str).tolist()
                cats = classify_transactions_batch(descs)

            new_rows = pd.DataFrame({
                "Date": work["__date"],
                "Month": default_month,
                "Year": default_year,
                "Description": descs,
                "Amount": work[c_amt].astype(float),
                "Category": cats
            })

            st.session_state.master_df = pd.concat(
                [st.session_state.master_df, new_rows],
                ignore_index=True
            )

            st.success(f"Added {len(new_rows)} transactions ✅")
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
