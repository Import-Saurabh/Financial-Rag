"""
pipeline/retrieval/retriever.py  —  Financial-RAG Semantic Retriever v2

Redesigned to consume the rich metadata produced by chunker_v2 and
extractor_v2.  Backward-compatible public API.

Key improvements over v1:
  1. Query intent analysis — parses queries for financial metrics, section
     types, temporal orientation (forward/historical), and table preferences.
  2. Metadata-aware pre-filtering — builds Qdrant where-filters from query
     intent before vector search, reducing candidate noise.
  3. Semantic flag scoring — forward-looking queries boost forward_looking
     chunks; guidance queries boost quantitative_guidance chunks.
  4. Metric-match boost — if query asks for "ROE", chunks mentioning ROE
     in financial_metrics get a direct score boost.
  5. Section-type inference — maps query text to canonical financial sections
     (Revenue, Margins, Cash Flow, …) and filters or boosts accordingly.
  6. Table-aware retrieval — P&L/BS/CF queries prefer table_summary chunks.
  7. Importance-score integration — uses chunker_v2's financial-signal
     importance as a multiplicative re-ranking factor.
  8. Duplicate / low-info filtering — excludes is_duplicate and
     is_low_information chunks at retrieval time.
  9. Hierarchical path matching — boosts chunks whose hierarchy_path contains
     query-relevant sections.
  10. Enhanced query expansion — uses the semantic concept vocabulary from
      chunker_v2 for richer embedding-space matching.
  11. Cross-collection routing — annual_report vs concall vs both, with
      intelligent query-based routing.
  12. Speaker-aware concall retrieval — management commentary boost for
      forward-looking queries; analyst questions boost for sentiment/concern
      queries.
"""

import re
import math
from typing import List, Dict, Optional, Any, Tuple, Set
from dataclasses import dataclass, field
from collections import Counter

from config.settings import ANNUAL_RETRIEVAL, CONCALL_RETRIEVAL, RETRIEVAL_BOOSTS
from pipeline.loader.embedder import embed_query
from pipeline.loader.qdrant_loader import query_collection
from utils.logger import get_logger

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 0.  Configuration & constants
# ═══════════════════════════════════════════════════════════════════════════════

CURRENT_FY       = 2025
DEFAULT_LOOKBACK = 3
MIN_RESULTS      = 8

# Section-type → canonical label mapping for query inference
_SECTION_TYPE_KEYWORDS = {
    "Revenue":        ["revenue", "sales", "turnover", "topline", "income", "total income"],
    "Margins":        ["margin", "ebitda", "ebit", "pbt", "pat", "profit", "profitability", "operating profit"],
    "Cash Flow":      ["cash flow", "ocf", "fcf", "free cash flow", "operating cash flow", "liquidity"],
    "Balance Sheet":  ["balance sheet", "assets", "liabilities", "equity", "net worth", "book value"],
    "Capex":          ["capex", "capital expenditure", "investment", "capacity expansion", "greenfield", "brownfield"],
    "Orders":         ["order book", "backlog", "pipeline", "bookings", "order inflow", "deal wins"],
    "Products":       ["product", "platform", "offering", "solution", "launch", "r&d", "innovation"],
    "Customers":      ["customer", "client", "account", "concentration", "dependence"],
    "Exports":        ["export", "international", "overseas", "geography", "domestic vs export"],
    "Segments":       ["segment", "business unit", "vertical", "division", "ind as 108"],
    "Risk":           ["risk", "headwind", "challenge", "uncertainty", "concern", "downside"],
    "Guidance":       ["guidance", "outlook", "forecast", "target", "projection", "expect"],
    "Competition":    ["competition", "competitor", "market share", "peer", "landscape"],
    "Corporate Governance": ["corporate governance", "board", "dividend", "buyback", "agm", "shareholder"],
    "ESG":            ["esg", "sustainability", "carbon", "climate", "csr", "environment"],
}

# Financial metrics vocabulary for query parsing
_FINANCIAL_METRICS = [
    "revenue", "ebitda", "ebit", "pbt", "pat", "net profit", "operating profit",
    "eps", "roe", "roce", "ronw", "book value", "nav", "p/e", "p/b", "ev/ebitda",
    "dividend", "dps", "capex", "ocf", "fcf", "working capital", "debt",
    "total assets", "equity", "net worth", "order book", "backlog",
    "yoy", "qoq", "cagr", "growth rate", "margin", "bps",
]

# Table-type preferences for financial-statement queries
_TABLE_TYPE_PREFERENCES = {
    "income_statement": ["revenue", "ebitda", "ebit", "pbt", "pat", "eps", "profit", "income statement", "p&l"],
    "balance_sheet":    ["balance sheet", "assets", "liabilities", "equity", "net worth", "book value"],
    "cash_flow":        ["cash flow", "ocf", "fcf", "operating cash flow", "free cash flow"],
    "segment_report":   ["segment", "business segment", "geographical segment", "ind as 108"],
}

