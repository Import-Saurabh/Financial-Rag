# Graph Report - Financial-Rag  (2026-08-04)

## Corpus Check
- 33 files · ~47,553 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 569 nodes · 1391 edges · 46 communities (17 shown, 29 thin omitted)
- Extraction: 81% EXTRACTED · 19% INFERRED · 0% AMBIGUOUS · INFERRED: 260 edges (avg confidence: 0.56)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `0650d00d`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- fusion_layer.py
- SynthesisPipeline
- RAGResponse
- pdf_extractor.py
- rag_engine.py
- NeedType
- server.py
- RetrievedChunk
- SetupGuide.md
- Ingest.py
- AtomicNeed
- Financial RAG — Equity Research System
- FusionLayer
- query_client.py
- retriever.py
- FusionInsight
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
1. `RetrievedChunk` - 60 edges
2. `SynthesisPipeline` - 37 edges
3. `FusionResult` - 31 edges
4. `BridgeResult` - 31 edges
5. `AtomicNeed` - 29 edges
6. `VectorAtomResult` - 29 edges
7. `ingest_pdf()` - 24 edges
8. `SqlAtomResult` - 24 edges
9. `InsightType` - 23 edges
10. `RAGResponse` - 23 edges

## Surprising Connections (you probably didn't know these)
- `NeedType` --uses--> `BridgeResult`  [INFERRED]
  decomposer/atomic_decomposer.py → schema_bridge/schema_bridge.py
- `NeedType` --uses--> `SchemaBridge`  [INFERRED]
  decomposer/atomic_decomposer.py → schema_bridge/schema_bridge.py
- `NeedType` --uses--> `SqlAtomResult`  [INFERRED]
  decomposer/atomic_decomposer.py → schema_bridge/schema_bridge.py
- `NeedType` --uses--> `VectorAtomResult`  [INFERRED]
  decomposer/atomic_decomposer.py → schema_bridge/schema_bridge.py
- `NeedType` --uses--> `SynthesisPipeline`  [INFERRED]
  decomposer/atomic_decomposer.py → synthesis/pipeline.py

## Import Cycles
- None detected.

## Communities (46 total, 29 thin omitted)

### Community 0 - "fusion_layer.py"
Cohesion: 0.19
Nodes (24): BridgeResult, ConcallClaim, _dedup_chunks(), _extract_numeric_claims(), _jaccard(), MetricRow, _dc, fusion/fusion_layer.py Layer 3 of the Quant CoPilot Intent Decomposition… (+16 more)

### Community 1 - "SynthesisPipeline"
Cohesion: 0.08
Nodes (32): AtomicDecomposer, Main decomposer class. Usage: decomposer = AtomicDecomposer() atoms =…, str, _builder_available(), _infer_symbol(), _minimal_fallback_prompt(), _mysql_reachable(), _pipeline_available() (+24 more)

### Community 2 - "RAGResponse"
Cohesion: 0.09
Nodes (29): _extract_years(), _normalise_fy(), Extract all fiscal years mentioned in the query and expand ranges. Handles:…, Convert "23", "2023", "25" → fiscal year int (e.g. 2023, 2025)., cached_generate(), _deserialize(), _exact_key(), FakeResponse (+21 more)

### Community 3 - "pdf_extractor.py"
Cohesion: 0.08
Nodes (56): _count_pages(), _detect_speaker_role(), extract_annual_report(), extract_concall(), extract_pdf(), _extract_prose_excluding_tables(), _extract_speaker_turns(), _extract_table() (+48 more)

### Community 4 - "rag_engine.py"
Cohesion: 0.12
Nodes (30): _build_context_legacy(), build_provider_catalogue(), _build_user_prompt_legacy(), _call_anthropic(), _call_gemini(), _call_openai_compat(), _call_with_retry(), _discover_ollama() (+22 more)

