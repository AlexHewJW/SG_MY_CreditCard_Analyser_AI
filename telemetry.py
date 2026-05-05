import streamlit as st
from sqlalchemy import create_engine, text
from datetime import datetime

# Get the URL from Streamlit Secrets
DB_URL = st.secrets["database"]["url"]

# Create a connection engine
engine = create_engine(DB_URL)

def check_db():
    """Initializes the table if it doesn't exist."""
    query = """
    CREATE TABLE IF NOT EXISTS category_overrides (
        ts TIMESTAMPTZ,
        description TEXT,
        amount NUMERIC,
        old_category TEXT,
        new_category TEXT,
        source TEXT
    );
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(query))
        return True, None
    except Exception as e:
        return False, str(e)

def log_manual_category_override(
    description,
    amount,
    old_category,
    new_category,
    source="manual_edit"
):
    """Inserts an override event into the cloud DB."""
    ts = datetime.utcnow()
    query = text("""
        INSERT INTO category_overrides (ts, description, amount, old_category, new_category, source)
        VALUES (:ts, :desc, :amt, :old, :new, :src)
    """)
    
    try:
        with engine.begin() as conn:
            conn.execute(query, {
                "ts": ts,
                "desc": description,
                "amt": amount,
                "old": old_category,
                "new": new_category,
                "src": source
            })
    except Exception as e:
        st.error(f"Database write failed: {e}")
        raise e