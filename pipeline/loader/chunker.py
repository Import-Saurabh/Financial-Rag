"""
pipeline/loader/chunker.py

Chunking strategies:
  Annual reports → 512-token sliding window for prose, row-group for tables
  Concalls       → speaker-turn aware, section-aware, never split mid Q&A

Phase-1 fixes:
  - Skip boilerplate blocks at chunk time (defence in depth)
  - Section-aware concall chunking (opening_remarks, qa, guidance)
  - One primary speaker per chunk when respect_speaker_turns=True
  - Rich metadata: section_type, retrieval_tags, importance_score → Qdrant
"""

import re
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from config.settings import ANNUAL_REPORT, CONCALL, MIN_CHUNK_WORDS
from pipeline.extract.pdf_extractor import ExtractedDocument, PageBlock
from pipeline.extract.text_cleaner import clean_text, is_garbage_text, is_boilerplate_text
from utils.logger import get_logger

log = get_logger(__name__)


# ─────────────────────────────────────────────
# Output dataclass
# ─────────────────────────────────────────────
@dataclass
class Chunk:
    chunk_id:     str
    doc_type:     str
    text:         str
    chunk_index:  int
    chunk_type:   str            # prose | table | speaker_turn
    section:      Optional[str]
    section_type: Optional[str]  # opening_remarks | qa | guidance | closing | content
    speaker:      Optional[str]
    speaker_role: Optional[str]
    page_start:   int
    page_end:     int
    word_count:   int
    symbol:       str
    year:         Optional[int]
    title:        str
    retrieval_tags: List[str] = field(default_factory=list)
    importance_score: float   = 0.5


def _make_id() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────────────────────
# Embedding text builder
# ─────────────────────────────────────────────
def build_embedding_text(chunk: Chunk) -> str:
    tags = ", ".join(chunk.retrieval_tags) if chunk.retrieval_tags else "none"

    lines = [
        f"Company: {chunk.symbol}",
        f"Document Type: {chunk.doc_type}",
        f"Year: {chunk.year or 'N/A'}",
        f"Section: {chunk.section or 'General'}",
    ]
    if chunk.section_type:
        lines.append(f"Section Type: {chunk.section_type}")
    lines.append(f"Chunk Type: {chunk.chunk_type}")
    if chunk.speaker:
        role = f" [{chunk.speaker_role}]" if chunk.speaker_role else ""
        lines.append(f"Speaker: {chunk.speaker}{role}")
    lines.append(f"Retrieval Tags: {tags}")
    lines.append("")
    lines.append("Content:")
    lines.append(chunk.text)

    return "\n".join(lines)


# ─────────────────────────────────────────────
# Importance score heuristic
# ─────────────────────────────────────────────
_TYPE_SCORE = {
    "speaker_turn": 0.85,
    "prose":        0.5,
    "table":        0.4,
}

_SECTION_TYPE_BOOST = {
    "qa":              0.15,
    "opening_remarks": 0.12,
    "guidance":        0.18,
    "closing":         0.05,
    "content":         0.08,
    "low_value":      -0.25,
}

_OUTLOOK_SIGNALS = [
    "guidance", "revenue guidance", "earnings guidance",
    "ebitda guidance", "margin guidance", "full year guidance",
    "quarterly guidance", "outlook", "forecast", "projection",
    "estimate", "target", "expect", "expects", "expected",
    "anticipate", "anticipated", "anticipating",
    "going forward", "looking ahead", "future",
    "next quarter", "next year", "coming quarters",
    "medium term", "long term", "near term",
    "over the next", "in the coming months",
    "for the remainder of the year",
    "growth", "double digit growth", "strong growth",
    "sustainable growth", "accelerate", "acceleration",
    "growth trajectory", "growth drivers",
    "expansion", "scale", "scaling",
    "market expansion", "international expansion",
    "strong demand", "healthy demand",
    "robust demand", "demand environment",
    "customer demand", "improving demand",
    "visibility on demand", "order momentum",
    "order book", "backlog", "bookings",
    "order inflow", "pipeline", "deal pipeline",
    "sales pipeline", "conversion pipeline",
    "large deal wins", "deal wins",
    "qualified pipeline",
    "capacity expansion", "capacity addition",
    "new facility", "new plant",
    "commissioning", "brownfield expansion",
    "greenfield project", "utilization",
    "capacity utilization",
    "capex", "capital expenditure",
    "investment cycle", "investing in",
    "growth investments", "strategic investments",
    "margin expansion", "margin improvement",
    "operating leverage", "profitability improvement",
    "efficiency gains", "cost optimization",
    "higher utilization",
    "industry outlook", "market outlook",
    "sector outlook", "positive outlook",
    "favorable environment",
    "confident", "remain confident",
    "well positioned", "positioned for growth",
    "strong visibility", "healthy visibility",
    "positive momentum", "encouraged by",
    "bullish", "optimistic",
]

