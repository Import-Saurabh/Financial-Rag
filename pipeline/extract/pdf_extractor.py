"""
pipeline/extract/pdf_extractor.py

Replaces pdfplumber with Docling for layout-aware extraction.

Docling gives us:
  - Automatic section header detection via layout analysis
  - True table extraction (TableFormer model) — no bbox-crop hacks needed
  - Cleaner prose blocks that never duplicate table text
  - Page provenance on every item

For concalls, we apply regex-based speaker-turn parsing on top of
Docling's text output, plus section detection (opening remarks, Q&A).

Phase-1 fixes:
  - Skip cover/disclaimer/participant boilerplate pages
  - Preserve document hierarchy and section headers
  - Improved speaker detection for Indian concall formats
  - Q&A section boundary detection
  - section_type metadata on every block

Dependencies:
    pip install docling
"""

import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional

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


# ─────────────────────────────────────────────
# CPU tuning for i5-1240P-class laptops (4 P-cores + 8 E-cores, 16 threads,
# no usable dedicated GPU — Iris Xe is not something Docling/PyTorch can
# offload matmuls to on this stack). The two things that actually move the
# needle without touching model quality:
#
#   1. Give Docling's own thread pool the real physical core count instead
#      of a hardcoded 8 (which under-uses the 1240P and, worse, can also
#      OVER-subscribe a smaller machine — it should track the host, not be
#      a magic number).
#   2. Pin OMP/MKL threads to the SAME number *before* torch/docling are
#      imported. Left unset, PyTorch's OpenMP pool and Docling's own
#      thread pool both try to claim all logical threads independently,
#      which causes CPU thread contention (each fighting the OS scheduler)
#      rather than any speedup — classic thread oversubscription. This is
#      very likely a meaningful chunk of why a 15MB annual report is
#      crawling: more threads were being *requested* than were being used
#      efficiently.
#
# Must run before `docling`/`torch` get imported anywhere in the process,
# so it lives at module import time, not inside _get_converter().
# ─────────────────────────────────────────────
def _optimal_thread_count() -> int:
    cpu_count = os.cpu_count() or 4
    # Leave 1-2 logical threads free for the OS / MinIO download / MySQL
    # driver / progress printing so the machine doesn't stutter under load.
    reserved = 2 if cpu_count >= 8 else 1
    return max(2, cpu_count - reserved)


_NUM_THREADS = _optimal_thread_count()

for _env_var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    # Respect an explicit override if the user already set one (e.g. in a
    # shared/production environment); only fill it in when unset.
    os.environ.setdefault(_env_var, str(_NUM_THREADS))


# ─────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────
@dataclass
class PageBlock:
    page_num:     int
    block_type:   str           # prose | table | section_header | speaker_turn
    text:         str
    section:      Optional[str] = None
    section_type: Optional[str] = None   # opening_remarks | qa | guidance | closing
    speaker:      Optional[str] = None
    speaker_role: Optional[str] = None
    table_data:   Optional[List[List]] = None


@dataclass
class ExtractedDocument:
    file_path:   str
    doc_type:    str
    total_pages: int
    blocks: List[PageBlock] = field(default_factory=list)


# ─────────────────────────────────────────────
# Docling converter (module-level singleton)
# ─────────────────────────────────────────────
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
    pipeline_options.do_ocr             = False   # text-layer PDFs only — OCR is the single
                                                   # biggest Docling cost and these financial
                                                   # PDFs are never scanned images.
    pipeline_options.do_table_structure = True    # keep: financial tables need real structure
    pipeline_options.table_structure_options.mode = TableFormerMode.FAST
    pipeline_options.accelerator_options = AcceleratorOptions(
        num_threads=_NUM_THREADS,   # was hardcoded to 8; now tracks the actual host
        device=AcceleratorDevice.CPU,
    )

    # Explicitly disable enrichment passes we never consume downstream.
    # These default to False in most Docling versions already, but pinning
    # them here means an upstream Docling upgrade can't silently turn one
    # on and add several extra model passes per page for free.
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


