#!/usr/bin/env python3
"""
ingest.py  —  Production ETL orchestration CLI v2

MinIO PDFs (annual reports / concalls)
  → Docling extract (v2: +fiscal_year, +company_name, +heading_level, +table_type)
  → chunk (v2: semantic chunking, rich metadata, structured embedding text)
  → embed (v2: structured query/document symmetry)
  → Qdrant (v2: full metadata payload for intent-aware retrieval) + MySQL

PDFs live in MinIO across two doc-type-specific buckets:

  annual-reports/{symbol_lower}/{filename}.pdf
  concall-transcripts/{symbol_lower}/{filename}.pdf

The stored `minio_key` in MySQL is the full "{bucket}/{key}" path.

Usage:
    python ingest.py --symbol HAL
    python ingest.py --symbol HAL --type annual
    python ingest.py --symbol HAL --type concall
    python ingest.py --all
    python ingest.py --all --year 2020
    python ingest.py --all --batch-size 10
    python ingest.py --all --dry-run
    python ingest.py --file annual-reports/bel/2025_Financial_Year_2025_from_bse.pdf
    python ingest.py --stats
    python ingest.py --list
    python ingest.py --report
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
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
from pipeline.loader import chunk_document
from pipeline.loader.chunker import build_embedding_text
from pipeline.loader.embedder import embed_texts
from utils.logger import get_logger

log = get_logger(__name__, LOG_DIR)

# Optional — only used for memory reporting; never a hard dependency.
try:
    import resource  # POSIX only
    _HAS_RESOURCE = True
except ImportError:
    _HAS_RESOURCE = False


# ─────────────────────────────────────────────
# Qdrant client (module-level singleton)
# ─────────────────────────────────────────────
_qdrant_client = None


def _get_qdrant_client():
    global _qdrant_client
    if _qdrant_client is not None:
        return _qdrant_client
    try:
        from qdrant_client import QdrantClient
        from config.settings import QDRANT_HOST, QDRANT_PORT, QDRANT_API_KEY
        url = f"http://{QDRANT_HOST}:{QDRANT_PORT}"
        kwargs = {"url": url}
        if QDRANT_API_KEY:
            kwargs["api_key"] = QDRANT_API_KEY
        _qdrant_client = QdrantClient(**kwargs)
        log.info(f"Qdrant client connected → {url}")
    except Exception as e:
        log.warning(f"Could not initialise Qdrant client from config: {e}")
        _qdrant_client = None
    return _qdrant_client


# ─────────────────────────────────────────────
# Collection name — uses SAME names as old qdrant_loader.py
#   annual_report → "annual_reports"
#   concall       → "concalls"
# This ensures retriever_v2 (which calls old qdrant_loader.query_collection)
# reads from the SAME collections that ingest_v2 writes to.
# ─────────────────────────────────────────────
def _collection_name(doc_type: str) -> str:
    from pipeline.loader.qdrant_loader import get_collection_name
    return get_collection_name(doc_type)


def _ensure_collection(name: str) -> None:
    """Create collection if it doesn't exist (same logic as old qdrant_loader)."""
    from qdrant_client.models import VectorParams, Distance
    client = _get_qdrant_client()
    if client is None:
        return
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        from config.settings import EMBEDDING_DIM
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        log.info(f"  Created Qdrant collection '{name}' (dim={EMBEDDING_DIM}, cosine)")


# ─────────────────────────────────────────────
# Doc-type → bucket mapping
# ─────────────────────────────────────────────
DOC_TYPE_BUCKETS = {
    "annual_report": "annual-reports",
    "concall":       "concall-transcripts",
}

_YEAR_RE = re.compile(r"^(\d{4})")
_VALID_SYMBOL_RE = re.compile(r"^[A-Z0-9&\-]{2,20}$")

# ─────────────────────────────────────────────
# Sidecar state
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
# ─────────────────────────────────────────────
def _parse_minio_key(key: str, doc_type: str, bucket: str) -> Optional[dict]:
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
    severity:  str = "error"


def _validate_pdf_metadata(pdf_info: dict) -> List[ValidationIssue]:
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


