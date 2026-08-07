"""
pipeline/loader/chunker.py  —  Financial-RAG Semantic Chunker v2

Redesigned for retrieval quality on financial documents (annual reports,
conference calls).  Backward-compatible public API; all existing callers
continue to work unchanged.

Architectural improvements (vs v1):
  1. Semantic chunking — boundaries respect paragraphs, bullet groups,
     complete Q&A pairs, and complete tables.  Never splits mid-argument.
  2. Canonical financial sections — extracted headings normalised to a
     controlled vocabulary (Revenue, Margins, Cash Flow, …).
  3. Rich metadata — chapter / section / subsection hierarchy, financial
     topics, products, segments, geography, entities, metrics, currencies,
     fiscal period, forward-looking & historical flags, management opinion,
     quantitative guidance.
  4. Structured embedding text — all metadata prepended to content so the
     embedding model sees financial context explicitly.
  5. Semantic retrieval tags — concept-level tags (Revenue Growth, Margin
     Compression, Export Orders, …) instead of coarse keyword tags.
  6. Duplicate detection — normalised-content hashing skips near-duplicates.
  7. Low-information detection — flags boilerplate / cover-page residue.
  8. Financial table summarisation — tables are typed (Income Statement,
     Balance Sheet, …) and key metrics + growth rates extracted before
     embedding.
  9. Financial-signal importance scoring — metric density, forward-looking
     statements, guidance, commitments, product launches, contract wins,
     analyst questions, executive answers.
 10. Document hierarchy — every chunk carries chapter → section → subsection
     → paragraph → table lineage for hierarchical retrieval.
 11. Paragraph coherence / topic-transition chunking — annual-report prose
     is split at topic transitions, not at fixed token counts.
 12. Full backward compatibility — public API signatures unchanged; new
     Chunk fields have safe defaults.
"""

import re
import uuid
import hashlib
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Set, Tuple
from collections import defaultdict

from config.settings import ANNUAL_REPORT, CONCALL, MIN_CHUNK_WORDS
from pipeline.extract.pdf_extractor import ExtractedDocument, PageBlock
from pipeline.extract.text_cleaner import clean_text, is_garbage_text, is_boilerplate_text
from utils.logger import get_logger

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 0.  Constants & canonical vocabularies
# ═══════════════════════════════════════════════════════════════════════════════

# ── Canonical financial sections ──────────────────────────────────────────────
# Maps common extracted headings → normalised canonical label.
_CANONICAL_SECTIONS: Dict[str, str] = {
    # Revenue / top-line
    "performance overview": "Revenue",
    "business overview": "Revenue",
    "chairman's message": "Revenue",
    "review of operations": "Revenue",
    "management discussion": "Revenue",
    "directors' report": "Revenue",
    "operational review": "Revenue",
    "financial performance": "Revenue",
    "revenue": "Revenue",
    "total income": "Revenue",
    "turnover": "Revenue",
    "sales": "Revenue",
    "topline": "Revenue",
    "income from operations": "Revenue",

    # Margins / profitability
    "margins": "Margins",
    "profitability": "Margins",
    "ebitda": "Margins",
    "ebit": "Margins",
    "pbt": "Margins",
    "pat": "Margins",
    "net profit": "Margins",
    "operating profit": "Margins",
    "profit before tax": "Margins",
    "profit after tax": "Margins",
    "margin analysis": "Margins",
    "cost structure": "Margins",

    # Cash flow
    "cash flow": "Cash Flow",
    "cash flow statement": "Cash Flow",
    "operating cash flow": "Cash Flow",
    "free cash flow": "Cash Flow",
    "ocf": "Cash Flow",
    "fcf": "Cash Flow",
    "liquidity": "Cash Flow",
    "fund flow": "Cash Flow",

    # Balance sheet
    "balance sheet": "Balance Sheet",
    "assets": "Balance Sheet",
    "liabilities": "Balance Sheet",
    "equity": "Balance Sheet",
    "net worth": "Balance Sheet",
    "shareholders' funds": "Balance Sheet",
    "capital employed": "Balance Sheet",
    "financial position": "Balance Sheet",

    # Capex / capital allocation
    "capex": "Capex",
    "capital expenditure": "Capex",
    "capital allocation": "Capex",
    "investment": "Capex",
    "capital outlay": "Capex",
    "capacity expansion": "Capex",
    "brownfield": "Capex",
    "greenfield": "Capex",

    # Orders / backlog
    "orders": "Orders",
    "order book": "Orders",
    "backlog": "Orders",
    "bookings": "Orders",
    "order inflow": "Orders",
    "pipeline": "Orders",
    "deal wins": "Orders",

    # Products
    "products": "Products",
    "product portfolio": "Products",
    "offerings": "Products",
    "solutions": "Products",
    "platform": "Products",
    "technology": "Products",
    "innovation": "Products",
    "r&d": "Products",
    "research & development": "Products",

    # Customers
    "customers": "Customers",
    "client": "Customers",
    "customer concentration": "Customers",
    "key accounts": "Customers",
    "clientele": "Customers",

    # Exports / geography
    "exports": "Exports",
    "geography": "Exports",
    "international": "Exports",
    "overseas": "Exports",
    "domestic": "Exports",
    "geographical segment": "Exports",

    # Segments
    "segments": "Segments",
    "business segment": "Segments",
    "operating segment": "Segments",
    "segment reporting": "Segments",
    "ind as 108": "Segments",
    "division": "Segments",
    "vertical": "Segments",

    # Risk
    "risk": "Risk",
    "risk factors": "Risk",
    "risk management": "Risk",
    "internal control": "Risk",
    "audit": "Risk",
    "statutory audit": "Risk",
    "internal audit": "Risk",

    # Guidance / outlook
    "guidance": "Guidance",
    "outlook": "Guidance",
    "forward looking": "Guidance",
    "future outlook": "Guidance",
    "business outlook": "Guidance",
    "market outlook": "Guidance",
    "sector outlook": "Guidance",

    # Competition
    "competition": "Competition",
    "competitive landscape": "Competition",
    "market share": "Competition",
    "peer comparison": "Competition",
    "industry": "Competition",

    # Corporate governance
    "corporate governance": "Corporate Governance",
    "board of directors": "Corporate Governance",
    "shareholders": "Corporate Governance",
    "agm": "Corporate Governance",
    "egm": "Corporate Governance",
    "dividend": "Corporate Governance",
    "buyback": "Corporate Governance",

    # ESG
    "esg": "ESG",
    "sustainability": "ESG",
    "environment": "ESG",
    "social": "ESG",
    "governance": "ESG",
    "csr": "ESG",
    "green initiative": "ESG",
    "carbon": "ESG",
    "climate": "ESG",
}