def _peek_page_count(pdf_path: Path) -> Optional[int]:
    """
    Cheap page-count peek via pypdfium2 (already a hard dependency through
    the Docling backend) — lets us log an expectation ("this is a 220-page
    PDF, it'll take a while") before the slow Docling convert() call starts,
    instead of the run looking hung for minutes.
    """
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            return len(doc)
        finally:
            doc.close()
    except Exception:
        return None


# ─────────────────────────────────────────────
# Live ETA progress bar around Docling's convert() call
#
# IMPORTANT — what this is and isn't: Docling's convert() is one blocking
# call with no per-page callback in this version, so there is no way to
# know its *actual* page-by-page position while it runs. What we do
# instead is track how many seconds/page THIS MACHINE has actually taken
# on past documents (separately for annual_report vs concall, since table
# density differs a lot) and use that learned rate + the page count we
# already peeked to render a live elapsed/ETA bar. It's an estimate, and
# the bar itself says so — treat the ETA as "roughly", not exact.
# ─────────────────────────────────────────────
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
        pass  # progress/ETA is a nicety, never worth failing ingestion over


def _estimated_sec_per_page(doc_type: str) -> float:
    state = _load_rate_state()
    return state.get(doc_type, {}).get("sec_per_page", _DEFAULT_SEC_PER_PAGE.get(doc_type, 5.0))


def _update_rate_state(doc_type: str, actual_sec_per_page: float) -> None:
    """Exponential moving average — recent runs matter more, but one weird
    outlier document doesn't wreck the estimate for everything after it."""
    state = _load_rate_state()
    prev = state.get(doc_type, {}).get("sec_per_page")
    new_rate = actual_sec_per_page if prev is None else (0.7 * prev + 0.3 * actual_sec_per_page)
    state[doc_type] = {"sec_per_page": round(new_rate, 3), "updated_at": time.time()}
    _save_rate_state(state)


def _convert_with_progress(converter, pdf_path: Path, doc_type: str, total_pages: Optional[int]):
    """
    Runs converter.convert() on a background thread while the main thread
    prints a live \\r-updating progress/ETA line. Returns the Docling
    ConversionResult (same object convert() would have returned directly).
    """
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
            frac = min(0.97, elapsed / expected_total)  # never claim 100% until it's actually done
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


# ─────────────────────────────────────────────
# Speaker detection (concalls)
# ─────────────────────────────────────────────
# Matches: "John Smith:", "John Smith -", "John Smith –", "Mr. John Smith:"
SPEAKER_PATTERN = re.compile(
    r"(?:^|\n)"
    r"("
    r"(?:Mr\.|Ms\.|Mrs\.|Dr\.|Prof\.)?\s*"          # optional honorific
    r"[A-Z][A-Za-z\s\.\-]{1,45}?"                    # name
    r"(?:\s*[\(\[]?(?:CEO|CFO|COO|CMD|MD|Moderator|Operator|Analyst)[\)\]]?)?"
    r")"
    r"\s*[:\-–—]\s*",
    re.MULTILINE,
)

# Inline speaker at start of line (common in BSE/NSE transcripts)
SPEAKER_LINE_PATTERN = re.compile(
    r"^("
    r"(?:Mr\.|Ms\.|Mrs\.|Dr\.)?\s*"
    r"[A-Z][A-Za-z\s\.\-]{2,50}"
    r")\s*[:\-–—]\s*(.+)$",
    re.MULTILINE,
)