_RISK_SIGNALS = [
    "risk", "risks", "headwind", "headwinds",
    "challenge", "challenges", "concern",
    "concerns", "uncertain", "uncertainty",
    "weak demand", "soft demand",
    "slowdown", "demand slowdown",
    "market slowdown", "softness",
    "muted demand", "sluggish demand",
    "margin pressure", "pricing pressure",
    "cost pressure", "margin contraction",
    "profitability pressure",
    "higher costs", "input cost inflation",
    "inflation", "interest rates",
    "high interest rates", "macroeconomic",
    "economic uncertainty", "recession",
    "economic slowdown", "volatile environment",
    "currency volatility", "foreign exchange",
    "fx risk", "forex impact",
    "currency headwinds",
    "supply chain", "disruption",
    "logistics challenges", "bottleneck",
    "shortage", "inventory correction",
    "competitive pressure", "competition",
    "pricing competition", "market share loss",
    "intense competition",
    "regulatory risk", "regulatory changes",
    "compliance risk", "policy uncertainty",
    "government intervention",
    "budget cuts", "deal delays",
    "deal postponement", "project delays",
    "client caution", "customer concentration",
    "customer attrition",
    "attrition", "talent shortage",
    "hiring challenges", "wage inflation",
    "employee costs",
    "execution risk", "implementation risk",
    "project overruns", "operational challenges",
    "geopolitical risk", "trade tensions",
    "sanctions", "tariffs", "conflict",
    "political instability",
    "cautious", "remain cautious",
    "limited visibility", "difficult environment",
    "challenging environment", "not immune",
    "pressure on demand", "pressure on margins",
    "monitoring closely", "adverse impact",
]

_OPPORTUNITY_SIGNALS = [
    "opportunity", "opportunities",
    "addressable market", "market opportunity",
    "untapped market", "white space",
    "strong demand", "robust demand",
    "healthy pipeline", "record pipeline",
    "strong order book", "record backlog",
    "new customer wins", "customer additions",
    "cross sell", "upsell",
    "wallet share", "customer expansion",
    "large deals", "mega deal",
    "strategic deal", "multi year contract",
    "contract wins", "deal momentum",
    "artificial intelligence", "ai",
    "generative ai", "genai",
    "machine learning", "automation",
    "digital transformation", "cloud migration",
    "data modernization",
    "product launch", "new offering",
    "new platform", "innovation",
    "research and development",
    "new geography", "new markets",
    "market penetration", "expansion plans",
    "capacity addition",
    "strategic partnership",
    "alliance", "joint venture",
    "ecosystem partnership",
    "productivity gains",
    "cost savings opportunity",
    "operating leverage",
    "excited about", "encouraged by",
    "significant opportunity",
    "strong momentum",
    "well positioned",
    "competitive advantage",
    "market leadership",
]

# Financial performance signals — boost for EBITDA/margin/revenue queries
_PERFORMANCE_SIGNALS = [
    "ebitda", "operating profit", "ebit", "pat", "pbt",
    "net profit", "revenue", "margin", "growth rate",
    "yoy", "year on year", "quarter on quarter", "qoq",
    "bps", "basis points", "percent", "crore", "million",
]


def _score_chunk(chunk: Chunk) -> float:
    base = _TYPE_SCORE.get(chunk.chunk_type, 0.5)
    if chunk.section_type:
        base += _SECTION_TYPE_BOOST.get(chunk.section_type, 0.0)
    if chunk.speaker_role == "management":
        base = min(base + 0.1, 1.0)
    elif chunk.speaker_role == "moderator":
        base = max(base - 0.2, 0.1)

    text_l = chunk.text.lower()
    if any(s in text_l for s in _OUTLOOK_SIGNALS):
        base = min(base + 0.2, 1.0)
    if any(s in text_l for s in _RISK_SIGNALS):
        base = min(base + 0.1, 1.0)
    if any(s in text_l for s in _OPPORTUNITY_SIGNALS):
        base = min(base + 0.15, 1.0)
    if any(s in text_l for s in _PERFORMANCE_SIGNALS):
        base = min(base + 0.12, 1.0)

    # Penalize early pages with little substance (residual cover content)
    if chunk.doc_type == "concall" and chunk.page_start <= 2:
        base = max(base - 0.15, 0.1)

    return round(max(0.0, min(base, 1.0)), 2)


