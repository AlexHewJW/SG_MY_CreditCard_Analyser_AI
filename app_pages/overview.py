import datetime

import altair as alt
import pandas as pd
import plotly.express as px
import streamlit as st

from transaction_service import delete_month

overview_heading, add_action = st.columns([3, 2], vertical_alignment="bottom")
with overview_heading:
    st.subheader("Monthly overview")
    st.caption("Review your spending and transactions by month.")
with add_action:
    if st.button(
        "Add transactions",
        icon=":material/add_circle:",
        type="primary",
        width="stretch",
    ):
        st.switch_page("app_pages/add_transactions.py")

current_year = datetime.datetime.now().year
years = list(range(1996, current_year + 1))[::-1]
months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

if "month_filter_revision" in st.session_state:
    legacy_month_key = f"filter_month_{st.session_state.month_filter_revision}"
    if legacy_month_key in st.session_state:
        st.session_state.filter_month = st.session_state[legacy_month_key]
        del st.session_state[legacy_month_key]
    del st.session_state.month_filter_revision

if "reset_month_view" in st.session_state:
    reset_year, reset_month = st.session_state.reset_month_view
    st.session_state.filter_year = reset_year
    st.session_state.filter_month = reset_month
    del st.session_state.reset_month_view

if "jump_to_date" in st.session_state:
    jump_date = st.session_state.jump_to_date
    st.session_state.filter_year = jump_date.year
    st.session_state.filter_month = jump_date.strftime("%b")
    del st.session_state.jump_to_date

if "filter_year" not in st.session_state:
    st.session_state.filter_year = current_year
if "filter_month" not in st.session_state:
    st.session_state.filter_month = datetime.datetime.now().strftime("%b")

master_df = st.session_state.master_df
filtered_data = master_df.copy()
filtered_data["Date"] = pd.to_datetime(filtered_data["Date"], errors="coerce")
filtered_data = filtered_data.dropna(subset=["Date"])
filtered_data["Year"] = filtered_data["Date"].dt.year
filtered_data["Month"] = filtered_data["Date"].dt.strftime("%b")

chart_year = st.session_state.filter_year
year_data = filtered_data[filtered_data["Year"] == chart_year].copy()
year_data["Amount"] = pd.to_numeric(year_data["Amount"], errors="coerce").fillna(0.0)
monthly_spending = (
    year_data.groupby("Month")["Amount"]
    .sum()
    .reindex(months, fill_value=0.0)
)
st.subheader(f"Monthly spending · {chart_year}")
if (monthly_spending > 0).any():
    monthly_comparison = pd.DataFrame({"Month": months, "Spending": monthly_spending.values})
    chart_key = f"monthly_spending_{chart_year}_{st.session_state.get('monthly_chart_revision', 0)}"
    month_selection = alt.selection_point(
        name="selected_month", fields=["Month"], toggle=False, clear=False
    )

    def select_chart_month():
        selection = st.session_state[chart_key].selection.get("selected_month", [])
        if selection and selection[0].get("Month") in months:
            st.session_state.filter_month = selection[0]["Month"]

    monthly_chart = (
        alt.Chart(monthly_comparison)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("Month:N", sort=months, axis=alt.Axis(title=None, labelAngle=0, grid=False)),
            y=alt.Y("Spending:Q", axis=alt.Axis(title=None, format="$,.0f", grid=False)),
            color=alt.condition(
                alt.datum.Month == st.session_state.filter_month,
                alt.value("#287A68"),
                alt.value("#8FBFB0"),
            ),
            tooltip=[
                alt.Tooltip("Month:N", title="Month"),
                alt.Tooltip("Spending:Q", title="Spending", format="$,.2f"),
            ],
        )
        .add_params(month_selection)
        .properties(height=210)
    )
    st.altair_chart(
        monthly_chart,
        key=chart_key,
        on_select=select_chart_month,
        width="stretch",
        alt=f"Monthly spending totals for {chart_year}",
    )
else:
    st.caption("Add transactions to see your month-by-month spending comparison.")

filter_year_col, filter_month_col = st.columns(2)
with filter_year_col:
    selected_year = st.selectbox("Year", years, key="filter_year")
with filter_month_col:
    selected_month = st.selectbox(
        "Month",
        months,
        key="filter_month",
        format_func=lambda month: datetime.datetime.strptime(month, "%b").strftime("%B"),
        on_change=lambda: st.session_state.update(
            monthly_chart_revision=st.session_state.get("monthly_chart_revision", 0) + 1
        ),
    )
selected_month_label = datetime.datetime.strptime(selected_month, "%b").strftime("%B")

month_data = filtered_data[
    (filtered_data["Year"] == selected_year)
    & (filtered_data["Month"] == selected_month)
].copy()
month_data["Amount"] = pd.to_numeric(month_data["Amount"], errors="coerce").fillna(0.0)

st.subheader(f"{selected_month_label} {selected_year}")

if not master_df.empty:
    with st.expander("Month actions", expanded=st.session_state.get("confirm_reset", False)):
        if st.button("Delete this month's transactions", icon=":material/delete:"):
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

    metric_spend, metric_count = st.columns(2)
    metric_spend.metric("Total spending", f"S${month_data['Amount'].sum():,.2f}")
    metric_count.metric("Transactions", f"{len(month_data):,}")

    if month_data.empty:
        st.caption(":material/inbox: No transactions for this month. Add a statement or enter one manually.")
    else:
        st.subheader("Spending by category")
        category_chart = px.pie(month_data, values="Amount", names="Category", hole=0.58)
        category_chart.update_layout(margin=dict(t=8, b=8, l=8, r=8), legend_title_text="Category")
        st.plotly_chart(category_chart, width="stretch")
