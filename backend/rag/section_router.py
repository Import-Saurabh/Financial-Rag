"""Section router for query-aware document retrieval."""
from typing import List

# Maps keywords in queries to relevant document section types
QUERY_TO_SECTIONS = {
    # Financial queries
    "revenue": ["financials", "md&a"],
    "profit": ["financials", "md&a"],
    "ebitda": ["financials"],
    "margin": ["financials", "md&a"],
    "eps": ["financials"],
    "roe": ["financials"],
    "assets": ["financials"],
    "liabilities": ["financials"],
    "cash flow": ["financials"],
    "debt": ["financials"],
    "receivables": ["financials"],
    "inventory": ["financials"],
    "working capital": ["financials"],
    "capex": ["financials"],
    "balance sheet": ["financials"],
    "income statement": ["financials"],
    
    # Qualitative questions
    "growth": ["md&a", "products", "entity"],
    "risk": ["risk", "md&a"],
    "strategy": ["md&a", "entity", "concept"],
    "segment": ["segment", "md&a"],
    "product": ["products", "md&a", "entity", "concept"],
    "business": ["md&a", "products", "entity"],
    "defence": ["products", "md&a", "entity", "concept"],
    "defense": ["products", "md&a", "entity", "concept"],
    "order book": ["md&a", "products", "entity"],
    "opportunity": ["md&a"],
    "outlook": ["md&a"],
    "guidance": ["md&a"],
    "management": ["md&a", "governance"],
    "commentary": ["md&a"],
    
    # Entity/Relationship queries (NEW)
    "customer": ["entity", "concept", "md&a"],
    "client": ["entity", "concept", "md&a"],
    "partner": ["entity", "concept", "md&a"],
    "supplier": ["entity", "concept", "md&a"],
    "subsidiary": ["entity", "md&a", "governance"],
    "acquisition": ["entity", "md&a"],
    "missile": ["entity", "concept", "products"],
    "torpedo": ["entity", "concept", "products"],
    "mine": ["entity", "concept", "products"],
    "weapon": ["entity", "concept", "products"],
    "drone": ["entity", "concept", "products"],
    "radar": ["entity", "concept", "products"],
    "navy": ["entity", "concept"],
    "drdo": ["entity", "concept"],
    "export": ["entity", "concept", "md&a"],
    "manufacture": ["entity", "concept", "products"],
    "technology": ["entity", "concept", "products"],
    "who": ["entity", "governance"],
    
    # Governance questions
    "chairman": ["governance", "entity"],
    "director": ["governance", "entity"],
    "audit committee": ["governance"],
    "board": ["governance", "entity"],
    "csr": ["governance"],
    "committee": ["governance"],
    "remuneration": ["governance"],
    "compliance": ["governance"],
}

def get_target_sections(query: str) -> List[str]:
    """Route a query to the most relevant document section types."""
    query_lower = query.lower()
    matched = set()
    for keyword, sections in QUERY_TO_SECTIONS.items():
        if keyword in query_lower:
            matched.update(sections)
    if not matched:
        return ["md&a", "financials", "governance", "products", "segment", "risk"]
    return list(matched)
