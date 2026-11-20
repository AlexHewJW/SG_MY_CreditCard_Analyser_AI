import hashlib
import streamlit as st
import pandas as pd
import plotly.express as px
from ai_logic import classify_transactions_batch
from pdf_parser import extract_pdf_tables
from transaction_service import add_transactions, delete_month
from datetime import datetime
from telemetry import check_db
from config import REQUIRED_COLUMNS

st.set_page_config(
    page_title="SG Spend Tracker",
    page_icon=":material/account_balance_wallet:",
    layout="wide",
)

DEBUG_MODE = False


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

if "active_tab" not in st.session_state:
    st.session_state.active_tab = 0  # 0 = Upload, 1 = Manual

if "csv_loaded" not in st.session_state:
    st.session_state.csv_loaded = False
# ----------------------------
# DB CHECK
# ----------------------------
if "db_ok" not in st.session_state:
    st.session_state.db_ok, st.session_state.db_error = check_db()

if not st.session_state.db_ok:
    if DEBUG_MODE:
        with st.expander("Technical details"):
            st.code(st.session_state.db_error)

# ----------------------------
# MASTER DATA
# ----------------------------
if "master_df" not in st.session_state:
    st.session_state.master_df = pd.DataFrame(columns=REQUIRED_COLUMNS)

st.title("SG Spend Tracker", icon=":material/account_balance_wallet:")

st.caption("A simple view of your monthly spending.")
st.markdown(":material/info: Your transactions are saved for this session. Download a CSV backup before leaving.")

st.subheader("Add transactions")
uploaded_file = st.file_uploader(
    "Choose a statement PDF",
    type=["pdf"],
    key=f"pdf_{st.session_state.uploader_key}"
)

with st.expander("Save or restore data", expanded=False, icon=":material/save:"):
    st.download_button(
        label="Download CSV backup",
        data=st.session_state.master_df.to_csv(index=False).encode("utf-8"),
        file_name="transactions.csv",
        mime="text/csv",
        icon=":material/download:",
    )

    uploaded_csv = st.file_uploader("Restore from CSV", type=["csv"])

    if uploaded_csv is None:
        st.session_state.csv_loaded = False

    if uploaded_csv and not st.session_state.csv_loaded:
        df_loaded = pd.read_csv(uploaded_csv)

        # Ensure required columns
        for col in REQUIRED_COLUMNS:
            if col not in df_loaded.columns:
                df_loaded[col] = None

        # Normalize
        df_loaded["Date"] = pd.to_datetime(df_loaded["Date"], errors="coerce")
        df_loaded["Month"] = df_loaded["Date"].dt.strftime("%b")
        df_loaded["Year"] = df_loaded["Date"].dt.year
        df_loaded["Amount"] = pd.to_numeric(df_loaded["Amount"], errors="coerce").fillna(0)

        st.session_state.master_df = df_loaded.reset_index(drop=True)

        st.session_state.csv_loaded = True

        st.success("Your backup has been restored.")
        st.rerun()

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

# Preserve the last month selected by the previous revision-keyed dropdown.
if "month_filter_revision" in st.session_state:
    legacy_month_key = f"filter_month_{st.session_state.month_filter_revision}"
    if legacy_month_key in st.session_state:
        st.session_state.filter_month = st.session_state[legacy_month_key]
        del st.session_state[legacy_month_key]
    del st.session_state.month_filter_revision

# ✅ APPLY pending jump BEFORE widgets are created
if "reset_month_view" in st.session_state:
    reset_year, reset_month = st.session_state.reset_month_view
    st.session_state.filter_year = reset_year
    st.session_state.filter_month = reset_month
    del st.session_state.reset_month_view

if "jump_to_date" in st.session_state:
    dt = st.session_state.jump_to_date

    st.session_state.filter_year = dt.year
    st.session_state.filter_month = dt.strftime("%b")

    del st.session_state.jump_to_date