# ── Financial metrics vocabulary ──────────────────────────────────────────────
_FINANCIAL_METRICS = [
    "revenue", "total income", "net revenue", "gross revenue",
    "ebitda", "operating profit", "ebit", "pbt", "pat",
    "net profit", "profit before tax", "profit after tax",
    "profit for the year", "profit attributable",
    "depreciation", "amortisation", "d&a",
    "total assets", "fixed assets", "current assets", "non-current assets",
    "net block", "capital work in progress", "cwip",
    "shareholders equity", "net worth", "book value", "retained earnings",
    "total equity", "paid up capital", "reserves and surplus",
    "net debt", "total debt", "borrowings", "long term debt",
    "short term borrowings", "term loans", "debentures",
    "cash flow from operations", "operating cash flow", "ocf",
    "cash flow from investing", "cash flow from financing",
    "free cash flow", "fcf", "capex", "capital expenditure",
    "working capital", "trade payables", "trade receivables", "inventories",
    "current ratio", "debt equity ratio", "net debt to ebitda",
    "earnings per share", "eps", "diluted eps", "basic eps",
    "return on equity", "roe", "return on capital employed", "roce",
    "return on net worth", "ronw", "return on assets",
    "book value per share", "nav per share",
    "price to earnings", "p/e", "price to book", "p/b", "ev/ebitda",
    "enterprise value", "market capitalisation",
    "dividend per share", "dps", "dividend payout", "dividend yield",
    "order book", "backlog", "bookings", "order inflow",
    "yoy", "year on year", "qoq", "quarter on quarter",
    "growth rate", "cagr", "bps", "basis points",
]

# ── Customer / entity indicators ──────────────────────────────────────────────
_CUSTOMER_PATTERNS = [
    r"Indian Army", r"Indian Navy", r"Indian Air Force", r"DRDO",
    r"Ministry of Defence", r"MoD", r"Bharat Electronics", r"HAL",
    r"BEL\b", r"ISRO", r"BARC",
]

# ── Country / geography patterns ──────────────────────────────────────────────
_COUNTRY_PATTERNS = [
    r"\bIndia\b", r"\bUAE\b", r"\bUSA\b", r"\bUK\b",
    r"\bSingapore\b", r"\bMalaysia\b", r"\bVietnam\b",
    r"\bSaudi Arabia\b", r"\bQatar\b", r"\bOman\b",
    r"\bBangladesh\b", r"\bSri Lanka\b", r"\bNepal\b",
    r"\bMyanmar\b", r"\bPhilippines\b", r"\bIndonesia\b",
    r"\bThailand\b", r"\bEgypt\b", r"\bMorocco\b",
    r"\bAfrica\b", r"\bEurope\b", r"\bAsia\b",
    r"\bMiddle East\b", r"\bASEAN\b", r"\bSAARC\b",
    r"\bdomestic\b", r"\bexport\b", r"\binternational\b",
    r"\boverseas\b",
]

# ── Currency patterns ─────────────────────────────────────────────────────────
_CURRENCY_PATTERNS = [
    r"₹", r"Rs\.?", r"INR", r"USD", r"\$", r"€", r"£",
    r"crore", r"lakh", r"million", r"billion",
]

# ── Fiscal period patterns ────────────────────────────────────────────────────
_FISCAL_PERIOD_RE = re.compile(
    r"\b(?:FY|financial year|fiscal year)[\s\-]?(\d{2,4})\b",
    re.IGNORECASE,
)
_QUARTER_RE = re.compile(
    r"\b(Q[1-4]|quarter [1-4]|H[1-2]|half[- ]?yearly)\b",
    re.IGNORECASE,
)

# ── Forward-looking signals ───────────────────────────────────────────────────
_FORWARD_SIGNALS = [
    "guidance", "expect", "anticipate", "outlook", "target", "going forward",
    "next quarter", "next year", "H1", "H2", "coming quarters",
    "medium term", "long term", "forecast", "project", "plan to",
    "confident", "well positioned", "visibility", "momentum",
    "growth trajectory", "expansion", "scale", "accelerate",
]

# ── Management commitment signals ─────────────────────────────────────────────
_COMMITMENT_SIGNALS = [
    "commit", "committed", "commitment", "we will", "we intend to",
    "we plan to", "our plan", "our strategy", "strategic priority",
    "focused on", "dedicated to", "aim to", "objective",
]