# Forward-looking query signals
_FORWARD_QUERY_SIGNALS = [
    "guidance", "outlook", "expect", "anticipate", "target", "going forward",
    "next quarter", "next year", "H1", "H2", "coming quarters", "forecast",
    "projection", "plan", "strategy", "future", "medium term", "long term",
]

# Historical query signals
_HISTORICAL_QUERY_SIGNALS = [
    "last year", "previous year", "prior year", "yoy", "year on year",
    "qoq", "quarter on quarter", "compared to", "versus", "historical",
    "past performance", "track record",
]

# Management-preference query signals
_MGMT_PREFERENCE_SIGNALS = [
    "management said", "ceo said", "cfo mentioned", "management commentary",
    "management discussion", "management believes", "management expects",
]

# Analyst-preference query signals
_ANALYST_PREFERENCE_SIGNALS = [
    "analyst asked", "analyst question", "from the floor", "question on",
    "concern raised", "analyst concern",
]

# Document-type routing keywords
_ANNUAL_PREF_SIGNALS = ["annual report", "annual", "report", "financial statement", "balance sheet", "audited"]
_CONCALL_PREF_SIGNALS = ["concall", "conference call", "earnings call", "management said", "qa", "q&a", "call transcript"]


# ═══════════════════════════════════════════════════════════════════════════════
# 1.  Intent taxonomy for query expansion  (v2 — greatly expanded)
# ═══════════════════════════════════════════════════════════════════════════════

_INTENT_EXPANSIONS: Dict[str, List[str]] = {
    # Concall / Management signals
    "outlook":        ["we expect", "we anticipate", "our outlook", "going forward",
                       "H1", "H2", "next quarter", "next year", "guidance"],
    "demand":         ["demand environment", "volume growth", "market demand",
                       "cargo volume", "throughput", "demand scenario"],
    "guidance":       ["FY guidance", "target", "projected", "forecast",
                       "we are confident", "we expect to achieve", "quantitative guidance"],
    "risk":           ["risk factors", "headwinds", "challenges", "macro risk",
                       "geopolitical", "trade disruption", "margin pressure"],
    "capex":          ["capital expenditure", "capex plan", "investment", "expansion",
                       "additions to fixed assets", "property plant equipment"],
    "margin":         ["EBITDA margin", "operating margin", "margin guidance",
                       "margin improvement", "EBIT margin", "gross margin",
                       "what affected margins", "margin pressure", "margin expansion", "margin compression"],
    "management":     ["management commentary", "CEO said", "CFO mentioned",
                       "management discussion", "MD&A", "management discussion and analysis"],
    "orders":         ["order book", "backlog", "bookings", "order inflow",
                       "pipeline", "deal wins", "order momentum", "contract wins"],
    "earnings_call":  ["earnings call", "conference call", "quarterly results",
                       "financial performance", "operating performance",
                       "management remarks", "analyst questions", "Q&A session",
                       "opening remarks", "prepared remarks"],

    # Income statement
    "revenue":        ["revenue from operations", "total income", "net revenue",
                       "revenue growth", "topline", "revenue target",
                       "income from operations", "gross revenue", "revenue decline"],
    "ebitda":         ["EBITDA", "earnings before interest tax depreciation",
                       "operating profit", "EBIT", "earnings before interest and tax",
                       "profit before depreciation interest and tax", "EBITDA margin"],
    "profit":         ["profit after tax", "PAT", "net profit", "profit before tax",
                       "PBT", "net income", "profit for the year",
                       "profit attributable to shareholders", "net profit margin"],
    "depreciation":   ["depreciation and amortisation", "D&A", "amortisation",
                       "depreciation on property plant"],

    # Balance sheet
    "assets":         ["total assets", "fixed assets", "current assets",
                       "non-current assets", "net block", "capital work in progress",
                       "intangible assets", "goodwill", "right of use assets"],
    "equity":         ["shareholders equity", "net worth", "book value",
                       "retained earnings", "other comprehensive income",
                       "total equity", "paid up capital", "reserves and surplus"],
    "debt":           ["net debt", "total debt", "borrowings", "long term debt",
                       "short term borrowings", "debt reduction", "leverage",
                       "net debt to EBITDA", "debt equity ratio",
                       "term loans", "debentures", "bonds"],
    "working_capital":["current liabilities", "trade payables", "trade receivables",
                       "inventories", "current ratio", "working capital"],

    # Cash flow statement
    "cashflow":       ["cash flow from operations", "operating cash flow",
                       "cash flow from investing", "cash flow from financing",
                       "free cash flow", "FCF", "net cash generated",
                       "cash and cash equivalents", "capex cash outflow",
                       "proceeds from borrowings", "repayment of borrowings"],
    "ocf":            ["operating cash flow", "cash from operations",
                       "net cash flow from operating activities",
                       "cash generated from operations"],

    # Financial ratios
    "eps":            ["earnings per share", "diluted EPS", "basic EPS",
                       "EPS growth", "diluted earnings per share",
                       "weighted average shares", "face value"],
    "roe_roce":       ["return on equity", "ROE", "return on capital employed",
                       "ROCE", "return on net worth", "return on assets",
                       "RONW", "capital efficiency"],
    "book_value":     ["book value per share", "net asset value per share",
                       "NAV per share", "tangible book value",
                       "total equity divided by shares outstanding"],
    "pe_pb":          ["price to earnings", "P/E ratio", "price to book",
                       "P/B ratio", "EV/EBITDA", "enterprise value",
                       "market capitalisation"],
    "dividends":      ["dividend per share", "DPS", "dividend payout",
                       "dividend yield", "interim dividend", "final dividend"],

    # Segment reporting
    "segments":       ["segment revenue", "segment EBITDA", "segment profit",
                       "business segment", "operating segment",
                       "Ind AS 108", "segment wise", "segment results",
                       "domestic ports", "international ports", "logistics segment"],
    "geography":      ["India revenue", "outside India", "geographical segment",
                       "domestic revenue", "export revenue", "overseas revenue",
                       "geographic breakdown", "India and rest of world",
                       "revenue from India", "revenue from outside India",
                       "geographic information"],

    # Strategic / product
    "product_launch": ["product launch", "new product", "new platform",
                       "new offering", "innovation", "r&d"],
    "contract_win":   ["contract win", "order win", "bagged", "secured",
                       "tender", "deal win", "contract award"],
    "esg":            ["ESG", "sustainability", "carbon", "climate", "CSR",
                       "green initiative", "environmental"],
}

