import hashlib

import pandas as pd
import streamlit as st

from ai_logic import classify_transactions_batch
from config import REQUIRED_COLUMNS
from pdf_parser import extract_pdf_tables
from transaction_service import add_transactions

DEBUG_MODE = False


@st.dialog("Please wait", dismissible=False, icon="spinner")
def show_processing_dialog(message):
    st.write(message)


st.subheader("Upload a statement")
st.caption("Import a PDF statement, review the detected transactions, then add them to your tracker.")
if st.session_state.get("transaction_processing_error"):
    st.error(st.session_state.pop("transaction_processing_error"))
uploaded_file = st.file_uploader(
    "Choose a statement PDF",
    type=["pdf"],
    key=f"pdf_{st.session_state.uploader_key}",
)

if DEBUG_MODE:
    with st.expander("PDF parser debug", expanded=False):
        debug_file = st.file_uploader("Upload PDF to diagnose", type=["pdf"], key="debug_pdf")
        if debug_file:
            import pdfplumber

            try:
                with pdfplumber.open(debug_file) as pdf:
                    st.write(f"Total pages: {len(pdf.pages)}")
                    for page_index, page in enumerate(pdf.pages[:4]):
                        st.markdown(f"Page {page_index + 1}")
                        extracted_text = page.extract_text() or ""
                        st.metric("Extracted text characters", len(extracted_text))
                        if extracted_text.strip():
                            st.text_area(f"Raw text (page {page_index + 1})", extracted_text[:1000])
                        else:
                            st.warning("No extractable text. This PDF may need OCR.")
            except Exception as error:
                st.error(f"Could not open PDF: {error}")

duplicate_pdf = False
if uploaded_file:
    upload_fingerprint = hashlib.sha256(uploaded_file.getvalue()).hexdigest()
    duplicate_pdf = upload_fingerprint in st.session_state.processed_pdf_fingerprints
    if duplicate_pdf:
        st.warning(
            "This exact PDF has already been imported in this browser.",
            title="Statement already imported",
        )
        if st.button("Choose a different statement", icon=":material/upload_file:"):
            for state_key in (
                "parsed_pdf_fingerprint",
                "preview_df",
                "pdf_parse_failed",
                "pdf_parse_diagnostics",
                "preview_editor_revision",
            ):
                st.session_state.pop(state_key, None)
            st.session_state.uploader_key += 1
            st.rerun()
    elif st.session_state.get("parsed_pdf_fingerprint") != upload_fingerprint:
        show_processing_dialog("Reading your statement and finding transactions…")
        parse_diagnostics = {}
        try:
            clean = extract_pdf_tables(uploaded_file, diagnostics=parse_diagnostics)
        except Exception as parse_error:
            clean = [["Date", "Description", "Amount"]]
            parse_diagnostics["parse_error"] = type(parse_error).__name__

        st.session_state.parsed_pdf_fingerprint = upload_fingerprint
        st.session_state.pdf_parse_diagnostics = parse_diagnostics

        if len(clean) <= 1:
            st.session_state.preview_df = pd.DataFrame(columns=["Date", "Description", "Amount"])
            st.session_state.pdf_parse_failed = True
        else:
            preview = pd.DataFrame(clean[1:], columns=clean[0])
            preview["Amount"] = pd.to_numeric(preview["Amount"], errors="coerce")
            preview = preview.dropna(subset=["Amount"]).copy()
            preview["Amount"] = preview["Amount"].abs()
            st.session_state.preview_df = preview.reset_index(drop=True)
            st.session_state.pdf_parse_failed = False
        st.rerun()

    parse_diagnostics = st.session_state.get("pdf_parse_diagnostics", {})
    ocr_diagnostics = parse_diagnostics.get("ocr", {})
    diagnostic_summary = {
        key: parse_diagnostics[key]
        for key in (
            "parser_route",
            "parsed_rows",
            "pdf_pages",
            "text_characters_by_page",
            "python_version",
            "package_versions",
            "parse_error",
        )
        if key in parse_diagnostics
    }
    if ocr_diagnostics:
        diagnostic_summary["ocr"] = {
            key: ocr_diagnostics[key]
            for key in (
                "available",
                "missing_dependencies",
                "pages",
                "detections_by_page",
                "header_pages",
                "fallback_pass_used",
                "fallback_detections_by_page",
                "ocr_rows_collected",
                "hsbc_date_crop_attempts",
                "hsbc_date_crop_recoveries",
                "error",
            )
            if key in ocr_diagnostics
        }

    if not duplicate_pdf and st.session_state.get("pdf_parse_failed"):
        st.warning("No transactions were detected. Check that the PDF is a supported statement with readable transaction details.")
    if not duplicate_pdf and DEBUG_MODE:
        with st.expander("PDF parse diagnostics", expanded=st.session_state.get("pdf_parse_failed", False)):
            st.json(diagnostic_summary)