### Community 5 - "NeedType"
Cohesion: 0.19
Nodes (15): _is_ebitda_multi_year_query(), _llm_decompose(), NeedType, Enum, str, decomposer/atomic_decomposer.py — patched Bug fixes applied in this version…, Returns True when the query asks for EBITDA across multiple years (CAGR, YoY,…, Decompose a user query into a list of AtomicNeed objects. symbol is stamped… (+7 more)

### Community 6 - "server.py"
Cohesion: 0.06
Nodes (47): BaseModel, FastAPI, server.py  — FastAPI wrapper around query.py ──────────────────────────────────, Rewrite 'from FY23 onward/onwards/forward/to present/to date/since FY23'     to, Synchronous query execution — runs in a thread pool so it doesn't     block the, Validate all providers by checking their model slugs are still live.     Return, Run provider validation in a thread (blocking I/O) without blocking the     eve, get (+39 more)

### Community 7 - "RetrievedChunk"
Cohesion: 0.27
Nodes (16): FusionResult, InsightType, Enum, str, RetrievedChunk, _dc, synthesis/prompt_builder.py Layer 5 of the Quant CoPilot Intent Decomposition…, Format a metric value with its unit for display. (+8 more)

### Community 8 - "SetupGuide.md"
Cohesion: 0.11
Nodes (18): 10. Filename Convention, 11. Verify MySQL, 12. Download Embedding Model, 13. Project Directory, 14. Verify Everything, 15. Ready for Ingestion, 1. System Requirements, 2. Clone the Repository (+10 more)

### Community 9 - "Ingest.py"
Cohesion: 0.08
Nodes (53): get_chunks_for_doc(), get_conn(), get_pending_documents(), _get_pool(), get_stats(), init_db(), insert_chunk(), is_already_ingested() (+45 more)

### Community 10 - "AtomicNeed"
Cohesion: 0.13
Nodes (22): AtomicNeed, _build_sql(), _classify(), _execute_sql_atom(), _execute_vector_atom(), _expand_comparative(), _fy_date_range(), _infer_fallback_sql_sub_type() (+14 more)

### Community 11 - "Financial RAG — Equity Research System"
Cohesion: 0.17
Nodes (11): Architecture, code:block1 (Financial-Rag/), code:bash (# 1. Clone and install), Directory Structure, Financial RAG — Equity Research System, Groq Free Tier, High-Level Architecture, Low-Level Pipeline Design (+3 more)

### Community 12 - "FusionLayer"
Cohesion: 0.19
Nodes (8): FusionLayer, _parse_year_from_period(), _pct_divergence(), Convert a period-end date string to an Indian FY year. Indian financial year…, Absolute percentage divergence between actual and claim., Cross-references SQL actuals with concall management claims. Usage: fusion =…, A single 0-1 score summarising how trustworthy this evidence bundle is, driven…, For each sub_type that has SQL results, scan the given chunk list (concall OR…

### Community 13 - "query_client.py"
Cohesion: 0.17
Nodes (31): ArgumentParser, query_client.py — drop-in replacement for query.py ────────────────────────────, Namespace, build_arg_parser(), fetch_providers(), _fmt_pct(), _fmt_secs(), _format_source() (+23 more)

### Community 14 - "retriever.py"
Cohesion: 0.07
Nodes (48): config/settings.py Central configuration for the Financial RAG system.…, Filter, build_embedding_text(), embed_query(), embed_texts(), _get_model(), pipeline/loader/embedder.py Singleton embedding model — loaded ONCE per…, Embed a single query string. (+40 more)

### Community 15 - "FusionInsight"
Cohesion: 0.24
Nodes (7): FusionInsight, _get_period_col(), Any, Serialise everything the synthesis prompt builder needs. Structure: {…, A cross-referenced finding between SQL actuals and concall claims., Return whichever date column is present in the row., Pick the citation set the LLM should actually quote from, instead of handing…

## Knowledge Gaps
- **24 isolated node(s):** `Financial RAG Setup Guide`, `1. System Requirements`, `2. Clone the Repository`, `Windows`, `Linux/macOS` (+19 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **29 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_logger()` connect `server.py` to `fusion_layer.py`, `SynthesisPipeline`, `RAGResponse`, `pdf_extractor.py`, `rag_engine.py`, `Ingest.py`, `AtomicNeed`, `retriever.py`?**
  _High betweenness centrality (0.096) - this node is a cross-community bridge._
- **Why does `RetrievedChunk` connect `RetrievedChunk` to `fusion_layer.py`, `SynthesisPipeline`, `RAGResponse`, `rag_engine.py`, `NeedType`, `server.py`, `AtomicNeed`, `FusionLayer`, `retriever.py`, `FusionInsight`?**
  _High betweenness centrality (0.089) - this node is a cross-community bridge._
- **Why does `RAGResponse` connect `RAGResponse` to `SynthesisPipeline`, `rag_engine.py`, `RetrievedChunk`?**
  _High betweenness centrality (0.047) - this node is a cross-community bridge._
- **Are the 48 inferred relationships involving `RetrievedChunk` (e.g. with `BridgeResult` and `ConcallClaim`) actually correct?**
  _`RetrievedChunk` has 48 INFERRED edges - model-reasoned connections that need verification._
- **Are the 23 inferred relationships involving `SynthesisPipeline` (e.g. with `AtomicDecomposer` and `AtomicNeed`) actually correct?**
  _`SynthesisPipeline` has 23 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `FusionResult` (e.g. with `RetrievedChunk` and `BridgeResult`) actually correct?**
  _`FusionResult` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 23 inferred relationships involving `BridgeResult` (e.g. with `AtomicNeed` and `NeedType`) actually correct?**
  _`BridgeResult` has 23 INFERRED edges - model-reasoned connections that need verification._