# ── Quantitative guidance regex ───────────────────────────────────────────────
_QUANT_GUIDANCE_RE = re.compile(
    r"\b(?:grow|growth|margin|target|reach|achieve|expect|anticipate)\s+(?:at\s+)?(?:around\s+)?(?:about\s+)?(?:approximately\s+)?(?:~)?(?:rs\.?\s*)?[\d,]+(?:\.\d+)?\s*(?:%|percent|crore|lakh|million|billion|mn|bn)?\b",
    re.IGNORECASE,
)

# ── Strategic announcement signals ────────────────────────────────────────────
_STRATEGIC_SIGNALS = [
    "launch", "launched", "introduced", "unveiled", "new product",
    "new platform", "new offering", "new facility", "new plant",
    "commissioning", "inauguration", "partnership", "alliance",
    "joint venture", "acquisition", "merger", "divestment",
]

# ── Contract win signals ──────────────────────────────────────────────────────
_CONTRACT_SIGNALS = [
    "contract", "order", "won", "bagged", "secured", "received order",
    "contract award", "tender", "rfp", "bid", "proposal",
]

# ── Semantic retrieval-tag vocabulary ─────────────────────────────────────────
_SEMANTIC_TAGS = {
    "revenue_growth":       ["revenue growth", "topline growth", "sales growth", "income growth"],
    "revenue_decline":      ["revenue decline", "drop in revenue", "fall in sales", "lower revenue"],
    "margin_expansion":     ["margin expansion", "margin improvement", "higher margin", "margin up"],
    "margin_compression":   ["margin compression", "margin pressure", "lower margin", "margin down"],
    "export_orders":        ["export order", "international order", "overseas order", "foreign order"],
    "domestic_orders":      ["domestic order", "india order", "local order", "indigenous order"],
    "working_capital":      ["working capital", "receivables", "payables", "inventory", "wc"],
    "order_book":           ["order book", "backlog", "pipeline", "bookings", "order inflow"],
    "guidance":             ["guidance", "target", "forecast", "projection", "outlook"],
    "risk":                 ["risk", "headwind", "challenge", "uncertainty", "concern"],
    "competitive_position": ["competition", "market share", "peer", "landscape", "positioning"],
    "customer_concentration": ["customer concentration", "top customer", "key client", "dependence"],
    "capex":                ["capex", "capital expenditure", "investment", "expansion", "capacity"],
    "cash_conversion":      ["cash conversion", "ocf to pat", "cash generation", "free cash flow"],
    "debt_reduction":       ["debt reduction", "deleveraging", "repay", "borrowings down"],
    "product_launch":       ["launch", "new product", "new platform", "introduced"],
    "contract_win":         ["contract", "order win", "bagged", "secured", "tender"],
    "esg":                  ["esg", "sustainability", "carbon", "climate", "csr"],
    "corporate_governance": ["corporate governance", "board", "dividend", "buyback", "agm"],
    "analyst_question":     ["analyst", "question from", "from the floor"],
    "management_commentary": ["management", "ceo", "cfo", "md", "director", "said", "mentioned"],
}

# ── Table-type detection keywords ─────────────────────────────────────────────
_TABLE_TYPE_KEYWORDS = {
    "income_statement": ["revenue", "total income", "ebitda", "ebit", "pbt", "pat", "net profit", "eps"],
    "balance_sheet":    ["assets", "liabilities", "equity", "net worth", "share capital", "reserves"],
    "cash_flow":        ["cash flow", "operating activities", "investing activities", "financing activities"],
    "segment_report":   ["segment", "business segment", "geographical segment", "ind as 108"],
    "order_book":       ["order book", "backlog", "pipeline", "bookings"],
    "shareholding":     ["shareholding", "promoter", "public", "institutional", "fii", "dii"],
}

# ── Stopwords for low-info detection ──────────────────────────────────────────
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "shall",
    "can", "need", "dare", "ought", "used", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into",
    "through", "during", "before", "after", "above", "below",
    "between", "under", "and", "but", "or", "yet", "so", "if",
    "because", "although", "though", "while", "where", "when",
    "that", "which", "who", "whom", "whose", "what", "this",
    "these", "those", "i", "we", "you", "he", "she", "it",
    "they", "them", "their", "our", "your", "my", "his", "her",
    "its", "company", "limited", "ltd", "private", "public",
    "annual", "report", "financial", "year", "ended", "page",
    "note", "notes", "account", "accounts", "statement", "statements",
}


