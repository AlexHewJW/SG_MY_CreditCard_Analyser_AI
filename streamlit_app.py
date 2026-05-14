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
# SUMMARY (✅ MOVED UP, FIXES CHART DISAPPEAR)
# ----------------------------
if not st.session_state.master_df.empty:
    m_df = st.session_state.master_df.copy()
    m_df["Date"] = pd.to_datetime(m_df["Date"])

    col1, col2 = st.columns([1,2])

    with col1:
        st.metric("Total Spend", f"S${m_df['Amount'].sum():,.2f}")
        summary = m_df.groupby("Category")["Amount"].sum()
        st.dataframe(summary)

    with col2:
        fig = px.pie(m_df, values="Amount", names="Category", hole=0.4)
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
        work_df = st.session_state.temp_df.copy()

        work_df["Amount"] = pd.to_numeric(
            work_df["Amount"].str.replace("SGD ","").str.replace(",","")
        )

        descs = work_df["Description"].tolist()
        cats = classify_transactions_batch(descs)

        new_rows = pd.DataFrame({
            "Date": pd.to_datetime(work_df["Date"] + f" 2026", format="%d %b %Y"),
            "Description": descs,
            "Amount": work_df["Amount"],
            "Category": cats,
            "Month": "May",
            "Year": 2026
        })

        st.session_state.master_df = pd.concat([st.session_state.master_df, new_rows])

        del st.session_state["temp_df"]
        st.session_state.uploader_key += 1
        st.session_state.is_processing_pdf = False

        st.success("✅ Added transactions!")
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

            st.session_state.master_df = pd.concat([st.session_state.master_df,new])
            st.rerun()

# ----------------------------
# EDIT PAGE
# ----------------------------
if st.session_state.show_edit:
    i = st.session_state.edit_index
    row = st.session_state.master_df.loc[i]

    st.subheader("✏️ Edit Transaction")

    nd = st.text_input("Description", value=row["Description"])
    na = st.number_input("Amount", value=float(row["Amount"]))
    nt = st.date_input("Date", value=pd.to_datetime(row["Date"]))

    cats = ["Food & Dining","Transport","Groceries","Shopping","Bills","Others"]
    current_idx = cats.index(row["Category"]) if row["Category"] in cats else 5
    nc = st.selectbox("Category", cats, index=current_idx)

    c1, c2, c3 = st.columns(3)

    # ✅ SAVE
    if c1.button("Save"):
        st.session_state.master_df.at[i,"Description"] = nd
        st.session_state.master_df.at[i,"Amount"] = na
        st.session_state.master_df.at[i,"Category"] = nc
        st.session_state.master_df.at[i,"Date"] = pd.to_datetime(nt)   # ✅ FIX

        # ✅ RESET INDEX (important)
        st.session_state.master_df = st.session_state.master_df.reset_index(drop=True)

        st.session_state.show_edit = False
        st.rerun()

    # ✅ DELETE
    if c2.button("Delete"):
        st.session_state.master_df = st.session_state.master_df.drop(i)

        # ✅ RESET INDEX (important)
        st.session_state.master_df = st.session_state.master_df.reset_index(drop=True)

        st.session_state.show_edit = False
        st.rerun()

    # ✅ CANCEL
    if c3.button("Cancel"):
        st.session_state.show_edit = False
        st.rerun()

    st.stop()

# ----------------------------
# HISTORY (FIXED INDEX ALIGNMENT)
# ----------------------------
if not st.session_state.master_df.empty:
    st.subheader("📝 Transaction History")

    df = st.session_state.master_df.copy()

    # ✅ FORCE consistent datetime
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

    # ✅ SORT
    df = df.sort_values(by="Date", ascending=False)

    # ✅ USE POSITION (IMPORTANT FIX)
    for pos, (idx, row) in enumerate(df.iterrows()):
        col1, col2, col3 = st.columns([6,2,2])

        with col1:
            st.write(f"**{row['Description']}**")
            st.caption(f"{row['Category']} • {row['Date'].strftime('%d %b %Y')}")

        with col2:
            st.write(f"S$ {row['Amount']:.2f}")

        with col3:
            # ✅ USE pos for key (not idx)
            if st.button("✏️ Edit", key=f"edit_{pos}", use_container_width=True):
                st.session_state.edit_index = idx   # ✅ original index preserved
                st.session_state.show_edit = True
                st.rerun()

        st.divider()