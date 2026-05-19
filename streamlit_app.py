import streamlit as st
import pandas as pd
import plotly.express as px
import pdfplumber
import re
from ai_logic import classify_transactions_batch
from datetime import datetime
from telemetry import check_db
from config import REQUIRED_COLUMNS

st.markdown("""
<style>
button {
    border: 1px solid #e0e0e0 !important;   /* ✅ border added */
    border-radius: 4px !important;
    text-align: left !important;
    padding: 6px 8px !important;
    background: white !important;
    width: 100% !important;
    font-family: monospace !important;
    font-size: 14px;
}

button:hover {
    background-color: #f5f5f5 !important;
    border-color: #bdbdbd !important;
}
</style>
""", unsafe_allow_html=True)

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

if "is_submitting_manual" not in st.session_state:
    st.session_state.is_submitting_manual = False


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
# MONTH / YEAR FILTER
# ----------------------------
df_filter = st.session_state.master_df.copy()

df_filter["Date"] = pd.to_datetime(df_filter["Date"], errors="coerce")
df_filter = df_filter.dropna(subset=["Date"])

df_filter["Year"] = df_filter["Date"].dt.year
df_filter["Month"] = df_filter["Date"].dt.strftime("%b")

current_year = datetime.now().year
years = list(range(1996, current_year + 1))
years = sorted(years, reverse=True)
months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

# ✅ APPLY pending jump BEFORE widgets are created
if "jump_to_date" in st.session_state:
    dt = st.session_state.jump_to_date

    st.session_state.filter_year = dt.year
    st.session_state.filter_month = dt.strftime("%b")

    del st.session_state.jump_to_date

col1, col2 = st.columns(2)

with col1:
    selected_year = st.selectbox("Year", years, key="filter_year")

with col2:
    selected_month = st.selectbox("Month", months, key="filter_month")

# ✅ DEFAULT INITIAL VALUE (PUT HERE)
if "filter_year" not in st.session_state:
    st.session_state.filter_year = datetime.now().year

if "filter_month" not in st.session_state:
    st.session_state.filter_month = datetime.now().strftime("%b")

# ----------------------------
# SUMMARY
# ----------------------------
if not st.session_state.master_df.empty:
    m_df = st.session_state.master_df.copy()
    m_df["Date"] = pd.to_datetime(m_df["Date"], errors="coerce")

    # ✅ RESET MONTH (top, very visible)
    col_reset, _ = st.columns([1, 5])
    with col_reset:
        if st.button("🧹 Reset This Month", use_container_width=True):
            st.session_state.confirm_reset = True

    # ✅ CONFIRMATION UI
    if st.session_state.get("confirm_reset"):
        st.warning("Confirm delete ALL transactions for this month?")
        c1, c2 = st.columns(2)

        if c1.button("✅ Yes, delete", use_container_width=True):
            df = st.session_state.master_df.copy()
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

            df = df[
                ~(
                    (df["Date"].dt.year == st.session_state.filter_year) &
                    (df["Date"].dt.strftime("%b") == st.session_state.filter_month)
                )
            ]

            st.session_state.master_df = df.reset_index(drop=True)

            # clear category filter if exists
            if "selected_category" in st.session_state:
                del st.session_state["selected_category"]

            del st.session_state.confirm_reset
            st.rerun()

        if c2.button("Cancel", use_container_width=True):
            del st.session_state.confirm_reset
            st.rerun()

    # ✅ FILTER CURRENT MONTH
    if "filter_year" in st.session_state and "filter_month" in st.session_state:
        m_df = m_df[
            (m_df["Date"].dt.year == st.session_state.filter_year) &
            (m_df["Date"].dt.strftime("%b") == st.session_state.filter_month)
        ]

    # ✅ CLEAN TYPES
    m_df["Amount"] = pd.to_numeric(m_df["Amount"], errors="coerce").fillna(0.0)
    m_df = m_df.dropna(subset=["Amount", "Date"])

    col1, col2 = st.columns([1, 2])

    # ✅ LEFT SIDE (summary table buttons)
    with col1:
        st.metric("Total Spend", f"S${m_df['Amount'].sum():,.2f}")

        summary = m_df.groupby("Category")["Amount"].sum().reset_index()

        st.subheader("By Category")

        if "selected_category" in st.session_state:
            if st.button("❌ Reset Filter", key="clear_filter_top"):
                del st.session_state["selected_category"]
                st.rerun()

        for i, row in summary.iterrows():
            text = f"{row['Category']:<25} S$ {row['Amount']:>10,.2f}"

            if st.button(text, key=f"cat_{i}", use_container_width=True):
                st.session_state.selected_category = row["Category"]

    # ✅ RIGHT SIDE (chart)
    with col2:
        if m_df.empty:
            st.info("No data for selected month.")
        else:
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

    if uploaded_file:
        clean = extract_pdf_tables(uploaded_file)
        df = pd.DataFrame(clean[1:], columns=clean[0])

        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
        df = df[df["Amount"] > 0]
        df["Amount"] = df["Amount"].apply(lambda x: f"SGD {x:,.2f}")

        # ✅ store preview so deletion persists
        if "preview_df" not in st.session_state:
            st.session_state.preview_df = df.reset_index(drop=True)

    # ✅ render preview with delete buttons
    if "preview_df" in st.session_state and not st.session_state.preview_df.empty:
        df = st.session_state.preview_df

        st.subheader("Preview")

        for i, row in df.iterrows():
            col1, col2, col3, col4 = st.columns([2,6,2,1])

            with col1:
                st.write(row["Date"])

            with col2:
                st.write(row["Description"])

            with col3:
                st.write(row["Amount"])

            with col4:
                if st.button("🗑", key=f"preview_del_{i}"):
                    st.session_state.preview_df = df.drop(i).reset_index(drop=True)
                    st.rerun()

        st.divider()

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

            
            dates = pd.to_datetime(
                work_df["Date"] + f" {st.session_state.filter_year}",
                format="%d %b %Y",
                errors='coerce'
            )


            new_rows = pd.DataFrame({
                "Date": dates,
                "Description": descs,
                "Amount": work_df["Amount"].astype(float), # Ensure float!
                "Category": cats,
                "Month": dates.dt.strftime("%b"),
                "Year": dates.dt.year
            }).dropna(subset=["Date"])

            
            # ✅ ADD TO MASTER
            if not new_rows.empty:
                st.session_state.master_df = pd.concat(
                    [st.session_state.master_df, new_rows],
                    ignore_index=True
                )

                # ✅ ✅ CRITICAL FIX: Jump to latest date
                latest_date = new_rows["Date"].max()
                st.session_state.jump_to_date = latest_date


            del st.session_state["temp_df"]
            st.session_state.is_processing_pdf = False
            st.session_state.uploader_key += 1

            if "preview_df" in st.session_state:
                del st.session_state.preview_df

            st.rerun()

    # ✅ GUARD (only tab-level)
    if st.session_state.is_processing_pdf:
        st.warning("Processing...")
        st.stop()

    # ✅ BUTTONS (Add + Discard)
    if uploaded_file:
        col1, col2 = st.columns(2)

        with col1:
            if st.button("🚀 Add to Master Tracker", use_container_width=True):
                st.session_state.temp_df = df.copy()
                st.session_state.is_processing_pdf = True
                st.rerun()

        with col2:
            if st.button("❌ Discard", use_container_width=True):
                # ✅ clear preview and reset uploader
                if "preview_df" in st.session_state:
                    del st.session_state.preview_df

                st.session_state.uploader_key += 1  # reset file uploader
                st.rerun()