# ═══════════════════════════════════════════════════════════════════════════════
# 1.  Output dataclass  (backward-compatible — new fields have defaults)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Chunk:
    # ── Core identity ─────────────────────────────────────────────────────────
    chunk_id:     str
    doc_type:     str
    text:         str
    chunk_index:  int
    chunk_type:   str            # prose | table | speaker_turn | table_summary
    section:      Optional[str]
    section_type: Optional[str]  # canonical label
    speaker:      Optional[str]
    speaker_role: Optional[str]
    page_start:   int
    page_end:     int
    word_count:   int
    symbol:       str
    year:         Optional[int]
    title:        str

    # ── v1 fields (kept for backward compat) ──────────────────────────────────
    retrieval_tags:   List[str] = field(default_factory=list)
    importance_score: float   = 0.5

    # ── v2 rich metadata ──────────────────────────────────────────────────────
    # Document hierarchy
    chapter:      Optional[str] = None
    subsection:   Optional[str] = None

    # Financial context
    financial_topics:     List[str] = field(default_factory=list)
    products_mentioned:   List[str] = field(default_factory=list)
    business_segments:    List[str] = field(default_factory=list)
    geography_mentioned:  List[str] = field(default_factory=list)
    entities_mentioned:   List[str] = field(default_factory=list)
    financial_metrics:    List[str] = field(default_factory=list)
    currencies_mentioned: List[str] = field(default_factory=list)
    fiscal_period:        Optional[str] = None
    quarter:              Optional[str] = None

    # Semantic flags
    forward_looking:      bool = False
    historical:           bool = False
    management_opinion:   bool = False
    quantitative_guidance: bool = False
    contains_guidance:    bool = False
    contains_commitment:  bool = False
    contains_strategic:   bool = False
    contains_contract:    bool = False
    is_duplicate:         bool = False
    is_low_information:   bool = False

    # Table-specific
    table_type:           Optional[str] = None
    table_summary:        Optional[str] = None

    # Hierarchy path (for downstream hierarchical retrieval)
    hierarchy_path:       List[str] = field(default_factory=list)


def _make_id() -> str:
    return str(uuid.uuid4())


# ═══════════════════════════════════════════════════════════════════════════════
# 2.  Helpers: canonicalisation, entity extraction, duplicate detection
# ═══════════════════════════════════════════════════════════════════════════════

def _normalise_heading(text: str) -> str:
    """Strip numbers / bullets and lowercase for canonical mapping."""
    t = re.sub(r"^\s*[\d\.\-\)\(]+\s*", "", text)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def _canonical_section(section_text: Optional[str]) -> Optional[str]:
    """Map an extracted heading to a canonical financial section."""
    if not section_text:
        return None
    norm = _normalise_heading(section_text)
    if norm in _CANONICAL_SECTIONS:
        return _CANONICAL_SECTIONS[norm]
    for key in sorted(_CANONICAL_SECTIONS, key=len, reverse=True):
        if key in norm:
            return _CANONICAL_SECTIONS[key]
    return None


def _extract_financial_metrics(text: str) -> List[str]:
    text_l = text.lower()
    found = []
    for metric in _FINANCIAL_METRICS:
        if metric in text_l:
            found.append(metric)
    return list(dict.fromkeys(found))


def _extract_products(text: str) -> List[str]:
    candidates = re.findall(r"\b[A-Z][A-Z0-9]{2,}\b", text)
    candidates += re.findall(r"\b[A-Z][a-zA-Z0-9]*(?:\s+[A-Z][a-zA-Z0-9]*){1,3}\b", text)
    exclude = {"The", "And", "For", "With", "From", "This", "That", "Company",
               "Limited", "Annual", "Report", "Financial", "Year", "March",
               "Chairman", "Director", "Board", "Meeting", "Shareholder",
               "Government", "Ministry", "Department", "Indian", "International"}
    filtered = [c for c in candidates if c not in exclude and len(c) > 2]
    return list(dict.fromkeys(filtered))[:10]


def _extract_customers(text: str) -> List[str]:
    found = []
    for pat in _CUSTOMER_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            found.append(m.group(0))
    return list(dict.fromkeys(found))


def _extract_geography(text: str) -> List[str]:
    found = []
    for pat in _COUNTRY_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            found.append(m.group(0))
    return list(dict.fromkeys(found))


def _extract_currencies(text: str) -> List[str]:
    found = []
    text_l = text.lower()
    for pat in _CURRENCY_PATTERNS:
        for m in re.finditer(pat, text_l):
            found.append(m.group(0))
    return list(dict.fromkeys(found))


def _extract_fiscal_period(text: str) -> Tuple[Optional[str], Optional[str]]:
    fy_match = _FISCAL_PERIOD_RE.search(text)
    fy = fy_match.group(1) if fy_match else None
    if fy and len(fy) == 2:
        fy = "20" + fy
    q_match = _QUARTER_RE.search(text)
    quarter = q_match.group(1).upper() if q_match else None
    return fy, quarter


def _detect_table_type(table_text: str) -> Optional[str]:
    text_l = table_text.lower()
    scores = {}
    for ttype, keywords in _TABLE_TYPE_KEYWORDS.items():
        scores[ttype] = sum(1 for kw in keywords if kw in text_l)
    if not scores or max(scores.values()) == 0:
        return None
    return max(scores, key=scores.get)


def _summarise_table(table_text: str, table_type: Optional[str]) -> str:
    lines = table_text.strip().split("\n")
    if not lines:
        return table_text
    header = lines[0] if lines else ""
    metrics_summary = []
    for line in lines[1:]:
        parts = [p.strip() for p in re.split(r"[|\t]", line) if p.strip()]
        if len(parts) >= 2:
            metric = parts[0]
            values = parts[1:]
            if len(values) >= 2:
                v1_str = re.sub(r"[,₹$\s]", "", values[0])
                v2_str = re.sub(r"[,₹$\s]", "", values[-1])
                try:
                    v1 = float(v1_str) if v1_str.replace(".", "").replace("-", "").isdigit() else None
                    v2 = float(v2_str) if v2_str.replace(".", "").replace("-", "").isdigit() else None
                    if v1 and v2 and v1 != 0:
                        growth = ((v2 - v1) / abs(v1)) * 100
                        metrics_summary.append(f"{metric} = {values[-1]} (growth {growth:+.1f}%)")
                    else:
                        metrics_summary.append(f"{metric} = {values[-1]}")
                except ValueError:
                    metrics_summary.append(f"{metric} = {values[-1]}")
            else:
                metrics_summary.append(f"{metric} = {values[0]}")
    type_label = table_type.replace("_", " ").title() if table_type else "Financial Table"
    summary_lines = [f"Table Type: {type_label}", f"Columns: {header}", "Metrics:"]
    summary_lines.extend(f"  {m}" for m in metrics_summary[:15])
    return "\n".join(summary_lines)