def _resolve_single_object(path: str, client: Optional[Minio] = None) -> dict:
    if client is None:
        client = _minio_client()

    path = path.strip().lstrip("/")
    parts = path.split("/", 1)
    if len(parts) < 2:
        raise ValueError(
            f"'{path}' is not a valid object path — expected "
            f"'{{bucket}}/{{symbol}}/{{filename}}.pdf', e.g. "
            f"'annual-reports/bel/2025_Financial_Year_2025_from_bse.pdf'"
        )

    bucket, key = parts
    reverse_bucket_map = {v: k for k, v in DOC_TYPE_BUCKETS.items()}
    if bucket not in reverse_bucket_map:
        raise ValueError(
            f"Unknown bucket '{bucket}' in '{path}'. "
            f"Known buckets: {list(DOC_TYPE_BUCKETS.values())}"
        )
    doc_type = reverse_bucket_map[bucket]

    parsed = _parse_minio_key(key, doc_type, bucket)
    if parsed is None:
        raise ValueError(
            f"Could not parse '{key}' as a valid PDF key under bucket '{bucket}' "
            f"(expected '{{symbol}}/{{filename}}.pdf')"
        )

    try:
        stat = client.stat_object(bucket, key)
    except S3Error as e:
        raise ValueError(f"Object not found in MinIO: '{path}' ({e})")

    parsed["size_bytes"] = stat.size or 0
    parsed["etag"] = (stat.etag or "").strip('"')
    return parsed


# ─────────────────────────────────────────────
# PDF discovery from MinIO
# ─────────────────────────────────────────────
def list_minio_pdfs(
    symbol:          Optional[str] = None,
    doc_type_filter: Optional[str] = None,
    year:            Optional[int] = None,
    client:          Optional[Minio] = None,
) -> List[dict]:
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
            parsed["etag"] = (obj.etag or "").strip('"')
            pdfs.append(parsed)

    return pdfs


def _download_pdf(bucket: str, key: str, client: Minio) -> Path:
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
# Qdrant upsert helper (v2 — full metadata payload)
# ─────────────────────────────────────────────
def _upsert_chunks_to_qdrant(
    chunks: List[Any],
    doc_type: str,
    vectors: List[List[float]],
) -> str:
    """Upsert chunks with full v2 metadata payload to Qdrant."""
    collection = _collection_name(doc_type)
    _ensure_collection(collection)
    client = _get_qdrant_client()

    if client is None:
        raise RuntimeError("Qdrant client not available — cannot upsert vectors")

    from qdrant_client.models import PointStruct

    points = []
    for chunk, vector in zip(chunks, vectors):
        payload = {
            # Core identity
            "text": chunk.text,
            "chunk_type": chunk.chunk_type,
            "section": chunk.section,
            "section_type": chunk.section_type,
            "symbol": chunk.symbol,
            "year": chunk.year,
            "doc_type": chunk.doc_type,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "word_count": chunk.word_count,
            "importance_score": chunk.importance_score,
            "retrieval_tags": chunk.retrieval_tags,

            # v2 hierarchy
            "chapter": chunk.chapter,
            "subsection": chunk.subsection,
            "hierarchy_path": chunk.hierarchy_path,

            # v2 financial entities
            "financial_metrics": chunk.financial_metrics,
            "products_mentioned": chunk.products_mentioned,
            "business_segments": chunk.business_segments,
            "geography_mentioned": chunk.geography_mentioned,
            "entities_mentioned": chunk.entities_mentioned,
            "currencies_mentioned": chunk.currencies_mentioned,
            "fiscal_period": chunk.fiscal_period,
            "quarter": chunk.quarter,

            # v2 semantic flags
            "forward_looking": chunk.forward_looking,
            "historical": chunk.historical,
            "management_opinion": chunk.management_opinion,
            "quantitative_guidance": chunk.quantitative_guidance,
            "contains_guidance": chunk.contains_guidance,
            "contains_commitment": chunk.contains_commitment,
            "contains_strategic": chunk.contains_strategic,
            "contains_contract": chunk.contains_contract,
            "is_duplicate": chunk.is_duplicate,
            "is_low_information": chunk.is_low_information,

            # v2 table-specific
            "table_type": chunk.table_type,
            "table_summary": chunk.table_summary,

            # Speaker (concalls)
            "speaker": chunk.speaker,
            "speaker_role": chunk.speaker_role,
        }
        points.append(PointStruct(id=chunk.chunk_id, vector=vector, payload=payload))

    client.upsert(collection_name=collection, points=points, wait=True)
    log.info(f"  Upserted {len(points)} vectors to Qdrant collection '{collection}'")
    return collection