# ----------------------------
# MANUAL ENTRY
# ----------------------------
with tab2:
    # ✅ Init state
    if "is_submitting_manual" not in st.session_state:
        st.session_state.is_submitting_manual = False

    with st.form("manual"):
        d = st.text_input("Merchant")
        a = st.number_input("Amount", min_value=0.0)
        dt = st.date_input("Date")

        submit = st.form_submit_button(
            "⏳ Adding..." if st.session_state.is_submitting_manual else "Add",
            disabled=st.session_state.is_submitting_manual
        )

    # ✅ Process AFTER form (important)
    if submit:
        st.session_state.temp_manual = {
            "Description": d,
            "Amount": a,
            "Date": dt
        }
        st.session_state.is_submitting_manual = True
        st.rerun()

    # ✅ Handle processing safely
    if st.session_state.is_submitting_manual and "temp_manual" in st.session_state:
        with st.spinner("Adding transaction..."):
            data = st.session_state.temp_manual

            cat = classify_transactions_batch([data["Description"]])[0]

            new = pd.DataFrame({
                "Date": [pd.to_datetime(data["Date"])],
                "Month": [data["Date"].strftime("%b")],
                "Year": [data["Date"].year],
                "Description": [data["Description"]],
                "Amount": [data["Amount"]],
                "Category": [cat]
            })

            st.session_state.master_df = pd.concat(
                [st.session_state.master_df, new],
                ignore_index=True
            )

           
            # ✅ Schedule jump (safe)
            st.session_state.jump_to_date = data["Date"]


            # ✅ cleanup
            del st.session_state.temp_manual
            st.session_state.is_submitting_manual = False

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
# HISTORY
# ----------------------------
if not st.session_state.master_df.empty:
    if "selected_category" in st.session_state:
        st.subheader(f"📝 {st.session_state.selected_category} Transactions")
    else:
        st.subheader("📝 All Transactions")

    
    df = st.session_state.master_df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

    
    if "filter_year" in st.session_state and "filter_month" in st.session_state:
        df = df[
            (df["Date"].dt.year == st.session_state.filter_year) &
            (df["Date"].dt.strftime("%b") == st.session_state.filter_month)
        ]

    # ✅ FILTER LOGIC
    if "selected_category" in st.session_state:
        df = df[df["Category"] == st.session_state.selected_category]

    # ✅ SORT
    df = df.sort_values(by="Date", ascending=False)

    # ✅ EMPTY CASE
    if df.empty:
        st.info("No transactions found.")
    else:
        for pos, (idx, row) in enumerate(df.iterrows()):
            col1, col2, col3 = st.columns([6,2,2])

            with col1:
                st.write(f"**{row['Description']}**")
                st.caption(f"{row['Category']} • {row['Date'].strftime('%d %b %Y')}")

            with col2:
                st.write(f"S$ {row['Amount']:.2f}")

            with col3:
                # ✅ EDIT ALWAYS AVAILABLE
                if st.button("✏️ Edit", key=f"edit_{pos}", use_container_width=True):
                    st.session_state.edit_index = idx
                    st.session_state.show_edit = True
                    st.rerun()

            st.divider()