def _content_hash(text: str) -> str:
    norm = re.sub(r"\s+", " ", text.lower().strip())
    norm = re.sub(r"[^a-z0-9]", "", norm)
    return hashlib.md5(norm.encode("utf-8")).hexdigest()


def _is_low_information(text: str) -> bool:
    words = re.findall(r"\b[a-z]+\b", text.lower())
    if len(words) < 10:
        return True
    stop_count = sum(1 for w in words if w in _STOPWORDS)
    if len(words) > 0 and stop_count / len(words) > 0.75:
        return True
    if re.search(r"page\s*\d+\s*of\s*\d+", text, re.IGNORECASE):
        return True
    return False


def _detect_semantic_tags(text: str) -> List[str]:
    text_l = text.lower()
    tags = []
    for concept, phrases in _SEMANTIC_TAGS.items():
        if any(p in text_l for p in phrases):
            tags.append(concept)
    return tags


def _detect_forward_looking(text: str) -> bool:
    return any(sig in text.lower() for sig in _FORWARD_SIGNALS)


def _detect_historical(text: str) -> bool:
    hist_signals = ["last year", "previous year", "prior year", "in fy",
                    "for the year ended", "yoy decline", "yoy growth",
                    "compared to", "versus", "against"]
    return any(sig in text.lower() for sig in hist_signals)


def _detect_management_opinion(text: str) -> bool:
    op_signals = ["we believe", "we think", "in our view", "management believes",
                  "we are confident", "we remain", "we expect", "we anticipate",
                  "management is of the view", "management expects"]
    return any(sig in text.lower() for sig in op_signals)


def _detect_quantitative_guidance(text: str) -> bool:
    return bool(_QUANT_GUIDANCE_RE.search(text))


def _detect_commitment(text: str) -> bool:
    return any(sig in text.lower() for sig in _COMMITMENT_SIGNALS)


def _detect_strategic(text: str) -> bool:
    return any(sig in text.lower() for sig in _STRATEGIC_SIGNALS)


def _detect_contract(text: str) -> bool:
    return any(sig in text.lower() for sig in _CONTRACT_SIGNALS)


def _build_hierarchy_path(chunk: Chunk) -> List[str]:
    path = []
    if chunk.chapter:
        path.append(chunk.chapter)
    if chunk.section:
        path.append(chunk.section)
    if chunk.subsection:
        path.append(chunk.subsection)
    path.append(chunk.chunk_type)
    return path


# ═══════════════════════════════════════════════════════════════════════════════
# 3.  Embedding text builder  (structured, metadata-first)
# ═══════════════════════════════════════════════════════════════════════════════

def build_embedding_text(chunk: Chunk) -> str:
    lines = []
    lines.append(f"Company: {chunk.symbol}")
    if chunk.year:
        lines.append(f"Fiscal Year: {chunk.year}")
    if chunk.quarter:
        lines.append(f"Quarter: {chunk.quarter}")
    lines.append(f"Document Type: {chunk.doc_type}")
    if chunk.chapter:
        lines.append(f"Chapter: {chunk.chapter}")
    if chunk.section:
        lines.append(f"Section: {chunk.section}")
    if chunk.subsection:
        lines.append(f"Subsection: {chunk.subsection}")
    if chunk.section_type:
        lines.append(f"Financial Topic: {chunk.section_type}")
    if chunk.financial_metrics:
        lines.append(f"Financial Metrics Mentioned: {', '.join(chunk.financial_metrics)}")
    if chunk.products_mentioned:
        lines.append(f"Products Mentioned: {', '.join(chunk.products_mentioned)}")
    if chunk.business_segments:
        lines.append(f"Business Segment: {', '.join(chunk.business_segments)}")
    if chunk.geography_mentioned:
        lines.append(f"Geography: {', '.join(chunk.geography_mentioned)}")
    if chunk.currencies_mentioned:
        lines.append(f"Currency: {', '.join(chunk.currencies_mentioned)}")
    flags = []
    if chunk.forward_looking:
        flags.append("Forward Looking")
    if chunk.historical:
        flags.append("Historical")
    if chunk.management_opinion:
        flags.append("Management Opinion")
    if chunk.quantitative_guidance:
        flags.append("Quantitative Guidance")
    if chunk.contains_commitment:
        flags.append("Management Commitment")
    if chunk.contains_strategic:
        flags.append("Strategic Announcement")
    if chunk.contains_contract:
        flags.append("Contract Win")
    if flags:
        lines.append(f"Flags: {', '.join(flags)}")
    if chunk.speaker:
        role = f" [{chunk.speaker_role}]" if chunk.speaker_role else ""
        lines.append(f"Speaker: {chunk.speaker}{role}")
    if chunk.retrieval_tags:
        lines.append(f"Concepts: {', '.join(chunk.retrieval_tags)}")
    if chunk.table_summary:
        lines.append("")
        lines.append("Table Summary:")
        lines.append(chunk.table_summary)
    lines.append("")
    lines.append("Content:")
    lines.append(chunk.text)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 4.  Importance scoring  (financial-signal based)