# ─────────────────────────────────────────────
# Core ingestion function (one PDF) — v2 enhanced
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

    # ── Step 0.5: duplicate content detection ──────────────────────────────
    content_hash_map = state.setdefault("content_hash_to_key", {})
    if not force and etag and etag in content_hash_map and content_hash_map[etag] != minio_key:
        original_key = content_hash_map[etag]
        log.info(f"  ⏭ Duplicate content of '{original_key}' (same ETag) — skipping")
        if report is not None:
            report.duplicates_skipped += 1
            report.documents_skipped += 1
        return "skipped_duplicate"

    # ── Step 0.6: incremental check ────────────────────────────────────────
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
        log.info("[1/5] Downloading from MinIO...")
        t_step = time.time()
        local_path = _download_pdf(bucket, key, client)
        timing["download_sec"] = round(time.time() - t_step, 2)
        log.info(f"  → {local_path} ({file_size_kb} KB) in {timing['download_sec']}s")

        # Step 1.5: sanity check + fingerprint
        sanity_err = _quick_pdf_sanity_check(local_path)
        if sanity_err:
            raise ValueError(f"PDF sanity check failed: {sanity_err}")
        if not etag or "-" in etag:
            etag = _file_md5(local_path)
            pdf_info["etag"] = etag

        # Step 2: Extract (Docling v2)
        log.info("[2/5] Extracting with Docling...")
        t_step = time.time()
        extracted = extract_pdf(local_path, doc_type)
        timing["extract_sec"] = round(time.time() - t_step, 2)
        if not extracted or not extracted.blocks:
            raise ValueError("Extraction returned no content")
        log.info(f"  → {len(extracted.blocks)} blocks | {extracted.total_pages} pages "
                  f"in {timing['extract_sec']}s")

        # v2: Use extracted fiscal_year / company_name when available
        extracted_year = getattr(extracted, "fiscal_year", None)
        extracted_company = getattr(extracted, "company_name", None)
        if extracted_year and not year:
            year = extracted_year
            log.info(f"  → Resolved fiscal year from document content: FY{year}")
        if extracted_company:
            log.info(f"  → Detected company name: {extracted_company}")

        # Step 3: Chunk (v2)
        log.info("[3/5] Chunking...")
        t_step = time.time()
        chunks = chunk_document(extracted, symbol, year, title)
        timing["chunk_sec"] = round(time.time() - t_step, 2)
        if not chunks:
            raise ValueError("Chunker returned no chunks")
        log.info(f"  → {len(chunks)} chunks in {timing['chunk_sec']}s")

        # Data-quality checks
        _check_chunk_quality(chunks, minio_key, report)

        # Step 4: Build structured embedding texts (v2)
        log.info("[4/5] Building structured embedding texts...")
        t_step = time.time()
        embedding_texts = [build_embedding_text(c) for c in chunks]
        timing["embed_build_sec"] = round(time.time() - t_step, 2)
        log.info(f"  → {len(embedding_texts)} structured texts in {timing['embed_build_sec']}s")

        # Step 5: Embed + upsert to Qdrant (v2)
        log.info("[5/5] Embedding + loading to Qdrant...")
        t_step = time.time()
        vectors = embed_texts(embedding_texts)
        timing["embed_sec"] = round(time.time() - t_step, 2)

        t_step = time.time()
        collection_name = _upsert_chunks_to_qdrant(chunks, doc_type, vectors)
        timing["upload_sec"] = round(time.time() - t_step, 2)

        # Record chunks in MySQL (v2: extended metadata)
        for chunk in chunks:
            chunk_meta = {
                "doc_id": doc_id,
                "qdrant_id": chunk.chunk_id,
                "collection": collection_name,
                "chunk_index": chunk.chunk_index,
                "chunk_type": chunk.chunk_type,
                "section": chunk.section,
                "speaker": chunk.speaker,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "word_count": chunk.word_count,
                # v2 fields (graceful fallback if DB schema not migrated)
                "section_type": chunk.section_type,
                "chapter": chunk.chapter,
                "subsection": chunk.subsection,
                "hierarchy_path": json.dumps(chunk.hierarchy_path) if chunk.hierarchy_path else None,
                "financial_metrics": json.dumps(chunk.financial_metrics) if chunk.financial_metrics else None,
                "products_mentioned": json.dumps(chunk.products_mentioned) if chunk.products_mentioned else None,
                "geography_mentioned": json.dumps(chunk.geography_mentioned) if chunk.geography_mentioned else None,
                "currencies_mentioned": json.dumps(chunk.currencies_mentioned) if chunk.currencies_mentioned else None,
                "forward_looking": chunk.forward_looking,
                "historical": chunk.historical,
                "quantitative_guidance": chunk.quantitative_guidance,
                "contains_commitment": chunk.contains_commitment,
                "contains_strategic": chunk.contains_strategic,
                "contains_contract": chunk.contains_contract,
                "is_duplicate": chunk.is_duplicate,
                "is_low_information": chunk.is_low_information,
                "table_type": chunk.table_type,
                "table_summary": chunk.table_summary,
                "importance_score": chunk.importance_score,
                "speaker_role": chunk.speaker_role,
            }
            try:
                insert_chunk(**chunk_meta)
            except TypeError as e:
                # DB schema hasn't been migrated for v2 fields — fall back to v1 insert
                log.debug(f"DB schema v1 fallback for insert_chunk: {e}")
                insert_chunk(
                    doc_id=doc_id,
                    qdrant_id=chunk.chunk_id,
                    collection=collection_name,
                    chunk_index=chunk.chunk_index,
                    chunk_type=chunk.chunk_type,
                    section=chunk.section,
                    speaker=chunk.speaker,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    word_count=chunk.word_count,
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
        log.info(f"  ✓ Done in {duration:.1f}s | {len(chunks)} chunks stored | "
                  f"peak RSS {_peak_rss_mb() or 'n/a'} MB")

        # Update sidecar state
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
                "fiscal_year": year, "company_name": extracted_company,
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
            f"{minio_key}: unusually small average chunk size ({avg_words:.0f} words)"
        )

    missing_section = sum(1 for c in chunks if not getattr(c, "section", None))
    if missing_section and missing_section / len(chunks) > 0.5:
        report.warnings.append(
            f"{minio_key}: {missing_section}/{len(chunks)} chunks missing section metadata"
        )

    # v2: Check canonical section coverage
    has_canonical = sum(1 for c in chunks if getattr(c, "section_type", None))
    if has_canonical < len(chunks) * 0.3:
        report.warnings.append(
            f"{minio_key}: only {has_canonical}/{len(chunks)} chunks have canonical section_type — "
            f"check extraction quality"
        )

    # v2: Check semantic flag density
    has_flags = sum(1 for c in chunks if getattr(c, "forward_looking", False)
                    or getattr(c, "quantitative_guidance", False)
                    or getattr(c, "contains_commitment", False))
    if len(chunks) > 10 and has_flags < 2:
        report.warnings.append(
            f"{minio_key}: very few semantic flags detected ({has_flags}/{len(chunks)}) — "
            f"document may be mostly boilerplate"
        )

    # v2: Check duplicate rate
    dupes = sum(1 for c in chunks if getattr(c, "is_duplicate", False))
    if dupes > len(chunks) * 0.2:
        report.warnings.append(
            f"{minio_key}: high duplicate rate ({dupes}/{len(chunks)}) — "
            f"consider deduplication tuning"
        )

    # v2: Check low-info rate
    low_info = sum(1 for c in chunks if getattr(c, "is_low_information", False))
    if low_info > len(chunks) * 0.3:
        report.warnings.append(
            f"{minio_key}: high low-information rate ({low_info}/{len(chunks)})"
        )

    if len(chunks) < 3:
        report.warnings.append(
            f"{minio_key}: only {len(chunks)} chunk(s) produced — document may be too short"
        )