def _tag_chunk(chunk: Chunk) -> List[str]:
    text_l = chunk.text.lower()
    tags   = []

    if chunk.section_type:
        tags.append(chunk.section_type)

    if any(w in text_l for w in ["revenue", "income", "sales", "turnover"]):
        tags.append("revenue")
    if any(w in text_l for w in ["ebitda", "operating profit", "ebit"]):
        tags.append("ebitda")
    if any(w in text_l for w in ["margin", "profitability", "bps", "basis points"]):
        tags.append("margin")
    if any(s in text_l for s in _OUTLOOK_SIGNALS):
        tags.append("forward_looking")
    if any(s in text_l for s in _RISK_SIGNALS):
        tags.append("risk")
    if any(s in text_l for s in _OPPORTUNITY_SIGNALS):
        tags.append("opportunity")
    if any(w in text_l for w in ["capex", "capital expenditure", "investment"]):
        tags.append("capex")
    if any(w in text_l for w in ["order book", "backlog", "pipeline", "bookings"]):
        tags.append("orders")
    if any(w in text_l for w in ["debt", "borrowing", "leverage", "repay"]):
        tags.append("debt")
    if any(w in text_l for w in ["dividend", "buyback", "return to shareholder"]):
        tags.append("capital_return")
    if any(w in text_l for w in ["segment", "business unit", "vertical"]):
        tags.append("segments")

    if chunk.chunk_type == "speaker_turn" and chunk.speaker_role == "analyst":
        tags.append("analyst_question")
    if chunk.chunk_type == "speaker_turn" and chunk.speaker_role == "management":
        tags.append("management_commentary")

    return list(dict.fromkeys(tags))  # dedupe, preserve order


# ─────────────────────────────────────────────
# Token-based split helper
# ─────────────────────────────────────────────
def _approx_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3)


def _split_by_tokens(text: str, max_tokens: int, overlap_tokens: int) -> List[str]:
    words         = text.split()
    max_words     = int(max_tokens / 1.3)
    overlap_words = int(overlap_tokens / 1.3)

    if len(words) <= max_words:
        return [text]

    chunks = []
    start  = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += max_words - overlap_words
    return chunks


def _finalise(chunk: Chunk) -> Chunk:
    chunk.retrieval_tags   = _tag_chunk(chunk)
    chunk.importance_score = _score_chunk(chunk)
    return chunk


def _should_skip_block(block: PageBlock) -> bool:
    """Defence-in-depth: skip blocks that slipped through extraction filter."""
    if is_boilerplate_text(block.text):
        return True
    if block.section_type == "low_value" and block.block_type == "prose":
        return True
    return False


