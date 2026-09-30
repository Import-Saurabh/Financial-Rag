"""Temporal resolver for fiscal year extraction and defaulting."""
import re
from datetime import date
from typing import List, Tuple, Optional

def get_current_fy(ref_date: date = None) -> int:
    """Get the current Indian fiscal year."""
    d = ref_date or date.today()
    return d.year + 1 if d.month >= 4 else d.year

def get_latest_completed_fy(ref_date: date = None) -> int:
    """Get the most recently completed fiscal year."""
    return get_current_fy(ref_date) - 1

def resolve_year_range(query: str, current_date: date = None) -> Tuple[int, int]:
    """
    Determine the correct fiscal year range for a query.
    
    Priority:
    1. Explicit years in query: "FY2025-26" → (2025, 2026)
    2. "year over year" / "YoY" without years → most recent 2 FYs
    3. "last 3 years" / "5 year trend" → appropriate range
    4. Default → most recent FY
    
    Indian FY convention: FY2026 = April 2025 to March 2026
    Current date of Sept 2026 → current FY is FY2027 (April 2026 - March 2027)
    Most recent completed FY = FY2026
    """
    query_lower = query.lower()
    
    # Priority 1: Explicit years in query
    # E.g. "FY2025-26", "FY25 to FY26", "2023-2025"
    explicit_match = re.search(r'(?:fy)?\s*(\d{2,4})\s*(?:[-–]|to|and)\s*(?:fy)?\s*(\d{2,4})', query_lower)
    if explicit_match:
        y1_str, y2_str = explicit_match.groups()
        y1 = int(y1_str) if len(y1_str) == 4 else 2000 + int(y1_str)
        y2 = int(y2_str) if len(y2_str) == 4 else (y1 // 100 * 100 + int(y2_str) if len(y2_str) == 2 else int(y2_str))
        if y2 < y1 and len(y2_str) == 2:
            y2 = 2000 + int(y2_str)
        return min(y1, y2), max(y1, y2)

    explicit_single = re.search(r'fy\s*(\d{2,4})', query_lower)
    if explicit_single:
        y_str = explicit_single.group(1)
        y = int(y_str) if len(y_str) == 4 else 2000 + int(y_str)
        return y, y

    # Priority 2: "last N years" / "N year trend"
    last_n_match = re.search(r'last\s+(\d+)\s+years?', query_lower) or re.search(r'(\d+)\s*year\s+trend', query_lower)
    if last_n_match:
        n = int(last_n_match.group(1))
        latest = get_latest_completed_fy(current_date)
        return latest - n + 1, latest

    # Priority 3: YoY / comparison queries without explicit years
    yoy_match = re.search(r'\byoy\b|year[\s\-]over[\s\-]year|compare|change', query_lower)
    if yoy_match:
        latest = get_latest_completed_fy(current_date)
        return latest - 1, latest

    # Default: most recent FY
    latest = get_latest_completed_fy(current_date)
    return latest, latest