_FORWARD_SIGNALS = [
    "outlook", "expect", "anticipate", "guidance", "target", "going forward",
    "H1", "H2", "next", "forecast", "project", "plan to",
    "demand environment", "demand scenario",
]


# ═══════════════════════════════════════════════════════════════════════════════
# 2.  Query intent dataclass  (NEW)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class QueryIntent:
    """Parsed intent from a natural-language financial query."""
    original_query: str
    expanded_query: str

    # Temporal
    is_forward_looking: bool = False
    is_historical: bool = False

    # Section / topic
    inferred_section_types: List[str] = field(default_factory=list)
    inferred_metrics: List[str] = field(default_factory=list)
    inferred_table_type: Optional[str] = None

    # Document type preference
    preferred_doc_type: Optional[str] = None  # "annual_report" | "concall" | None

    # Speaker preference (concalls)
    preferred_speaker_role: Optional[str] = None  # "management" | "analyst" | None

    # Semantic flags to boost
    boost_flags: List[str] = field(default_factory=list)

    # Year filter
    resolved_years: List[int] = field(default_factory=list)
    explicit_years: List[int] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# 3.  Query intent parser  (NEW)
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_query_intent(query: str) -> QueryIntent:
    """Parse a financial query into structured intent."""
    q_lower = query.lower()

    intent = QueryIntent(
        original_query=query,
        expanded_query=query,
    )

    # ── Temporal orientation ──────────────────────────────────────────────────
    intent.is_forward_looking = any(sig in q_lower for sig in _FORWARD_QUERY_SIGNALS)
    intent.is_historical = any(sig in q_lower for sig in _HISTORICAL_QUERY_SIGNALS)

    # ── Section type inference ────────────────────────────────────────────────
    for section, keywords in _SECTION_TYPE_KEYWORDS.items():
        if any(kw in q_lower for kw in keywords):
            if section not in intent.inferred_section_types:
                intent.inferred_section_types.append(section)

    # ── Financial metrics ─────────────────────────────────────────────────────
    for metric in _FINANCIAL_METRICS:
        if metric in q_lower:
            if metric not in intent.inferred_metrics:
                intent.inferred_metrics.append(metric)

    # ── Table type preference ─────────────────────────────────────────────────
    for ttype, keywords in _TABLE_TYPE_PREFERENCES.items():
        if any(kw in q_lower for kw in keywords):
            intent.inferred_table_type = ttype
            break

    # ── Document type routing ─────────────────────────────────────────────────
    annual_score = sum(1 for sig in _ANNUAL_PREF_SIGNALS if sig in q_lower)
    concall_score = sum(1 for sig in _CONCALL_PREF_SIGNALS if sig in q_lower)
    if annual_score > concall_score and annual_score > 0:
        intent.preferred_doc_type = "annual_report"
    elif concall_score > annual_score and concall_score > 0:
        intent.preferred_doc_type = "concall"

    # ── Speaker preference ────────────────────────────────────────────────────
    if any(sig in q_lower for sig in _MGMT_PREFERENCE_SIGNALS):
        intent.preferred_speaker_role = "management"
    elif any(sig in q_lower for sig in _ANALYST_PREFERENCE_SIGNALS):
        intent.preferred_speaker_role = "analyst"

    # ── Semantic flags to boost ───────────────────────────────────────────────
    if intent.is_forward_looking:
        intent.boost_flags.append("forward_looking")
    if "guidance" in q_lower or "target" in q_lower:
        intent.boost_flags.append("quantitative_guidance")
    if any(kw in q_lower for kw in ["commit", "plan", "strategy", "will"]):
        intent.boost_flags.append("contains_commitment")
    if any(kw in q_lower for kw in ["launch", "new product", "new platform"]):
        intent.boost_flags.append("contains_strategic")
    if any(kw in q_lower for kw in ["contract", "order", "won", "bagged"]):
        intent.boost_flags.append("contains_contract")

    # ── Year parsing ──────────────────────────────────────────────────────────
    intent.resolved_years, intent.explicit_years = parse_year_intent(query)

    # ── Query expansion ───────────────────────────────────────────────────────
    intent.expanded_query = _expand_query(query)

    return intent


