# Graph Report - Financial-Rag  (2026-07-29)

## Corpus Check
- 42 files · ~49,947 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 711 nodes · 2157 edges · 45 communities (15 shown, 30 thin omitted)
- Extraction: 64% EXTRACTED · 36% INFERRED · 0% AMBIGUOUS · INFERRED: 771 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `8241f151`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- BridgeResult
- RetrievedChunk
- RAGResponse
- chunker.py
- rag_engine.py
- eval_suite.py
- metric_engine.py
- str
- SetupGuide.md
- Ingest.py
- AtomicNeed
- Financial RAG — Equity Research System
- query_client.py
- retriever.py
- latency_optimizer.py
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
1. `RetrievedChunk` - 112 edges
2. `BridgeResult` - 68 edges
3. `AtomicNeed` - 67 edges
4. `VectorAtomResult` - 66 edges
5. `SynthesisPipeline` - 59 edges
6. `NeedType` - 57 edges
7. `TimeHorizon` - 57 edges
8. `FusionResult` - 53 edges
9. `PromptBuilder` - 53 edges
10. `SqlAtomResult` - 52 edges

## Surprising Connections (you probably didn't know these)
- `NeedType` --uses--> `fusion/test_fusion_layer.py Self-contained unit tests for FusionLayer. No DB,…`  [INFERRED]
  decomposer/atomic_decomposer.py → fusion/test_fusion_layer.py
- `NeedType` --uses--> `Numbers without a recognised unit should NOT be captured.`  [INFERRED]
  decomposer/atomic_decomposer.py → fusion/test_fusion_layer.py
- `NeedType` --uses--> `BUG 2: ConcallClaim.symbol must carry the company from chunk metadata.`  [INFERRED]
  decomposer/atomic_decomposer.py → fusion/test_fusion_layer.py
- `NeedType` --uses--> `BUG 2: Orphan forward FusionInsight.symbol was always ''. The orphan-forward…`  [INFERRED]
  decomposer/atomic_decomposer.py → fusion/test_fusion_layer.py
- `NeedType` --uses--> `SQL has revenue data, no concall chunks → UNMATCHED insight.`  [INFERRED]
  decomposer/atomic_decomposer.py → fusion/test_fusion_layer.py

## Import Cycles
- None detected.

## Communities (45 total, 30 thin omitted)

### Community 0 - "BridgeResult"
Cohesion: 0.10
Nodes (75): BridgeResult, ConcallClaim, _extract_numeric_claims(), FusionInsight, FusionLayer, FusionResult, _get_period_col(), InsightType (+67 more)