else:
    st.caption(":material/inbox: No transactions yet. Select Add transactions to import a statement or enter one manually.")

if not master_df.empty and not st.session_state.get("show_edit"):
    history = master_df.copy()
    history["Date"] = pd.to_datetime(history["Date"], errors="coerce")
    history = history[
        (history["Date"].dt.year == selected_year)
        & (history["Date"].dt.strftime("%b") == selected_month)
    ]

    category_options = sorted(history["Category"].dropna().astype(str).unique().tolist())
    return_category = st.session_state.pop("transaction_return_category", None)
    if return_category is not None:
        st.session_state.category_filter = (
            return_category if return_category in category_options else "All categories"
        )
    selected_category = st.selectbox(
        "Filter by category",
        ["All categories", *category_options],
        key="category_filter",
    )
    if selected_category != "All categories":
        history = history[history["Category"] == selected_category]

    st.subheader(f"{selected_month_label} transactions")
    history = history.sort_values(by="Date", ascending=False)

    if history.empty:
        st.info("No transactions found.")
    else:
        history_view = history[["Date", "Description", "Amount", "Category"]].copy()
        history_view["Date"] = history_view["Date"].dt.strftime("%d %b %Y")
        history_view["Amount"] = pd.to_numeric(history_view["Amount"], errors="coerce").fillna(0.0)
        history_selection = st.dataframe(
            history_view,
            key=(
                f"transaction_history_{selected_year}_{selected_month}_{selected_category}_"
                f"{st.session_state.get('transaction_history_revision', 0)}"
            ),
            on_select="rerun",
            selection_mode="single-row",
            hide_index=True,
            height=360,
            row_height=38,
            width="stretch",
            column_config={
                "Date": st.column_config.TextColumn("Date", width="small"),
                "Description": st.column_config.TextColumn("Merchant", width="large"),
                "Amount": st.column_config.NumberColumn("Amount", format="S$%.2f", width="small"),
                "Category": st.column_config.TextColumn("Category", width="medium"),
            },
            alt="Transactions for the selected month",
        )
        selected_rows = history_selection.selection.rows
        selected_index = history.index[selected_rows[0]] if selected_rows and selected_rows[0] < len(history) else None
        selection_context = (selected_year, selected_month, selected_category, selected_index)
        if st.session_state.get("confirm_delete_transaction") != selection_context:
            st.session_state.pop("confirm_delete_transaction", None)

        edit_action, delete_action = st.columns(2)
        if edit_action.button("Edit selected transaction", icon=":material/edit:", disabled=selected_index is None):
            st.session_state.edit_index = selected_index
            st.session_state.transaction_return_category = selected_category
            st.session_state.show_edit = True
            st.rerun()
        if delete_action.button("Delete selected transaction", icon=":material/delete:", disabled=selected_index is None):
            st.session_state.confirm_delete_transaction = selection_context

        if st.session_state.get("confirm_delete_transaction") == selection_context and selected_index is not None:
            st.warning(f"Delete {history.loc[selected_index, 'Description']} from your transactions?")
            confirm_action, cancel_action = st.columns(2)
            if confirm_action.button("Confirm delete", type="primary"):
                st.session_state.master_df = st.session_state.master_df.drop(selected_index).reset_index(drop=True)
                st.session_state.transaction_history_revision = (
                    st.session_state.get("transaction_history_revision", 0) + 1
                )
                st.session_state.show_edit = False
                st.session_state.pop("confirm_delete_transaction", None)
                st.rerun()
            if cancel_action.button("Cancel deletion"):
                st.session_state.pop("confirm_delete_transaction", None)
                st.rerun()

if st.session_state.get("show_edit"):
    transaction_index = st.session_state.edit_index
    try:
        row = st.session_state.master_df.loc[[transaction_index]].iloc[0]
    except (KeyError, IndexError):
        st.error("Transaction no longer exists.")
        st.session_state.show_edit = False
        st.rerun()

    st.subheader("Edit transaction")
    description = st.text_input("Description", value=str(row["Description"]))
    amount = st.number_input("Amount", value=float(row["Amount"]))
    transaction_date = st.date_input("Date", value=pd.to_datetime(row["Date"]))

    categories = ["Food & Dining", "Transport", "Groceries", "Shopping", "Bills", "Others"]
    current_category = str(row["Category"])
    category_index = categories.index(current_category) if current_category in categories else 5
    category = st.selectbox("Category", categories, index=category_index)

    with st.container(horizontal=True):
        save_clicked = st.button("Save changes", type="primary", icon=":material/check:")
        cancel_clicked = st.button("Cancel")

    if save_clicked:
        st.session_state.master_df.at[transaction_index, "Description"] = description
        st.session_state.master_df.at[transaction_index, "Amount"] = float(amount)
        st.session_state.master_df.at[transaction_index, "Category"] = category
        st.session_state.master_df.at[transaction_index, "Date"] = pd.to_datetime(transaction_date)
        st.session_state.master_df.at[transaction_index, "Month"] = transaction_date.strftime("%b")
        st.session_state.master_df.at[transaction_index, "Year"] = transaction_date.year
        st.session_state.master_df = st.session_state.master_df.reset_index(drop=True)
        st.session_state.show_edit = False
        st.rerun()

    if cancel_clicked:
        st.session_state.show_edit = False
        st.rerun()