# ─────────────────────────────────────────────
# Annual Report Chunker
# ─────────────────────────────────────────────
def chunk_annual_report(
    doc:    ExtractedDocument,
    symbol: str,
    year:   Optional[int],
    title:  str,
) -> List[Chunk]:
    cfg    = ANNUAL_REPORT
    chunks: List[Chunk] = []
    idx    = 0

    current_section      = "General"
    current_section_type = "content"
    prose_buffer         = []
    buffer_pages         = []

    def flush_prose():
        nonlocal idx
        if not prose_buffer:
            return
        combined = " ".join(prose_buffer)
        cleaned  = clean_text(combined, aggressive=True)
        if is_garbage_text(cleaned, MIN_CHUNK_WORDS):
            prose_buffer.clear()
            buffer_pages.clear()
            return

        if cfg["inject_section_header"] and current_section:
            prefixed = f"[Section: {current_section}]\n{cleaned}"
        else:
            prefixed = cleaned

        splits = _split_by_tokens(prefixed, cfg["chunk_size"], cfg["chunk_overlap"])
        for split in splits:
            if is_garbage_text(split, MIN_CHUNK_WORDS):
                continue
            chunk = Chunk(
                chunk_id     = _make_id(),
                doc_type     = "annual_report",
                text         = split,
                chunk_index  = idx,
                chunk_type   = "prose",
                section      = current_section,
                section_type = current_section_type,
                speaker      = None,
                speaker_role = None,
                page_start   = buffer_pages[0] if buffer_pages else 0,
                page_end     = buffer_pages[-1] if buffer_pages else 0,
                word_count   = len(split.split()),
                symbol       = symbol,
                year         = year,
                title        = title,
            )
            chunks.append(_finalise(chunk))
            idx += 1

        prose_buffer.clear()
        buffer_pages.clear()

    for block in doc.blocks:
        if _should_skip_block(block):
            continue

        if block.block_type == "section_header":
            flush_prose()
            current_section      = block.text
            current_section_type = block.section_type or "content"
            continue

        if block.block_type == "table":
            flush_prose()
            rows       = block.table_data or []
            row_group  = cfg["table_row_group"]
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

                prefix = f"[Section: {current_section}] [Table]\n"
                chunk  = Chunk(
                    chunk_id     = _make_id(),
                    doc_type     = "annual_report",
                    text         = prefix + table_text,
                    chunk_index  = idx,
                    chunk_type   = "table",
                    section      = current_section,
                    section_type = current_section_type,
                    speaker      = None,
                    speaker_role = None,
                    page_start   = block.page_num,
                    page_end     = block.page_num,
                    word_count   = len(table_text.split()),
                    symbol       = symbol,
                    year         = year,
                    title        = title,
                )
                chunks.append(_finalise(chunk))
                idx += 1
            continue

        if block.block_type == "prose":
            prose_buffer.append(block.text)
            buffer_pages.append(block.page_num)
            if _approx_tokens(" ".join(prose_buffer)) > cfg["chunk_size"] * 2:
                flush_prose()

    flush_prose()
    log.info(f"  → {len(chunks)} chunks from annual report")
    return chunks


# ─────────────────────────────────────────────
# Concall Chunker — section + speaker aware
# ─────────────────────────────────────────────
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

        # Section prefix helps embedding model distinguish Q&A from opening remarks
        section_label = section_type.replace("_", " ").title()
        prefix = (
            f"[Concall: {symbol} FY{year or '?'}] "
            f"[Section: {section_label}] "
        )
        if primary.speaker:
            prefix += f"[Speaker: {primary.speaker}"
            if primary.speaker_role:
                prefix += f" ({primary.speaker_role})"
            prefix += "]\n"

        final_text = prefix + combined

        chunk = Chunk(
            chunk_id     = _make_id(),
            doc_type     = "concall",
            text         = final_text,
            chunk_index  = idx,
            chunk_type   = "speaker_turn" if primary.block_type == "speaker_turn" else "prose",
            section      = section,
            section_type = section_type,
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
        # One chunk per speaker turn (or small group of related turns)
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

            # Q&A pairing: group analyst question + management answer
            if block.speaker_role == "analyst" and qa_buffer:
                flush_qa_pair()

            block_tokens = _approx_tokens(block.text)

            # Flush if this turn alone exceeds chunk size
            if block_tokens > cfg["chunk_size"]:
                flush_qa_pair()
                c = _make_chunk_from_turns([block])
                if c:
                    chunks.append(c)
                continue

            # Flush if adding would exceed limit (unless Q&A pair in progress)
            current_tokens = sum(_approx_tokens(t.text) for t in qa_buffer)
            if current_tokens + block_tokens > cfg["chunk_size"] and qa_buffer:
                # Keep analyst+answer together when possible
                if not (qa_buffer[-1].speaker_role == "analyst" and block.speaker_role == "management"):
                    flush_qa_pair()

            qa_buffer.append(block)

            # After management answer, flush the Q&A pair
            if len(qa_buffer) >= 2 and qa_buffer[-1].speaker_role == "management":
                if qa_buffer[-2].speaker_role == "analyst" or block.speaker_role == "management":
                    flush_qa_pair()

        flush_qa_pair()

    else:
        # Legacy: merge turns up to chunk_size
        turn_buffer:   List[PageBlock] = []
        buffer_tokens: int             = 0

        def flush_turns():
            nonlocal turn_buffer, buffer_tokens
            c = _make_chunk_from_turns(turn_buffer)
            if c:
                chunks.append(c)
            turn_buffer   = []
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

    log.info(f"  → {len(chunks)} chunks from concall")
    return chunks


# ─────────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────────
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