MGMT_KEYWORDS = [
    "ceo", "cfo", "coo", "cmd", "managing director", "chief executive",
    "chief financial", "chairman", "director", "president", "vice president",
    "head of", "moderator", "operator", "coordinator", "executive",
    "founder", "promoter", "whole-time", "joint md",
]
ANALYST_KEYWORDS = [
    "analyst", "research", "securities", "capital", "bank", "asset",
    "fund", "investment", "equity", "management", "broking", "finance",
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


def _infer_section_type(text: str, current: Optional[str]) -> Optional[str]:
    """Update section_type based on header text or Q&A transition signals."""
    header_type = classify_section_header(text)
    if header_type:
        return header_type
    # Q&A often starts with analyst question patterns after opening remarks
    if current == "opening_remarks":
        if re.search(r"\b(?:first\s+question|take\s+(?:the\s+)?first\s+question|open\s+(?:the\s+)?(?:floor|line))\b", text, re.I):
            return "qa"
    return current


def _extract_speaker_turns(
    page_text: str,
    page_num: int,
    section: Optional[str] = None,
    section_type: Optional[str] = None,
) -> List[PageBlock]:
    """Parse speaker-labelled dialogue from a page of concall text."""
    blocks: List[PageBlock] = []

    # Try line-by-line speaker pattern first (more reliable for transcripts)
    line_matches = list(SPEAKER_LINE_PATTERN.finditer(page_text))
    if len(line_matches) >= 2:
        for i, m in enumerate(line_matches):
            speaker = m.group(1).strip()
            body_start = m.end()
            body_end = line_matches[i + 1].start() if i + 1 < len(line_matches) else len(page_text)
            body = page_text[body_start:body_end].strip()
            # Remove leading colon artifacts
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

    # Fallback: split-based parser
    segments = SPEAKER_PATTERN.split(page_text)
    i = 0
    while i < len(segments):
        seg = segments[i].strip()
        if not seg:
            i += 1
            continue
        if i + 1 < len(segments) and len(seg) < 70 and "\n" not in seg:
            speaker = seg.strip()
            body    = segments[i + 1].strip() if i + 1 < len(segments) else ""
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

    return blocks


# Annual report sections to deprioritize (still extracted as headers for context,
# but prose under these gets lower importance downstream)
LOW_VALUE_SECTIONS = re.compile(
    r"(?:corporate\s+information|company\s+information|"
    r"board\s+of\s+directors|directors?\s+report|notice\s+of\s+(?:annual\s+)?general\s+meeting|"
    r"corporate\s+governance\s+report|statutory\s+information|"
    r"shareholder\s+information|investor\s+information|"
    r"registered\s+office|contact\s+(?:us|details))",
    re.IGNORECASE,
)


def _is_low_value_section(section: str) -> bool:
    return bool(LOW_VALUE_SECTIONS.search(section or ""))


# ─────────────────────────────────────────────
# Docling item label constants
# ─────────────────────────────────────────────
def _get_labels():
    try:
        from docling_core.types.doc import DocItemLabel
        return DocItemLabel
    except ImportError:
        from docling.datamodel.document import DocItemLabel  # type: ignore
        return DocItemLabel


# ─────────────────────────────────────────────
# Annual report extractor
# ─────────────────────────────────────────────
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
                 f"(~{_preview_pages} pages — large annual reports can take several "
                 f"minutes on CPU-only layout/table models, this is expected)")
    else:
        log.info(f"  Extracting annual report with Docling: {pdf_path.name}")
    result = _convert_with_progress(converter, pdf_path, "annual_report", _preview_pages)
    dl_doc = result.document

    total_pages = getattr(dl_doc, "num_pages", None)
    if callable(total_pages):
        total_pages = total_pages()
    if total_pages is None or total_pages == 0:
        total_pages = _count_pages(dl_doc)
    doc_out.total_pages = total_pages

    current_section = "General"
    current_section_type = None
    skipped_pages = 0

    # Group items by page for boilerplate page filtering
    page_items: dict[int, list] = {}
    for item, _level in dl_doc.iterate_items():
        page_num = _page_of(item)
        page_items.setdefault(page_num, []).append((item, _level))

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
            continue

        for item, _level in page_items[page_num]:
            label    = getattr(item, "label", None)
            text     = (getattr(item, "text", "") or "").strip()
            if not text and label != L.TABLE:
                continue

            if label == L.SECTION_HEADER:
                current_section = text
                current_section_type = "low_value" if _is_low_value_section(text) else "content"
                doc_out.blocks.append(PageBlock(
                    page_num     = page_num,
                    block_type   = "section_header",
                    text         = text,
                    section      = text,
                    section_type = current_section_type,
                ))

            elif label == L.TABLE:
                table_data, table_text = _extract_table(item)
                if table_text.strip():
                    prefix = f"[Section: {current_section}] [Table]\n"
                    doc_out.blocks.append(PageBlock(
                        page_num     = page_num,
                        block_type   = "table",
                        text         = prefix + table_text,
                        section      = current_section,
                        section_type = current_section_type,
                        table_data   = table_data,
                    ))

            elif label in (L.TEXT, L.PARAGRAPH, L.LIST_ITEM, L.CAPTION, L.FOOTNOTE):
                # Skip prose under low-value sections on early pages
                if current_section_type == "low_value" and page_num <= 15:
                    continue
                doc_out.blocks.append(PageBlock(
                    page_num     = page_num,
                    block_type   = "prose",
                    text         = text,
                    section      = current_section,
                    section_type = current_section_type,
                ))

    if skipped_pages:
        log.info(f"  Skipped {skipped_pages} boilerplate page(s)")
    log.info(f"  → {len(doc_out.blocks)} blocks | {doc_out.total_pages} pages")
    return doc_out