### Community 1 - "RetrievedChunk"
Cohesion: 0.07
Nodes (76): RetrievedChunk, rag/rag_engine.py — patched to use SynthesisPipeline (Layer 5) What changed…, Build the full catalogue of configured providers. Model slug correctness (as of…, Call Anthropic Messages API directly., Lightweight health-check for a single provider. Strategy per provider type: •…, Fallback: send a 1-token completion to check the provider is alive., Validate every entry in *catalogue* (or build a fresh one if None). Updates the…, Return cached healthy providers; rebuild if cache is empty. (+68 more)

### Community 2 - "RAGResponse"
Cohesion: 0.11
Nodes (26): run_tests(), cached_generate(), _deserialize(), _exact_key(), FakeResponse, get_cache(), _meta_key(), Any (+18 more)

### Community 3 - "chunker.py"
Cohesion: 0.08
Nodes (50): _count_pages(), _detect_speaker_role(), extract_annual_report(), extract_concall(), extract_pdf(), _extract_prose_excluding_tables(), _extract_speaker_turns(), _extract_table() (+42 more)

### Community 4 - "rag_engine.py"
Cohesion: 0.05
Nodes (66): BaseModel, FastAPI, server.py  — FastAPI wrapper around query.py ──────────────────────────────────, Pre-warm every heavy component before accepting requests., Rewrite 'from FY23 onward/onwards/forward/to present/to date/since FY23'     to, # NOTE: cancelling does NOT kill the underlying thread (Python limitation),, Synchronous query execution — runs in a thread pool so it doesn't     block the, Return available provider list so query_client can show the menu. (+58 more)

### Community 5 - "eval_suite.py"
Cohesion: 0.08
Nodes (23): _compute_metrics(), DatasetBuilder, EvalDataset, EvalResults, GoldenSample, load(), _nanmean(), _print_query_row() (+15 more)

### Community 6 - "metric_engine.py"
Cohesion: 0.10
Nodes (41): available_years(), _bs_annual(), _conn(), _forward_eps(), get_growth(), get_leverage(), _get_pool(), get_profitability() (+33 more)

### Community 7 - "str"
Cohesion: 0.14
Nodes (14): classify_doc(), download_pdf(), extract_documents(), extract_year(), fetch_page(), main(), safe_name(), str (+6 more)

### Community 8 - "SetupGuide.md"
Cohesion: 0.11
Nodes (18): 10. Filename Convention, 11. Verify MySQL, 12. Download Embedding Model, 13. Project Directory, 14. Verify Everything, 15. Ready for Ingestion, 1. System Requirements, 2. Clone the Repository (+10 more)

### Community 9 - "Ingest.py"
Cohesion: 0.13
Nodes (35): get_chunks_for_doc(), get_conn(), get_pending_documents(), _get_pool(), get_stats(), init_db(), insert_chunk(), is_already_ingested() (+27 more)

### Community 10 - "AtomicNeed"
Cohesion: 0.07
Nodes (71): AtomicDecomposer, AtomicNeed, _extract_years(), _is_ebitda_multi_year_query(), _llm_decompose(), NeedType, _normalise_fy(), Enum (+63 more)

### Community 11 - "Financial RAG — Equity Research System"
Cohesion: 0.17
Nodes (11): Architecture, code:block1 (Financial-Rag/), code:bash (# 1. Clone and install), Directory Structure, Financial RAG — Equity Research System, Groq Free Tier, High-Level Architecture, Low-Level Pipeline Design (+3 more)

### Community 13 - "query_client.py"
Cohesion: 0.32
Nodes (7): query_client.py — drop-in replacement for query.py ────────────────────────────, Try to get live provider list from server; fall back to hardcoded., fetch_providers(), main(), pick_provider(), query_client.py — drop-in replacement for query.py…, Try to get live provider list from server; fall back to hardcoded.

### Community 14 - "retriever.py"
Cohesion: 0.06
Nodes (53): config/settings.py Central configuration for the Financial RAG system.…, Filter, Logger, build_embedding_text(), Build a context-prefixed string to embed instead of raw text. The embedding…, embed_query(), embed_texts(), _get_model() (+45 more)

## Knowledge Gaps
- **24 isolated node(s):** `Financial RAG Setup Guide`, `1. System Requirements`, `2. Clone the Repository`, `Windows`, `Linux/macOS` (+19 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **30 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `RetrievedChunk` connect `RetrievedChunk` to `BridgeResult`, `RAGResponse`, `rag_engine.py`, `AtomicNeed`, `retriever.py`?**
  _High betweenness centrality (0.129) - this node is a cross-community bridge._
- **Why does `get_logger()` connect `retriever.py` to `BridgeResult`, `RetrievedChunk`, `RAGResponse`, `chunker.py`, `rag_engine.py`, `eval_suite.py`, `Ingest.py`, `AtomicNeed`?**
  _High betweenness centrality (0.088) - this node is a cross-community bridge._
- **Why does `SynthesisPipeline` connect `RetrievedChunk` to `BridgeResult`, `RAGResponse`, `rag_engine.py`, `str`, `AtomicNeed`?**
  _High betweenness centrality (0.049) - this node is a cross-community bridge._
- **Are the 97 inferred relationships involving `RetrievedChunk` (e.g. with `BridgeResult` and `ConcallClaim`) actually correct?**
  _`RetrievedChunk` has 97 INFERRED edges - model-reasoned connections that need verification._
- **Are the 58 inferred relationships involving `BridgeResult` (e.g. with `AtomicNeed` and `NeedType`) actually correct?**
  _`BridgeResult` has 58 INFERRED edges - model-reasoned connections that need verification._
- **Are the 48 inferred relationships involving `AtomicNeed` (e.g. with `_atom()` and `fusion/test_fusion_layer.py Self-contained unit tests for FusionLayer. No DB,…`) actually correct?**
  _`AtomicNeed` has 48 INFERRED edges - model-reasoned connections that need verification._
- **Are the 58 inferred relationships involving `VectorAtomResult` (e.g. with `AtomicNeed` and `NeedType`) actually correct?**
  _`VectorAtomResult` has 58 INFERRED edges - model-reasoned connections that need verification._