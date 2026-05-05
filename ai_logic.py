import streamlit as st
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
import json

# 1. LOCAL RULES (The "Shield")
# These handle 80% of SG transactions with 0% AI effort
SG_MAPPING = {
    "Transport": ["esso", "shell", "spc", "caltex", "simplygo", "lta", "mrt", "bus", "grab", "gojek", "tada", "comfortdelgro", "ez-link"],
    "Food & Dining": ["kopitiam", "food republic", "mcdonald", "starbucks", "grabfood", "foodpanda", "toast box", "breadtalk", "old chang kee"],
    "Groceries": ["ntuc", "fairprice", "sheng siong", "cold storage", "giant", "don don donki", "redmart"],
    "Shopping": ["shopee", "lazada", "amazon", "uniqlo", "taobao", "tiktok shop"],
    "Bills": ["sp services", "singtel", "starhub", "m1", "netflix", "spotify"]
}

def get_local_category(desc):
    desc_lower = str(desc).lower()
    for category, keywords in SG_MAPPING.items():
        if any(key in desc_lower for key in keywords):
            return category
    return None

# 2. THE MICROMODEL (The "Brain")
@st.cache_resource
def load_micromodel():
    """Loads the 135M model into RAM once. Uses ~350MB."""
    checkpoint = "HuggingFaceTB/SmolLM2-135M-Instruct"
    tokenizer = AutoTokenizer.from_pretrained(checkpoint)
    # Using float16 on CPU to save memory
    model = AutoModelForCausalLM.from_pretrained(
        checkpoint, 
        torch_dtype=torch.float16, 
        device_map="cpu"
    )
    return tokenizer, model

def classify_with_ai(transaction_name, tokenizer, model):
    """Uses the micromodel to guess unknown categories."""
    prompt_template = [
        {"role": "system", "content": "You are a Singapore expense assistant. Categorize the transaction into: Food & Dining, Transport, Groceries, Shopping, Bills, or Others. Return ONLY the category name."},
        {"role": "user", "content": f"Transaction: {transaction_name}"}
    ]
    
    input_text = tokenizer.apply_chat_template(prompt_template, tokenize=False)
    inputs = tokenizer(input_text, return_tensors="pt")
    
    with torch.no_grad():
        # Limit tokens to 5 to force a short answer and save RAM
        outputs = model.generate(**inputs, max_new_tokens=5, temperature=0.1)
    
    full_output = tokenizer.decode(outputs[0], skip_special_tokens=True)
    # Extract the assistant's specific answer
    category = full_output.split("assistant")[-1].strip()
    return category

# 3. MAIN WORKFLOW
def process_all_transactions(transaction_list):
    """The logic your main streamlit_app.py will call."""
    tokenizer, model = load_micromodel()
    final_results = []

    for name in transaction_list:
        # Step A: Check local rules first
        match = get_local_category(name)
        
        if match:
            final_results.append(match)
        else:
            # Step B: Use AI if rules fail
            try:
                ai_match = classify_with_ai(name, tokenizer, model)
                final_results.append(ai_match)
            except Exception:
                final_results.append("Others")
                
    return final_results

def classify_transactions_batch(transaction_list):
    """
    This is the entry point called by the Streamlit app.
    It wraps the process_all_transactions logic.
    """
    # Simply call your existing workflow
    return process_all_transactions(transaction_list)