# ─────────────────────────────────────────────
# Parallel batch worker
# ─────────────────────────────────────────────
def _ingest_worker(pdf_info: dict, force: bool, dry_run: bool) -> Dict[str, Any]:
    """Runs in a separate process. Returns a plain dict (must be picklable)."""
    worker_client = _minio_client()
    worker_state: Dict[str, Any] = {"etags": {}, "content_hash_to_key": {}}
    worker_report = RunReport()

    t0 = time.time()
    status = ingest_pdf(
        pdf_info, force=force, client=worker_client,
        state=worker_state, report=worker_report, dry_run=dry_run,
    )
    return {
        "minio_key":    pdf_info["minio_key"],
        "status":       status,
        "elapsed_sec":  round(time.time() - t0, 2),
        "chunks_created":   worker_report.chunks_created,
        "vectors_uploaded": worker_report.vectors_uploaded,
        "warnings":     worker_report.warnings,
        "failures":     worker_report.failures,
    }


def _run_batch_parallel(
    pdfs: List[dict], force: bool, dry_run: bool,
    workers: int, report: RunReport, total: int,
) -> None:
    if workers > 3:
        log.warning(
            f"--workers {workers} requested — on a 16GB laptop this risks OOM "
            f"(each worker loads its own Docling + embedding models). Capping at 3."
        )
        workers = 3

    done = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_ingest_worker, p, force, dry_run): p for p in pdfs}
        for fut in as_completed(futures):
            pdf_info = futures[fut]
            try:
                result = fut.result()
            except Exception as e:
                result = {
                    "minio_key": pdf_info["minio_key"], "status": "failed",
                    "elapsed_sec": 0.0, "chunks_created": 0, "vectors_uploaded": 0,
                    "warnings": [], "failures": [{"minio_key": pdf_info["minio_key"],
                                                    "error": f"{type(e).__name__}: {e}"}],
                }

            done += 1
            if result["status"] == "ingested":
                report.documents_processed += 1
            elif result["status"] == "failed":
                pass
            else:
                report.documents_skipped += 1
                if result["status"] == "skipped_duplicate":
                    report.duplicates_skipped += 1
                elif result["status"] == "skipped_invalid":
                    report.validation_failed += 1

            report.chunks_created   += result["chunks_created"]
            report.vectors_uploaded += result["vectors_uploaded"]
            report.warnings.extend(result["warnings"])
            report.failures.extend(result["failures"])
            report.per_doc_timing.append({
                "minio_key": result["minio_key"], "duration_sec": result["elapsed_sec"],
            })

            bar = _progress_bar(done, total)
            print(f"  {bar}  {result['status']:<26} {result['minio_key']}  "
                  f"({result['elapsed_sec']:.1f}s)")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Financial RAG — Ingestion Pipeline (MinIO → Qdrant) v2")
    ap.add_argument("--symbol", "-s",  help="Company symbol (e.g. HAL)")
    ap.add_argument("--type", "-t", choices=["annual", "concall"], help="Filter by document type")
    ap.add_argument("--year", "-y", type=int, help="Filter by year (e.g. 2020)")
    ap.add_argument("--all",   action="store_true", help="Ingest all objects across both buckets")
    ap.add_argument(
        "--file", "-f", action="append", default=None, metavar="BUCKET/KEY",
        help="Ingest one exact object by full path, e.g. "
             "'annual-reports/bel/2025_Financial_Year_2025_from_bse.pdf'. "
             "Repeatable: --file a/x.pdf --file b/y.pdf",
    )
    ap.add_argument("--force", action="store_true", help="Re-ingest already ingested docs")
    ap.add_argument("--stats", action="store_true", help="Show database stats and exit")
    ap.add_argument("--list",  action="store_true", help="List available MinIO objects and exit")
    ap.add_argument("--report", action="store_true", help="Show the last run's validation report and exit")
    ap.add_argument("--dry-run", action="store_true",
                     help="Validate + detect duplicates/incremental work, ingest nothing")
    ap.add_argument("--batch-size", type=int, default=25,
                     help="Number of documents processed per batch (default: 25)")
    ap.add_argument("--workers", type=int, default=1,
                     help="Parallel worker processes for multi-document runs "
                          "(--all/--symbol only; --file always runs single-process). "
                          "2 is a sane ceiling on a 16GB laptop. Default: 1 (sequential).")
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

    if args.file:
        pdfs = []
        resolution_errors: List[str] = []
        for raw_path in args.file:
            try:
                pdfs.append(_resolve_single_object(raw_path, client=client))
            except ValueError as e:
                log.error(f"  ✗ {e}")
                resolution_errors.append(str(e))
        if not pdfs:
            log.error("None of the requested --file path(s) could be resolved. Aborting.")
            sys.exit(1)
        if resolution_errors:
            log.warning(
                f"{len(resolution_errors)} of {len(args.file)} requested file(s) could not "
                f"be resolved and will be skipped; proceeding with the remaining "
                f"{len(pdfs)}."
            )
    elif args.all:
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
    workers = max(1, args.workers)
    use_parallel = workers > 1 and total > 1
    print(f"\n▶ Processing {total} document(s) in batches of {batch_size}"
          f"{f' with {workers} parallel workers' if use_parallel else ''}"
          f"{' [DRY RUN]' if args.dry_run else ''}\n")

    if use_parallel:
        _run_batch_parallel(pdfs, args.force, args.dry_run, workers, report, total)
    else:
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

            _save_state(state)
            log.info(f"Batch {batch_start // batch_size + 1} complete "
                     f"({min(batch_start + batch_size, total)}/{total} documents)")

    report.finish(time.time() - run_t0)
    report.print_summary()
    saved_path = report.save()
    log.info(f"Full report saved to {saved_path}")


if __name__ == "__main__":
    main()