# ═══════════════════════════════════════════════════════════════════════════════
# 4.  Query expansion  (enhanced v2)
# ═══════════════════════════════════════════════════════════════════════════════

def _expand_query(query: str) -> str:
    """
    Enrich the query string with domain-specific expansion phrases.
    v2: Also injects inferred section types and metrics for richer embedding match.
    """
    q_lower = query.lower()
    expansions: List[str] = []

    # Intent-based expansions
    for intent, phrases in _INTENT_EXPANSIONS.items():
        if intent in q_lower or any(p.lower() in q_lower for p in phrases[:3]):
            expansions.extend(phrases[:4])

    # Forward-looking signals
    if any(sig in q_lower for sig in ["outlook", "h1", "h2", "next", "expect",
                                       "guidance", "demand environment", "going forward"]):
        expansions.extend(_FORWARD_SIGNALS[:5])

    # Section-type injection
    for section, keywords in _SECTION_TYPE_KEYWORDS.items():
        if any(kw in q_lower for kw in keywords):
            expansions.append(section.lower().replace(" ", "_"))

    # Metric injection
    for metric in _FINANCIAL_METRICS:
        if metric in q_lower and metric not in expansions:
            expansions.append(metric)

    if not expansions:
        return query

    seen = set()
    unique = []
    for p in expansions:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    enriched = query + ". " + ". ".join(unique[:15])
    return enriched


# ═══════════════════════════════════════════════════════════════════════════════
# 5.  Result dataclass  (backward-compatible)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    score: float
    vector_score: float
    bm25_score: float
    metadata: Dict[str, Any]

    # v2 scoring transparency
    recency_boost: float = 0.0
    semantic_boost: float = 0.0
    metric_boost: float = 0.0
    importance_factor: float = 1.0
    table_boost: float = 0.0
    section_boost: float = 0.0
    hierarchy_boost: float = 0.0
    speaker_penalty: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 6.  Year intent parser  (unchanged from v1 — already fixed)
# ═══════════════════════════════════════════════════════════════════════════════

def _normalise_fy(raw: str) -> int:
    y = int(raw)
    return 2000 + y if y < 100 else y


def parse_year_intent(query: str) -> Tuple[List[int], List[int]]:
    """
    Returns (resolved_years, explicit_years).
    resolved_years  — full year list for ChromaDB/Qdrant where-filter.
    explicit_years  — only years the user actually named.
    """
    q = query.lower()

    m = re.search(r"(?:last|past|previous|recent)\s+(\d+)\s+years?", q)
    if m:
        n = int(m.group(1))
        years = list(range(CURRENT_FY - n + 1, CURRENT_FY + 1))
        return years, years

    m = re.search(
        r"fy[\s\-]*(\d{2,4})\s*(?:to|through|[-\/–])\s*(?:fy[\s\-]*)?(\d{2,4})",
        q,
    )
    if m:
        y1 = _normalise_fy(m.group(1))
        y2 = _normalise_fy(m.group(2))
        years = list(range(min(y1, y2), max(y1, y2) + 1))
        return years, years

    m = re.search(r"(20\d{2})\s*(?:to|through|\-|–)\s*(20\d{2})", q)
    if m:
        y1, y2 = int(m.group(1)), int(m.group(2))
        years = list(range(min(y1, y2), max(y1, y2) + 1))
        return years, years

    all_fy = re.findall(r"\bfy[\s\-]*(\d{2,4})\b", q)
    if len(all_fy) > 1:
        years = sorted({_normalise_fy(y) for y in all_fy})
        if years[-1] - years[0] == len(years) - 1:
            pass
        return years, years

    if len(all_fy) == 1:
        years = [_normalise_fy(all_fy[0])]
        return years, years

    m = re.search(r"(?:financial\s+year|year)\s+(20\d{2})", q)
    if m:
        years = [int(m.group(1))]
        return years, years

    plain_years = sorted({
        int(y) for y in re.findall(r"\b(20\d{2})\b", q)
        if 2010 <= int(y) <= CURRENT_FY
    })
    if plain_years:
        return plain_years, plain_years

    log.info(f"  No year hint found — defaulting to last {DEFAULT_LOOKBACK} FY")
    resolved = list(range(CURRENT_FY - DEFAULT_LOOKBACK + 1, CURRENT_FY + 1))
    return resolved, []