# ✅ DEFAULT INITIAL VALUE (PUT HERE)
if "filter_year" not in st.session_state:
    st.session_state.filter_year = datetime.now().year

if "filter_month" not in st.session_state:
    st.session_state.filter_month = datetime.now().strftime("%b")

filter_year_col, filter_month_col = st.columns(2)
with filter_year_col:
    selected_year = st.selectbox("Year", years, key="filter_year")
with filter_month_col:
    selected_month = st.selectbox(
        "Month",
        months,
        key="filter_month",
        format_func=lambda month: datetime.strptime(month, "%b").strftime("%B"),
    )
selected_month_label = datetime.strptime(selected_month, "%b").strftime("%B")

# ----------------------------
# SUMMARY
# ----------------------------
st.subheader(f"{selected_month_label} {selected_year}")

if not st.session_state.master_df.empty:
    m_df = st.session_state.master_df.copy()
    m_df["Date"] = pd.to_datetime(m_df["Date"], errors="coerce")

    with st.expander("Month actions", expanded=st.session_state.get("confirm_reset", False)):
        if st.button(
            "Delete this month's transactions",
            icon=":material/delete:",
        ):
            st.session_state.confirm_reset = True

        if st.session_state.get("confirm_reset"):
            st.warning("This will permanently remove every transaction for this month.")
            confirm_col, cancel_col = st.columns(2)
            if confirm_col.button("Delete transactions", type="primary"):
                st.session_state.master_df = delete_month(
                    st.session_state.master_df,
                    st.session_state.filter_year,
                    st.session_state.filter_month,
                )
                st.session_state.reset_month_view = (
                    st.session_state.filter_year,
                    st.session_state.filter_month,
                )
                st.session_state.pop("category_filter", None)
                del st.session_state.confirm_reset
                st.rerun()
            if cancel_col.button("Keep transactions"):
                del st.session_state.confirm_reset
                st.rerun()

    m_df["Date"] = pd.to_datetime(m_df["Date"], errors="coerce")
    m_df = m_df[
        (m_df["Date"].dt.year == selected_year)
        & (m_df["Date"].dt.strftime("%b") == selected_month)
    ].copy()
    m_df["Amount"] = pd.to_numeric(m_df["Amount"], errors="coerce").fillna(0.0)
    m_df = m_df.dropna(subset=["Amount", "Date"])

    metric_spend, metric_count = st.columns(2)
    metric_spend.metric("Total spending", f"S${m_df['Amount'].sum():,.2f}")
    metric_count.metric("Transactions", f"{len(m_df):,}")

    if m_df.empty:
        st.caption(":material/inbox: No transactions for this month. Add a statement or enter one manually below.")
    else:
        st.subheader("Spending by category")
        fig = px.pie(m_df, values="Amount", names="Category", hole=0.58)
        fig.update_layout(margin=dict(t=8, b=8, l=8, r=8), legend_title_text="Category")
        st.plotly_chart(fig, width="stretch")
else:
    st.caption(":material/inbox: No transactions yet. Add a statement above or enter one manually below.")

year_df = df_filter[df_filter["Year"] == selected_year].copy()
year_df["Amount"] = pd.to_numeric(year_df["Amount"], errors="coerce").fillna(0.0)
yearly_monthly_spend = (
    year_df.assign(Month=year_df["Date"].dt.strftime("%b"))
    .groupby("Month")["Amount"]
    .sum()
    .reindex(months, fill_value=0.0)
)
with st.expander(f"Compare spending across {selected_year}"):
    monthly_comparison = pd.DataFrame({"Month": months, "Spending": yearly_monthly_spend.values})
    monthly_fig = px.bar(monthly_comparison, x="Month", y="Spending")
    monthly_fig.update_layout(
        margin=dict(t=8, b=8, l=8, r=8),
        xaxis_title=None,
        yaxis_title="Spending (S$)",
    )
    st.plotly_chart(monthly_fig, width="stretch")

# ----------------------------
# TABS
# ----------------------------
tabs = st.tabs(["Upload a statement", "Add manually"])

