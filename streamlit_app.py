import datetime
import hashlib
import json

import pandas as pd
import streamlit as st

from browser_storage import browser_transaction_storage
from config import REQUIRED_COLUMNS
from telemetry import check_db

st.set_page_config(
    page_title="SG Spend Tracker",
    page_icon=":material/account_balance_wallet:",
    layout="wide",
)


@st.dialog("Please wait", dismissible=False, icon="spinner")
def show_restore_dialog():
    st.write("Restoring your transactions from the backup...")


if "master_df" not in st.session_state:
    st.session_state.master_df = pd.DataFrame(columns=REQUIRED_COLUMNS)
if "browser_storage_loaded" not in st.session_state:
    st.session_state.browser_storage_loaded = False
if "processed_pdf_fingerprints" not in st.session_state:
    st.session_state.processed_pdf_fingerprints = []
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

transaction_records = json.loads(
    st.session_state.master_df.to_json(orient="records", date_format="iso")
)
storage_result = browser_transaction_storage(
    storage_key="sg-spend-tracker-transactions-v1",
    ready=st.session_state.browser_storage_loaded,
    transactions=transaction_records,
    processed_pdf_fingerprints=st.session_state.processed_pdf_fingerprints,
)

if not st.session_state.browser_storage_loaded:
    if storage_result.loaded is None:
        st.caption("Restoring your transactions from this browser…")
        st.stop()

    loaded_data = storage_result.loaded
    if loaded_data.get("error"):
        st.session_state.browser_storage_error = loaded_data["error"]
    else:
        st.session_state.processed_pdf_fingerprints = list(
            dict.fromkeys(loaded_data.get("processedPdfFingerprints", []))
        )
        stored_df = pd.DataFrame(loaded_data.get("transactions", []))
        if not stored_df.empty:
            for column in REQUIRED_COLUMNS:
                if column not in stored_df.columns:
                    stored_df[column] = None
            stored_df["Date"] = pd.to_datetime(stored_df["Date"], errors="coerce")
            stored_df["Month"] = stored_df["Date"].dt.strftime("%b")
            stored_df["Year"] = stored_df["Date"].dt.year
            stored_df["Amount"] = pd.to_numeric(
                stored_df["Amount"], errors="coerce"
            ).fillna(0.0)
            st.session_state.master_df = stored_df[REQUIRED_COLUMNS].reset_index(drop=True)
    st.session_state.browser_storage_loaded = True
    st.rerun()

st.title("SG Spend Tracker", icon=":material/account_balance_wallet:")
st.caption("A simple view of your monthly spending.")
st.markdown(":material/info: Transactions save in this browser. Download a CSV backup to keep a separate copy.")
if st.session_state.get("browser_storage_error") or storage_result.save_error:
    st.warning(
        st.session_state.get("browser_storage_error")
        or storage_result.save_error
        or "Browser storage is unavailable. Download a CSV backup to keep your data."
    )

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
        st.session_state.pop("csv_restore_fingerprint", None)
        st.session_state.pop("csv_restore_error", None)
    elif st.session_state.get("csv_restore_fingerprint") != hashlib.sha256(uploaded_csv.getvalue()).hexdigest():
        show_restore_dialog()
        try:
            restored_df = pd.read_csv(uploaded_csv)
            for column in REQUIRED_COLUMNS:
                if column not in restored_df.columns:
                    restored_df[column] = None

            restored_df["Date"] = pd.to_datetime(restored_df["Date"], errors="coerce")
            restored_df["Month"] = restored_df["Date"].dt.strftime("%b")
            restored_df["Year"] = restored_df["Date"].dt.year
            restored_df["Amount"] = pd.to_numeric(restored_df["Amount"], errors="coerce").fillna(0.0)
            st.session_state.master_df = restored_df.reset_index(drop=True)
            st.session_state.pop("csv_restore_error", None)
        except (ValueError, UnicodeError, pd.errors.ParserError):
            st.session_state.csv_restore_error = "Could not read the backup. Please choose a valid CSV file."
        st.session_state.csv_loaded = True
        st.session_state.csv_restore_fingerprint = hashlib.sha256(uploaded_csv.getvalue()).hexdigest()
        st.rerun()
    if st.session_state.get("csv_restore_error"):
        st.error(st.session_state.csv_restore_error)

page = st.navigation(
    [
        st.Page("app_pages/overview.py", title="Overview", icon=":material/dashboard:"),
        st.Page("app_pages/add_transactions.py", title="Add transactions", icon=":material/add_circle:"),
    ],
    position="top",
)
page.run()
