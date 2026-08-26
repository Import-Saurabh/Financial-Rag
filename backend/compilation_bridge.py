#!/usr/bin/env python3
"""
ingest.py  —  Production ETL orchestration CLI v2

MinIO PDFs (annual reports / concalls)
  -> OpenKB compile (PageIndex + Groq/Llama3)
  -> MySQL (Ingestion Logs & metadata)

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

if "OPENROUTER_API_KEY" in os.environ:
    os.environ.pop("OPENROUTER_API_KEY")

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
)

from utils.logger import get_logger

log = get_logger(__name__, LOG_DIR)

# Optional — only used for memory reporting; never a hard dependency.
try:
    import resource  # POSIX only
    _HAS_RESOURCE = True
except ImportError:
    _HAS_RESOURCE = False


# ─────────────────────────────────────────────
# Doc-type -> bucket mapping
# ─────────────────────────────────────────────
DOC_TYPE_BUCKETS = {
    "annual_report": "annual-reports",
    "concall":       "concall-transcripts",
}

_YEAR_RE = re.compile(r"^(\d{4})")
_VALID_SYMBOL_RE = re.compile(r"^[A-Z0-9&\-]{2,20}$")

# Matches litellm/Groq's "Request too large" TPM error, e.g.:
#   "Request too large for model `openai/gpt-oss-20b` ... on tokens per
#    minute (TPM): Limit 8000, Requested 19874, please reduce your message
#    size and try again."
# This is a STRUCTURAL failure (the single request exceeds the provider's
# per-minute budget on its own) — unlike a plain "Rate limit reached"
# frequency error, sleeping and retrying the identical request will never
# succeed. It must be handled by shrinking the request, not waiting it out.
_REQUEST_TOO_LARGE_RE = re.compile(
    r"Request too large.*?Limit[:\s]+(\d+).*?Requested[:\s]+(\d+)", re.IGNORECASE
)

# Matches a plain (non-oversized) frequency rate limit, e.g.:
#   "Rate limit reached for model ... Used 6931, Requested 1347.
#    Please try again in 2.085s."
# Unlike _REQUEST_TOO_LARGE_RE, this is a genuinely TRANSIENT limit — the
# request itself fits fine, the rolling per-minute window is just nearly
# exhausted. The provider tells us exactly how long to wait; openkb's
# internal retry ignores that and sleeps a flat 60s regardless, which is
# correct but wasteful. We intercept it to honor the actual suggested wait.
_RATE_LIMIT_WAIT_RE = re.compile(
    r"Rate limit reached.*?Please try again in ([\d.]+)(ms|s)\b", re.IGNORECASE
)


class ChunkTooLargeError(Exception):
    """Raised when a single openkb/PageIndex LLM call for a chunk exceeded
    the provider's per-minute token budget in one shot. Signals the caller
    to split the chunk further and retry the pieces — retrying the same
    chunk unmodified will fail identically every time."""

    def __init__(self, limit: int, requested: int):
        self.limit = limit
        self.requested = requested
        super().__init__(
            f"Single LLM call requested {requested} tokens, but provider TPM "
            f"limit is {limit} tokens — request must be split, not retried as-is."
        )

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
    bar = "#" * filled + "-" * (width - filled)
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
    pages_compiled:     int = 0
    lint_warnings:      int = 0
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
        print(f"  Pages compiled        : {self.pages_compiled}")
        print(f"  Lint warnings         : {self.lint_warnings}")
        print(f"  Failures              : {len(self.failures)}")
        print(f"  Warnings              : {len(self.warnings)}")
        if self.total_duration_sec is not None:
            print(f"  Total run time        : {self.total_duration_sec:.1f}s")

        if self.failures:
            print("\n  -- Failures --")
            for f in self.failures:
                print(f"    X {f['minio_key']}")
                print(f"      {f['error']}")
            if len(self.failures) > 20:
                print(f"    ... and {len(self.failures) - 20} more (see saved report)")

        if self.warnings:
            print("\n  -- Warnings --")
            for w in self.warnings[:20]:
                print(f"    ! {w}")
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
# Core ingestion function (one PDF) — v2 enhanced
# ─────────────────────────────────────────────
def ingest_pdf(
    pdf_info: dict,
    force:    bool = False,
    client:   Optional[Minio] = None,
    state:    Optional[Dict[str, Any]] = None,
    report:   Optional[RunReport] = None,
    dry_run:  bool = False,
    llm_model: Optional[str] = None,
    retry_buffer_sec: float = 3.0,
    chunk_cooldown_sec: float = 8.0,
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
            log.error(f"  X Validation failed: {msg}")
        else:
            log.warning(f"  ! Validation warning: {msg}")
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
        log.info(f"  >> Duplicate content of '{original_key}' (same ETag) — skipping")
        if report is not None:
            report.duplicates_skipped += 1
            report.documents_skipped += 1
        return "skipped_duplicate"

    # ── Step 0.6: incremental check ────────────────────────────────────────
    prior_etag = state.setdefault("etags", {}).get(minio_key)
    already_in_db = is_already_ingested(minio_key)
    if not force and already_in_db and prior_etag and etag and prior_etag == etag:
        log.info("  >> Already ingested and content unchanged (ETag match), skipping")
        if report is not None:
            report.documents_skipped += 1
        return "skipped_already_ingested"
    if already_in_db and prior_etag and etag and prior_etag != etag:
        log.info(f"  R Content changed since last ingestion (ETag {prior_etag[:8]}->{etag[:8]}) "
                  f"— re-ingesting")
    elif not force and already_in_db and not prior_etag:
        log.info("  >> Already ingested (per DB), skipping (use --force to re-ingest)")
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
        log.info(f"  -> {local_path} ({file_size_kb} KB) in {timing['download_sec']}s")

        # Step 1.5: sanity check + fingerprint
        sanity_err = _quick_pdf_sanity_check(local_path)
        if sanity_err:
            raise ValueError(f"PDF sanity check failed: {sanity_err}")
        if not etag or "-" in etag:
            etag = _file_md5(local_path)
            pdf_info["etag"] = etag

        # Step 2: OpenKB Compile
        log.info("[2/3] Compiling PDF directly into OpenKB wiki...")
        import subprocess
        from pypdf import PdfReader, PdfWriter
        t_step = time.time()
        
        # openkb add
        try:
            wiki_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "openkb_wiki")
            
            if llm_model:
                import yaml
                openkb_conf_path = os.path.join(wiki_dir, ".openkb", "config.yaml")
                if os.path.exists(openkb_conf_path):
                    with open(openkb_conf_path, "r") as f:
                        conf_lines = f.readlines()
                    with open(openkb_conf_path, "w") as f:
                        for line in conf_lines:
                            if line.startswith("model:"):
                                f.write(f"model: {llm_model}\n")
                            else:
                                f.write(line)
                                
                # Patch .env to set LLM_API_KEY to the correct provider's key
                env_path = os.path.join(wiki_dir, ".env")
                if os.path.exists(env_path):
                    with open(env_path, "r") as f:
                        env_content = f.read()
                    new_key = None
                    if "nvidia" in llm_model.lower():
                        m = re.search(r'NVIDIA_API_KEY=["\']?([^"\'\n]+)["\']?', env_content)
                        if m: new_key = m.group(1)
                    elif "gemini" in llm_model.lower():
                        m = re.search(r'GEMINI_API_KEY=["\']?([^"\'\n]+)["\']?', env_content)
                        if m: new_key = m.group(1)
                    elif "groq" in llm_model.lower():
                        m = re.search(r'GROQ_API_KEY=["\']?([^"\'\n]+)["\']?', env_content)
                        if m: new_key = m.group(1)
                    elif "deepseek" in llm_model.lower():
                        m = re.search(r'DEEPSEEK_API_KEY=["\']?([^"\'\n]+)["\']?', env_content)
                        if m: new_key = m.group(1)
                        
                    if new_key:
                        env_content = re.sub(r'export LLM_API_KEY=.*|LLM_API_KEY=.*', f'export LLM_API_KEY="{new_key}"', env_content)
                        with open(env_path, "w") as f:
                            f.write(env_content)
            
            reader = PdfReader(str(local_path))
            total_pages = len(reader.pages)
            
            def _warn_if_stale_openkb_running():
                """openkb writes a local sqlite DB (pageindex.db). If a prior run was
                killed (Ctrl+C, crash) without releasing its handle, a leftover
                openkb.exe can hold a Windows file lock that makes the *next* run's
                mutation-rollback fail with WinError 32. Surface that early instead
                of letting it show up as a mysterious hang."""
                if os.name != "nt":
                    return
                try:
                    out = subprocess.run(
                        ["tasklist", "/FI", "IMAGENAME eq openkb.exe", "/FO", "CSV"],
                        capture_output=True, text=True, timeout=10,
                    )
                    lines = [l for l in out.stdout.splitlines() if "openkb.exe" in l.lower()]
                    if lines:
                        log.warning(
                            f"  ! Found {len(lines)} existing openkb.exe process(es) still "
                            f"running before this call started. If the previous run crashed "
                            f"or was Ctrl+C'd, this can hold a lock on pageindex.db and cause "
                            f"'Mutation rollback failed: WinError 32' on this run. If this run "
                            f"fails with that error, close those processes first "
                            f"(taskkill /IM openkb.exe /F) and re-run."
                        )
                except Exception as e:
                    log.debug(f"  (stale-process check skipped: {e})")

            def _force_kill(proc: "subprocess.Popen") -> None:
                """Kill the process AND its child tree. proc.kill() alone can leave
                orphaned children on Windows when shell=True spawns via cmd.exe."""
                try:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                            capture_output=True, timeout=10,
                        )
                    else:
                        proc.kill()
                except Exception as kill_err:
                    log.warning(f"  ! Failed to force-kill hung process {proc.pid}: {kill_err}")

            # Lines openkb/PageIndex prints that are pure noise — one real LLM call
            # produces TWO of these (one via its logger, one via a manual print).
            # We don't drop them silently; we fold them into a running call count
            # instead, so you still know work is happening without the spam.
            _NOISY_LINE_RE = re.compile(
                r"LiteLLM.*DeprecationWarning|^LiteLLM WARNING:", re.IGNORECASE
            )
            # Signals an LLM call (or the openkb step around it) actually failed —
            # as opposed to the noisy-but-harmless deprecation warning above, which
            # fires on every request regardless of outcome. These patterns catch
            # tracebacks, provider errors (rate limits, timeouts, connection
            # errors), and openkb's own failure/retry language.
            _ERROR_LINE_RE = re.compile(
                r"\b(error|exception|traceback|rate.?limit|timed?.?out|aborted|"
                r"failed|retrying|refused|unauthorized|invalid.api.key)\b",
                re.IGNORECASE,
            )
            _SPINNER_FRAMES = "|/-\\"

            def run_openkb_with_retry(
                cmd, cwd, max_retries=20, hang_timeout_sec=7200, label="openkb add",
            ):
                """
                Streams the child process's stdout/stderr instead of blocking on it.
                - Repeated LiteLLM deprecation-warning lines are collapsed into a
                  running "N LLM call(s)" counter instead of being reprinted.
                - Every other line (stage markers like 'start find_toc_pages',
                  'toc found', genuine errors, etc.) is still logged, once, as-is.
                - A single live status line (spinner + elapsed time + last known
                  stage + call count) is kept updated in place via '\\r' so you get
                  continuous visual confirmation it's alive without the log
                  scrolling out of control.
                - hang_timeout_sec is a hard ceiling on one attempt's wall-clock
                  time; on timeout the process (and its child tree) are
                  force-killed and this counts as a failed attempt, subject to the
                  normal retry/backoff below. Set to None to disable.
                """
                import time
                import threading

                _warn_if_stale_openkb_running()

                base_delay = 10
                for attempt in range(max_retries):
                    state = {
                        "stage": "starting…",
                        "llm_warns_seen": 0,
                        "llm_calls": 0,
                        "llm_errors": 0,
                        "error_lines": [],   # keep the actual text for the end-of-attempt summary
                        "fatal_oversized": None,   # set to {"limit","requested"} on a
                                                    # structural "Request too large" hit
                        "fatal_wait_sec": None,    # set to the provider's own suggested
                                                    # wait (in seconds) on a plain, transient
                                                    # frequency rate limit
                        "done": False,
                    }
                    render_lock = threading.Lock()
                    t_start = time.time()

                    def _render(spin_idx: int = 0) -> None:
                        with render_lock:
                            elapsed = int(time.time() - t_start)
                            frame = _SPINNER_FRAMES[spin_idx % len(_SPINNER_FRAMES)]
                            err_part = (
                                f" | [!] {state['llm_errors']} issue(s)"
                                if state["llm_errors"] else ""
                            )
                            line = (
                                f"\r  {frame} [{label}] {state['stage'][:40]:<40} "
                                f"| {state['llm_calls']:>3} LLM call(s){err_part} "
                                f"| {elapsed:>4}s elapsed  "
                            )
                            sys.stdout.write(line)
                            sys.stdout.flush()

                    def _reader(proc: "subprocess.Popen") -> None:
                        for raw_line in proc.stdout:
                            line = raw_line.rstrip("\n").rstrip("\r")
                            if not line.strip():
                                continue

                            oversized = _REQUEST_TOO_LARGE_RE.search(line)
                            if oversized and state["fatal_oversized"] is None:
                                limit_tok, requested_tok = int(oversized.group(1)), int(oversized.group(2))
                                state["fatal_oversized"] = {"limit": limit_tok, "requested": requested_tok}
                                sys.stdout.write("\r" + " " * 100 + "\r")
                                log.error(
                                    f"  [!] [{label}] Provider rejected a single call as "
                                    f"structurally too large (requested {requested_tok} tok, "
                                    f"limit {limit_tok} tok) — this will never succeed by "
                                    f"waiting, killing the run early and splitting the chunk "
                                    f"instead of burning through internal retries."
                                )
                                _force_kill(proc)
                                # Don't fall through to normal noisy/error handling below —
                                # we've already logged and are tearing this attempt down.
                                continue

                            freq_wait = _RATE_LIMIT_WAIT_RE.search(line)
                            if (
                                freq_wait
                                and state["fatal_oversized"] is None
                                and state["fatal_wait_sec"] is None
                            ):
                                raw_val, unit = float(freq_wait.group(1)), freq_wait.group(2).lower()
                                wait_sec = raw_val / 1000.0 if unit == "ms" else raw_val
                                log.warning(
                                    f"  [!] [{label}] Transient rate limit hit (provider suggests {wait_sec:.1f}s). "
                                    f"Letting internal engine sleep and retry to preserve progress."
                                )
                                # DO NOT force_kill(proc). Let openkb handle its internal retry!
                                continue

                            if _NOISY_LINE_RE.search(line):
                                # each real LLM round-trip emits this warning twice.
                                # NOTE: this fires when a request is *sent*, not when
                                # it succeeds — it's an attempt counter, not a
                                # success counter. Actual pass/fail comes from the
                                # error-pattern check below.
                                state["llm_warns_seen"] += 1
                                state["llm_calls"] = state["llm_warns_seen"] // 2
                                continue
                            sys.stdout.write("\r" + " " * 100 + "\r")  # clear status line
                            if _ERROR_LINE_RE.search(line):
                                state["llm_errors"] += 1
                                state["error_lines"].append(line)
                                log.error(f"  [!] [{label}] {line}")
                            else:
                                log.info(f"  [{label}] {line}")
                            state["stage"] = line
                        state["done"] = True

                    def _ticker() -> None:
                        i = 0
                        while not state["done"]:
                            _render(i)
                            i += 1
                            time.sleep(0.25)

                    proc = None
                    try:
                        proc = subprocess.Popen(
                            cmd, shell=(os.name == "nt"), cwd=cwd,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1,
                        )
                        reader_thread = threading.Thread(
                            target=_reader, args=(proc,), daemon=True
                        )
                        ticker_thread = threading.Thread(target=_ticker, daemon=True)
                        reader_thread.start()
                        ticker_thread.start()

                        try:
                            returncode = proc.wait(timeout=hang_timeout_sec)
                        except subprocess.TimeoutExpired:
                            state["done"] = True
                            print()  # move off the status line
                            log.error(
                                f"  X {label} exceeded hang timeout of {hang_timeout_sec}s "
                                f"— force-killing process {proc.pid} (this usually means a "
                                f"stale openkb.exe from a previous crashed run is holding a "
                                f"lock on pageindex.db; see warning above)."
                            )
                            _force_kill(proc)
                            raise subprocess.CalledProcessError(
                                -1, cmd, output=f"hung for >{hang_timeout_sec}s, force-killed"
                            )

                        state["done"] = True
                        reader_thread.join(timeout=2)
                        print()  # move off the status line, one final time

                        if returncode != 0:
                            raise subprocess.CalledProcessError(returncode, cmd)

                        if state["llm_errors"]:
                            # openkb exited 0 (so it recovered / retried internally),
                            # but don't let that hide that something went wrong along
                            # the way — flag it loudly instead of only logging inline.
                            log.warning(
                                f"  ! {label} completed successfully (exit 0), but "
                                f"{state['llm_errors']} line(s) matched error/retry "
                                f"patterns during the run. Last one: "
                                f"{state['error_lines'][-1][:200]!r}. "
                                f"Review the [!] lines above if results look off — "
                                f"internal single-call retries are usually fine, but "
                                f"repeated identical errors are not."
                            )
                        return {
                            "proc": proc,
                            "llm_calls": state["llm_calls"],
                            "llm_errors": state["llm_errors"],
                        }

                    except subprocess.CalledProcessError as e:
                        if state["fatal_oversized"] is not None:
                            # Structural failure: this exact request will fail identically
                            # no matter how many times or how long we wait between
                            # attempts. Skip the remaining retry budget entirely and let
                            # the caller split the chunk instead.
                            raise ChunkTooLargeError(
                                state["fatal_oversized"]["limit"],
                                state["fatal_oversized"]["requested"],
                            )
                        if state["fatal_wait_sec"] is not None:
                            # Transient window-budget limit: the request itself is fine,
                            # we just killed the process early instead of letting it sleep
                            # a wasteful flat 60s. Honor the provider's own suggested wait,
                            # plus a safety buffer that GROWS on repeated collisions within
                            # this same chunk — if attempt 1's buffer wasn't enough headroom
                            # (e.g. concurrent usage elsewhere keeps refilling the TPM
                            # window), attempt 2 waits longer rather than colliding again
                            # at the same margin.
                            wait_sec = state["fatal_wait_sec"] + retry_buffer_sec * (attempt + 1)
                            if attempt < max_retries - 1:
                                log.info(
                                    f"  -> Waiting {wait_sec:.1f}s (provider-suggested "
                                    f"{state['fatal_wait_sec']:.1f}s + {retry_buffer_sec * (attempt + 1):.1f}s "
                                    f"buffer) before retrying same request... "
                                    f"(Attempt {attempt+1}/{max_retries})"
                                )
                                time.sleep(wait_sec)
                                continue
                            else:
                                raise ValueError(
                                    f"OpenKB compilation still hitting the provider's "
                                    f"per-minute rate limit after {attempt+1} attempts "
                                    f"(most recent suggested wait: {wait_sec:.1f}s). The "
                                    f"account's TPM budget may be persistently saturated — "
                                    f"try again shortly, or use a model/tier with more "
                                    f"headroom via --llm-model."
                                )
                        err_msg = str(e)
                        if attempt < max_retries - 1:
                            sleep_time = base_delay * (2 ** attempt)
                            log.warning(f"  -> Process error hit. Retrying in {sleep_time}s... (Attempt {attempt+1}/{max_retries})\nError: {err_msg[:200]}")
                            time.sleep(sleep_time)
                        else:
                            raise ValueError(f"OpenKB compilation failed after {attempt+1} attempts: {err_msg}")

                # Defense in depth: every exit from the loop above should have either
                # `return`ed a result or `raise`d. If we ever reach here it means a
                # future edit added a retry branch that forgot to do either (exactly
                # the bug that caused a silent None to propagate previously) — fail
                # loudly instead of letting a NoneType error surface three frames away.
                raise ValueError(
                    f"OpenKB compilation retry loop exhausted {max_retries} attempts "
                    f"without succeeding or raising a specific error — this indicates "
                    f"a bug in the retry logic itself."
                )
                            
            log.info(f"  -> Sending {local_path.name} directly to OpenKB...")
            result = run_openkb_with_retry(
                [r"C:\Users\hp\AppData\Roaming\Python\Python310\Scripts\openkb.exe", "add", str(local_path)],
                cwd=wiki_dir,
                label="openkb add [full]"
            )
            total_llm_calls = result["llm_calls"]
            total_llm_errors = result["llm_errors"]
            
            timing["openkb_add_sec"] = round(time.time() - t_step, 2)
            timing["llm_calls_total"] = total_llm_calls
            timing["llm_errors_total"] = total_llm_errors
            log.info(
                f"  -> openkb add completed in {timing['openkb_add_sec']}s "
                f"| {total_llm_calls} LLM call(s) total "
                f"({total_llm_errors} flagged issue(s))"
            )
            
            # openkb lint
            t_step = time.time()
            lint_res = subprocess.run([r"C:\Users\hp\AppData\Roaming\Python\Python310\Scripts\openkb.exe", "lint"], capture_output=True, text=True, shell=(os.name=="nt"), cwd=wiki_dir)
            timing["openkb_lint_sec"] = round(time.time() - t_step, 2)
            lint_warnings = lint_res.stdout.count("warning") + lint_res.stderr.count("warning")
            log.info(f"  -> openkb lint completed in {timing['openkb_lint_sec']}s with {lint_warnings} warnings")
            
        except Exception as e:
            if isinstance(e, ValueError) and "OpenKB compilation failed" in str(e):
                raise
            raise ValueError(f"OpenKB compilation failed: {e}")
            
        
        duration = time.time() - t0
        pages_compiled = 1 # Assuming 1 document compiled
        
        mark_document_ingested(doc_id, pages_compiled, pages_compiled)
        log_ingestion(
            symbol         = symbol,
            doc_type       = doc_type,
            minio_key      = minio_key,
            status         = "success",
            chunks_created = pages_compiled,
            duration_sec   = duration,
        )
        log.info(f"  OK Done in {duration:.1f}s | compiled successfully | "
                  f"peak RSS {_peak_rss_mb() or 'n/a'} MB")
        
        if report is not None:
            report.pages_compiled += pages_compiled
            report.lint_warnings += lint_warnings


        # Update sidecar state
        state["etags"][minio_key] = etag
        if etag:
            state["content_hash_to_key"][etag] = minio_key
        _save_state(state)

        if report is not None:
            report.documents_processed += 1
            report.pages_compiled += pages_compiled
            report.lint_warnings += lint_warnings
            report.per_doc_timing.append({
                "minio_key": minio_key, "duration_sec": round(duration, 2),
                **timing, "peak_rss_mb": _peak_rss_mb(),
                "fiscal_year": year, "company_name": None,
            })
        return "ingested"

    except Exception as e:
        duration = time.time() - t0
        log.exception(f"  X Failed: {e}")
        try:
            mark_document_failed(doc_id)
        except Exception:
            pass
        log_ingestion(
            symbol       = symbol,
            doc_type     = doc_type,
            minio_key    = minio_key,
            status       = "failed",
            message      = str(e)[:250],
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
        "chunks_created":   worker_report.pages_compiled,
        "vectors_uploaded": worker_report.lint_warnings,
        "warnings":     worker_report.warnings,
        "failures":     worker_report.failures,
    }


def _run_batch_parallel(
    pdfs: List[dict], force: bool, dry_run: bool,
    workers: int, report: RunReport, total: int,
) -> None:
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
                    "elapsed_sec": 0.0, "pages_compiled": 0, "lint_warnings": 0,
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

            report.pages_compiled   += result["pages_compiled"]
            report.lint_warnings += result["lint_warnings"]
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
    ap = argparse.ArgumentParser(description="Financial RAG — Ingestion Pipeline (MinIO -> Qdrant) v2")
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
    ap.add_argument("--llm-model", type=str, default=None,
                     help="Override the LLM model used by OpenKB (e.g. nvidia_nim/nvidia/nemotron-4-340b-instruct)")
    ap.add_argument("--retry-buffer-sec", type=float, default=3.0,
                     help="Extra buffer (seconds) added on top of the provider's own "
                          "suggested wait when a transient TPM rate limit is hit, scaled "
                          "up on repeated collisions within the same chunk. Default: 3.0")
    ap.add_argument("--chunk-cooldown-sec", type=float, default=8.0,
                     help="Pause (seconds) before starting each new chunk's compile, "
                          "when the previous chunk made real LLM calls — gives the "
                          "provider's rolling TPM window headroom instead of firing the "
                          "next chunk's first call immediately. Set to 0 to disable. "
                          "Default: 8.0")
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
        print("----------------------------------------------------\n")
        return

    client = _minio_client()

    if args.list:
        doc_type_filter = "annual_report" if args.type == "annual" else args.type
        pdfs = list_minio_pdfs(symbol=args.symbol, doc_type_filter=doc_type_filter, year=args.year, client=client)
        print(f"\n-- MinIO objects - buckets {list(DOC_TYPE_BUCKETS.values())} - {len(pdfs)} PDF(s) --")
        for p in pdfs:
            ingested = "OK" if is_already_ingested(p["minio_key"]) else "·"
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
                log.error(f"  X {e}")
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
    print(f"\n> Processing {total} document(s) in batches of {batch_size}"
          f"{f' with {workers} parallel workers' if use_parallel else ''}"
          f"{' [DRY RUN]' if args.dry_run else ''}\n")

    if use_parallel:
        _run_batch_parallel(pdfs, args.force, args.dry_run, workers, report, total, llm_model=args.llm_model)
    else:
        for batch_start in range(0, total, batch_size):
            batch = pdfs[batch_start:batch_start + batch_size]
            for idx_in_batch, pdf_info in enumerate(batch):
                global_idx = batch_start + idx_in_batch + 1
                doc_t0 = time.time()
                status = ingest_pdf(
                    pdf_info, force=args.force, client=client,
                    state=state, report=report, dry_run=args.dry_run, llm_model=args.llm_model,
                    retry_buffer_sec=args.retry_buffer_sec, chunk_cooldown_sec=args.chunk_cooldown_sec,
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