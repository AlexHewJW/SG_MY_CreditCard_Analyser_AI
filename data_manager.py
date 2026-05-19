import pandas as pd
import os
from config import REQUIRED_COLUMNS

DATA_FILE = "data.csv"

def load_data():
    try:
        if os.path.exists(DATA_FILE):
            return pd.read_csv(DATA_FILE)
    except:
        pass
    return pd.DataFrame(columns=REQUIRED_COLUMNS)

def save_data(df):
    df.to_csv(DATA_FILE, index=False)
