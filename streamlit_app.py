import streamlit as st
import pandas as pd
import plotly.express as px
import pdfplumber
import re
from ai_logic import classify_transactions_batch
from datetime import datetime
from telemetry import check_db
from config import REQUIRED_COLUMNS

st.set_page_config(page_title="SG Spend Tracker", page_icon="💳", layout="wide")

# ----------------------------
# STATE INIT
# ----------------------------
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

if "is_processing_pdf" not in st.session_state:
    st.session_state.is_processing_pdf = False

if "show_edit" not in st.session_state:
    st.session_state.show_edit = False

# ----------------------------
# PDF PARSER
# ----------------------------
def extract_pdf_text(file):
    text = ""
    with pdfplumber.open(file) as pdf:
        for p in pdf.pages:
            text += p.extract_text() or ""
    return text

def extract_pdf_tables(file):
    text = extract_pdf_text(file)
    lines = text.split('\n')

    rows = [["Date", "Description", "Amount"]]
    date_regex = r"^(\d{2}\s[A-Z]{3})\s"
    current = None

    for line in lines:
        line = line.strip()
        m = re.match(date_regex, line)

        if m:
            if current:
                rows.append(current)

            nums = re.findall(r"(\d[\d,.]*\.\d{2})", line)
            date = m.group(1)

            desc = line[len(date):].strip()
            for n in nums:
                desc = desc.replace(n, "").strip()

            current = [date, desc, nums[0] if nums else "0.00"]
            continue

        if current:
            if len(current[1]) > 150 or any(x in line.upper() for x in ["PAGE", "TOTAL"]):
                rows.append(current)
                current = None
            else:
                if not re.match(r"^\d{5,}$", line):
                    current[1] += f" {line}"

    if current:
        rows.append(current)

    return rows

# ----------------------------
# DB CHECK
# ----------------------------
if "db_ok" not in st.session_state:
    ok, err = check_db()
    if not ok:
        st.error(f"DB Error: {err}")

# ----------------------------
# MASTER DATA
# ----------------------------
if "master_df" not in st.session_state:
    st.session_state.master_df = pd.DataFrame(columns=REQUIRED_COLUMNS)

st.title("💳 SG Spend Tracker")

# ----------------------------
# SUMMARY
# ----------------------------
if not st.session_state.master_df.empty:
    # Use a local copy and force numeric/datetime types immediately
    m_df = st.session_state.master_df.copy()
    m_df["Amount"] = pd.to_numeric(m_df["Amount"], errors="coerce").fillna(0.0)
    m_df["Date"] = pd.to_datetime(m_df["Date"], errors="coerce")
    
    # Drop rows that failed conversion to prevent Plotly errors
    m_df = m_df.dropna(subset=["Amount", "Date"])

    col1, col2 = st.columns([1,2])
    with col1:
        st.metric("Total Spend", f"S${m_df['Amount'].sum():,.2f}")
        summary = m_df.groupby("Category")["Amount"].sum().reset_index()
        st.dataframe(summary, hide_index=True)

    with col2:
        fig = px.pie(m_df, values="Amount", names="Category", hole=0.4)
        fig.update_layout(margin=dict(t=0, b=0, l=0, r=0))
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

# ----------------------------
# TABS
# ----------------------------
tab1, tab2 = st.tabs(["📂 Upload", "✍️ Manual"])

# ----------------------------
# UPLOAD TAB
# ----------------------------
with tab1:
    uploaded_file = st.file_uploader(
        "Upload Statement",
        type=["pdf"],
        key=f"pdf_{st.session_state.uploader_key}"
    )

    if not uploaded_file:
        st.info("📄 Upload a statement to begin")

    if uploaded_file:
        clean = extract_pdf_tables(uploaded_file)
        df = pd.DataFrame(clean[1:], columns=clean[0])

        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
        df = df[df["Amount"] > 0]
        df["Amount"] = df["Amount"].apply(lambda x: f"SGD {x:,.2f}")

        st.dataframe(df, use_container_width=True)

    # ✅ PROCESS FIRST
    if st.session_state.is_processing_pdf and "temp_df" in st.session_state:
        with st.spinner("AI is categorizing..."):
            work_df = st.session_state.temp_df.copy()

            # REMOVE FORMATTING: Convert "SGD 1,234.56" -> 1234.56 (float)
            work_df["Amount"] = (
                work_df["Amount"]
                .astype(str)
                .str.replace("SGD", "", regex=False)
                .str.replace(",", "", regex=False)
                .str.strip()
            )
            work_df["Amount"] = pd.to_numeric(work_df["Amount"], errors="coerce").fillna(0.0)

            descs = work_df["Description"].tolist()
            cats = classify_transactions_batch(descs)

            new_rows = pd.DataFrame({
                "Date": pd.to_datetime(work_df["Date"] + " 2026", format="%d %b %Y", errors='coerce'),
                "Description": descs,
                "Amount": work_df["Amount"].astype(float), # Ensure float!
                "Category": cats,
                "Month": "May",
                "Year": 2026
            }).dropna(subset=["Date"])

            # Use ignore_index to prevent duplicate index errors
            st.session_state.master_df = pd.concat([st.session_state.master_df, new_rows], ignore_index=True)

            del st.session_state["temp_df"]
            st.session_state.is_processing_pdf = False
            st.session_state.uploader_key += 1
            st.rerun()

    # ✅ GUARD (only tab-level)
    if st.session_state.is_processing_pdf:
        st.warning("Processing...")
        st.stop()

    # ✅ BUTTON
    if uploaded_file and st.button("🚀 Add to Master Tracker"):
        st.session_state.temp_df = df.copy()
        st.session_state.is_processing_pdf = True
        st.rerun()