# ─────────────────────────────────────────────
# Concall extractor
# ─────────────────────────────────────────────
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
    result = _convert_with_progress(converter, pdf_path, "concall", _preview_pages)
    dl_doc = result.document

    total_pages = getattr(dl_doc, "num_pages", None)
    if callable(total_pages):
        total_pages = total_pages()
    if total_pages is None or total_pages == 0:
        total_pages = _count_pages(dl_doc)
    doc_out.total_pages = total_pages

    page_texts: dict[int, list[str]] = {}
    page_headers: dict[int, list[str]] = {}

    for item, _level in dl_doc.iterate_items():
        label = getattr(item, "label", None)
        text  = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        page_num = _page_of(item)
        if label == L.SECTION_HEADER:
            page_headers.setdefault(page_num, []).append(text)
        elif label in (L.TEXT, L.PARAGRAPH, L.LIST_ITEM, L.SECTION_HEADER):
            page_texts.setdefault(page_num, []).append(text)

    current_section      = "Conference Call"
    current_section_type = "opening_remarks"
    skipped_pages        = 0
    content_started      = False

    for page_num in sorted(set(page_texts) | set(page_headers)):
        # Update section from headers on this page
        for hdr in page_headers.get(page_num, []):
            st = classify_section_header(hdr)
            if st:
                current_section_type = st
                current_section = hdr
            else:
                current_section = hdr

        page_text = "\n".join(page_texts.get(page_num, []))
        if not page_text.strip():
            continue

        # Skip boilerplate pages (cover, disclaimer, participants)
        if not content_started and is_boilerplate_page(page_text, page_num):
            skipped_pages += 1
            continue

        # Content starts when we see a speaker turn or substantive text
        if not content_started:
            if SPEAKER_LINE_PATTERN.search(page_text) or len(page_text.split()) > 80:
                content_started = True
            else:
                skipped_pages += 1
                continue

        # Detect Q&A transition within page text
        current_section_type = _infer_section_type(page_text, current_section_type)

        turns = _extract_speaker_turns(
            page_text, page_num,
            section=current_section,
            section_type=current_section_type,
        )

        # If no speaker turns found, emit as prose only if substantive
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
    log.info(f"  → {len(doc_out.blocks)} speaker blocks | {doc_out.total_pages} pages")
    return doc_out


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _page_of(item) -> int:
    prov = getattr(item, "prov", None)
    if prov:
        try:
            return prov[0].page_no
        except (IndexError, AttributeError):
            pass
    return 0


def _count_pages(dl_doc) -> int:
    pages = set()
    for item, _ in dl_doc.iterate_items():
        pages.add(_page_of(item))
    return max(pages) if pages else 0


def _extract_table(item) -> tuple[List[List], str]:
    table_data = []
    table_text = ""

    try:
        df = item.export_to_dataframe()
        table_data = [list(df.columns)] + df.values.tolist()
        rows = []
        for row in table_data:
            rows.append(" | ".join(str(c or "").strip() for c in row))
        table_text = "\n".join(rows)
    except Exception:
        try:
            table_text = item.export_to_markdown() or ""
        except Exception:
            table_text = getattr(item, "text", "") or ""

    return table_data, table_text


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
        return None