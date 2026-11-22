import streamlit as st
from sqlalchemy import create_engine, text
from datetime import datetime, timezone
from decimal import Decimal

# Get the URL from Streamlit Secrets
DB_URL = st.secrets["database"]["url"]

# Avoid prepared-statement name collisions with transaction-pooled connections.
engine = create_engine(DB_URL, connect_args={"prepare_threshold": None})

def check_db():
    """Initializes the table if it doesn't exist."""
    query = """
    CREATE TABLE IF NOT EXISTS category_overrides (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        description TEXT,
        amount NUMERIC(12,2),
        old_category TEXT,
        new_category TEXT,
        source TEXT DEFAULT 'manual_edit'
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
    ts = datetime.now(timezone.utc)

    query = text("""
        INSERT INTO public.category_overrides
        (ts, description, amount, old_category, new_category, source)
        VALUES (:ts, :desc, :amt, :old, :new, :src)
        RETURNING ts, description, amount, old_category, new_category, source
    """)

    try:
        with engine.begin() as conn:
            result = conn.execute(query, {
                "ts": ts,
                "desc": description,
                "amt": Decimal(str(amount)),
                "old": old_category,
                "new": new_category,
                "src": source
            })

            inserted = result.mappings().one()

            st.success("Database INSERT successful!")
            st.write("Inserted record:", dict(inserted))

            # Verify the database can read the inserted record
            check = conn.execute(text("""
                SELECT COUNT(*)
                FROM public.category_overrides
                WHERE ts = :ts
            """), {"ts": ts}).scalar()

            st.write("Matching records:", check)

    except Exception as e:
        st.error(f"Database write failed: {e}")
        raise
