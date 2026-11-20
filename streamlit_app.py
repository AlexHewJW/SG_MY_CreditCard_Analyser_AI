import datetime

import pandas as pd
import streamlit as st

from config import REQUIRED_COLUMNS
from telemetry import check_db

st.set_page_config(
    page_title="SG Spend Tracker",
    page_icon=":material/account_balance_wallet:",
    layout="wide",
)

if "master_df" not in st.session_state:
    st.session_state.master_df = pd.DataFrame(columns=REQUIRED_COLUMNS)
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0
if "is_processing_pdf" not in st.session_state:
    st.session_state.is_processing_pdf = False
if "is_submitting_manual" not in st.session_state:
    st.session_state.is_submitting_manual = False
if "show_edit" not in st.session_state:
    st.session_state.show_edit = False
if "filter_year" not in st.session_state:
    st.session_state.filter_year = datetime.datetime.now().year
if "filter_month" not in st.session_state:
    st.session_state.filter_month = datetime.datetime.now().strftime("%b")
if "csv_loaded" not in st.session_state:
    st.session_state.csv_loaded = False

if "db_ok" not in st.session_state:
    st.session_state.db_ok, st.session_state.db_error = check_db()

st.title("SG Spend Tracker", icon=":material/account_balance_wallet:")
st.caption("A simple view of your monthly spending.")
st.markdown(":material/info: Your transactions are saved for this session. Download a CSV backup before leaving.")

with st.expander("Save or restore data", expanded=False, icon=":material/save:"):
    st.download_button(
        label="Download CSV backup",
        data=st.session_state.master_df.to_csv(index=False).encode("utf-8"),
        file_name="transactions.csv",
        mime="text/csv",
        icon=":material/download:",
    )

    uploaded_csv = st.file_uploader("Restore from CSV", type=["csv"], key="restore_csv")
    if uploaded_csv is None:
        st.session_state.csv_loaded = False
    elif not st.session_state.csv_loaded:
        restored_df = pd.read_csv(uploaded_csv)
        for column in REQUIRED_COLUMNS:
            if column not in restored_df.columns:
                restored_df[column] = None

        restored_df["Date"] = pd.to_datetime(restored_df["Date"], errors="coerce")
        restored_df["Month"] = restored_df["Date"].dt.strftime("%b")
        restored_df["Year"] = restored_df["Date"].dt.year
        restored_df["Amount"] = pd.to_numeric(restored_df["Amount"], errors="coerce").fillna(0.0)
        st.session_state.master_df = restored_df.reset_index(drop=True)
        st.session_state.csv_loaded = True
        st.success("Your backup has been restored.")
        st.rerun()

page = st.navigation(
    [
        st.Page("app_pages/overview.py", title="Overview", icon=":material/dashboard:"),
        st.Page("app_pages/add_transactions.py", title="Add transactions", icon=":material/add_circle:"),
    ],
    position="top",
)
page.run()
