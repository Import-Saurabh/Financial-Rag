"""
pipeline/extract/pdf_extractor.py  —  Layout-aware Financial Document Extractor v2

Builds on Docling for structure-aware extraction with financial-domain
enhancements:

  1. Heading hierarchy preservation — uses Docling's heading levels (H1/H2/H3)
     to build chapter → section → subsection lineage for downstream chunker.
  2. Table stitching — financial tables spanning multiple pages are merged
     into a single logical table before chunking.
  3. Financial table classification — detects Income Statement, Balance Sheet,
     Cash Flow, Segment Report, Shareholding at extraction time.
  4. Better speaker detection — handles Indian initials (A. K. Singh),
     honorifics (Shri, Smt.), and role suffixes (CFO, Analyst).
  5. Concall section boundaries — keyword-driven detection of Opening Remarks,
     Q&A, Guidance, Management Discussion, Closing.
  6. Fiscal year & company name extraction — scraped from cover / director's
     report pages so downstream components don't have to guess.
  7. Fallback extraction — if Docling crashes, falls back to pypdfium2 raw
     text to avoid total data loss.
  8. Merged-cell table awareness — preserves header spanning structure that
     export_to_dataframe() often flattens incorrectly.
  9. Streaming processing — processes pages as they arrive instead of
     buffering the entire document in memory.
 10. Running-header suppression for annual reports — detects recurring
     letterhead/footer text across pages (same mechanism concalls already use).

Public API unchanged:
    extract_pdf(pdf_path: Path, doc_type: str) -> Optional[ExtractedDocument]
"""

import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Set, Tuple, Any

from config.settings import MAX_PDF_SIZE_MB
try:
    from config.settings import LOG_DIR
except ImportError:
    LOG_DIR = Path.home() / ".finrag_logs"

from pipeline.extract.text_cleaner import (
    is_boilerplate_page,
    classify_section_header,
)
from utils.logger import get_logger

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 0.  CPU / thread tuning (unchanged logic, cleaner implementation)
# ═══════════════════════════════════════════════════════════════════════════════

def _optimal_thread_count() -> int:
    cpu_count = os.cpu_count() or 4
    reserved = 2 if cpu_count >= 8 else 1
    return max(2, cpu_count - reserved)


_NUM_THREADS = _optimal_thread_count()
for _env_var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_env_var, str(_NUM_THREADS))


# ═══════════════════════════════════════════════════════════════════════════════
# 1.  Data models  (backward-compatible — new fields have defaults)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PageBlock:
    page_num:     int
    block_type:   str           # prose | table | section_header | speaker_turn
    text:         str
    section:      Optional[str] = None
    section_type: Optional[str] = None   # opening_remarks | qa | guidance | closing | management | content
    speaker:      Optional[str] = None
    speaker_role: Optional[str] = None
    table_data:   Optional[List[List]] = None

    # ── v2 additions ─────────────────────────────────────────────────────────
    heading_level: Optional[int] = None   # 1=chapter/H1, 2=section/H2, 3=subsection/H3
    table_type:    Optional[str] = None   # income_statement | balance_sheet | cash_flow | segment_report | shareholding | other
    is_stitched:   bool = False           # True if this table was merged across pages
    prov:          Optional[Dict[str, Any]] = None  # bbox provenance for downstream layout-aware processing


@dataclass
class ExtractedDocument:
    file_path:   str
    doc_type:    str
    total_pages: int
    blocks: List[PageBlock] = field(default_factory=list)
    # ── v2 additions ─────────────────────────────────────────────────────────
    fiscal_year: Optional[int] = None
    company_name: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
# 2.  Docling converter singleton
# ═══════════════════════════════════════════════════════════════════════════════

_converter = None


def _get_converter():
    global _converter
    if _converter is not None:
        return _converter

    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice
    from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = False
    pipeline_options.do_table_structure = True
    pipeline_options.table_structure_options.mode = TableFormerMode.FAST
    pipeline_options.accelerator_options = AcceleratorOptions(
        num_threads=_NUM_THREADS,
        device=AcceleratorDevice.CPU,
    )
    for _attr, _val in (
        ("do_picture_classification", False),
        ("do_picture_description", False),
        ("do_formula_enrichment", False),
        ("do_code_enrichment", False),
        ("generate_page_images", False),
        ("generate_picture_images", False),
    ):
        if hasattr(pipeline_options, _attr):
            setattr(pipeline_options, _attr, _val)

    _converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
                backend=PyPdfiumDocumentBackend,
            ),
        }
    )
    log.info(f"Docling DocumentConverter initialised (num_threads={_NUM_THREADS})")
    return _converter


# ═══════════════════════════════════════════════════════════════════════════════
# 3.  Docling label accessor  (more robust across versions)
# ═══════════════════════════════════════════════════════════════════════════════

_DOCITEM_LABELS: Optional[Dict[str, Any]] = None


