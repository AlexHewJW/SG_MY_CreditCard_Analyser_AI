import pandas as pd

def add_transactions(master_df, new_rows):
    return pd.concat([master_df, new_rows], ignore_index=True)

def delete_month(master_df, year, month):
    df = master_df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

    return df[
        ~(
            (df["Date"].dt.year == year) &
            (df["Date"].dt.strftime("%b") == month)
        )
    ].reset_index(drop=True)

def update_transaction(df, idx, new_data):
    df.at[idx, "Description"] = new_data["Description"]
    df.at[idx, "Amount"] = new_data["Amount"]
    df.at[idx, "Category"] = new_data["Category"]
    df.at[idx, "Date"] = new_data["Date"]
    df.at[idx, "Month"] = new_data["Date"].strftime("%b")
    df.at[idx, "Year"] = new_data["Date"].year
    return df.reset_index(drop=True)