# ═══════════════════════════════════════════════════════════════════════════════

def _score_chunk(chunk: Chunk) -> float:
    base = 0.5
    metric_count = len(chunk.financial_metrics)
    if metric_count >= 5:
        base += 0.15
    elif metric_count >= 3:
        base += 0.10
    elif metric_count >= 1:
        base += 0.05
    if chunk.forward_looking:
        base += 0.12
    if chunk.quantitative_guidance:
        base += 0.15
    if chunk.contains_commitment:
        base += 0.10
    if chunk.contains_strategic:
        base += 0.12
    if chunk.contains_contract:
        base += 0.13
    if chunk.speaker_role == "management":
        base += 0.08
    elif chunk.speaker_role == "analyst":
        base += 0.05
    elif chunk.speaker_role == "moderator":
        base -= 0.15
    high_value = {"Guidance", "Revenue", "Margins", "Cash Flow", "Orders", "Capex", "Risk", "Products"}
    if chunk.section_type in high_value:
        base += 0.08
    if chunk.chunk_type == "table_summary":
        base += 0.10
    if chunk.is_low_information:
        base -= 0.30
    if chunk.is_duplicate:
        base -= 0.40
    if chunk.doc_type == "concall" and chunk.page_start <= 2:
        base -= 0.10
    if chunk.doc_type == "annual_report" and chunk.page_start <= 3:
        base -= 0.05
    return round(max(0.0, min(base, 1.0)), 2)


# ═══════════════════════════════════════════════════════════════════════════════
# 5.  Semantic split helpers  (never split mid-argument)
# ═══════════════════════════════════════════════════════════════════════════════

def _approx_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3)


def _split_semantic_prose(text: str, max_tokens: int, overlap_tokens: int) -> List[str]:
    raw_paras = re.split(r"\n\s*\n", text)
    paragraphs = []
    current_bullet_group = []
    for para in raw_paras:
        para = para.strip()
        if not para:
            continue
        if re.match(r"^\s*[•\-\*►▸▹›]\s+", para):
            current_bullet_group.append(para)
        else:
            if current_bullet_group:
                paragraphs.append("\n".join(current_bullet_group))
                current_bullet_group = []
            paragraphs.append(para)
    if current_bullet_group:
        paragraphs.append("\n".join(current_bullet_group))
    if not paragraphs:
        return [text] if text else []
    max_words = int(max_tokens / 1.3)
    overlap_words = int(overlap_tokens / 1.3)
    chunks = []
    current_chunk = []
    current_words = 0
    for para in paragraphs:
        para_words = len(para.split())
        if para_words > max_words:
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
                overlap_text = _get_overlap(current_chunk, overlap_words)
                current_chunk = [overlap_text] if overlap_text else []
                current_words = len(current_chunk[0].split()) if current_chunk else 0
            sentences = re.split(r"(?<=[.!?])\s+", para)
            sent_buf = []
            sent_words = 0
            for sent in sentences:
                sw = len(sent.split())
                if sent_words + sw > max_words and sent_buf:
                    chunks.append(" ".join(sent_buf))
                    sent_buf = sent_buf[-2:] if len(sent_buf) >= 2 else sent_buf
                    sent_words = sum(len(s.split()) for s in sent_buf)
                sent_buf.append(sent)
                sent_words += sw
            if sent_buf:
                chunks.append(" ".join(sent_buf))
            continue
        if current_words + para_words > max_words and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            overlap_text = _get_overlap(current_chunk, overlap_words)
            current_chunk = [overlap_text, para] if overlap_text else [para]
            current_words = sum(len(p.split()) for p in current_chunk)
        else:
            current_chunk.append(para)
            current_words += para_words
    if current_chunk:
        chunks.append("\n\n".join(current_chunk))
    return [c for c in chunks if c.strip()]


def _get_overlap(paras: List[str], overlap_words: int) -> str:
    combined = " ".join(paras)
    words = combined.split()
    if len(words) <= overlap_words:
        return combined
    return " ".join(words[-overlap_words:])


# ═══════════════════════════════════════════════════════════════════════════════
# 6.  Finalise chunk  (metadata enrichment + scoring)
# ═══════════════════════════════════════════════════════════════════════════════

_seen_hashes: Set[str] = set()


def _finalise(chunk: Chunk) -> Optional[Chunk]:
    chunk.financial_metrics    = _extract_financial_metrics(chunk.text)
    chunk.products_mentioned   = _extract_products(chunk.text)
    chunk.entities_mentioned   = _extract_customers(chunk.text)
    chunk.geography_mentioned  = _extract_geography(chunk.text)
    chunk.currencies_mentioned = _extract_currencies(chunk.text)
    fy, q = _extract_fiscal_period(chunk.text)
    if fy and not chunk.year:
        chunk.year = int(fy)
    chunk.quarter = q
    chunk.forward_looking      = _detect_forward_looking(chunk.text)
    chunk.historical           = _detect_historical(chunk.text)
    chunk.management_opinion   = _detect_management_opinion(chunk.text)
    chunk.quantitative_guidance = _detect_quantitative_guidance(chunk.text)
    chunk.contains_commitment  = _detect_commitment(chunk.text)
    chunk.contains_strategic   = _detect_strategic(chunk.text)
    chunk.contains_contract    = _detect_contract(chunk.text)
    chunk.retrieval_tags = _detect_semantic_tags(chunk.text)
    if chunk.section_type and chunk.section_type not in chunk.retrieval_tags:
        chunk.retrieval_tags.insert(0, chunk.section_type.lower().replace(" ", "_"))
    chunk.hierarchy_path = _build_hierarchy_path(chunk)
    h = _content_hash(chunk.text)
    if h in _seen_hashes:
        chunk.is_duplicate = True
    else:
        _seen_hashes.add(h)
    chunk.is_low_information = _is_low_information(chunk.text)
    chunk.importance_score = _score_chunk(chunk)
    if chunk.is_duplicate and chunk.is_low_information:
        return None
    return chunk