else:
    for state_key in (
        "parsed_pdf_fingerprint",
        "preview_df",
        "pdf_parse_failed",
        "pdf_parse_diagnostics",
        "preview_editor_revision",
    ):
        st.session_state.pop(state_key, None)

if uploaded_file and not duplicate_pdf and not st.session_state.get("pdf_parse_failed"):
    preview_df = st.session_state.get("preview_df", pd.DataFrame())
    if not preview_df.empty:
        st.subheader("Review imported transactions")
        st.caption("Check the imported details before adding them to your tracker. Amounts are in S$.")
        if "preview_editor_revision" not in st.session_state:
            st.session_state.preview_editor_revision = 0

        editor_key = (
            f"preview_editor_{st.session_state.parsed_pdf_fingerprint[:12]}_"
            f"{st.session_state.preview_editor_revision}"
        )
        preview_rows = preview_df.reset_index(drop=True).copy()
        if "Delete" not in preview_rows.columns:
            preview_rows.insert(0, "Delete", False)

        if st.button(
            "Add a transaction",
            icon=":material/add:",
            help="Add a row if the statement contains a transaction the parser missed.",
        ):
            preview_rows = pd.concat(
                [
                    preview_rows,
                    pd.DataFrame([{"Delete": False, "Date": "", "Description": "", "Amount": 0.0}]),
                ],
                ignore_index=True,
            )
            st.session_state.preview_df = preview_rows
            st.session_state.preview_editor_revision += 1
            st.rerun()

        edited_preview = st.data_editor(
            preview_rows,
            key=editor_key,
            column_config={
                "Delete": st.column_config.CheckboxColumn(
                    "Delete",
                    width=62,
                    help="Select rows to remove from this import.",
                ),
                "Date": st.column_config.TextColumn("Date", width=74),
                "Description": st.column_config.TextColumn("Merchant", width=130),
                "Amount": st.column_config.NumberColumn(
                    "Amount",
                    width=82,
                    format="S$%.2f",
                    min_value=0.0,
                    step=0.01,
                ),
            },
            num_rows="fixed",
            hide_index=True,
            width="stretch",
            height=300,
            alt="Imported transactions ready for review",
        ).reset_index(drop=True)
        st.session_state.preview_df = edited_preview

        selected_for_deletion = edited_preview["Delete"].fillna(False)
        delete_col, add_col, discard_col = st.columns(3)
        if delete_col.button(
            "Delete selected",
            icon=":material/delete:",
            disabled=not selected_for_deletion.any(),
            width="stretch",
        ):
            st.session_state.preview_df = (
                edited_preview.loc[~selected_for_deletion]
                .drop(columns="Delete")
                .reset_index(drop=True)
            )
            st.session_state.preview_editor_revision += 1
            st.rerun()

        if add_col.button("Add transactions", type="primary", width="stretch"):
            st.session_state.temp_df = (
                edited_preview.drop(columns="Delete", errors="ignore").copy()
            )
            st.session_state.is_processing_pdf = True
            st.rerun()

        if discard_col.button("Remove statement", width="stretch"):
            for state_key in (
                "preview_df",
                "parsed_pdf_fingerprint",
                "pdf_parse_failed",
                "pdf_parse_diagnostics",
                "preview_editor_revision",
            ):
                st.session_state.pop(state_key, None)
            st.session_state.uploader_key += 1
            st.rerun()

