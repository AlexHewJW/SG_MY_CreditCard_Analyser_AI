import streamlit as st
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from config import SG_MAPPING, ALLOWED_CATEGORIES  # Centralized source of truth

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
    """Uses the micromodel and validates against ALLOWED_CATEGORIES."""
    # Build prompt using categories from config
    cat_options = ", ".join([c for c in ALLOWED_CATEGORIES if c != "Others"])
    
    prompt_template = [
        {"role": "system", "content": f"You are a Singapore expense assistant. Categorize into ONLY one of these: {cat_options}. Return ONLY the category name."},
        {"role": "user", "content": f"Transaction: {transaction_name}"}
    ]
    
    input_text = tokenizer.apply_chat_template(prompt_template, tokenize=False)
    inputs = tokenizer(input_text, return_tensors="pt")
    
    with torch.no_grad():
        # Short tokens to prevent rambling
        outputs = model.generate(**inputs, max_new_tokens=10, temperature=0.1)
    
    input_len = inputs["input_ids"].shape[1]

    ai_response = tokenizer.decode(
        outputs[0][input_len:],   # only decode new generated tokens
        skip_special_tokens=True
    ).strip()

    # ----------------------------
    # STRICT VALIDATION
    # ----------------------------
    strict_cat = "Others"
    for cat in ALLOWED_CATEGORIES:
        if cat.lower() in ai_response.lower():
            strict_cat = cat
            break

    print("Strict cat : ", strict_cat)
    return strict_cat

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
    """Entry point for batch processing."""
    return process_all_transactions(transaction_list)