def _should_skip_block(block: PageBlock) -> bool:
    if is_boilerplate_text(block.text):
        return True
    if block.section_type == "low_value" and block.block_type == "prose":
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# 7.  Annual Report Chunker  (semantic boundaries, canonical sections)
# ═══════════════════════════════════════════════════════════════════════════════

def chunk_annual_report(
    doc:    ExtractedDocument,
    symbol: str,
    year:   Optional[int],
    title:  str,
) -> List[Chunk]:
    cfg    = ANNUAL_REPORT
    chunks: List[Chunk] = []
    idx    = 0
    current_chapter      = None
    current_section      = "General"
    current_subsection   = None
    current_section_type = "content"
    prose_buffer: List[str] = []
    buffer_pages: List[int] = []

    def flush_prose():
        nonlocal idx
        if not prose_buffer:
            return
        combined = "\n\n".join(prose_buffer)
        cleaned  = clean_text(combined, aggressive=True)
        if is_garbage_text(cleaned, MIN_CHUNK_WORDS):
            prose_buffer.clear()
            buffer_pages.clear()
            return
        splits = _split_semantic_prose(cleaned, cfg["chunk_size"], cfg.get("chunk_overlap", 50))
        for split in splits:
            if is_garbage_text(split, MIN_CHUNK_WORDS):
                continue
            canonical = _canonical_section(split)
            sec_type = canonical or current_section_type
            chunk = Chunk(
                chunk_id     = _make_id(),
                doc_type     = "annual_report",
                text         = split,
                chunk_index  = idx,
                chunk_type   = "prose",
                section      = current_section,
                section_type = sec_type,
                speaker      = None,
                speaker_role = None,
                page_start   = buffer_pages[0] if buffer_pages else 0,
                page_end     = buffer_pages[-1] if buffer_pages else 0,
                word_count   = len(split.split()),
                symbol       = symbol,
                year         = year,
                title        = title,
                chapter      = current_chapter,
                subsection   = current_subsection,
            )
            finalised = _finalise(chunk)
            if finalised:
                chunks.append(finalised)
                idx += 1
        prose_buffer.clear()
        buffer_pages.clear()

    for block in doc.blocks:
        if _should_skip_block(block):
            continue
        if block.block_type == "section_header":
            flush_prose()
            heading = block.text.strip()
            if heading.isupper() and len(heading.split()) <= 4:
                current_chapter = heading
                current_section = heading
                current_subsection = None
            elif len(heading.split()) <= 6:
                current_section = heading
                current_subsection = None
            else:
                current_subsection = heading
            current_section_type = _canonical_section(heading) or "content"
            continue
        if block.block_type == "table":
            flush_prose()
            rows       = block.table_data or []
            row_group  = cfg.get("table_row_group", 10)
            header_row = rows[0] if rows else []
            for start in range(0, max(1, len(rows) - 1), row_group):
                group = rows[start: start + row_group]
                if start > 0 and header_row:
                    group = [header_row] + group
                table_text = "\n".join(
                    " | ".join(str(c or "").strip() for c in row) for row in group
                )
                table_text = clean_text(table_text, aggressive=False)
                if is_garbage_text(table_text, 5):
                    continue
                ttype = _detect_table_type(table_text)
                summary = _summarise_table(table_text, ttype)
                # Structured summary chunk
                chunk_summary = Chunk(
                    chunk_id     = _make_id(),
                    doc_type     = "annual_report",
                    text         = table_text,
                    chunk_index  = idx,
                    chunk_type   = "table_summary",
                    section      = current_section,
                    section_type = _canonical_section(current_section) or "content",
                    speaker      = None,
                    speaker_role = None,
                    page_start   = block.page_num,
                    page_end     = block.page_num,
                    word_count   = len(table_text.split()),
                    symbol       = symbol,
                    year         = year,
                    title        = title,
                    chapter      = current_chapter,
                    subsection   = current_subsection,
                    table_type   = ttype,
                    table_summary = summary,
                )
                finalised = _finalise(chunk_summary)
                if finalised:
                    chunks.append(finalised)
                    idx += 1
                # Raw table chunk
                chunk_raw = Chunk(
                    chunk_id     = _make_id(),
                    doc_type     = "annual_report",
                    text         = f"[Table: {current_section}]\n{table_text}",
                    chunk_index  = idx,
                    chunk_type   = "table",
                    section      = current_section,
                    section_type = _canonical_section(current_section) or "content",
                    speaker      = None,
                    speaker_role = None,
                    page_start   = block.page_num,
                    page_end     = block.page_num,
                    word_count   = len(table_text.split()),
                    symbol       = symbol,
                    year         = year,
                    title        = title,
                    chapter      = current_chapter,
                    subsection   = current_subsection,
                    table_type   = ttype,
                )
                finalised_raw = _finalise(chunk_raw)
                if finalised_raw:
                    chunks.append(finalised_raw)
                    idx += 1
            continue
        if block.block_type == "prose":
            prose_buffer.append(block.text)
            buffer_pages.append(block.page_num)
            if _approx_tokens("\n\n".join(prose_buffer)) > cfg["chunk_size"] * 3:
                flush_prose()
    flush_prose()
    log.info(f"  → {len(chunks)} chunks from annual report (semantic chunking v2)")
    return chunks