# ----------------------------
# MANUAL ENTRY
# ----------------------------
with tab2:
    with st.form("manual"):
        d = st.text_input("Merchant")
        a = st.number_input("Amount", min_value=0.0)
        dt = st.date_input("Date")

        if st.form_submit_button("Add"):
            cat = classify_transactions_batch([d])[0]

            new = pd.DataFrame({
                "Date":[pd.to_datetime(dt)],
                "Month":[dt.strftime("%b")],
                "Year":[dt.year],
                "Description":[d],
                "Amount":[a],
                "Category":[cat]
            })

            st.session_state.master_df = pd.concat([st.session_state.master_df,new], ignore_index=True)
            st.rerun()

# ----------------------------
# EDIT PAGE
# ----------------------------
if st.session_state.show_edit:
    i = st.session_state.edit_index
    
    # Use .loc with a list then .iloc[0] to guarantee a single row object
    try:
        row = st.session_state.master_df.loc[[i]].iloc[0]
    except (KeyError, IndexError):
        st.error("Transaction no longer exists.")
        st.session_state.show_edit = False
        st.rerun()

    st.subheader("✏️ Edit Transaction")

    # Force values to primitive types (str, float) to avoid ValueError
    nd = st.text_input("Description", value=str(row["Description"]))
    na = st.number_input("Amount", value=float(row["Amount"]))
    nt = st.date_input("Date", value=pd.to_datetime(row["Date"]))

    cats = ["Food & Dining","Transport","Groceries","Shopping","Bills","Others"]
    current_cat = str(row["Category"])
    current_idx = cats.index(current_cat) if current_cat in cats else 5
    nc = st.selectbox("Category", cats, index=current_idx)

    c1, c2, c3 = st.columns(3)

    if c1.button("Save"):
        # Update using .at and ensure index is clean
        st.session_state.master_df.at[i, "Description"] = nd
        st.session_state.master_df.at[i, "Amount"] = float(na)
        st.session_state.master_df.at[i, "Category"] = nc
        st.session_state.master_df.at[i, "Date"] = pd.to_datetime(nt)
        st.session_state.master_df.at[i, "Month"] = nt.strftime("%b")
        st.session_state.master_df.at[i, "Year"] = nt.year
        
        st.session_state.master_df = st.session_state.master_df.reset_index(drop=True)
        st.session_state.show_edit = False
        st.rerun()

    if c2.button("Delete"):
        st.session_state.master_df = st.session_state.master_df.drop(i).reset_index(drop=True)
        st.session_state.show_edit = False
        st.rerun()

    if c3.button("Cancel"):
        st.session_state.show_edit = False
        st.rerun()

    st.stop()

# ----------------------------
# HISTORY (FORMAL ALIGNED TABLE)
# ----------------------------
if not st.session_state.master_df.empty:
    st.subheader("📝 Transaction History")

    # 1. Define Column Ratios
    # [Date, Description, Category, Amount, Edit_Button]
    col_widths = [1.5, 3.5, 2, 2, 1]

    # 2. Header Row
    h = st.columns(col_widths)
    h[0].caption("**DATE**")
    h[1].caption("**DESCRIPTION**")
    h[2].caption("**CATEGORY**")
    h[3].caption("**AMOUNT**")
    h[4].caption("**ACTION**")
    st.divider()

    # 3. Data Rows
    df = st.session_state.master_df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.sort_values(by="Date", ascending=False)

    for idx, row in df.iterrows():
        r = st.columns(col_widths)
        
        # Data columns
        r[0].write(f"{row['Date'].strftime('%Y-%m-%d')}")
        r[1].write(row['Description'][:30])
        r[2].write(row['Category'])
        r[3].write(f"S$ {row['Amount']:,.2f}")
        
        # The "Hidden" Clicker
        # We make the button label "Edit" but stylistically it acts as the row trigger
        if r[4].button("Edit", key=f"edit_{idx}", use_container_width=True):
            st.session_state.edit_index = idx
            st.session_state.show_edit = True
            st.rerun()
            
        # Optional: Subtle line between rows for mobile scannability
        st.markdown("<hr style='margin:0; padding:0; opacity:0.1'>", unsafe_allow_html=True)