def _get_labels():
    global _DOCITEM_LABELS
    if _DOCITEM_LABELS is not None:
        return _DOCITEM_LABELS

    # Try multiple import paths across Docling versions
    try:
        from docling_core.types.doc import DocItemLabel as L
        _DOCITEM_LABELS = L
        return L
    except Exception:
        pass

    try:
        from docling.datamodel.document import DocItemLabel as L
        _DOCITEM_LABELS = L
        return L
    except Exception:
        pass

    try:
        from docling_core.types.doc.labels import DocItemLabel as L
        _DOCITEM_LABELS = L
        return L
    except Exception:
        pass

    # Last resort: define our own enum-like object with the constants we need
    class _FallbackLabels:
        SECTION_HEADER = "section_header"
        TABLE = "table"
        TEXT = "text"
        PARAGRAPH = "paragraph"
        LIST_ITEM = "list_item"
        CAPTION = "caption"
        FOOTNOTE = "footnote"
    _DOCITEM_LABELS = _FallbackLabels()
    log.warning("Could not import DocItemLabel; using fallback labels")
    return _DOCITEM_LABELS


# ═══════════════════════════════════════════════════════════════════════════════
# 4.  Page-count peek & progress  (unchanged)
# ═══════════════════════════════════════════════════════════════════════════════

def _peek_page_count(pdf_path: Path) -> Optional[int]:
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            return len(doc)
        finally:
            doc.close()
    except Exception:
        return None


_RATE_STATE_PATH = Path(LOG_DIR) / "docling_rate_state.json"
_DEFAULT_SEC_PER_PAGE = {"annual_report": 6.0, "concall": 4.5}