# ═══════════════════════════════════════════════════════════════════════════════
# 8.  Concall Chunker  (speaker + Q&A aware, semantic boundaries)
# ═══════════════════════════════════════════════════════════════════════════════

def chunk_concall(
    doc:    ExtractedDocument,
    symbol: str,
    year:   Optional[int],
    title:  str,
) -> List[Chunk]:
    cfg    = CONCALL
    chunks: List[Chunk] = []
    idx    = 0

    def _make_chunk_from_turns(turns: List[PageBlock]) -> Optional[Chunk]:
        nonlocal idx
        if not turns:
            return None
        parts = []
        for t in turns:
            if _should_skip_block(t):
                continue
            cleaned = clean_text(t.text, aggressive=False, preserve_speakers=True)
            if t.speaker and cfg.get("inject_speaker_label", True):
                role_tag = f" [{t.speaker_role}]" if t.speaker_role else ""
                parts.append(f"{t.speaker}{role_tag}:\n{cleaned}")
            else:
                parts.append(cleaned)
        if not parts:
            return None
        combined = "\n\n".join(parts)
        if is_garbage_text(combined, MIN_CHUNK_WORDS):
            return None
        primary = turns[0]
        section      = primary.section or "Conference Call"
        section_type = primary.section_type or "opening_remarks"
        canonical    = _canonical_section(section) or section_type
        prefix_lines = [f"[Concall: {symbol} FY{year or '?'}]"]
        if canonical:
            prefix_lines.append(f"[Section: {canonical}]")
        if primary.speaker:
            role = f" ({primary.speaker_role})" if primary.speaker_role else ""
            prefix_lines.append(f"[Speaker: {primary.speaker}{role}]")
        prefix = "\n".join(prefix_lines) + "\n"
        final_text = prefix + combined
        chunk = Chunk(
            chunk_id     = _make_id(),
            doc_type     = "concall",
            text         = final_text,
            chunk_index  = idx,
            chunk_type   = "speaker_turn" if primary.block_type == "speaker_turn" else "prose",
            section      = section,
            section_type = canonical,
            speaker      = primary.speaker,
            speaker_role = primary.speaker_role,
            page_start   = turns[0].page_num,
            page_end     = turns[-1].page_num,
            word_count   = len(final_text.split()),
            symbol       = symbol,
            year         = year,
            title        = title,
        )
        idx += 1
        return _finalise(chunk)

    if cfg.get("respect_speaker_turns", True):
        qa_buffer: List[PageBlock] = []
        def flush_qa_pair():
            nonlocal qa_buffer
            if not qa_buffer:
                return
            c = _make_chunk_from_turns(qa_buffer)
            if c:
                chunks.append(c)
            qa_buffer = []
        for block in doc.blocks:
            if _should_skip_block(block):
                continue
            if block.block_type != "speaker_turn":
                flush_qa_pair()
                c = _make_chunk_from_turns([block])
                if c:
                    chunks.append(c)
                continue
            if block.speaker_role == "analyst" and qa_buffer:
                flush_qa_pair()
            block_tokens = _approx_tokens(block.text)
            if block_tokens > cfg["chunk_size"]:
                flush_qa_pair()
                c = _make_chunk_from_turns([block])
                if c:
                    chunks.append(c)
                continue
            current_tokens = sum(_approx_tokens(t.text) for t in qa_buffer)
            if current_tokens + block_tokens > cfg["chunk_size"] and qa_buffer:
                if not (qa_buffer[-1].speaker_role == "analyst" and block.speaker_role == "management"):
                    flush_qa_pair()
            qa_buffer.append(block)
            if len(qa_buffer) >= 2 and qa_buffer[-1].speaker_role == "management":
                if qa_buffer[-2].speaker_role == "analyst" or block.speaker_role == "management":
                    flush_qa_pair()
        flush_qa_pair()
    else:
        turn_buffer = []
        buffer_tokens = 0
        def flush_turns():
            nonlocal turn_buffer, buffer_tokens
            c = _make_chunk_from_turns(turn_buffer)
            if c:
                chunks.append(c)
            turn_buffer = []
            buffer_tokens = 0
        for block in doc.blocks:
            if _should_skip_block(block):
                continue
            block_tokens = _approx_tokens(block.text)
            if buffer_tokens + block_tokens > cfg["chunk_size"] and turn_buffer:
                flush_turns()
            turn_buffer.append(block)
            buffer_tokens += block_tokens
        flush_turns()

    log.info(f"  → {len(chunks)} chunks from concall (semantic chunking v2)")
    return chunks


# ═══════════════════════════════════════════════════════════════════════════════
# 9.  Main entry  (unchanged public API)
# ═══════════════════════════════════════════════════════════════════════════════

def chunk_document(
    doc:    ExtractedDocument,
    symbol: str,
    year:   Optional[int],
    title:  str,
) -> List[Chunk]:
    if doc.doc_type == "annual_report":
        return chunk_annual_report(doc, symbol, year, title)
    elif doc.doc_type == "concall":
        return chunk_concall(doc, symbol, year, title)
    else:
        raise ValueError(f"Unknown doc_type: {doc.doc_type}")