if st.session_state.is_processing_pdf and "temp_df" in st.session_state:
    show_processing_dialog("Categorizing transactions and adding them to your tracker…")
    with st.spinner("Adding transactions..."):
        work_df = st.session_state.temp_df.copy()
        work_df = work_df.drop(columns="Delete", errors="ignore")
        work_df["Amount"] = pd.to_numeric(work_df["Amount"], errors="coerce")
        work_df["Description"] = work_df["Description"].fillna("").astype(str).str.strip()
        work_df["Date"] = work_df["Date"].fillna("").astype(str).str.strip()
        work_df = work_df[
            (work_df["Description"] != "")
            & (work_df["Date"] != "")
            & work_df["Amount"].notna()
        ].copy()

        def normalize_date(value, fallback_year):
            for date_format in ("%d %b %Y", "%d %b", "%d/%m/%Y", "%d/%m"):
                try:
                    parsed_date = pd.to_datetime(value, format=date_format)
                    if date_format in ("%d %b", "%d/%m"):
                        parsed_date = parsed_date.replace(year=fallback_year)
                    return parsed_date
                except (TypeError, ValueError):
                    continue
            return pd.NaT

        dates = work_df["Date"].apply(lambda value: normalize_date(value, st.session_state.filter_year))
        descriptions = work_df["Description"].tolist()
        try:
            categories = classify_transactions_batch(descriptions) if descriptions else []
        except Exception:
            st.session_state.is_processing_pdf = False
            st.session_state.pop("temp_df", None)
            st.session_state.transaction_processing_error = (
                "Could not categorize the transactions. Please try again."
            )
            st.rerun()
        new_rows = pd.DataFrame(
            {
                "Date": dates,
                "Description": descriptions,
                "Amount": work_df["Amount"].astype(float),
                "Category": categories,
                "Month": dates.dt.strftime("%b"),
                "Year": dates.dt.year,
            }
        ).dropna(subset=["Date"])

        if not new_rows.empty:
            st.session_state.master_df = add_transactions(st.session_state.master_df, new_rows)
            st.session_state.jump_to_date = new_rows["Date"].max()
            pdf_fingerprint = st.session_state.get("parsed_pdf_fingerprint")
            if pdf_fingerprint and pdf_fingerprint not in st.session_state.processed_pdf_fingerprints:
                st.session_state.processed_pdf_fingerprints.append(pdf_fingerprint)

        for state_key in ("temp_df", "preview_df", "parsed_pdf_fingerprint", "pdf_parse_failed"):
            st.session_state.pop(state_key, None)
        st.session_state.is_processing_pdf = False
        st.session_state.uploader_key += 1
        st.success(f"Added {len(new_rows)} transaction(s).")
        st.switch_page("app_pages/overview.py")

st.divider()
st.subheader("Add a transaction manually")
with st.form("manual_transaction"):
    description = st.text_input("Merchant or description")
    amount = st.number_input("Amount (S$)", min_value=0.0, step=0.01)
    transaction_date = st.date_input("Date")
    submit_manual = st.form_submit_button("Add transaction", type="primary")

if submit_manual:
    if not description.strip():
        st.warning("Enter a merchant or description first.")
    else:
        st.session_state.temp_manual = {
            "Description": description.strip(),
            "Amount": amount,
            "Date": transaction_date,
        }
        st.session_state.is_submitting_manual = True
        st.rerun()

if st.session_state.is_submitting_manual and "temp_manual" in st.session_state:
    show_processing_dialog("Categorizing and adding your transaction…")
    with st.spinner("Adding transaction..."):
        data = st.session_state.temp_manual
        try:
            category = classify_transactions_batch([data["Description"]])[0]
        except Exception:
            st.session_state.is_submitting_manual = False
            st.session_state.pop("temp_manual", None)
            st.session_state.transaction_processing_error = (
                "Could not categorize the transaction. Please try again."
            )
            st.rerun()
        new_row = pd.DataFrame(
            {
                "Date": [pd.to_datetime(data["Date"])],
                "Month": [data["Date"].strftime("%b")],
                "Year": [data["Date"].year],
                "Description": [data["Description"]],
                "Amount": [data["Amount"]],
                "Category": [category],
            }
        )
        st.session_state.master_df = add_transactions(st.session_state.master_df, new_row)
        st.session_state.jump_to_date = data["Date"]
        st.session_state.pop("temp_manual", None)
        st.session_state.is_submitting_manual = False
        st.success("Transaction added.")
        st.switch_page("app_pages/overview.py")