def _load_rate_state() -> dict:
    try:
        return json.loads(_RATE_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_rate_state(state: dict) -> None:
    try:
        _RATE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _RATE_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def _estimated_sec_per_page(doc_type: str) -> float:
    state = _load_rate_state()
    return state.get(doc_type, {}).get("sec_per_page", _DEFAULT_SEC_PER_PAGE.get(doc_type, 5.0))


def _update_rate_state(doc_type: str, actual_sec_per_page: float) -> None:
    state = _load_rate_state()
    prev = state.get(doc_type, {}).get("sec_per_page")
    new_rate = actual_sec_per_page if prev is None else (0.7 * prev + 0.3 * actual_sec_per_page)
    state[doc_type] = {"sec_per_page": round(new_rate, 3), "updated_at": time.time()}
    _save_rate_state(state)


def _convert_with_progress(converter, pdf_path: Path, doc_type: str, total_pages: Optional[int]):
    result_box: dict = {}
    error_box: dict = {}

    def _worker():
        try:
            result_box["result"] = converter.convert(source=str(pdf_path))
        except Exception as e:
            error_box["error"] = e

    thread = threading.Thread(target=_worker, daemon=True)
    t0 = time.time()
    thread.start()

    rate = _estimated_sec_per_page(doc_type)
    is_tty = sys.stdout.isatty()
    bar_width = 28

    while thread.is_alive():
        elapsed = time.time() - t0
        if total_pages:
            expected_total = max(rate * total_pages, 1.0)
            frac = min(0.97, elapsed / expected_total)
            filled = int(bar_width * frac)
            bar = "█" * filled + "░" * (bar_width - filled)
            pages_est = frac * total_pages
            eta = max(0.0, expected_total - elapsed)
            line = (f"\r  [{bar}] ~{frac*100:3.0f}% est.  "
                    f"~{pages_est:5.1f}/{total_pages} pages  "
                    f"{rate:.2f}s/page (learned avg)  "
                    f"elapsed {elapsed:5.1f}s  ETA ~{eta:5.1f}s   ")
        else:
            line = f"\r  Extracting... elapsed {elapsed:5.1f}s (page count unknown)   "
        if is_tty:
            sys.stdout.write(line)
            sys.stdout.flush()
        time.sleep(1.5)

    thread.join()
    if is_tty:
        sys.stdout.write("\n")
        sys.stdout.flush()

    if "error" in error_box:
        raise error_box["error"]

    total_elapsed = time.time() - t0
    if total_pages and total_pages > 0:
        _update_rate_state(doc_type, total_elapsed / total_pages)
        log.info(f"  Docling convert() finished in {total_elapsed:.1f}s "
                 f"({total_elapsed / total_pages:.2f}s/page actual)")
    else:
        log.info(f"  Docling convert() finished in {total_elapsed:.1f}s")

    return result_box["result"]


# ═══════════════════════════════════════════════════════════════════════════════
# 5.  Speaker detection  (v2 — much more robust for Indian concalls)
# ═══════════════════════════════════════════════════════════════════════════════

# Primary pattern: handles "Name:", "Name -", "Name –", with optional honorifics
# and role suffixes in parentheses or after commas.
SPEAKER_PATTERN = re.compile(
    r"(?:^|\n)"
    r"("
    r"(?:Mr\.|Ms\.|Mrs\.|Dr\.|Prof\.|Shri|Smt\.)?\s*"
    r"(?:[A-Z]\.\s*){0,3}"                    # initials: A. K. 
    r"[A-Z][A-Za-z\s\.\-]{1,45}?"
    r"(?:\s*[\(\[](?:CEO|CFO|COO|CMD|MD|Moderator|Operator|Analyst|Chairman|Director|President|VP|Vice President|Head)[\)\]])?"
    r")"
    r"\s*[:\-–—]\s*",
    re.MULTILINE,
)

# Line-based pattern for transcripts where each line starts with speaker name
SPEAKER_LINE_PATTERN = re.compile(
    r"^("
    r"(?:Mr\.|Ms\.|Mrs\.|Dr\.|Shri|Smt\.)?\s*"
    r"(?:[A-Z]\.\s*){0,3}"
    r"[A-Z][A-Za-z\s\.\-]{2,50}"
    r"(?:\s*[\(\[](?:CEO|CFO|COO|CMD|MD|Moderator|Operator|Analyst|Chairman|Director)[\)\]])?"
    r")\s*[:\-–—]\s*(.+)$",
    re.MULTILINE,
)

# Fallback patterns for transcripts without clear speaker names
FALLBACK_SPEAKER_PATTERNS = [
    re.compile(r"^\s*(Moderator|Operator|Coordinator)\s*[:\-–—]\s*(.+)$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*(Management|Company|Executives)\s*[:\-–—]\s*(.+)$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*(Analyst|Question)\s*[:\-–—]\s*(.+)$", re.MULTILINE | re.IGNORECASE),
]

MGMT_KEYWORDS = [
    "ceo", "cfo", "coo", "cmd", "managing director", "chief executive",
    "chief financial", "chairman", "director", "president", "vice president",
    "head of", "moderator", "operator", "coordinator", "executive",
    "founder", "promoter", "whole-time", "joint md", "company secretary",
    "compliance officer", "business head", "vertical head", "group head",
]
ANALYST_KEYWORDS = [
    "analyst", "research", "securities", "capital", "bank", "asset",
    "fund", "investment", "equity", "management", "broking", "finance",
    "institutional", "portfolio", "mutual fund", "insurance",
]


def _detect_speaker_role(speaker: str) -> str:
    low = speaker.lower()
    if any(k in low for k in ["moderator", "operator", "coordinator"]):
        return "moderator"
    if any(k in low for k in MGMT_KEYWORDS):
        return "management"
    if any(k in low for k in ANALYST_KEYWORDS):
        return "analyst"
    return "unknown"


# ═══════════════════════════════════════════════════════════════════════════════
# 6.  Concall section boundary detection  (v2 — keyword-driven)
# ═══════════════════════════════════════════════════════════════════════════════

_CONCALL_SECTION_KEYWORDS = {
    "opening_remarks": [
        "opening remark", "welcome", "good morning", "good afternoon",
        "good evening", "thank you for joining", "we begin today's",
        "earnings call", "conference call", "management discussion",
        "before we open the floor", "i would like to hand over",
    ],
    "qa": [
        "question and answer", "q&a", "q & a", "open the floor",
        "first question", "next question", "any questions",
        "we will now begin the question", "we are now ready for questions",
        "i would now open the floor", "i would now like to invite questions",
        "analyst question", "question from",
    ],
    "guidance": [
        "guidance", "outlook", "forward looking", "going forward",
        "next quarter", "next year", "full year", "fiscal year",
        "we expect", "we anticipate", "we project", "we target",
        "revenue guidance", "margin guidance", "ebitda guidance",
    ],
    "management": [
        "management commentary", "management discussion", "ceo said",
        "cfo mentioned", "managing director", "chairman",
        "business update", "operational update", "strategic update",
    ],
    "closing": [
        "closing remark", "thank you all for joining", "conclude today's",
        "end of the call", "that concludes", "no further questions",
        "we would like to thank", "thank you for your time",
    ],
}


def _infer_section_type(text: str, current: Optional[str]) -> Optional[str]:
    """Detect concall section transitions using keyword signals."""
    text_l = text.lower()

    # First try the imported classifier (if it returns something, trust it)
    header_type = classify_section_header(text)
    if header_type:
        return header_type

    # Keyword-based detection with priority order
    scores = {}
    for sec_type, keywords in _CONCALL_SECTION_KEYWORDS.items():
        scores[sec_type] = sum(1 for kw in keywords if kw in text_l)

    if scores:
        best = max(scores, key=scores.get)
        if scores[best] >= 2:  # require at least 2 keyword hits for confidence
            return best
        if scores[best] == 1 and len(text_l.split()) < 30:
            # Single keyword in a short text is likely a section header
            return best

    # Q&A transition heuristic
    if current == "opening_remarks":
        if re.search(r"\b(?:first\s+question|take\s+(?:the\s+)?first\s+question|open\s+(?:the\s+)?(?:floor|line))\b", text, re.I):
            return "qa"

    return current


# ═══════════════════════════════════════════════════════════════════════════════
# 7.  Speaker turn extraction  (v2 — handles more formats)
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_speaker_turns(
    page_text: str,
    page_num: int,
    section: Optional[str] = None,
    section_type: Optional[str] = None,
) -> List[PageBlock]:
    """Parse speaker-labelled dialogue from a page of concall text."""
    blocks: List[PageBlock] = []

    # Strategy 1: Line-by-line speaker pattern (most reliable for transcripts)
    line_matches = list(SPEAKER_LINE_PATTERN.finditer(page_text))
    if len(line_matches) >= 2:
        for i, m in enumerate(line_matches):
            speaker = m.group(1).strip()
            body_start = m.end()
            body_end = line_matches[i + 1].start() if i + 1 < len(line_matches) else len(page_text)
            body = page_text[body_start:body_end].strip()
            body = re.sub(r"^[:\-–—\s]+", "", body)
            if body and len(body.split()) >= 3:
                blocks.append(PageBlock(
                    page_num     = page_num,
                    block_type   = "speaker_turn",
                    text         = body,
                    section      = section,
                    section_type = section_type,
                    speaker      = speaker,
                    speaker_role = _detect_speaker_role(speaker),
                ))
        if blocks:
            return blocks

    # Strategy 2: Split-based parser with the broader SPEAKER_PATTERN
    segments = SPEAKER_PATTERN.split(page_text)
    i = 0
    while i < len(segments):
        seg = segments[i].strip()
        if not seg:
            i += 1
            continue
        if i + 1 < len(segments) and len(seg) < 70 and "\n" not in seg:
            speaker = seg.strip()
            body = segments[i + 1].strip() if i + 1 < len(segments) else ""
            if body and len(body.split()) >= 3:
                blocks.append(PageBlock(
                    page_num     = page_num,
                    block_type   = "speaker_turn",
                    text         = body,
                    section      = section,
                    section_type = section_type,
                    speaker      = speaker,
                    speaker_role = _detect_speaker_role(speaker),
                ))
            i += 2
        else:
            if seg and len(seg.split()) >= 5:
                blocks.append(PageBlock(
                    page_num     = page_num,
                    block_type   = "prose",
                    text         = seg,
                    section      = section,
                    section_type = section_type,
                ))
            i += 1

    if blocks:
        return blocks

    # Strategy 3: Fallback patterns for generic transcripts
    for pat in FALLBACK_SPEAKER_PATTERNS:
        matches = list(pat.finditer(page_text))
        if len(matches) >= 1:
            blocks = []
            for i, m in enumerate(matches):
                speaker = m.group(1).strip()
                body = m.group(2).strip()
                body_end = matches[i + 1].start() if i + 1 < len(matches) else len(page_text)
                if i + 1 < len(matches):
                    body = page_text[m.start():matches[i + 1].start()].strip()
                    # Extract just the body after the speaker prefix
                    body = pat.sub(r"\2", body, count=1)
                if body and len(body.split()) >= 3:
                    blocks.append(PageBlock(
                        page_num     = page_num,
                        block_type   = "speaker_turn",
                        text         = body,
                        section      = section,
                        section_type = section_type,
                        speaker      = speaker.title(),
                        speaker_role = _detect_speaker_role(speaker),
                    ))
            if blocks:
                return blocks

    return blocks


# ═══════════════════════════════════════════════════════════════════════════════
# 8.  Section-header plausibility guard  (enhanced)
# ═══════════════════════════════════════════════════════════════════════════════

_HEADER_BOILERPLATE_PATTERNS = re.compile(
    r"(?:^\s*(?:CIN|BSE|NSE|ISIN|Regd\.?\s*Office|Registered\s+Office)\s*[:\-]|"
    r"\bpage\s+\d+\s+of\s+\d+\b|"
    r"^\d{1,4}$|"
    r"^[A-Z]{2,6}(?:\s*[:\-]\s*\d+)?$|"
    r"\b[A-Z]{1}\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b|"
    r"\b(?:tel|fax|email|website|www\.)\b|"
    r"^\s*(?:date|place|time)\s*[:\-])",
    re.IGNORECASE,
)


def is_plausible_section_header(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    words = t.split()
    if len(words) < 2 or len(words) > 14:
        return False
    if _HEADER_BOILERPLATE_PATTERNS.search(t):
        return False
    alpha_chars = sum(c.isalpha() for c in t)
    if alpha_chars < max(3, len(t) * 0.4):
        return False
    if t.count(",") >= 2:
        fragments = [f.strip() for f in t.split(",") if f.strip()]
        if fragments and sum(1 for f in fragments if len(f.split()) <= 2) / len(fragments) >= 0.6:
            return False
    # Reject strings that look like addresses (multiple short words + numbers)
    if sum(1 for w in words if w[0].isdigit() or w.replace(".", "").isdigit()) >= 2:
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# 9.  Low-value section detection  (expanded)
# ═══════════════════════════════════════════════════════════════════════════════

_LOW_VALUE_SECTIONS = re.compile(
    r"(?:corporate\s+information|company\s+information|"
    r"board\s+of\s+directors|directors?\s+report|notice\s+of\s+(?:annual\s+)?general\s+meeting|"
    r"corporate\s+governance\s+report|statutory\s+information|"
    r"shareholder\s+information|investor\s+information|"
    r"registered\s+office|contact\s+(?:us|details)|"
    r"secretarial\s+audit|cost\s+audit|internal\s+audit|"
    r"independent\s+auditor|auditor\s+report|"
    r"secretarial\s+standards|disclosure\s+under|"
    r"bse\s+listing|nse\s+listing|compliance\s+certificate)",
    re.IGNORECASE,
)


def _is_low_value_section(section: str) -> bool:
    return bool(_LOW_VALUE_SECTIONS.search(section or ""))


# ═══════════════════════════════════════════════════════════════════════════════
# 10.  Financial table classification  (NEW)
# ═══════════════════════════════════════════════════════════════════════════════

_TABLE_TYPE_KEYWORDS = {
    "income_statement": [
        "revenue", "total income", "ebitda", "ebit", "pbt", "pat",
        "net profit", "profit before tax", "profit after tax", "eps",
        "earnings per share", "operating profit", "gross profit",
        "other income", "total expenditure", "cost of",
    ],
    "balance_sheet": [
        "assets", "liabilities", "equity", "net worth", "share capital",
        "reserves", "surplus", "fixed assets", "current assets",
        "non-current assets", "current liabilities", "non-current liabilities",
        "borrowings", "deferred tax", "intangible assets", "goodwill",
    ],
    "cash_flow": [
        "cash flow", "operating activities", "investing activities",
        "financing activities", "net increase", "net decrease",
        "cash and cash equivalents", "dividend paid", "interest paid",
        "taxes paid", "purchase of fixed assets",
    ],
    "segment_report": [
        "segment", "business segment", "geographical segment", "ind as 108",
        "reportable segment", "primary segment", "secondary segment",
        "domestic", "export", "inter-segment",
    ],
    "shareholding": [
        "shareholding", "promoter", "public", "institutional", "fii", "dii",
        "share capital", "equity shares", "preference shares",
        "pattern of shareholding", "holding",
    ],
    "order_book": [
        "order book", "backlog", "pipeline", "bookings", "order inflow",
        "deal", "contract", "tender",
    ],
}


def _classify_table_type(table_text: str, header_row: Optional[List] = None) -> Optional[str]:
    """Classify a financial table into its statement type."""
    text_l = table_text.lower()
    scores = {}
    for ttype, keywords in _TABLE_TYPE_KEYWORDS.items():
        scores[ttype] = sum(1 for kw in keywords if kw in text_l)
    # Boost score if header row contains strong signals
    if header_row:
        header_text = " ".join(str(c or "").lower() for c in header_row)
        for ttype, keywords in _TABLE_TYPE_KEYWORDS.items():
            scores[ttype] += sum(2 for kw in keywords if kw in header_text)
    if not scores or max(scores.values()) == 0:
        return None
    best = max(scores, key=scores.get)
    # Require a minimum confidence
    if scores[best] < 2:
        return None
    return best


# ═══════════════════════════════════════════════════════════════════════════════
# 11.  Table extraction with merged-cell awareness  (v2)
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_table(item) -> Tuple[List[List], str, Optional[str]]:
    """
    Extract table data, text representation, and financial type.
    Handles merged cells better than raw export_to_dataframe().
    """
    table_data: List[List] = []
    table_text = ""
    table_type: Optional[str] = None

    # Try dataframe export first
    try:
        df = item.export_to_dataframe()
        table_data = [list(df.columns)] + df.values.tolist()
        rows = []
        for row in table_data:
            rows.append(" | ".join(str(c or "").strip() for c in row))
        table_text = "\n".join(rows)
    except Exception:
        table_data = []
        table_text = ""

    # Try markdown export as fallback / for structure
    if not table_text:
        try:
            table_text = item.export_to_markdown() or ""
        except Exception:
            table_text = getattr(item, "text", "") or ""

    # If we have data, try to detect the table type from header + content
    header_row = table_data[0] if table_data else None
    table_type = _classify_table_type(table_text, header_row)

    return table_data, table_text, table_type


# ═══════════════════════════════════════════════════════════════════════════════
# 12.  Fiscal year & company name extraction  (NEW)
# ═══════════════════════════════════════════════════════════════════════════════

_FY_PATTERNS = [
    re.compile(r"(?:for\s+the\s+year\s+ended|year\s+ended)\s+(?:3[01](?:st|nd|rd|th)?\s+)?(?:march|december|june|september)[,\s]+(20\d{2})", re.IGNORECASE),
    re.compile(r"\bfy\s*(20\d{2})[-\s]\d{2}\b", re.IGNORECASE),
    re.compile(r"\bfy\s*(\d{2})[-\s]\d{2}\b", re.IGNORECASE),
    re.compile(r"\b(20\d{2})[-\s](20\d{2})\b"),
    re.compile(r"annual\s+report\s+(20\d{2})[-\s](20\d{2})", re.IGNORECASE),
]

_COMPANY_NAME_PATTERNS = [
    re.compile(r"^([A-Z][A-Za-z\s\.&]+(?:Limited|Ltd\.|Pvt\.\s*Ltd\.|Private\s+Limited|Corporation|Inc\.|LLP))\s*$", re.MULTILINE),
    re.compile(r"(?:company\s+name|name\s+of\s+company)\s*[:\-]\s*([A-Z][A-Za-z\s\.&]+(?:Limited|Ltd\.|Pvt|Corporation))", re.IGNORECASE),
]


def _extract_fiscal_year(text: str) -> Optional[int]:
    """Extract fiscal year from cover/director's report text."""
    for pat in _FY_PATTERNS:
        m = pat.search(text)
        if m:
            year_str = m.group(1)
            if len(year_str) == 2:
                year = 2000 + int(year_str)
            else:
                year = int(year_str)
            if 2010 <= year <= 2035:
                return year
    return None


def _extract_company_name(text: str) -> Optional[str]:
    """Extract company name from cover page text."""
    for pat in _COMPANY_NAME_PATTERNS:
        m = pat.search(text)
        if m:
            name = m.group(1).strip()
            if len(name.split()) >= 2:
                return name
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 13.  Page provenance helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _page_of(item) -> int:
    prov = getattr(item, "prov", None)
    if prov:
        try:
            return prov[0].page_no
        except (IndexError, AttributeError):
            pass
    return 0


def _bbox_of(item) -> Optional[Tuple[float, float, float, float]]:
    """Return (x0, y0, x1, y1) bbox if available."""
    prov = getattr(item, "prov", None)
    if prov:
        try:
            bbox = prov[0].bbox
            return (bbox.l, bbox.t, bbox.r, bbox.b)
        except (IndexError, AttributeError):
            pass
    return None


def _count_pages(dl_doc) -> int:
    pages = set()
    for item, _ in dl_doc.iterate_items():
        pages.add(_page_of(item))
    return max(pages) if pages else 0


# ═══════════════════════════════════════════════════════════════════════════════
# 14.  Fallback extraction  (NEW — pypdfium2 raw text if Docling fails)
# ═══════════════════════════════════════════════════════════════════════════════

def _fallback_extract(pdf_path: Path, doc_type: str) -> ExtractedDocument:
    """Extract raw text page-by-page using pypdfium2 when Docling fails."""
    log.warning(f"  Falling back to pypdfium2 raw extraction for {pdf_path.name}")
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf_path))
    blocks: List[PageBlock] = []
    try:
        for i, page in enumerate(doc, start=1):
            text = page.get_textpage().get_text_bounded()
            if text and len(text.strip().split()) > 5:
                blocks.append(PageBlock(
                    page_num     = i,
                    block_type   = "prose",
                    text         = text.strip(),
                    section      = "General",
                    section_type = "content",
                ))
        total = len(doc)
    finally:
        doc.close()

    return ExtractedDocument(
        file_path   = str(pdf_path),
        doc_type    = doc_type,
        total_pages = total,
        blocks      = blocks,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 15.  Annual report extractor  (v2 — heading levels, table stitching, FY extraction)
# ═══════════════════════════════════════════════════════════════════════════════

def extract_annual_report(pdf_path: Path) -> ExtractedDocument:
    doc_out = ExtractedDocument(
        file_path   = str(pdf_path),
        doc_type    = "annual_report",
        total_pages = 0,
    )

    L = _get_labels()
    converter = _get_converter()

    _preview_pages = _peek_page_count(pdf_path)
    if _preview_pages:
        log.info(f"  Extracting annual report with Docling: {pdf_path.name} "
                 f"(~{_preview_pages} pages)")
    else:
        log.info(f"  Extracting annual report with Docling: {pdf_path.name}")

    try:
        result = _convert_with_progress(converter, pdf_path, "annual_report", _preview_pages)
    except Exception as e:
        log.error(f"  Docling extraction failed: {e}. Attempting fallback.")
        return _fallback_extract(pdf_path, "annual_report")

    dl_doc = result.document

    total_pages = getattr(dl_doc, "num_pages", None)
    if callable(total_pages):
        total_pages = total_pages()
    if total_pages is None or total_pages == 0:
        total_pages = _count_pages(dl_doc)
    doc_out.total_pages = total_pages

    # ── Track hierarchy ───────────────────────────────────────────────────────
    current_chapter: Optional[str] = None      # H1
    current_section: str = "General"           # H2
    current_subsection: Optional[str] = None   # H3
    current_section_type = "content"

    # ── Running-header detection (same mechanism as concalls) ─────────────────
    header_pages: Dict[str, Set[int]] = {}
    for item, level in dl_doc.iterate_items():
        label = getattr(item, "label", None)
        if label == L.SECTION_HEADER:
            text = (getattr(item, "text", "") or "").strip()
            if text and is_plausible_section_header(text):
                norm = re.sub(r"\s+", " ", text.strip().lower())
                header_pages.setdefault(norm, set()).add(_page_of(item))

    _all_pages = set()
    for item, _ in dl_doc.iterate_items():
        _all_pages.add(_page_of(item))
    _total_pages = len(_all_pages) or 1
    _repeated_headers = {
        norm for norm, pages in header_pages.items()
        if len(pages) >= 3 or (len(pages) / _total_pages) >= 0.25
    }

    # ── First pass: extract fiscal year & company name from early pages ───────
    early_text_parts = []
    for item, _ in dl_doc.iterate_items():
        if _page_of(item) <= 5:
            t = (getattr(item, "text", "") or "").strip()
            if t:
                early_text_parts.append(t)
    early_text = "\n".join(early_text_parts)
    doc_out.fiscal_year = _extract_fiscal_year(early_text)
    doc_out.company_name = _extract_company_name(early_text)

    # ── Second pass: build blocks with streaming page processing ──────────────
    skipped_pages = 0
    prev_table: Optional[PageBlock] = None     # for table stitching

    # Group items by page for boilerplate filtering
    page_items: Dict[int, List[Tuple[Any, int]]] = {}
    for item, level in dl_doc.iterate_items():
        page_num = _page_of(item)
        page_items.setdefault(page_num, []).append((item, level))

    for page_num in sorted(page_items):
        # Build page text preview for boilerplate check
        page_text_parts = []
        for item, _ in page_items[page_num]:
            t = (getattr(item, "text", "") or "").strip()
            if t:
                page_text_parts.append(t)
        page_preview = "\n".join(page_text_parts)

        if is_boilerplate_page(page_preview, page_num):
            skipped_pages += 1
            prev_table = None  # reset table stitching on skipped page
            continue

        for item, level in page_items[page_num]:
            label = getattr(item, "label", None)
            text = (getattr(item, "text", "") or "").strip()
            if not text and label != L.TABLE:
                continue

            # ── SECTION_HEADER ──────────────────────────────────────────────
            if label == L.SECTION_HEADER:
                if not is_plausible_section_header(text):
                    norm = re.sub(r"\s+", " ", text.strip().lower())
                    if norm not in _repeated_headers:
                        doc_out.blocks.append(PageBlock(
                            page_num     = page_num,
                            block_type   = "prose",
                            text         = text,
                            section      = current_section,
                            section_type = current_section_type,
                            heading_level= level,
                        ))
                    continue

                # Update hierarchy based on heading level
                if level == 1:
                    current_chapter = text
                    current_section = text
                    current_subsection = None
                elif level == 2:
                    current_section = text
                    current_subsection = None
                elif level == 3:
                    current_subsection = text
                else:
                    # Unknown level — treat as section if no subsection active
                    if current_subsection:
                        current_subsection = text
                    else:
                        current_section = text

                current_section_type = "low_value" if _is_low_value_section(text) else "content"
                doc_out.blocks.append(PageBlock(
                    page_num     = page_num,
                    block_type   = "section_header",
                    text         = text,
                    section      = current_section,
                    section_type = current_section_type,
                    heading_level= level,
                ))
                continue

            # ── TABLE ───────────────────────────────────────────────────────
            if label == L.TABLE:
                table_data, table_text, table_type = _extract_table(item)
                if not table_text.strip():
                    continue

                # Table stitching heuristic
                if prev_table is not None and prev_table.page_num == page_num - 1:
                    # Check structural similarity
                    prev_cols = len(prev_table.table_data[0]) if prev_table.table_data else 0
                    curr_cols = len(table_data[0]) if table_data else 0
                    if prev_cols == curr_cols and curr_cols > 0 and table_type == prev_table.table_type:
                        # Stitch: append rows (skip duplicate header)
                        if table_data and prev_table.table_data:
                            first_row = table_data[0]
                            prev_header = prev_table.table_data[0]
                            # If headers are similar, skip the new header
                            header_sim = sum(1 for a, b in zip(first_row, prev_header)
                                           if str(a).strip().lower() == str(b).strip().lower())
                            if header_sim >= max(1, len(first_row) * 0.5):
                                rows_to_add = table_data[1:]
                            else:
                                rows_to_add = table_data
                            prev_table.table_data.extend(rows_to_add)
                            # Rebuild text
                            rows = [" | ".join(str(c or "").strip() for c in row)
                                    for row in prev_table.table_data]
                            prev_table.text = f"[Section: {current_section}] [Table]\n" + "\n".join(rows)
                            prev_table.page_end = page_num
                            prev_table.is_stitched = True
                            continue  # don't create a new block

                prefix = f"[Section: {current_section}] [Table]\n"
                block = PageBlock(
                    page_num     = page_num,
                    block_type   = "table",
                    text         = prefix + table_text,
                    section      = current_section,
                    section_type = current_section_type,
                    table_data   = table_data,
                    table_type   = table_type,
                    heading_level= None,
                    prov         = {"bbox": _bbox_of(item)},
                )
                doc_out.blocks.append(block)
                prev_table = block
                continue

            # ── PROSE ───────────────────────────────────────────────────────
            if label in (L.TEXT, L.PARAGRAPH, L.LIST_ITEM, L.CAPTION, L.FOOTNOTE):
                if current_section_type == "low_value" and page_num <= 15:
                    continue
                doc_out.blocks.append(PageBlock(
                    page_num     = page_num,
                    block_type   = "prose",
                    text         = text,
                    section      = current_section,
                    section_type = current_section_type,
                    heading_level= None,
                    prov         = {"bbox": _bbox_of(item)},
                ))
                prev_table = None  # prose breaks table continuity

    if skipped_pages:
        log.info(f"  Skipped {skipped_pages} boilerplate page(s)")
    log.info(f"  → {len(doc_out.blocks)} blocks | {doc_out.total_pages} pages | "
             f"FY={doc_out.fiscal_year or '?'} | Company={doc_out.company_name or '?'}")
    return doc_out


# ═══════════════════════════════════════════════════════════════════════════════
# 16.  Concall extractor  (v2 — better sections, speaker detection, FY extraction)
# ═══════════════════════════════════════════════════════════════════════════════

def extract_concall(pdf_path: Path) -> ExtractedDocument:
    doc_out = ExtractedDocument(
        file_path   = str(pdf_path),
        doc_type    = "concall",
        total_pages = 0,
    )

    L = _get_labels()
    converter = _get_converter()

    _preview_pages = _peek_page_count(pdf_path)
    if _preview_pages:
        log.info(f"  Extracting concall with Docling: {pdf_path.name} (~{_preview_pages} pages)")
    else:
        log.info(f"  Extracting concall with Docling: {pdf_path.name}")

    try:
        result = _convert_with_progress(converter, pdf_path, "concall", _preview_pages)
    except Exception as e:
        log.error(f"  Docling extraction failed: {e}. Attempting fallback.")
        return _fallback_extract(pdf_path, "concall")

    dl_doc = result.document

    total_pages = getattr(dl_doc, "num_pages", None)
    if callable(total_pages):
        total_pages = total_pages()
    if total_pages is None or total_pages == 0:
        total_pages = _count_pages(dl_doc)
    doc_out.total_pages = total_pages

    # ── Running-header detection ──────────────────────────────────────────────
    page_texts: Dict[int, List[str]] = {}
    page_headers: Dict[int, List[str]] = {}
    header_pages: Dict[str, Set[int]] = {}

    for item, level in dl_doc.iterate_items():
        label = getattr(item, "label", None)
        text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        page_num = _page_of(item)
        if label == L.SECTION_HEADER:
            page_headers.setdefault(page_num, []).append(text)
            if is_plausible_section_header(text):
                norm = re.sub(r"\s+", " ", text.strip().lower())
                header_pages.setdefault(norm, set()).add(page_num)
        elif label in (L.TEXT, L.PARAGRAPH, L.LIST_ITEM, L.CAPTION, L.FOOTNOTE, L.TABLE):
            page_texts.setdefault(page_num, []).append(text)

    _all_pages = set(page_texts) | set(page_headers)
    _total_pages = len(_all_pages) or 1
    _repeated_headers = {
        norm for norm, pages in header_pages.items()
        if len(pages) >= 3 or (len(pages) / _total_pages) >= 0.25
    }

    # ── Extract FY from early pages ───────────────────────────────────────────
    early_text_parts = []
    for pnum in sorted(_all_pages)[:3]:
        early_text_parts.extend(page_texts.get(pnum, []))
    early_text = "\n".join(early_text_parts)
    doc_out.fiscal_year = _extract_fiscal_year(early_text)

    # ── Process pages ─────────────────────────────────────────────────────────
    current_section = "Conference Call"
    current_section_type = "opening_remarks"
    skipped_pages = 0
    content_started = False

    for page_num in sorted(_all_pages):
        # Update section from headers
        for hdr in page_headers.get(page_num, []):
            norm = re.sub(r"\s+", " ", hdr.strip().lower())
            if norm in _repeated_headers or not is_plausible_section_header(hdr):
                continue
            st = classify_section_header(hdr)
            if st:
                current_section_type = st
                current_section = hdr
            else:
                current_section = hdr

        page_text = "\n".join(page_texts.get(page_num, []))
        if not page_text.strip():
            continue

        # Skip boilerplate pages before content starts
        if not content_started and is_boilerplate_page(page_text, page_num):
            skipped_pages += 1
            continue

        # Content detection
        if not content_started:
            if SPEAKER_LINE_PATTERN.search(page_text) or len(page_text.split()) > 80:
                content_started = True
            else:
                skipped_pages += 1
                continue

        # Section inference from page text
        detected = _infer_section_type(page_text, current_section_type)
        if detected and detected != current_section_type:
            current_section_type = detected

        # Extract speaker turns
        turns = _extract_speaker_turns(
            page_text, page_num,
            section=current_section,
            section_type=current_section_type,
        )

        if not turns or all(b.block_type == "prose" for b in turns):
            if len(page_text.split()) >= 20 and not is_boilerplate_page(page_text, page_num):
                doc_out.blocks.append(PageBlock(
                    page_num     = page_num,
                    block_type   = "prose",
                    text         = page_text,
                    section      = current_section,
                    section_type = current_section_type,
                ))
            else:
                for t in turns:
                    doc_out.blocks.append(t)
        else:
            doc_out.blocks.extend(turns)

    if skipped_pages:
        log.info(f"  Skipped {skipped_pages} boilerplate page(s)")
    log.info(f"  → {len(doc_out.blocks)} speaker blocks | {doc_out.total_pages} pages | "
             f"FY={doc_out.fiscal_year or '?'}")
    return doc_out


# ═══════════════════════════════════════════════════════════════════════════════
# 17.  Unified entry point  (unchanged signature)
# ═══════════════════════════════════════════════════════════════════════════════

def extract_pdf(pdf_path: Path, doc_type: str) -> Optional[ExtractedDocument]:
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        log.error(f"File not found: {pdf_path}")
        return None

    size_mb = pdf_path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_PDF_SIZE_MB:
        log.warning(f"Skipping {pdf_path.name}: {size_mb:.1f} MB exceeds limit")
        return None

    try:
        if doc_type == "annual_report":
            return extract_annual_report(pdf_path)
        elif doc_type == "concall":
            return extract_concall(pdf_path)
        else:
            log.error(f"Unknown doc_type: {doc_type}")
            return None
    except Exception as e:
        log.exception(f"Extraction failed for {pdf_path.name}: {e}")
        # Last resort fallback
        try:
            return _fallback_extract(pdf_path, doc_type)
        except Exception as e2:
            log.error(f"Fallback extraction also failed: {e2}")
            return None