# ═══════════════════════════════════════════════════════════════════════════════
# 7.  Recency boost  (unchanged)
# ═══════════════════════════════════════════════════════════════════════════════

def recency_boost(year: int) -> float:
    return max(0.0, (year - 2000) * 0.01)


# ═══════════════════════════════════════════════════════════════════════════════
# 8.  BM25  (unchanged)
# ═══════════════════════════════════════════════════════════════════════════════

class BM25:
    def __init__(self, corpus: List[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tokenized = [self._tok(d) for d in corpus]
        self.N = len(corpus)
        self.avgdl = sum(len(d) for d in self.tokenized) / max(self.N, 1)
        self._build_idf()

    def _tok(self, text: str) -> List[str]:
        return re.findall(r"\b[a-zA-Z0-9%]+\b", text.lower())

    def _build_idf(self):
        from collections import Counter
        df = Counter()
        for doc in self.tokenized:
            df.update(set(doc))
        self.idf = {t: math.log((self.N - f + 0.5) / (f + 0.5) + 1)
                    for t, f in df.items()}

    def get_scores(self, query: str) -> List[float]:
        from collections import Counter
        qtoks = self._tok(query)
        scores = []
        for doc in self.tokenized:
            tf = Counter(doc)
            dl = len(doc)
            s = sum(
                self.idf.get(t, 0) *
                tf.get(t, 0) * (self.k1 + 1) /
                (tf.get(t, 0) + self.k1 * (1 - self.b + self.b * dl / max(self.avgdl, 1)))
                for t in qtoks
            )
            scores.append(s)
        return scores


def _minmax(scores: List[float]) -> List[float]:
    mn, mx = min(scores), max(scores)
    if mx == mn:
        return [1.0] * len(scores)
    return [(s - mn) / (mx - mn) for s in scores]


# ═══════════════════════════════════════════════════════════════════════════════
# 9.  Qdrant where-filter builder  (v2 — metadata-aware)
# ═══════════════════════════════════════════════════════════════════════════════

def _build_where(
    symbol: Optional[str],
    years: Optional[List[int]],
    intent: Optional[QueryIntent] = None,
) -> Optional[dict]:
    """
    Build a Qdrant filter dict. v2 adds metadata-aware filtering from query intent.
    """
    where: dict = {}
    if symbol:
        where["symbol"] = symbol.upper()
    if years:
        where["year"] = years[0] if len(years) == 1 else list(years)

    if intent:
        # Filter by inferred section type if we have high confidence
        if len(intent.inferred_section_types) == 1:
            where["section_type"] = intent.inferred_section_types[0]
        elif len(intent.inferred_section_types) > 1:
            where["section_type"] = intent.inferred_section_types

        # Filter by table type for financial-statement queries
        if intent.inferred_table_type:
            where["table_type"] = intent.inferred_table_type

        # Filter by speaker role for concall queries
        if intent.preferred_speaker_role:
            where["speaker_role"] = intent.preferred_speaker_role

        # Exclude duplicates and low-info chunks
        where["is_duplicate"] = False
        where["is_low_information"] = False

    return where or None


# ═══════════════════════════════════════════════════════════════════════════════
# 10.  Semantic scoring  (NEW)
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_semantic_boost(meta: Dict[str, Any], intent: QueryIntent) -> float:
    """
    Compute a boost based on how well a chunk's semantic flags align with
    the query intent. Range: 0.0 to +0.15.
    """
    boost = 0.0

    # Forward-looking alignment
    if intent.is_forward_looking and meta.get("forward_looking"):
        boost += 0.08
    if intent.is_historical and meta.get("historical"):
        boost += 0.05

    # Semantic flag alignment
    for flag in intent.boost_flags:
        if meta.get(flag):
            boost += 0.06

    # Quantitative guidance boost for guidance queries
    if "guidance" in intent.inferred_section_types and meta.get("quantitative_guidance"):
        boost += 0.10

    # Management opinion boost for opinion-seeking queries
    if intent.is_forward_looking and meta.get("management_opinion"):
        boost += 0.05

    return round(min(boost, 0.20), 3)


def _compute_metric_boost(meta: Dict[str, Any], intent: QueryIntent) -> float:
    """
    Boost chunks that explicitly mention the financial metrics the user asked about.
    Range: 0.0 to +0.12.
    """
    if not intent.inferred_metrics:
        return 0.0

    chunk_metrics = meta.get("financial_metrics", [])
    if not chunk_metrics:
        return 0.0

    chunk_metrics_l = [m.lower() for m in chunk_metrics]
    matches = sum(1 for m in intent.inferred_metrics if m.lower() in chunk_metrics_l)

    if matches >= 3:
        return 0.12
    elif matches >= 2:
        return 0.08
    elif matches >= 1:
        return 0.04
    return 0.0


def _compute_table_boost(meta: Dict[str, Any], intent: QueryIntent) -> float:
    """
    For financial-statement queries, strongly prefer table_summary chunks.
    Range: 0.0 to +0.15.
    """
    if not intent.inferred_table_type:
        return 0.0

    chunk_type = meta.get("chunk_type", "")
    table_type = meta.get("table_type", "")

    # Strong boost for matching table_summary
    if chunk_type == "table_summary" and table_type == intent.inferred_table_type:
        return 0.15
    if chunk_type == "table_summary":
        return 0.08
    # Slight boost for any table on table queries
    if chunk_type in ("table", "table_summary"):
        return 0.03
    return 0.0


def _compute_section_boost(meta: Dict[str, Any], intent: QueryIntent) -> float:
    """
    Boost chunks whose canonical section type matches the inferred query section.
    Range: 0.0 to +0.10.
    """
    if not intent.inferred_section_types:
        return 0.0

    chunk_section = meta.get("section_type", "")
    if not chunk_section:
        return 0.0

    if chunk_section in intent.inferred_section_types:
        return 0.10
    return 0.0


def _compute_hierarchy_boost(meta: Dict[str, Any], intent: QueryIntent) -> float:
    """
    Boost chunks whose hierarchy_path contains query-relevant sections.
    Range: 0.0 to +0.06.
    """
    hierarchy = meta.get("hierarchy_path", [])
    if not hierarchy or not intent.inferred_section_types:
        return 0.0

    hierarchy_l = [h.lower().replace(" ", "_") for h in hierarchy]
    for section in intent.inferred_section_types:
        if section.lower().replace(" ", "_") in hierarchy_l:
            return 0.06
    return 0.0


def _compute_importance_factor(meta: Dict[str, Any]) -> float:
    """
    Multiplicative factor based on chunk importance score.
    Maps 0.0–1.0 importance to 0.7–1.3 multiplier.
    """
    importance = meta.get("importance_score", 0.5)
    # Linear map: 0.0→0.7, 0.5→1.0, 1.0→1.3
    return 0.7 + (importance * 0.6)


# ═══════════════════════════════════════════════════════════════════════════════
# 11.  Core annual retrieval  (v2 — intent-aware)
# ═══════════════════════════════════════════════════════════════════════════════

def _run_annual_query(
    query: str,
    symbol: Optional[str],
    years: Optional[List[int]],
    top_k: int,
    intent: Optional[QueryIntent] = None,
) -> List[RetrievedChunk]:
    expanded_query = intent.expanded_query if intent else _expand_query(query)
    query_vec = embed_query(expanded_query)
    where = _build_where(symbol, years, intent)

    result = query_collection(
        doc_type="annual_report",
        query_embedding=query_vec,
        top_k=top_k * 2,  # retrieve more candidates for re-ranking
        where=where,
    )
    if not result:
        return []

    ids    = [r["id"] for r in result]
    docs   = [r["text"] for r in result]
    metas  = [r["metadata"] for r in result]
    vscore = [r["score"] for r in result]

    bm25   = BM25(docs)
    bscore = bm25.get_scores(expanded_query)

    nv = _minmax(vscore)
    nb = _minmax(bscore)
    fused = [(v + b) / 2 for v, b in zip(nv, nb)]

    results = []
    for cid, text, meta, fs, vs, bs in zip(ids, docs, metas, fused, vscore, bscore):
        # Skip duplicates and low-info (defensive, also filtered in where)
        if meta.get("is_duplicate") or meta.get("is_low_information"):
            continue

        # Compute all v2 boosts
        r_boost = recency_boost(meta.get("year", 0))
        s_boost = _compute_semantic_boost(meta, intent) if intent else 0.0
        m_boost = _compute_metric_boost(meta, intent) if intent else 0.0
        t_boost = _compute_table_boost(meta, intent) if intent else 0.0
        sec_boost = _compute_section_boost(meta, intent) if intent else 0.0
        h_boost = _compute_hierarchy_boost(meta, intent) if intent else 0.0
        imp_factor = _compute_importance_factor(meta)

        # Combine: fused score + additive boosts, then multiply by importance
        final_score = (fs + r_boost + s_boost + m_boost + t_boost + sec_boost + h_boost) * imp_factor
        final_score = max(0.0, min(final_score, 2.0))

        results.append(RetrievedChunk(
            chunk_id=cid, text=text, score=round(final_score, 4),
            vector_score=vs, bm25_score=bs, metadata=meta,
            recency_boost=r_boost, semantic_boost=s_boost,
            metric_boost=m_boost, table_boost=t_boost,
            section_boost=sec_boost, hierarchy_boost=h_boost,
            importance_factor=imp_factor,
        ))

    results.sort(key=lambda c: c.score, reverse=True)
    return results[:top_k]


def retrieve_annual(
    query: str,
    symbol: Optional[str] = None,
    years: Optional[List[int]] = None,
    intent: Optional[QueryIntent] = None,
) -> List[RetrievedChunk]:
    cfg = ANNUAL_RETRIEVAL

    results = _run_annual_query(query, symbol, years, cfg["top_k_vector"], intent)

    # Fallback: too few results → widen to all years
    if len(results) < MIN_RESULTS and years:
        log.warning(
            f"  Only {len(results)} annual results for years={years}, "
            f"falling back to all years"
        )
        results = _run_annual_query(query, symbol, years=None, top_k=cfg["top_k_vector"], intent=intent)

    log.info(f"  Annual retrieval: {len(results)} candidates | years={years} | "
             f"sections={intent.inferred_section_types if intent else '?'}")
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 12.  Core concall retrieval  (v2 — intent-aware)
# ═══════════════════════════════════════════════════════════════════════════════

def retrieve_concall(
    query: str,
    symbol: Optional[str] = None,
    years: Optional[List[int]] = None,
    speaker_role: Optional[str] = None,
    intent: Optional[QueryIntent] = None,
) -> List[RetrievedChunk]:
    cfg = CONCALL_RETRIEVAL
    expanded_query = intent.expanded_query if intent else _expand_query(query)
    query_vec = embed_query(expanded_query)

    where: dict = {}
    if symbol:
        where["symbol"] = symbol.upper()
    if years:
        where["year"] = years[0] if len(years) == 1 else list(years)

    # Speaker role: prefer intent-derived, fall back to explicit param
    effective_speaker = intent.preferred_speaker_role if (intent and intent.preferred_speaker_role) else speaker_role
    if effective_speaker:
        where["speaker_role"] = effective_speaker

    # Exclude duplicates and low-info
    where["is_duplicate"] = False
    where["is_low_information"] = False

    # Section-type filter for concalls
    if intent and intent.inferred_section_types:
        if len(intent.inferred_section_types) == 1:
            where["section_type"] = intent.inferred_section_types[0]
        else:
            where["section_type"] = intent.inferred_section_types

    where = where or None

    result = query_collection(
        doc_type="concall",
        query_embedding=query_vec,
        top_k=cfg["top_k_vector"] * 2,
        where=where,
    )

    if not result:
        if years:
            log.warning("  Concall: no results with year filter, falling back")
            where_fallback = {"symbol": symbol.upper()} if symbol else None
            if where_fallback:
                where_fallback["is_duplicate"] = False
                where_fallback["is_low_information"] = False
            result = query_collection(
                doc_type="concall",
                query_embedding=query_vec,
                top_k=cfg["top_k_vector"] * 2,
                where=where_fallback,
            )
        if not result:
            return []

    ids    = [r["id"] for r in result]
    docs   = [r["text"] for r in result]
    metas  = [r["metadata"] for r in result]
    vscore = [r["score"] for r in result]

    bm25   = BM25(docs)
    bscore = bm25.get_scores(expanded_query)

    nv     = _minmax(vscore)
    nb     = _minmax(bscore)
    fused  = [(v + b) / 2 for v, b in zip(nv, nb)]

    results = []
    for cid, text, meta, fs, vs, bs in zip(ids, docs, metas, fused, vscore, bscore):
        if meta.get("is_duplicate") or meta.get("is_low_information"):
            continue

        role = meta.get("speaker_role", "unknown")
        role_penalty = 0.0
        if role == "moderator":
            role_penalty = 0.08
        elif role == "unknown":
            role_penalty = 0.03

        # Intent-aware speaker boost
        speaker_boost = 0.0
        if intent:
            if intent.preferred_speaker_role == "management" and role == "management":
                speaker_boost = 0.06
            elif intent.preferred_speaker_role == "analyst" and role == "analyst":
                speaker_boost = 0.04
            # Forward-looking queries strongly prefer management
            if intent.is_forward_looking and role == "management":
                speaker_boost = max(speaker_boost, 0.08)

        r_boost = recency_boost(meta.get("year", 0))
        s_boost = _compute_semantic_boost(meta, intent) if intent else 0.0
        m_boost = _compute_metric_boost(meta, intent) if intent else 0.0
        sec_boost = _compute_section_boost(meta, intent) if intent else 0.0
        h_boost = _compute_hierarchy_boost(meta, intent) if intent else 0.0
        imp_factor = _compute_importance_factor(meta)

        final_score = (fs + r_boost + s_boost + m_boost + sec_boost + h_boost +
                       speaker_boost - role_penalty) * imp_factor
        final_score = max(0.0, min(final_score, 2.0))

        results.append(RetrievedChunk(
            chunk_id=cid, text=text,
            score=round(final_score, 4),
            vector_score=vs, bm25_score=bs, metadata=meta,
            recency_boost=r_boost, semantic_boost=s_boost,
            metric_boost=m_boost, section_boost=sec_boost,
            hierarchy_boost=h_boost, speaker_penalty=role_penalty,
            importance_factor=imp_factor,
        ))

    results.sort(key=lambda c: c.score, reverse=True)
    log.info(f"  Concall retrieval: {len(results)} candidates | years={years} | "
             f"speaker={effective_speaker or 'any'} | "
             f"sections={intent.inferred_section_types if intent else '?'}")
    return results[:cfg["top_k_vector"]]


# ═══════════════════════════════════════════════════════════════════════════════
# 13.  Unified entry point  (unchanged signature, enhanced internals)
# ═══════════════════════════════════════════════════════════════════════════════

def retrieve(
    query: str,
    doc_type: str,
    symbol: Optional[str] = None,
    year: Optional[int] = None,
    year_range: Optional[Tuple[int, int]] = None,
    speaker_role: Optional[str] = None,
) -> List[RetrievedChunk]:
    """
    Backward-compatible retrieve().
    Internally parses query intent and routes to the appropriate collection.
    """
    chunks, _, _ = retrieve_with_years(
        query, doc_type, symbol, year, year_range, speaker_role
    )
    return chunks


def retrieve_with_years(
    query: str,
    doc_type: str,
    symbol: Optional[str] = None,
    year: Optional[int] = None,
    year_range: Optional[Tuple[int, int]] = None,
    speaker_role: Optional[str] = None,
) -> Tuple[Any, List[int], List[int]]:
    """
    Returns (chunks_or_tuple, resolved_years, explicit_years).
    v2: Parses query intent once and passes it to collection-specific retrievers.
    """
    # Parse query intent once
    intent = _parse_query_intent(query)

    if year:
        intent.resolved_years = [year]
        intent.explicit_years = [year]
    elif year_range:
        intent.resolved_years = list(range(year_range[0], year_range[1] + 1))
        intent.explicit_years = intent.resolved_years

    log.info(f"  Query intent: sections={intent.inferred_section_types} | "
             f"metrics={intent.inferred_metrics} | "
             f"forward={intent.is_forward_looking} | "
             f"table_type={intent.inferred_table_type or '?'} | "
             f"doc_pref={intent.preferred_doc_type or '?'} | "
             f"speaker_pref={intent.preferred_speaker_role or '?'} | "
             f"years={intent.resolved_years}")

    if doc_type == "annual_report":
        chunks = retrieve_annual(query, symbol, intent.resolved_years, intent=intent)
        return chunks, intent.resolved_years, intent.explicit_years
    elif doc_type == "concall":
        chunks = retrieve_concall(query, symbol, intent.resolved_years, speaker_role, intent=intent)
        return chunks, intent.resolved_years, intent.explicit_years
    else:
        # "both" — intelligent routing based on query preference
        if intent.preferred_doc_type == "annual_report":
            annual  = retrieve_annual(query, symbol, intent.resolved_years, intent=intent)
            concall = []
        elif intent.preferred_doc_type == "concall":
            annual  = []
            concall = retrieve_concall(query, symbol, intent.resolved_years, speaker_role, intent=intent)
        else:
            annual  = retrieve_annual(query, symbol, intent.resolved_years, intent=intent)
            concall = retrieve_concall(query, symbol, intent.resolved_years, speaker_role, intent=intent)
        return (annual, concall), intent.resolved_years, intent.explicit_years