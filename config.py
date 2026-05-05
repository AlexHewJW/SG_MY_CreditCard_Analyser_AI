# config.py

# The strictly allowed categories for the AI and UI
ALLOWED_CATEGORIES = [
    "Food & Dining", 
    "Transport", 
    "Groceries", 
    "Shopping", 
    "Bills",
    "Others"
]

# Required columns for the final dataframe
REQUIRED_COLUMNS = ["Date", "Month", "Year", "Description", "Amount", "Category"]

# Local rules for SG transactions
SG_MAPPING = {
    "Transport": ["esso", "shell", "spc", "caltex", "simplygo", "lta", "mrt", "bus", "grab", "gojek", "tada", "comfortdelgro", "ez-link"],
    "Food & Dining": ["kopitiam", "food republic", "mcdonald", "starbucks", "grabfood", "foodpanda", "toast box", "breadtalk", "old chang kee"],
    "Groceries": ["ntuc", "fairprice", "sheng siong", "cold storage", "giant", "don don donki", "redmart"],
    "Shopping": ["shopee", "lazada", "amazon", "uniqlo", "taobao", "tiktok shop"],
    "Bills": ["sp services", "singtel", "starhub", "m1", "netflix", "spotify"]
}