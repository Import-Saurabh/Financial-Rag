"""
pipeline/loader/embedder.py  —  Financial-RAG Embedding Engine v2

Singleton embedding model — loaded ONCE per process, never reloaded.
PID guard ensures subprocesses reload safely.

v2 additions:
  - build_query_embedding_text() — structures queries with financial context
    (company, metrics, temporal flags) to create embedding symmetry with
    chunker_v2's structured document embeddings.
  - embed_query_structured() — uses structured query text for better
    financial-domain retrieval.
  - batch embedding with metadata-aware text selection.
"""

import os
from typing import List, Optional, Dict, Any

from config.settings import EMBEDDING_MODEL, EMBEDDING_BATCH_SIZE
from utils.logger import get_logger

log = get_logger(__name__)

_model      = None
_loaded_pid = None


def _get_model():
    global _model, _loaded_pid
    current_pid = os.getpid()

    if _model is not None and _loaded_pid == current_pid:
        return _model

    log.info(f"Loading embedding model: {EMBEDDING_MODEL} (PID {current_pid})")
    from sentence_transformers import SentenceTransformer
    _model      = SentenceTransformer(EMBEDDING_MODEL)
    _loaded_pid = current_pid
    log.info("Embedding model ready")
    return _model


def embed_texts(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []

    model      = _get_model()
    all_embs   = []

    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i: i + EMBEDDING_BATCH_SIZE]
        embs  = model.encode(
            batch,
            batch_size          = EMBEDDING_BATCH_SIZE,
            show_progress_bar   = False,
            convert_to_numpy    = True,
            normalize_embeddings = True,
        )
        all_embs.extend(embs.tolist())

    return all_embs


def embed_query(query: str) -> List[float]:
    """Embed a single query string (legacy, unstructured)."""
    return embed_texts([query])[0]


def build_query_embedding_text(
    query: str,
    symbol: Optional[str] = None,
    metrics: Optional[List[str]] = None,
    section_types: Optional[List[str]] = None,
    is_forward_looking: bool = False,
    is_historical: bool = False,
    table_type: Optional[str] = None,
) -> str:
    """
    Build a structured query text that mirrors chunker_v2's structured
    embedding text. This creates embedding symmetry: the query and document
    embeddings live in the same structured semantic space.

    Example output for "What is BEL's revenue guidance for FY26?":
        Query: What is BEL's revenue guidance for FY26?
        Company: BEL
        Financial Topic: Revenue, Guidance
        Financial Metrics Mentioned: revenue
        Flags: Forward Looking
        Table Preference: income_statement
        Content: What is BEL's revenue guidance for FY26?
    """
    lines = [f"Query: {query}"]

    if symbol:
        lines.append(f"Company: {symbol}")
    if section_types:
        lines.append(f"Financial Topic: {', '.join(section_types)}")
    if metrics:
        lines.append(f"Financial Metrics Mentioned: {', '.join(metrics)}")

    flags = []
    if is_forward_looking:
        flags.append("Forward Looking")
    if is_historical:
        flags.append("Historical")
    if table_type:
        flags.append(f"Table Preference: {table_type}")
    if flags:
        lines.append(f"Flags: {', '.join(flags)}")

    lines.append("")
    lines.append("Content:")
    lines.append(query)

    return "\n".join(lines)


def embed_query_structured(
    query: str,
    symbol: Optional[str] = None,
    metrics: Optional[List[str]] = None,
    section_types: Optional[List[str]] = None,
    is_forward_looking: bool = False,
    is_historical: bool = False,
    table_type: Optional[str] = None,
) -> List[float]:
    """
    Embed a query using structured text for better financial-domain retrieval.
    Use this when you have parsed query intent (e.g. from retriever_v2).
    """
    structured = build_query_embedding_text(
        query=query,
        symbol=symbol,
        metrics=metrics,
        section_types=section_types,
        is_forward_looking=is_forward_looking,
        is_historical=is_historical,
        table_type=table_type,
    )
    return embed_texts([structured])[0]


# Re-export so qdrant_loader only needs: from pipeline.loader.embedder import ...
from pipeline.loader.chunker import build_embedding_text  # noqa: E402, F401