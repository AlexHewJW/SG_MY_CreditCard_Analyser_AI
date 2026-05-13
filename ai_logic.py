import streamlit as st
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from config import SG_MAPPING, ALLOWED_CATEGORIES

# --------------------------------------------------
# 1. RULE-BASED MATCH (FAST & PRECISE)
# --------------------------------------------------
def get_local_category(desc):
    desc_lower = str(desc).lower()
    for category, keywords in SG_MAPPING.items():
        if any(key in desc_lower for key in keywords):
            return category
    return None

# --------------------------------------------------
# 2. LOAD TRAINED CLASSIFIER (FROM HUGGING FACE)
# --------------------------------------------------

@st.cache_resource
def load_micromodel():
    checkpoint = "immaxowa/sg-expense-classifier"

    tokenizer = AutoTokenizer.from_pretrained(
        checkpoint,
        use_fast=False
    )

    model = AutoModelForSequenceClassification.from_pretrained(
        checkpoint,
        device_map="cpu",
        torch_dtype=torch.float32
    )

    model.eval()
    return tokenizer, model

# --------------------------------------------------
# 3. AI CLASSIFICATION (LOGITS → ARGMAX)
# --------------------------------------------------
def classify_with_ai(transaction_name, tokenizer, model):
    """
    Classify a transaction using the trained classifier.
    Always returns EXACTLY one category from ALLOWED_CATEGORIES.
    """
    inputs = tokenizer(
        transaction_name,
        return_tensors="pt",
        truncation=True
    )

    with torch.no_grad():
        logits = model(**inputs).logits
        pred_id = logits.argmax(dim=-1).item()

    return ALLOWED_CATEGORIES[pred_id]

# --------------------------------------------------
# 4. MAIN WORKFLOW (RULES → AI FALLBACK)
# --------------------------------------------------
def process_all_transactions(transaction_list):
    """
    Core logic used by streamlit_app.py
    """
    tokenizer, model = load_micromodel()
    final_results = []

    for name in transaction_list:
        # Step A: Try rule-based detection first
        match = get_local_category(name)

        # Step B: Use AI only if rules fail
        if not match:
            try:
                match = classify_with_ai(name, tokenizer, model)
            except Exception:
                match = "Others"

        final_results.append(match)

    return final_results

# --------------------------------------------------
# 5. PUBLIC ENTRY POINT
# --------------------------------------------------
def classify_transactions_batch(transaction_list):
    return process_all_transactions(transaction_list)