tab1 = tabs[0]
tab2 = tabs[1]

# ----------------------------
# UPLOAD TAB
# ----------------------------
with tab1:
    if DEBUG_MODE:
        with st.expander("🔧 PDF Parser Debug", expanded=False):
            debug_file = st.file_uploader("Upload PDF to diagnose", type=["pdf"], key="debug_pdf")
            if debug_file:
                import pdfplumber
                try:
                    with pdfplumber.open(debug_file) as pdf:
                        st.write(f"**Total pages:** {len(pdf.pages)}")
                        for i, page in enumerate(pdf.pages):
                            if i > 3:
                                st.info("Showing first 4 pages only.")
                                break
                            st.markdown(f"---\n**Page {i+1}**")
                            col_a, col_b, col_c = st.columns(3)
                            text = page.extract_text() or ""
                            words = page.extract_words()
                            chars = page.chars
                            col_a.metric("extract_text chars", len(text))
                            col_b.metric("extract_words count", len(words))
                            col_c.metric("raw chars", len(chars))
                            if text.strip():
                                st.text_area(f"Raw text (page {i+1})", text[:1000], height=200)
                            elif chars:
                                sample = "".join(c["text"] for c in chars[:200])
                                st.text_area(f"Raw chars (page {i+1})", sample, height=100)
                            else:
                                st.error("No extractable text — PDF may be scanned image (needs OCR)")
                            if words:
                                st.write("**First 20 words with positions:**")
                                st.dataframe(pd.DataFrame(words[:20])[["text","x0","top","x1","bottom"]])
                            debug_file.seek(0)
                            try:
                                from pdf_parser import extract_pdf_tables
                                debug_file.seek(0)
                                raw = extract_pdf_tables(debug_file, debug=False)
                                st.write(f"**Parser output:** {len(raw)-1} rows")
                                if len(raw) > 1:
                                    st.dataframe(pd.DataFrame(raw[1:], columns=raw[0]))
                                else:
                                    st.warning("Parser returned 0 rows — check pdf_parser.py")
                            except Exception as parse_err:
                                st.error(f"Parser error: {parse_err}")
                except Exception as e:
                    st.error(f"Could not open PDF: {e}")

    if uploaded_file:
        upload_fingerprint = hashlib.sha256(uploaded_file.getvalue()).hexdigest()
        if st.session_state.get("parsed_pdf_fingerprint") != upload_fingerprint:
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
                df = pd.DataFrame(clean[1:], columns=clean[0])
                df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
                df = df.dropna(subset=["Amount"]).copy()
                df["Amount"] = df["Amount"].abs()
                df["Amount"] = df["Amount"].apply(lambda x: f"{x:,.2f}")
                st.session_state.preview_df = df.reset_index(drop=True)
                st.session_state.pdf_parse_failed = False

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

        if st.session_state.get("pdf_parse_failed"):
            st.warning("No transactions were parsed from this PDF. Check that it is a supported statement with readable transaction details.")
        if DEBUG_MODE:
            with st.expander("PDF parse diagnostics", expanded=st.session_state.get("pdf_parse_failed", False)):
                st.caption("Sanitized parser and OCR counts only. Statement text and transaction details are not included; row counts do not guarantee that every transaction was detected.")
                st.json(diagnostic_summary)
    else:
        for state_key in ("parsed_pdf_fingerprint", "preview_df", "pdf_parse_failed", "pdf_parse_diagnostics"):
            if state_key in st.session_state:
                del st.session_state[state_key]

    # ✅ render preview with delete buttons
    if "preview_df" in st.session_state and not st.session_state.preview_df.empty:
        df = st.session_state.preview_df

        st.subheader("Review imported transactions")
        st.caption("Remove any transaction that does not belong in this statement.")
        for row_index, row in df.iterrows():
            with st.container(horizontal=True, vertical_alignment="center", border=True):
                st.markdown(
                    f"**{row['Description']}**  \n{row['Date']} · S${row['Amount']}"
                )
                if st.button(
                    "Remove",
                    icon=":material/delete:",
                    key=f"preview_del_{st.session_state.parsed_pdf_fingerprint[:12]}_{row_index}",
                    help="Remove this transaction from the import.",
                ):
                    st.session_state.preview_df = (
                        df.drop(index=row_index).reset_index(drop=True)
                    )
                    st.rerun()

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

            def normalize_date(value, fallback_year):
                if pd.isna(value):
                    return pd.NaT
                s = str(value).strip()
                for fmt in ["%d %b %Y", "%d %b", "%d/%m/%Y", "%d/%m"]:
                    try:
                        return pd.to_datetime(s, format=fmt)
                    except Exception:
                        pass
                try:
                    return pd.to_datetime(s + f" {fallback_year}", format="%d %b %Y")
                except Exception:
                    try:
                        return pd.to_datetime(s + f" {fallback_year}", format="%d/%m/%Y")
                    except Exception:
                        return pd.NaT

            dates = work_df["Date"].apply(lambda x: normalize_date(x, st.session_state.filter_year))

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
                st.session_state.master_df = add_transactions(
                    st.session_state.master_df,
                    new_rows
                )

                # ✅ ✅ CRITICAL FIX: Jump to latest date
                latest_date = new_rows["Date"].max()
                st.session_state.jump_to_date = latest_date

            del st.session_state["temp_df"]
            st.session_state.is_processing_pdf = False
            st.session_state.uploader_key += 1

            for state_key in ("preview_df", "parsed_pdf_fingerprint", "pdf_parse_failed"):
                if state_key in st.session_state:
                    del st.session_state[state_key]

            st.rerun()

    # ✅ GUARD (only tab-level)
    if st.session_state.is_processing_pdf:
        st.warning("Processing...")
        st.stop()

    # ✅ BUTTONS (Add + Discard)
    if uploaded_file:
        col1, col2 = st.columns(2)

        with col1:
            if "preview_df" in st.session_state and not st.session_state.preview_df.empty and st.button("Add transactions", type="primary", width="stretch"):
                st.session_state.temp_df = df.copy()
                st.session_state.is_processing_pdf = True
                st.rerun()

        with col2:
            if st.button("Remove statement", width="stretch"):
                # ✅ clear preview and reset uploader
                if "preview_df" in st.session_state:
                    del st.session_state.preview_df
                for state_key in ("parsed_pdf_fingerprint", "pdf_parse_failed"):
                    if state_key in st.session_state:
                        del st.session_state[state_key]

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
        d = st.text_input("Merchant or description")
        a = st.number_input("Amount", min_value=0.0)
        dt = st.date_input("Date")

        submit = st.form_submit_button(
            "⏳ Adding..." if st.session_state.is_submitting_manual else "Add",
            disabled=st.session_state.is_submitting_manual
        )

    # ✅ Process AFTER form (important)
    if submit:
        st.session_state.active_tab = 1  # ✅ stay on manual tab

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

            st.session_state.master_df = add_transactions(
                st.session_state.master_df,
                new
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

    st.subheader("Edit transaction")

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
    df = st.session_state.master_df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

    # ✅ APPLY MONTH FILTER
    if "filter_year" in st.session_state and "filter_month" in st.session_state:
        df = df[
            (df["Date"].dt.year == st.session_state.filter_year) &
            (df["Date"].dt.strftime("%b") == st.session_state.filter_month)
        ]

    category_options = sorted(df["Category"].dropna().astype(str).unique().tolist())
    selected_category = st.selectbox(
        "Filter by category",
        ["All categories", *category_options],
        key="category_filter",
    )
    if selected_category != "All categories":
        df = df[df["Category"] == selected_category]

    st.subheader(f"{selected_month_label} transactions")

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
                if st.button("Edit", icon=":material/edit:", key=f"edit_{pos}"):
                    st.session_state.edit_index = idx
                    st.session_state.show_edit = True
                    st.rerun()

            st.divider()
            