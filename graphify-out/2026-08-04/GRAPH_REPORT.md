# Graph Report - Financial-Rag  (2026-08-03)

## Corpus Check
- 35 files · ~43,455 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 573 nodes · 1562 edges · 45 communities (15 shown, 30 thin omitted)
- Extraction: 70% EXTRACTED · 30% INFERRED · 0% AMBIGUOUS · INFERRED: 475 edges (avg confidence: 0.55)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `da807ccd`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- RetrievedChunk
- SynthesisPipeline
- RAGResponse
- chunker.py
- rag_engine.py
- qdrant_loader.py
- reranker.py
- get_logger
- SetupGuide.md
- Ingest.py
- AtomicNeed
- Financial RAG — Equity Research System
- settings.py
- query_client.py
- retriever.py
- Simplified trimmer: for large-context providers returns all chunks.     For Gro
- Retry policy (revised):       • 429 (rate-limit)  → back off and retry (max 2 r
- Generate a cited answer using the full synthesis pipeline.      New parameters
- One atomic information need extracted from the user query.
- Populate sql_table and sql_columns from SUBTYPE_TABLE_MAP.
- Extract explicitly mentioned fiscal years from a query string.
- Extract NSE symbols mentioned in the query (uppercase tokens).
- Apply pattern rules to extract atomic needs. Returns list (may be empty).
- Post-processing: when the query has forward-looking signals AND a QUANTITATIVE
- Call LLM to decompose a query into atoms.
- Decompose a user query into a list of AtomicNeed objects.          Strategy:
- Same as decompose() but returns a diagnostic dict:           {             "qu
- Additive score adjustment:       + bonus  when query is forward-looking AND chu
- Returns a Voyage client if VOYAGE_API_KEY is set, else None.
- Lazy-load BAAI/bge-reranker-v2-m3 via sentence-transformers.      Memory footp
- Score each document against the query using bge-reranker-v2-m3.      CrossEnco
- Re-rank retrieved chunks.       Primary  : Voyage Rerank-2.5  (API, finance/SEC
- Rerank each collection independently so concall prose cannot displace     annua
- # NOTE: recency_boost is intentionally NOT applied here.
- Query /api/tags; return one entry per installed model. Never raises.
- Build the user-turn prompt.      resolved_years — used for the year-filter not
- Drop lowest-ranked chunks until the full prompt fits within:       (a) the mode
- resolved_years — years used for ChromaDB retrieval filter.     explicit_years —
- Indian FY: April of (fy_year-1) → March of fy_year.     e.g. FY2024 = 2023-04-0
- Build a parameterized SELECT for one SQL-backed AtomicNeed.      Returns (sql_
- A COMPARATIVE atom targets multiple symbols.     Expand it into one atom per sy
- Translates a list of AtomicNeed objects into concrete data-fetch results.
- Dispatch all atoms to the appropriate channel(s), running them in         paral
- Helper for the common case: fetch several metrics for one company.          Ex

## God Nodes (most connected - your core abstractions)
1. `RetrievedChunk` - 94 edges
2. `SynthesisPipeline` - 58 edges
3. `PromptBuilder` - 45 edges
4. `BridgeResult` - 44 edges
5. `VectorAtomResult` - 42 edges
6. `SynthesisResult` - 40 edges
7. `SqlAtomResult` - 37 edges
8. `AtomicNeed` - 35 edges
9. `BuiltPrompt` - 33 edges
10. `FusionResult` - 30 edges

## Surprising Connections (you probably didn't know these)
- `NeedType` --uses--> `BridgeResult`  [INFERRED]
  decomposer/atomic_decomposer.py → schema_bridge/schema_bridge.py
- `NeedType` --uses--> `SqlAtomResult`  [INFERRED]
  decomposer/atomic_decomposer.py → schema_bridge/schema_bridge.py
- `NeedType` --uses--> `VectorAtomResult`  [INFERRED]
  decomposer/atomic_decomposer.py → schema_bridge/schema_bridge.py
- `NeedType` --uses--> `synthesis/pipeline.py Orchestrates the full intent-decomposition → retrieval →…`  [INFERRED]
  decomposer/atomic_decomposer.py → synthesis/pipeline.py
- `NeedType` --uses--> `RetrievedChunk`  [INFERRED]
  decomposer/atomic_decomposer.py → synthesis/pipeline.py

## Import Cycles
- None detected.

## Communities (45 total, 30 thin omitted)

### Community 0 - "RetrievedChunk"
Cohesion: 0.09
Nodes (54): BridgeResult, ConcallClaim, _extract_numeric_claims(), FusionInsight, FusionLayer, FusionResult, _get_period_col(), InsightType (+46 more)

### Community 1 - "SynthesisPipeline"
Cohesion: 0.07
Nodes (67): str, _infer_symbol(), _minimal_fallback_prompt(), _mysql_reachable(), _pipeline_available(), Any, Path, Cheap connectivity probe — used only for pipeline-mode gating, not for actual… (+59 more)

### Community 2 - "RAGResponse"
Cohesion: 0.11
Nodes (25): cached_generate(), _deserialize(), _exact_key(), FakeResponse, get_cache(), _meta_key(), Any, Path (+17 more)

### Community 3 - "chunker.py"
Cohesion: 0.08
Nodes (50): _count_pages(), _detect_speaker_role(), extract_annual_report(), extract_concall(), extract_pdf(), _extract_prose_excluding_tables(), _extract_speaker_turns(), _extract_table() (+42 more)

### Community 4 - "rag_engine.py"
Cohesion: 0.06
Nodes (59): BaseModel, FastAPI, server.py  — FastAPI wrapper around query.py ──────────────────────────────────, Rewrite 'from FY23 onward/onwards/forward/to present/to date/since FY23'     to, Synchronous query execution — runs in a thread pool so it doesn't     block the, Validate all providers by checking their model slugs are still live.     Return, Run provider validation in a thread (blocking I/O) without blocking the     eve, get (+51 more)

### Community 5 - "qdrant_loader.py"
Cohesion: 0.19
Nodes (20): Filter, build_embedding_text(), Build a context-prefixed string to embed instead of raw text. The embedding…, _build_filter(), collection_count(), delete_by_symbol(), _ensure_collection(), get_collection_name() (+12 more)

### Community 6 - "reranker.py"
Cohesion: 0.21
Nodes (14): _ensure_model(), _load_model_blocking(), pipeline/retrieval/reranker.py BUGS FIXED IN THIS VERSION…, Load the reranker model. Priority: 1. Pre-quantized INT8 ONNX at _INT8_PATH…, Return the cached model, loading it if needed (thread-safe)., Fire model loading in a daemon thread so the first query is faster., Score all candidates in one batched call and return top_k. Falls back to…, Rerank a flat list of candidates (single doc_type or mixed). (+6 more)

### Community 7 - "get_logger"
Cohesion: 0.23
Nodes (9): Logger, embed_query(), embed_texts(), _get_model(), pipeline/loader/embedder.py Singleton embedding model — loaded ONCE per…, Embed a single query string., get_logger(), Path (+1 more)

### Community 8 - "SetupGuide.md"
Cohesion: 0.11
Nodes (18): 10. Filename Convention, 11. Verify MySQL, 12. Download Embedding Model, 13. Project Directory, 14. Verify Everything, 15. Ready for Ingestion, 1. System Requirements, 2. Clone the Repository (+10 more)

### Community 9 - "Ingest.py"
Cohesion: 0.13
Nodes (35): get_chunks_for_doc(), get_conn(), get_pending_documents(), _get_pool(), get_stats(), init_db(), insert_chunk(), is_already_ingested() (+27 more)

### Community 10 - "AtomicNeed"
Cohesion: 0.07
Nodes (61): AtomicDecomposer, AtomicNeed, _extract_years(), _is_ebitda_multi_year_query(), _llm_decompose(), NeedType, _normalise_fy(), Enum (+53 more)

### Community 11 - "Financial RAG — Equity Research System"
Cohesion: 0.17
Nodes (11): Architecture, code:block1 (Financial-Rag/), code:bash (# 1. Clone and install), Directory Structure, Financial RAG — Equity Research System, Groq Free Tier, High-Level Architecture, Low-Level Pipeline Design (+3 more)

### Community 13 - "query_client.py"
Cohesion: 0.38
Nodes (6): query_client.py — drop-in replacement for query.py ────────────────────────────, fetch_providers(), main(), pick_provider(), query_client.py — drop-in replacement for query.py…, Try to get live provider list from server; fall back to hardcoded.

### Community 14 - "retriever.py"
Cohesion: 0.12
Nodes (23): BM25, _build_where(), _expand_query(), _minmax(), _normalise_fy(), parse_year_intent(), Any, pipeline/retrieval/retriever.py FIXES applied in this version: [FIX 1]… (+15 more)

## Knowledge Gaps
- **24 isolated node(s):** `Financial RAG Setup Guide`, `1. System Requirements`, `2. Clone the Repository`, `Windows`, `Linux/macOS` (+19 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **30 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `RetrievedChunk` connect `RetrievedChunk` to `SynthesisPipeline`, `RAGResponse`, `rag_engine.py`, `reranker.py`, `AtomicNeed`, `retriever.py`?**
  _High betweenness centrality (0.146) - this node is a cross-community bridge._
- **Why does `get_logger()` connect `get_logger` to `RetrievedChunk`, `SynthesisPipeline`, `RAGResponse`, `chunker.py`, `rag_engine.py`, `qdrant_loader.py`, `reranker.py`, `Ingest.py`, `AtomicNeed`, `retriever.py`?**
  _High betweenness centrality (0.086) - this node is a cross-community bridge._
- **Why does `SynthesisPipeline` connect `SynthesisPipeline` to `RetrievedChunk`, `AtomicNeed`, `RAGResponse`, `rag_engine.py`?**
  _High betweenness centrality (0.074) - this node is a cross-community bridge._
- **Are the 79 inferred relationships involving `RetrievedChunk` (e.g. with `BridgeResult` and `ConcallClaim`) actually correct?**
  _`RetrievedChunk` has 79 INFERRED edges - model-reasoned connections that need verification._
- **Are the 43 inferred relationships involving `SynthesisPipeline` (e.g. with `AtomicDecomposer` and `AtomicNeed`) actually correct?**
  _`SynthesisPipeline` has 43 INFERRED edges - model-reasoned connections that need verification._
- **Are the 34 inferred relationships involving `PromptBuilder` (e.g. with `FusionResult` and `InsightType`) actually correct?**
  _`PromptBuilder` has 34 INFERRED edges - model-reasoned connections that need verification._
- **Are the 35 inferred relationships involving `BridgeResult` (e.g. with `AtomicNeed` and `NeedType`) actually correct?**
  _`BridgeResult` has 35 INFERRED edges - model-reasoned connections that need verification._