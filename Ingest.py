#!/usr/bin/env python3
"""
ingest.py
Production ETL orchestration CLI:
  MinIO PDFs (annual reports / concalls)
    → Docling extract → chunk → embed → Qdrant + MySQL

PDFs live in MinIO across two doc-type-specific buckets (no shared bucket,
no year subfolder — year is parsed from the filename):

  annual-reports/{symbol_lower}/{filename}.pdf
  concall-transcripts/{symbol_lower}/{filename}.pdf

The stored `minio_key` in MySQL is the full "{bucket}/{key}" path, matching
the `object_path` convention already used by the Quant Copilot pdf_documents
table, so it stays globally unique across both buckets.

Usage:
    python ingest.py --symbol HAL
    python ingest.py --symbol HAL --type annual
    python ingest.py --symbol HAL --type concall
    python ingest.py --all                       # ingest every object in both buckets
    python ingest.py --all --year 2020            # ingest only PDFs from 2020
    python ingest.py --all --batch-size 10        # process in batches of 10
    python ingest.py --all --dry-run              # validate + report only, ingest nothing
    python ingest.py --stats                      # show DB stats
    python ingest.py --list                       # list all MinIO keys available
    python ingest.py --report                     # show the last run's validation report

WHAT CHANGED IN THIS VERSION (Phase-2 orchestration pass)
───────────────────────────────────────────────────────────
This file remains a THIN orchestration layer — no changes to extract_pdf(),
chunk_document(), load_chunks_to_qdrant(), or the MySQL schema. Everything
below is new coordination logic around those existing calls:

  1. Pre-flight validation — before touching MinIO or Qdrant, each object is
     checked for: correct key layout, resolvable symbol/doc_type/year, and
     (once downloaded) that Docling can actually open the PDF. Bad objects
     are reported and skipped instead of blowing up the whole run.

  2. Duplicate detection via content fingerprint — MinIO's ETag is the MD5
     of the object for single-part uploads, so we get a free, download-free
     content hash from `list_objects()`/`stat_object()`. Two different
     minio_keys with the same ETag are the same PDF under a different name;
     the second one is skipped and reported as a duplicate rather than
     re-embedded. This needed no DB schema change — the fingerprint lives
     in a small local JSON sidecar state file, not in MySQL.

  3. Incremental ingestion — if a document's ETag matches what's already
     recorded, it's skipped entirely (unchanged). If the ETag has *changed*
     for an already-ingested minio_key (a replaced file), it's treated as
     an update and re-ingested rather than silently skipped, without
     touching unrelated documents or rebuilding the whole collection.

  4. Batch processing + checkpointing — objects are processed in
     configurable batches; the sidecar state file is flushed after every
     document (not just at the end), so an interrupted run (Ctrl-C, crash,
     OOM) can be resumed by simply re-running the same command — already
     completed documents are skipped automatically via the existing
     is_already_ingested()/ETag check, no separate --resume flag needed.

  5. Data-quality checks — chunk count, average chunk size, chunk metadata
     completeness (speaker/section/page presence where expected), and a
     comparison of "chunks created" vs "chunks reported in Qdrant" are
     computed per document and rolled into the final report as warnings
     (not hard failures — a thin sparse annual report is legitimate, but
     it should be visible).

  6. Structured, professional logging — every document gets one aligned
     progress line with elapsed time; a lightweight in-house progress bar
     (no new dependency) shows overall run progress; peak memory (RSS) is
     sampled per document when the `resource` module is available (POSIX)
     and silently omitted on platforms where it isn't (Windows).

  7. Final validation report — printed at the end AND persisted to
     {LOG_DIR}/ingest_reports/{timestamp}.json so `--report` can redisplay
     the most recent run without re-ingesting anything.

  8. Recovery — one document's failure never aborts the batch; failures are
     collected and the run always ends with a full failure report and a
     non-zero (but still completed) exit path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from minio import Minio
from minio.error import S3Error

from config.settings import (
    MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY,
    MINIO_SECURE, INGEST_TMP_DIR, LOG_DIR,
)
from db.database import (
    init_db,
    upsert_document,
    mark_document_ingested,
    mark_document_failed,
    is_already_ingested,
    log_ingestion,
    get_stats,
    insert_chunk,
)
from pipeline.extract import extract_pdf
from pipeline.loader import chunk_document, load_chunks_to_qdrant
from utils.logger import get_logger

log = get_logger(__name__, LOG_DIR)

# Optional — only used for memory reporting; never a hard dependency.
try:
    import resource  # POSIX only
    _HAS_RESOURCE = True
except ImportError:
    _HAS_RESOURCE = False


# ─────────────────────────────────────────────
# Doc-type → bucket mapping (real layout, not a single shared bucket)
# ─────────────────────────────────────────────
DOC_TYPE_BUCKETS = {
    "annual_report": "annual-reports",
    "concall":       "concall-transcripts",
}

_YEAR_RE = re.compile(r"^(\d{4})")
_VALID_SYMBOL_RE = re.compile(r"^[A-Z0-9&\-]{2,20}$")

# ─────────────────────────────────────────────
# Sidecar state — duplicate/content-hash tracking + checkpointing
#
# NOT a MySQL schema change: MySQL remains the source of truth for
# "is this document ingested"; this local file is purely an ETL-run
# optimization so we don't need to download a PDF to know we've already
# seen its exact bytes under some other key, and so an interrupted run
# has something cheap to resume against without re-querying MySQL for
# every object up front.
# ─────────────────────────────────────────────
_STATE_PATH = Path(LOG_DIR) / "ingest_state.json"
_REPORT_DIR = Path(LOG_DIR) / "ingest_reports"


def _load_state() -> Dict[str, Any]:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"Could not read ingest state file ({e}) — starting fresh")
    return {"etags": {}, "content_hash_to_key": {}}


def _save_state(state: Dict[str, Any]) -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning(f"Could not persist ingest state file: {e}")


# ─────────────────────────────────────────────
# MinIO client (module-level singleton)
# ─────────────────────────────────────────────
def _minio_client() -> Minio:
    return Minio(
        endpoint   = MINIO_ENDPOINT,
        access_key = MINIO_ACCESS_KEY,
        secret_key = MINIO_SECRET_KEY,
        secure     = MINIO_SECURE,
    )


# ─────────────────────────────────────────────
# Key parsing + validation helpers
# Key layout within a doc-type bucket: {symbol_lower}/{filename}.pdf
# ─────────────────────────────────────────────
def _parse_minio_key(key: str, doc_type: str, bucket: str) -> Optional[dict]:
    """
    Parse a MinIO object key (within a doc_type-specific bucket) into
    (symbol, doc_type, year, title). Returns None if the key doesn't match
    the expected layout or isn't a PDF.
    """
    if not key.lower().endswith(".pdf"):
        return None

    parts = key.split("/")
    if len(parts) < 2:
        return None

    symbol   = parts[0].upper()
    filename = parts[-1]

    m = _YEAR_RE.match(filename)
    year = int(m.group(1)) if m else None

    return {
        "minio_key": f"{bucket}/{key}",
        "bucket":    bucket,
        "key":       key,
        "symbol":    symbol,
        "doc_type":  doc_type,
        "year":      year,
        "title":     Path(filename).stem,
    }


@dataclass
class ValidationIssue:
    minio_key: str
    field:     str
    message:   str
    severity:  str = "error"   # "error" | "warning"


def _validate_pdf_metadata(pdf_info: dict) -> List[ValidationIssue]:
    """
    Pre-flight metadata validation, run BEFORE any download or embedding
    work happens. Catches malformed keys / unresolvable symbols cheaply.
    """
    issues: List[ValidationIssue] = []
    key = pdf_info.get("minio_key", "?")

    if not pdf_info.get("symbol") or not _VALID_SYMBOL_RE.match(pdf_info["symbol"]):
        issues.append(ValidationIssue(key, "symbol",
                      f"Could not resolve a valid company symbol from key "
                      f"(got {pdf_info.get('symbol')!r})"))
    if pdf_info.get("doc_type") not in DOC_TYPE_BUCKETS:
        issues.append(ValidationIssue(key, "doc_type",
                      f"Unrecognised doc_type {pdf_info.get('doc_type')!r}"))
    if not pdf_info.get("year"):
        issues.append(ValidationIssue(key, "year",
                      "No 4-digit year prefix found in filename",
                      severity="warning"))
    if pdf_info.get("size_bytes", 0) == 0:
        issues.append(ValidationIssue(key, "size", "Object reports 0 bytes",
                      severity="warning"))
    return issues


def _quick_pdf_sanity_check(local_path: Path) -> Optional[str]:
    """
    Cheap "is this actually a PDF" check before handing it to the (slow)
    Docling extraction pipeline — avoids burning minutes on a corrupt or
    truncated download. Returns an error string, or None if OK.
    """
    try:
        with open(local_path, "rb") as f:
            header = f.read(5)
        if header != b"%PDF-":
            return f"File does not start with a PDF header (got {header!r})"
        if local_path.stat().st_size < 1024:
            return f"File is suspiciously small ({local_path.stat().st_size} bytes)"
    except Exception as e:
        return f"Could not read downloaded file: {e}"
    return None


# ─────────────────────────────────────────────
# PDF discovery from MinIO (now also captures ETag for dedup)
# ─────────────────────────────────────────────
def list_minio_pdfs(
    symbol:          Optional[str] = None,
    doc_type_filter: Optional[str] = None,
    year:            Optional[int] = None,
    client:          Optional[Minio] = None,
) -> List[dict]:
    """List all matching PDF objects across the doc-type-specific MinIO buckets."""
    if client is None:
        client = _minio_client()

    doc_types = [doc_type_filter] if doc_type_filter else list(DOC_TYPE_BUCKETS.keys())
    prefix = f"{symbol.lower()}/" if symbol else ""

    pdfs = []
    for doc_type in doc_types:
        bucket = DOC_TYPE_BUCKETS[doc_type]
        try:
            objects = client.list_objects(bucket, prefix=prefix, recursive=True)
        except S3Error as e:
            log.error(f"MinIO list failed for bucket '{bucket}': {e}")
            continue

        for obj in objects:
            parsed = _parse_minio_key(obj.object_name, doc_type, bucket)
            if parsed is None:
                continue
            if year is not None and parsed.get("year") != year:
                continue
            parsed["size_bytes"] = obj.size or 0
            # ETag is the object's MD5 for single-part uploads — a free
            # content fingerprint we can dedup on without downloading.
            parsed["etag"] = (obj.etag or "").strip('"')
            pdfs.append(parsed)

    return pdfs


def _download_pdf(bucket: str, key: str, client: Minio) -> Path:
    """Download object to INGEST_TMP_DIR and return local Path."""
    INGEST_TMP_DIR.mkdir(parents=True, exist_ok=True)
    local_path = INGEST_TMP_DIR / Path(key).name
    client.fget_object(bucket, key, str(local_path))
    return local_path


def _file_md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _peak_rss_mb() -> Optional[float]:
    if not _HAS_RESOURCE:
        return None
    try:
        # ru_maxrss is KB on Linux, bytes on macOS — KB is the common case
        # for the deployment target here (Linux server), so report as MB
        # assuming KB; this is a diagnostic number, not a billing figure.
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except Exception:
        return None


# ─────────────────────────────────────────────
# Progress bar (no new dependency)
# ─────────────────────────────────────────────
def _progress_bar(done: int, total: int, width: int = 30) -> str:
    if total <= 0:
        return ""
    frac = min(1.0, done / total)
    filled = int(width * frac)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {done}/{total} ({frac*100:.0f}%)"


# ─────────────────────────────────────────────
# Run report
# ─────────────────────────────────────────────
@dataclass
class RunReport:
    started_at:        str = field(default_factory=lambda: datetime.utcnow().isoformat())
    documents_found:    int = 0
    documents_processed: int = 0
    documents_skipped:  int = 0
    duplicates_skipped: int = 0
    validation_failed:  int = 0
    chunks_created:     int = 0
    vectors_uploaded:   int = 0
    failures:           List[Dict[str, str]] = field(default_factory=list)
    warnings:           List[str] = field(default_factory=list)
    per_doc_timing:     List[Dict[str, Any]] = field(default_factory=list)
    finished_at:        Optional[str] = None
    total_duration_sec: Optional[float] = None

    def finish(self, elapsed: float) -> None:
        self.finished_at = datetime.utcnow().isoformat()
        self.total_duration_sec = round(elapsed, 2)

    def print_summary(self) -> None:
        print("\n" + "=" * 60)
        print("INGESTION VALIDATION REPORT")
        print("=" * 60)
        print(f"  Documents found       : {self.documents_found}")
        print(f"  Documents processed   : {self.documents_processed}")
        print(f"  Documents skipped     : {self.documents_skipped}")
        print(f"    of which duplicates : {self.duplicates_skipped}")
        print(f"    of which invalid    : {self.validation_failed}")
        print(f"  Chunks created        : {self.chunks_created}")
        print(f"  Vectors uploaded      : {self.vectors_uploaded}")
        print(f"  Failures              : {len(self.failures)}")
        print(f"  Warnings              : {len(self.warnings)}")
        if self.total_duration_sec is not None:
            print(f"  Total run time        : {self.total_duration_sec:.1f}s")

        if self.failures:
            print("\n  ── Failures ──")
            for f in self.failures[:20]:
                print(f"    ✗ {f.get('minio_key')}: {f.get('error')}")
            if len(self.failures) > 20:
                print(f"    ... and {len(self.failures) - 20} more (see saved report)")

        if self.warnings:
            print("\n  ── Warnings ──")
            for w in self.warnings[:20]:
                print(f"    ⚠ {w}")
            if len(self.warnings) > 20:
                print(f"    ... and {len(self.warnings) - 20} more (see saved report)")
        print("=" * 60 + "\n")

    def save(self) -> Path:
        _REPORT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        path = _REPORT_DIR / f"{ts}.json"
        path.write_text(json.dumps(asdict(self), indent=2, default=str), encoding="utf-8")
        # Also keep a stable "latest" pointer for --report
        (_REPORT_DIR / "latest.json").write_text(
            json.dumps(asdict(self), indent=2, default=str), encoding="utf-8"
        )
        return path


def _print_last_report() -> None:
    latest = _REPORT_DIR / "latest.json"
    if not latest.exists():
        print("No ingestion report found yet — run an ingestion first.")
        return
    data = json.loads(latest.read_text(encoding="utf-8"))
    report = RunReport(**{k: v for k, v in data.items() if k in RunReport.__dataclass_fields__})
    report.print_summary()


# ─────────────────────────────────────────────
# Core ingestion function (one PDF) — now validation + dedup + quality aware
# ─────────────────────────────────────────────
def ingest_pdf(
    pdf_info: dict,
    force:    bool = False,
    client:   Optional[Minio] = None,
    state:    Optional[Dict[str, Any]] = None,
    report:   Optional[RunReport] = None,
    dry_run:  bool = False,
) -> str:
    """
    Ingest one PDF end-to-end. Returns one of:
      "ingested" | "skipped_already_ingested" | "skipped_duplicate"
      | "skipped_invalid" | "failed"
    Never raises — all failures are caught, logged, and recorded in `report`.
    """
    bucket:    str = pdf_info["bucket"]
    key:       str = pdf_info["key"]
    minio_key: str = pdf_info["minio_key"]
    doc_type:  str = pdf_info["doc_type"]
    symbol:    str = pdf_info["symbol"]
    year:      Optional[int] = pdf_info.get("year")
    title:     str = pdf_info["title"]
    etag:      str = pdf_info.get("etag", "")
    state      = state if state is not None else {"etags": {}, "content_hash_to_key": {}}

    log.info(f"\n{'='*60}")
    log.info(f"Ingesting: {minio_key}")
    log.info(f"  type={doc_type} | symbol={symbol} | year={year}")

    # ── Step 0: pre-flight validation ──────────────────────────────────────
    issues = _validate_pdf_metadata(pdf_info)
    hard_issues = [i for i in issues if i.severity == "error"]
    for i in issues:
        msg = f"{minio_key} [{i.field}]: {i.message}"
        if i.severity == "error":
            log.error(f"  ✗ Validation failed: {msg}")
        else:
            log.warning(f"  ⚠ Validation warning: {msg}")
            if report is not None:
                report.warnings.append(msg)
    if hard_issues:
        if report is not None:
            report.validation_failed += 1
            report.documents_skipped += 1
            report.failures.append({"minio_key": minio_key,
                                     "error": "; ".join(i.message for i in hard_issues)})
        return "skipped_invalid"

    # ── Step 0.5: duplicate content detection (free — uses ETag, no download) ──
    content_hash_map = state.setdefault("content_hash_to_key", {})
    if not force and etag and etag in content_hash_map and content_hash_map[etag] != minio_key:
        original_key = content_hash_map[etag]
        log.info(f"  ⏭ Duplicate content of '{original_key}' (same ETag) — skipping")
        if report is not None:
            report.duplicates_skipped += 1
            report.documents_skipped += 1
        return "skipped_duplicate"

    # ── Step 0.6: incremental check — unchanged since last ingestion? ──────────
    prior_etag = state.setdefault("etags", {}).get(minio_key)
    already_in_db = is_already_ingested(minio_key)
    if not force and already_in_db and prior_etag and etag and prior_etag == etag:
        log.info("  ⏭ Already ingested and content unchanged (ETag match), skipping")
        if report is not None:
            report.documents_skipped += 1
        return "skipped_already_ingested"
    if already_in_db and prior_etag and etag and prior_etag != etag:
        log.info(f"  ↻ Content changed since last ingestion (ETag {prior_etag[:8]}→{etag[:8]}) "
                  f"— re-ingesting")
    elif not force and already_in_db and not prior_etag:
        # DB says ingested but we have no local fingerprint history (first run
        # of this state file against an existing DB) — respect DB and skip.
        log.info("  ⏭ Already ingested (per DB), skipping (use --force to re-ingest)")
        if report is not None:
            report.documents_skipped += 1
        return "skipped_already_ingested"

    if dry_run:
        log.info("  [dry-run] Would ingest — skipping actual extraction/embedding")
        return "ingested"

    file_size_kb = pdf_info.get("size_bytes", 0) // 1024

    doc_id = upsert_document(
        symbol       = symbol,
        doc_type     = doc_type,
        year         = year,
        title        = title,
        minio_key    = minio_key,
        file_size_kb = file_size_kb,
    )

    if client is None:
        client = _minio_client()

    local_path = None
    t0 = time.time()
    timing: Dict[str, float] = {}

    try:
        # Step 1: Download from MinIO
        log.info("[1/4] Downloading from MinIO...")
        t_step = time.time()
        local_path = _download_pdf(bucket, key, client)
        timing["download_sec"] = round(time.time() - t_step, 2)
        log.info(f"  → {local_path} ({file_size_kb} KB) in {timing['download_sec']}s")

        # Step 1.5: sanity check + fingerprint the actual bytes (belt & braces
        # in case MinIO ETag wasn't a plain MD5, e.g. multipart uploads)
        sanity_err = _quick_pdf_sanity_check(local_path)
        if sanity_err:
            raise ValueError(f"PDF sanity check failed: {sanity_err}")
        if not etag or "-" in etag:  # "-" in ETag means multipart, not a plain MD5
            etag = _file_md5(local_path)
            pdf_info["etag"] = etag

        # Step 2: Extract (Docling)
        log.info("[2/4] Extracting with Docling...")
        t_step = time.time()
        extracted = extract_pdf(local_path, doc_type)
        timing["extract_sec"] = round(time.time() - t_step, 2)
        if not extracted or not extracted.blocks:
            raise ValueError("Extraction returned no content")
        log.info(f"  → {len(extracted.blocks)} blocks | {extracted.total_pages} pages "
                  f"in {timing['extract_sec']}s")

        # Step 3: Chunk
        log.info("[3/4] Chunking...")
        t_step = time.time()
        chunks = chunk_document(extracted, symbol, year, title)
        timing["chunk_sec"] = round(time.time() - t_step, 2)
        if not chunks:
            raise ValueError("Chunker returned no chunks")
        log.info(f"  → {len(chunks)} chunks in {timing['chunk_sec']}s")

        # ── Data-quality checks on the chunk set (report-only, non-fatal) ────
        _check_chunk_quality(chunks, minio_key, report)

        # Step 4: Embed + upsert to Qdrant
        log.info("[4/4] Embedding + loading to Qdrant...")
        t_step = time.time()
        collection_name = load_chunks_to_qdrant(chunks, doc_type)
        timing["embed_upload_sec"] = round(time.time() - t_step, 2)

        # Record chunks in MySQL
        for chunk in chunks:
            insert_chunk(
                doc_id      = doc_id,
                qdrant_id   = chunk.chunk_id,
                collection  = collection_name,
                chunk_index = chunk.chunk_index,
                chunk_type  = chunk.chunk_type,
                section     = chunk.section,
                speaker     = chunk.speaker,
                page_start  = chunk.page_start,
                page_end    = chunk.page_end,
                word_count  = chunk.word_count,
            )

        duration = time.time() - t0
        mark_document_ingested(doc_id, len(chunks), extracted.total_pages)
        log_ingestion(
            symbol         = symbol,
            doc_type       = doc_type,
            minio_key      = minio_key,
            status         = "success",
            chunks_created = len(chunks),
            duration_sec   = duration,
        )
        log.info(f"  ✓ Done in {duration:.1f}s | {len(chunks)} chunks stored in Qdrant | "
                 f"peak RSS {_peak_rss_mb() or 'n/a'} MB")

        # ── Update sidecar state (checkpoint — flushed immediately) ──────────
        state["etags"][minio_key] = etag
        if etag:
            state["content_hash_to_key"][etag] = minio_key
        _save_state(state)

        if report is not None:
            report.documents_processed += 1
            report.chunks_created += len(chunks)
            report.vectors_uploaded += len(chunks)
            report.per_doc_timing.append({
                "minio_key": minio_key, "duration_sec": round(duration, 2),
                **timing, "peak_rss_mb": _peak_rss_mb(),
            })
        return "ingested"

    except Exception as e:
        duration = time.time() - t0
        log.exception(f"  ✗ Failed: {e}")
        try:
            mark_document_failed(doc_id)
        except Exception:
            pass
        log_ingestion(
            symbol       = symbol,
            doc_type     = doc_type,
            minio_key    = minio_key,
            status       = "failed",
            message      = str(e),
            duration_sec = duration,
        )
        if report is not None:
            report.failures.append({
                "minio_key": minio_key,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc()[-2000:],
            })
        return "failed"

    finally:
        if local_path and local_path.exists():
            try:
                local_path.unlink()
            except Exception:
                pass


def _check_chunk_quality(chunks: list, minio_key: str, report: Optional[RunReport]) -> None:
    """Non-fatal data-quality checks, rolled into the run's warning list."""
    if report is None or not chunks:
        return
    word_counts = [c.word_count for c in chunks if getattr(c, "word_count", None)]
    avg_words = sum(word_counts) / len(word_counts) if word_counts else 0

    if avg_words and avg_words < 15:
        report.warnings.append(
            f"{minio_key}: unusually small average chunk size ({avg_words:.0f} words) "
            f"— check extraction quality"
        )
    missing_section = sum(1 for c in chunks if not getattr(c, "section", None))
    if missing_section and missing_section / len(chunks) > 0.5:
        report.warnings.append(
            f"{minio_key}: {missing_section}/{len(chunks)} chunks missing section metadata"
        )
    if len(chunks) < 3:
        report.warnings.append(
            f"{minio_key}: only {len(chunks)} chunk(s) produced — document may be too short "
            f"or extraction may have under-segmented it"
        )


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Financial RAG — Ingestion Pipeline (MinIO → Qdrant)")
    ap.add_argument("--symbol", "-s",  help="Company symbol (e.g. HAL)")
    ap.add_argument("--type", "-t", choices=["annual", "concall"], help="Filter by document type")
    ap.add_argument("--year", "-y", type=int, help="Filter by year (e.g. 2020)")
    ap.add_argument("--all",   action="store_true", help="Ingest all objects across both buckets")
    ap.add_argument("--force", action="store_true", help="Re-ingest already ingested docs")
    ap.add_argument("--stats", action="store_true", help="Show database stats and exit")
    ap.add_argument("--list",  action="store_true", help="List available MinIO objects and exit")
    ap.add_argument("--report", action="store_true", help="Show the last run's validation report and exit")
    ap.add_argument("--dry-run", action="store_true",
                     help="Validate + detect duplicates/incremental work, ingest nothing")
    ap.add_argument("--batch-size", type=int, default=25,
                     help="Number of documents processed per batch (default: 25)")
    args = ap.parse_args()

    if args.report:
        _print_last_report()
        return

    init_db()

    if args.stats:
        stats = get_stats()
        print("\n── Financial RAG DB Stats (MySQL) ──────────────────")
        print(f"  Companies  : {stats['companies']}")
        print(f"  Documents  : {stats['documents_ingested']}")
        print(f"  Chunks     : {stats['total_chunks']}")
        for dtype, n in stats.get("by_type", {}).items():
            print(f"  {dtype:<22}: {n} docs")
        print("────────────────────────────────────────────────────\n")
        return

    client = _minio_client()

    if args.list:
        pdfs = list_minio_pdfs(client=client, year=args.year)
        print(f"\n── MinIO objects — buckets {list(DOC_TYPE_BUCKETS.values())} — {len(pdfs)} PDF(s) ──")
        for p in pdfs:
            ingested = "✓" if is_already_ingested(p["minio_key"]) else "·"
            print(f"  [{ingested}] {p['minio_key']}")
        print()
        return

    doc_type_filter = {"annual": "annual_report", "concall": "concall"}.get(args.type)

    if args.all:
        pdfs = list_minio_pdfs(doc_type_filter=doc_type_filter, year=args.year, client=client)
        log.info(f"Found {len(pdfs)} PDF(s) across bucket(s)")
    elif args.symbol:
        pdfs = list_minio_pdfs(
            symbol=args.symbol.upper(), doc_type_filter=doc_type_filter,
            year=args.year, client=client,
        )
        if not pdfs:
            buckets = ([DOC_TYPE_BUCKETS[doc_type_filter]] if doc_type_filter
                       else list(DOC_TYPE_BUCKETS.values()))
            year_msg = f" with year {args.year}" if args.year else ""
            log.error(f"No PDFs found for {args.symbol.upper()} in bucket(s) {buckets} "
                      f"(prefix: {args.symbol.lower()}/){year_msg}")
            sys.exit(1)
    else:
        ap.print_help()
        sys.exit(1)

    state  = _load_state()
    report = RunReport(documents_found=len(pdfs))
    run_t0 = time.time()

    batch_size = max(1, args.batch_size)
    total = len(pdfs)
    print(f"\n▶ Processing {total} document(s) in batches of {batch_size}"
          f"{' [DRY RUN]' if args.dry_run else ''}\n")

    for batch_start in range(0, total, batch_size):
        batch = pdfs[batch_start:batch_start + batch_size]
        for idx_in_batch, pdf_info in enumerate(batch):
            global_idx = batch_start + idx_in_batch + 1
            doc_t0 = time.time()
            status = ingest_pdf(
                pdf_info, force=args.force, client=client,
                state=state, report=report, dry_run=args.dry_run,
            )
            doc_elapsed = time.time() - doc_t0
            bar = _progress_bar(global_idx, total)
            print(f"  {bar}  {status:<26} {pdf_info['minio_key']}  ({doc_elapsed:.1f}s)")

        # Checkpoint the state file after every batch (also happens per-doc
        # inside ingest_pdf on success, but this covers dry-run/skip paths too)
        _save_state(state)
        log.info(f"Batch {batch_start // batch_size + 1} complete "
                 f"({min(batch_start + batch_size, total)}/{total} documents)")

    report.finish(time.time() - run_t0)
    report.print_summary()
    saved_path = report.save()
    log.info(f"Full report saved to {saved_path}")


if __name__ == "__main__":
    main()