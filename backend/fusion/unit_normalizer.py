import re
from typing import Tuple, Optional

def normalize_to_crore(value: float, unit: str) -> Tuple[float, str]:
    """
    Normalizes a value to crore.
    
    Unit multipliers:
    - crore/cr → 1.0
    - lakh/lakhs → 0.01  
    - thousand/thousands → 0.001
    - million → 0.1
    - billion → 100.0
    """
    unit_lower = unit.lower().strip()
    multiplier = 1.0
    
    if unit_lower in ['crore', 'cr', 'crores']:
        multiplier = 1.0
    elif unit_lower in ['lakh', 'lakhs', 'lac', 'lacs']:
        multiplier = 0.01
    elif unit_lower in ['thousand', 'thousands']:
        multiplier = 0.001
    elif unit_lower in ['million', 'millions', 'mn']:
        multiplier = 0.1
    elif unit_lower in ['billion', 'billions', 'bn']:
        multiplier = 100.0
        
    return value * multiplier, 'crore'

def detect_and_normalize(text: str) -> Optional[Tuple[float, str]]:
    """
    Extracts financial figures from text and normalizes them to crore.
    Returns (normalized_value, 'crore') or None.
    """
    # Regex to capture number and optional unit
    # Matches formats like: 12.34 million, 5,000 crores, 10 cr, etc.
    pattern = r'(\d+(?:,\d{3})*(?:\.\d+)?)\s*(crores?|cr|lakhs?|lacs?|thousands?|millions?|mn|billions?|bn)?'
    
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
        
    val_str = match.group(1).replace(',', '')
    try:
        val = float(val_str)
    except ValueError:
        return None
        
    unit = match.group(2) or ''
    return normalize_to_crore(val, unit)

def safe_compare(sql_value: float, sql_unit: str, doc_claim_text: str) -> str:
    """
    Compares a SQL value/unit with a claim text from a document.
    Returns 'CONFIRM', 'CONTRADICT', 'APPROXIMATE', or 'UNVERIFIABLE'.
    """
    doc_normalized = detect_and_normalize(doc_claim_text)
    if not doc_normalized:
        return 'UNVERIFIABLE'
        
    doc_val, _ = doc_normalized
    sql_val_norm, _ = normalize_to_crore(sql_value, sql_unit)
    
    if sql_val_norm == 0 and doc_val == 0:
        return 'CONFIRM'
        
    if sql_val_norm == 0 or doc_val == 0:
        diff_pct = float('inf')
    else:
        diff_pct = abs(sql_val_norm - doc_val) / abs(sql_val_norm)
        
    if diff_pct == 0.0:
        return 'CONFIRM'
    elif diff_pct <= 0.05:
        return 'APPROXIMATE'
    else:
        return 'CONTRADICT'
