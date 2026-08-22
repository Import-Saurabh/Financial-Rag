# Integration Plan: Total Vector DB Removal — Moving Fully to OpenKB + PageIndex with ETL API

**Version:** 4.0 (Grounded in actual `ingest.py`; zero vector-DB dependency, MinIO retained as document store)
**Goal:** **Completely and permanently remove all vector database dependency — Qdrant, embeddings, and vector-similarity search of every kind — from the Financial-RAG system.** There is no vector store anywhere in the target architecture, including the cache layer. Retrieval moves entirely to **OpenKB + PageIndex** (reasoning-based retrieval over a document tree) for text, and the **Quant_CoPilot-ETL API** (pure SQL) for numbers.

**What does NOT change:** Source PDFs (annual reports, concall transcripts) continue to live in **MinIO** exactly as they do today — `annual-reports/{symbol}/{filename}.pdf` and `concall-transcripts/{symbol}/{filename}.pdf`. MinIO is a document/object store, not a vector store, so it is untouched by this migration. It remains the single source of truth for raw PDFs; OpenKB's wiki is built *from* what's downloaded out of MinIO, the same way Qdrant's vectors used to be.

> **What changed in v4 vs v3:** v3 corrected "ChromaDB" → "Qdrant" and rewrote Phase 2 as a tail-replacement. v4 makes explicit that this is a **total, no-exceptions removal of vector-DB dependency** — including the Phase 7 semantic cache, which previously used a small local embedding model + Redis vector search (`FT.SEARCH`) and has now been redesigned to be vector-free (see Phase 7). MinIO's role as PDF object storage is called out explicitly throughout so it isn't mistaken for part of the vector stack being removed.

---

## 1. Executive Summary

### 1.1 The Strategic Shift
Currently, our system relies on **Qdrant** (two collections, `annual_reports` and `concalls`) with `all-MiniLM-L6-v2`-class embeddings generated via `embed_texts()`. We are eradicating this vector-first approach **entirely** and adopting a **reasoning-first, structure-aware** architecture with **zero vector database dependency anywhere in the stack** — not in primary retrieval, not in caching, not anywhere. Source PDFs stay exactly where they are today, in **MinIO**; only the retrieval layer built on top of them changes.

**Why remove Vector DB entirely?**
1. **Accuracy Ceiling:** Vector search caps at ~82% accuracy on complex financial benchmarks. PageIndex achieves **98.7%** on FinanceBench.
2. **Context Loss:** Qdrant requires chunking, which breaks logical flows in 200+ page financial reports. PageIndex uses a hierarchical tree index, preserving the exact logical structure.
3. **Hallucinations:** Vector similarity (semantic closeness) often retrieves irrelevant sections. PageIndex *reasons* through the document tree (Table of Contents → Sections → Subsections) like a human expert.
4. **Obsolescence:** Maintaining two retrieval paths (Qdrant + OpenKB) doubles complexity. We are committing to OpenKB as the single source of truth for textual/document reasoning.

### 1.2 The New Hybrid Architecture
We are replacing "Vector Similarity" with "Structured Reasoning" — completely, not partially.
- **Document Storage (Raw PDFs):** Stays in **MinIO**, unchanged. This is object storage, not a vector store, and is not part of what's being removed.
- **Document Knowledge (Qualitative):** 100% handled by OpenKB + PageIndex.
- **Numerical Knowledge (Quantitative):** 100% handled by the Quant_CoPilot-ETL API (Pure SQL).
- **Query Caching:** Handled without any vector similarity search (see Phase 7) — no embedding model runs anywhere in the target architecture.
- **Fusion:** The LLM synthesizes reasoning from both sources to produce the final answer.

---

## 2. Target Architecture (Single Source of Truth)

```mermaid
flowchart TD
    MinIO[(MinIO — Raw PDFs<br>annual-reports/ · concall-transcripts/)] --> Ingest[compilation_bridge.py<br>Docling extract]
    Ingest --> OpenKBCompile[openkb add / lint]
    OpenKBCompile --> Wiki[(OpenKB Wiki + PageIndex Tree)]

    User[User Query] --> Gateway[API Gateway / Rate Limiter]
    Gateway --> Cache{Redis Exact/Structured-Key Cache<br>no vector search}

    Cache -- Cache Hit --> Response[Instant Response]
    Cache -- Cache Miss --> Router[Query Intent Router]

    Router -- "Numerical (e.g., Revenue, EBITA)" --> ETL[Quant_CoPilot-ETL API]
    Router -- "Qualitative (e.g., Business Model)" --> Wiki
    Router -- "Hybrid (e.g., High Margin + Strategy)" --> Parallel[Parallel Retrieval]

    ETL --> Fusion[Evidence Fusion & Reranker]
    Wiki --> Fusion
    Parallel --> Fusion

    Fusion --> LLM[LLM Synthesis Layer<br>(Groq / Llama 3)]
    LLM --> Final[Verified Final Answer + Citations]
    Final --> Cache
```

**Key Architectural Change:**
- **Qdrant is removed** from `requirements.txt`, all import statements, and both collections (`annual_reports`, `concalls`) are decommissioned.
- **All embedding models are removed from the entire stack, with no exceptions** — including `pipeline/loader/embedder.py::embed_texts` (primary retrieval) *and* the Redis semantic cache's local embedding model, which is redesigned in Phase 7 to use exact/structured-key matching instead of vector similarity.
- Retrieval relies **solely** on OpenKB's tree traversal for text, and pure SQL for numbers. There is no vector index anywhere in the target architecture.
- **MinIO is unaffected.** It's a PDF/object store, not a vector store — `annual-reports/{symbol}/` and `concall-transcripts/{symbol}/` continue to be the source of truth for raw documents, exactly as today.
- **Docling is demoted to an ETL-only fork, not a gate in front of OpenKB.** PageIndex parses PDFs directly — `openkb add {pdf_path}` takes the raw PDF and builds its own tree from the document's native TOC/heading structure (see Phase 1, step 4). There is no need to pre-extract text with Docling before handing a document to OpenKB. Docling is only still useful for one thing: pulling structured tables into clean rows for the `Quant_CoPilot-ETL` push (Phase 2, step 3d) — that's a job PageIndex's reasoning tree isn't built for. It runs in parallel with, not before, the OpenKB compile step.

---

## 3. Prerequisites & Environment Setup

### 3.1 Infrastructure Setup
| Component | Version | Purpose |
| :--- | :--- | :--- |
| **OpenKB** | v0.9+ | Knowledge compilation engine |
| **PageIndex (Rust/Python)** | Latest | Tree indexing and reasoning retrieval |
| **Redis Stack** | 7.2+ | Semantic caching (Vector search inside Redis) |
| **Kubernetes** | 1.28+ | Orchestration for stateless OpenKB pods |
| **Quant_CoPilot-ETL** | Deployed | Accessible via internal network |
| **MinIO** *(kept)* | current | PDF source of truth — `annual-reports/{symbol}/`, `concall-transcripts/{symbol}/` |
| **MySQL** *(kept, re-shaped)* | current | Document-level ingestion tracking (`ai_hedge_fund`/`quant_db`) |

### 3.2 Environment Variables (`.env`)
```bash
# ========== OPENKB CORE ==========
OPENKB_WIKI_DIR=/data/openkb_wiki
OPENKB_MODEL=groq/llama-3.3-70b-versatile   # Or use Ollama/llama3:latest for local
OPENKB_PAGEINDEX_THRESHOLD=20               # Pages threshold for enabling tree index
OPENKB_PARALLEL_WORKERS=4                   # For indexing concurrency

# ========== QUANT COPILOT ETL ==========
ETL_API_BASE_URL=http://etl-svc:8000
ETL_API_KEY=your_super_secret_key

# ========== CACHE & PERFORMANCE ==========
REDIS_URL=redis://redis-svc:6379
SEMANTIC_SIMILARITY_THRESHOLD=0.92
CACHE_TTL_SECONDS=86400                     # 24 hours

# ========== LLM GROQ ==========
GROQ_API_KEY=your_groq_key

# ========== SYSTEM ==========
LOG_LEVEL=INFO
MAX_RETRIEVAL_DEPTH=5                       # Prevent infinite tree loops
FALLBACK_ENABLED=true                       # Fallback to simple summary if OpenKB fails
```

### 3.3 Existing Pipeline Assets to Preserve (new in v3)

`ingest.py` is not a naive script — it's the harness that makes ingestion idempotent, resumable, and safe to re-run on a 16GB/no-GPU laptop. Everything below is **doc-type- and retrieval-backend-agnostic** and should carry forward untouched into the OpenKB pipeline:

| Asset | Location in `ingest.py` | Why it survives the migration |
| :--- | :--- | :--- |
| MinIO discovery (`list_minio_pdfs`, `_resolve_single_object`, `_parse_minio_key`) | lines ~184–325 | Bucket/key parsing, symbol/year extraction — nothing to do with vectors |
| Pre-flight validation (`_validate_pdf_metadata`, `_quick_pdf_sanity_check`) | lines ~217–248 | Symbol regex, doc-type check, PDF header sniff |
| ETag-based dedup + incremental state (`_load_state`/`_save_state`, `content_hash_to_key`) | lines ~152–167, ~565–590 | This is *the* reason re-running `--all` doesn't re-process unchanged docs. Keep verbatim. |
| CLI surface (`--symbol`, `--all`, `--file`, `--year`, `--dry-run`, `--force`, `--workers`, `--batch-size`, `--stats`, `--list`, `--report`) | `main()`, lines ~928–1057 | Muscle memory + scripts/cron jobs already call this shape. `compilation_bridge.py` should expose the identical CLI, not a new one. |
| `RunReport` (JSON summary + `latest.json`) | lines ~366–425 | Ops visibility; just needs new counters (see §Phase 2) |
| `ProcessPoolExecutor` batch runner, capped at 3 workers | lines ~874–923 | The cap exists because Docling + embedding models are memory-heavy per process. This constraint **loosens** once embedding is removed (see Phase 2 note on concurrency) |
| Docling extraction (`extract_pdf`) | Step 2, lines ~630–647 | Kept, but **demoted** — no longer a gate before OpenKB (which parses PDFs natively). Runs only as an optional, parallel fork for table extraction feeding the ETL API. |

**Bottom line:** Phase 2 is a *tail replacement* (steps 3–5 of `ingest_pdf`), not a rewrite of the whole file.

---

## 4. Step-by-Step Integration & Migration Plan

### Phase 1: OpenKB Wiki Initialization & Configuration (Day 1-2)

**Goal:** Set up the OpenKB environment and validate the tree index generation.

**Steps:**
1. **Install OpenKB**:
   ```bash
   pip install openkb
   # Ensure PageIndex is installed as a dependency
   ```
2. **Initialize the Wiki Directory**:
   ```bash
   mkdir -p /data/openkb_wiki
   cd /data/openkb_wiki
   openkb init
   ```
3. **Configure `config.yaml`** in the wiki root:
   ```yaml
   llm:
     provider: groq
     model: llama-3.3-70b-versatile
     temperature: 0.0
   pageindex:
     threshold: 20
     max_depth: 10
   compilation:
     enable_cross_references: true
     lint_after_add: true
   ```
4. **Test Compilation**: Add a sample 100-page PDF.
   ```bash
   openkb add sample_annual_report.pdf
   ```
5. **Verify**: Check the `pages/` directory. Ensure the tree hierarchy is correctly generated.

---

### Phase 2: Eradicating Qdrant from the Ingestion Pipeline (Day 3-6) — *rewritten in v3*

**Goal:** Replace steps 3–5 of `ingest_pdf()` (chunk → build embedding text → embed → upsert to Qdrant) with an OpenKB compile step, **without** touching steps 0–2 (validation, dedup, download, Docling extraction) or the CLI/batch/report layer.

**What actually gets deleted:**
- `pipeline/loader/chunker.py` (`chunk_document`, `build_embedding_text`) — the v2 semantic chunker
- `pipeline/loader/embedder.py` (`embed_texts`)
- `pipeline/loader/qdrant_loader.py` (`get_collection_name`) and `_get_qdrant_client`, `_ensure_collection`, `_upsert_chunks_to_qdrant` in `ingest.py`
- `qdrant-client` from `requirements.txt`
- The 30-column `insert_chunk()` payload in `db/database.py` (chunk_type, section_type, hierarchy_path, financial_metrics, forward_looking, quantitative_guidance, contains_commitment/strategic/contract, is_duplicate, is_low_information, table_type, table_summary, speaker/speaker_role, importance_score, retrieval_tags, etc.)

**The known gap this creates (call this out explicitly to stakeholders):** that 30-column chunk metadata schema is doing real work today — it's what lets the current retriever filter/rerank on things like "forward-looking + quantitative guidance" or "management opinion in a concall." OpenKB's tree index does **not** have an equivalent per-node semantic-flag payload out of the box. Two options, pick one before Day 6:
- **(a) Trust PageIndex reasoning to recover this implicitly** — i.e., accept that a query like "forward-looking guidance on margins" is now answered by the LLM reasoning over the relevant tree branch rather than a pre-computed flag. Simpler, but you lose deterministic filtering.
- **(b) Keep a lightweight sidecar tagger** — run the existing regex/heuristic flag-detection functions (currently embedded in the v2 chunker) over Docling's extracted blocks *before* handing text to `openkb add`, and store the flags as page-level frontmatter/metadata in the OpenKB page files (OpenKB supports arbitrary frontmatter). This preserves filterability without reintroducing embeddings.

Recommend (b) if any current retrieval prompts rely on `contains_guidance`/`forward_looking` filtering; otherwise (a) is less to maintain.

**Detailed Actions:**
1. **Remove dependencies**: Delete `qdrant-client` from `requirements.txt`. `sentence-transformers` / embedding libs stay *only* if Phase 7's semantic cache still needs them (see §7).
2. **Modify `ingest_pdf()` in place** (don't rewrite the function — replace its middle):
   - Keep Steps 0, 0.5, 0.6 (validation, dedup, incremental check) and Step 1 (MinIO download) exactly as-is.
   - **Demote Step 2 (Docling extraction) to a conditional, ETL-only fork — not a gate before OpenKB.** OpenKB/PageIndex parses PDFs natively and doesn't need Docling's output as input (`openkb add {pdf_path}` takes the raw PDF directly). Run Docling only when the document actually contains tables worth pushing to the ETL API; skip it otherwise. This also means most of the current `extracted.fiscal_year`/`extracted.company_name` auto-detection can be dropped or kept as a light fallback only when the filename-based year regex (`_YEAR_RE`) fails to match — it's no longer load-bearing for retrieval.
   - Replace old Steps 3–5 (chunk → build embedding text → embed → upsert to Qdrant) with a single compile step that hands the **downloaded PDF file directly** to OpenKB:
     ```
     [2/3] (conditional) Docling table extraction → push to ETL API
     [3/3] Compiling PDF directly into OpenKB wiki (openkb add {local_path}) + linting
     ```
3. **Implement the bridge as `compilation_bridge.py`**, exposing the **same CLI surface as `ingest.py`** (`--symbol`, `--all`, `--file`, `--year`, `--dry-run`, `--force`, `--workers`, `--batch-size`, `--stats`, `--list`, `--report`) so existing operational scripts/cron jobs don't need to change their invocation, only their entrypoint:
   - Reuses `list_minio_pdfs` / `_resolve_single_object` for discovery — no reimplementation.
   - For each resolved PDF that passes validation and isn't a dedup/incremental skip:
     a. Extract Ticker, Year, Document Type from the filename/key (already done — reuse `pdf_info`; no Docling needed for this in the common case).
     b. Run `openkb add {downloaded_pdf_path}` directly (subprocess or SDK) — **not** a Docling-extracted-text staging file.
     c. Run `openkb lint` to check for contradictions.
     d. **Separately and optionally**, if the document type/heuristics suggest it's table-heavy (annual reports especially), run Docling purely to extract structured tables and push them to `etl_client.py` — this fork never touches the OpenKB path and can even be deferred to a later batch job if it slows down the main compile loop.
4. **Re-shape MySQL tracking**:
   - Keep `upsert_document`, `mark_document_ingested`, `mark_document_failed`, `is_already_ingested`, `log_ingestion` — these are document-level, not vector-level, and the ETag/incremental logic in `ingest_pdf()` depends on `is_already_ingested` returning correctly.
   - Replace the `chunks` table's Qdrant-specific columns (`qdrant_id`, `collection`) with `openkb_page_id`, `openkb_wiki_path`. Drop the embedding-tied columns per the (a)/(b) decision above; if (b), keep the semantic-flag columns but populate them from the sidecar tagger instead of the chunker.
   - Migration note: write a one-off script to backfill `openkb_page_id` for already-ingested docs during the Phase 5 re-indexing run — don't try to map old `qdrant_id`s onto new page IDs, there's no 1:1 relationship (chunks vs. tree nodes).
5. **Update `RunReport`**: replace `chunks_created` / `vectors_uploaded` counters with `pages_compiled` / `lint_warnings`. Keep everything else (`documents_processed`, `duplicates_skipped`, `validation_failed`, `per_doc_timing`, `warnings`, `failures`) as-is — they're not vector-specific.
6. **Concurrency note**: the current `--workers` cap of 3 exists because each `ProcessPoolExecutor` worker loads its own Docling + local embedding model — that's a *local RAM* constraint on a 16GB/no-GPU box. Once `embed_texts()` is gone *and* Docling is off the main OpenKB path (only spun up occasionally for the ETL table-extraction fork), each worker's steady-state memory footprint drops sharply — the binding constraint shifts almost entirely to **Groq API concurrency/rate limits**, not local RAM. Raise the worker cap more confidently than in v3 (start at 5–6, watch for 429s) but add the same circuit-breaker/backoff pattern planned for the ETL client in Phase 5 around `openkb add` calls too — Groq rate-limiting on compilation is the new failure mode to guard against, not OOM.
7. **Validation**: Run the pipeline on a batch of 50 documents via `compilation_bridge.py --all --dry-run` first (dry-run path already exists in `ingest_pdf` — Step 0.5–0.6 run, actual compile is skipped), then a live batch. Confirm all are compiled into the wiki, `openkb lint` reports no contradictions, and `--report` shows expected `pages_compiled` counts.

---

### Phase 3: Building the Query Intent Router (Day 7-9)

**Goal:** Replace the old "Hybrid Search" dispatcher with a new Intent Router. Since we have no Vector DB, we must classify queries to route between OpenKB (text) and ETL (numbers).

**Detailed Actions:**
1. **Define Query Categories**:
   - `NUMERICAL`: "What was Q3 revenue?", "EBITDA for 2024".
   - `QUALITATIVE`: "Explain the business model", "What are the risks?".
   - `COMPARISON`: "Compare Company A and B margins" (Hybrid).
   - `AGGREGATION`: "Total revenue of tech sector" (ETL).
2. **Implement `router.py`**:
   - Use a **rule-based regex** matcher for speed (sub-5ms) or a **small LLM (Groq-Llama-3.1-8b)** for complex disambiguation.
   - **Regex Rules**:
     - If contains `$`, `%`, `crore`, `million`, `revenue`, `profit`, `quarter` → `NUMERICAL`.
     - If contains `business`, `strategy`, `model`, `risk`, `competitor` → `QUALITATIVE`.
     - If contains multiple tickers (`and`, `vs`, `compare`) → `COMPARISON`.
3. **Create Routing Decision Map**:
   ```json
   {
     "NUMERICAL": { "use_etl": true, "use_openkb": false },
     "QUALITATIVE": { "use_etl": false, "use_openkb": true },
     "HYBRID": { "use_etl": true, "use_openkb": true, "primary": "etl_filter_then_openkb" }
   }
   ```

---

### Phase 4: OpenKB Retriever Implementation (Day 10-12)

**Goal:** Replace the Qdrant similarity search with the PageIndex reasoning search.

**Detailed Actions:**
1. **Implement `retriever_openkb.py`**:
   - Method: `retrieve(question, top_k=5)`.
   - Call `openkb query "{question}" --json` via subprocess.
   - Parse the JSON output. OpenKB outputs page IDs, summaries, and relevance paths.
   - **Fallback Logic**: If `openkb query` times out (>10s) or returns empty, fallback to simple keyword search on the text files within the wiki.
2. **Extract Metadata**:
   - Pull `source_file`, `page_number`, `section_title` from the result.
   - If Phase 2 option (b) was taken, also pull the sidecar semantic flags from page frontmatter.
   - Store this in the `evidence` object for citations.
3. **Performance Tuning**:
   - Set `max_depth` to 5 to prevent overly deep tree traversal.
   - Pre-load the wiki index into memory for faster subprocess response.

---

### Phase 5: ETL API Client Integration (Day 13-15)

**Goal:** Securely connect to the Quant_CoPilot-ETL API for structured data.

**Detailed Actions:**
1. **Implement `etl_client.py`**:
   - `get_metric(ticker, metric, year, quarter)` → Calls `/api/v1/financials/metric`.
   - `get_trend(ticker, metric, quarters)` → Calls `/api/v1/financials/trend`.
   - `compare_peers(tickers, metric)` → Calls `/api/v1/financials/compare`.
2. **Resilience Engineering**:
   - Implement **Circuit Breaker** (fail after 3 consecutive errors) — reuse the same pattern for `openkb add`/`openkb query` calls (see Phase 2 note 6).
   - Implement **Retry with Backoff** (exponential: 1s, 2s, 4s).
   - Cache frequent ETL calls (e.g., "RELIANCE Revenue 2024") in Redis for 1 hour to avoid rate limits.
3. **Validation**: Ensure the API returns exact numeric JSON. The LLM will use this directly without performing any calculations.

---

### Phase 6: Enhanced Fusion & Synthesis Engine (Day 16-19)

**Goal:** Combine results from OpenKB and ETL and generate the final answer. **No vector reranker** is needed now, but we keep the cross-encoder for ranking *text* evidence.

**Detailed Actions:**
1. **Fuse Evidence**:
   - If `NUMERICAL`: Build context directly from ETL JSON + maybe a small snippet from OpenKB for context.
   - If `QUALITATIVE`: Use only OpenKB page texts.
   - If `HYBRID`:
     1. Query ETL to get the list of qualifying tickers (e.g., "margin > 40%").
     2. Pass these tickers to OpenKB to fetch their business model pages.
2. **Prompt Engineering** (Update `prompts.py`):
   - Create distinct prompts:
     - `PROMPT_NUMERICAL`: "You are given exact JSON data. State the numbers clearly. Do not recalculate."
     - `PROMPT_QUALITATIVE`: "Synthesize the following extracted pages from the annual report."
     - `PROMPT_HYBRID`: "Here are the financial filters (JSON) and the relevant business descriptions. Explain why these companies match the criteria."
3. **Synthesis**:
   - Connect to Groq.
   - Generate the answer.
   - Attach metadata: `sources` (page numbers from OpenKB) and `data_sources` (ETL database tables).

---

### Phase 7: Query Caching Layer — Vector-Free (Day 20-22)

**Goal:** Manage concurrency and reduce LLM costs **without any vector database or embedding model anywhere in the caching path.** The old design used Redis with an internal vector index (`FT.SEARCH`) and a small local embedding model — that entire approach is dropped in favor of structured/exact-key caching, split by query type so cache-hit quality doesn't collapse.

**Detailed Actions:**
1. **Setup Redis Stack** as a plain key-value cache (no `redisearch` vector module needed — a standard Redis instance is sufficient now).
2. **Implement `query_cache.py`** with two keying strategies, chosen based on the Phase 3 router's classification of the incoming query:
   - **`NUMERICAL` / `AGGREGATION` queries — structured tuple key.** The Phase 3 router already extracts `{ticker, metric, period}`-style tuples to decide ETL routing. Reuse that same tuple as the Redis cache key (e.g. `metric:RELIANCE:revenue:Q3FY24`). This means "Reliance Q3 revenue" and "What was RIL's revenue in Q3" hit the same cache entry even though the raw text differs — no embedding required, because the router already normalized the query into structured form.
   - **`QUALITATIVE` / `HYBRID` queries — normalized-text exact key.** Lowercase, strip punctuation/whitespace, resolve known ticker aliases, and use the normalized string as the key. This won't catch every paraphrase, but it's zero-dependency and correct; accept a lower hit rate here in exchange for total vector-DB removal.
   - **Cache Store**: Store the query (raw + normalized/tuple key), the response, and a TTL of 24h.
   - **Cache Lookup**: Compute the same key (tuple or normalized string) from the incoming query and do a direct Redis `GET` — sub-10ms, no similarity search of any kind.
3. **Wiring**: Wrap the `EnhancedRAGEngine.query()` method with the cache check, routing to the tuple-key or normalized-text path based on the Phase 3 intent classification.
4. **Dependency cleanup**: `sentence-transformers` and any embedding library can now be removed from `requirements.txt` entirely — there is no remaining use for it anywhere in the system after this phase.

---

### Phase 8: Production Deployment & Zero-Downtime Cutover (Day 23-26)

**Goal:** Deploy to production and completely disable the old vector services.

**Detailed Actions:**
1. **Dockerize**:
   - Create `Dockerfile` with OpenKB pre-installed.
   - Ensure the Wiki directory is mounted as a persistent volume.
2. **Kubernetes Configuration**:
   - Deploy **OpenKB Retriever** as a Stateless Deployment.
   - Set `HPA (Horizontal Pod Autoscaler)` to scale based on `cpu` or `custom_qps`.
   - Load the entire OpenKB Wiki into a `emptyDir` or shared volume to ensure fast pod startup.
3. **Traffic Switching**:
   - **Step 1**: Deploy the new service alongside the old one.
   - **Step 2**: Route 10% of traffic to the new OpenKB path. Monitor error rates and latency.
   - **Step 3**: If stable for 2 hours, ramp up to 100%.
   - **Step 4**: **Shut down** the Qdrant container and the old embedding generation cron jobs.
4. **Cleanup**: Delete the old Qdrant persistent volumes to free up storage.

---

### Phase 9: Monitoring & Cost Observability (Day 27-28)

**Goal:** Set up dashboards to monitor the new architecture.

**Detailed Actions:**
1. **Metrics to Track**:
   - `openkb_query_duration_seconds` (Alert if > 8s).
   - `openkb_compile_duration_seconds` and `openkb_compile_rate_limit_hits_total` (new — replaces old embedding-time metrics; watches for the Groq rate-limit failure mode from Phase 2 note 6).
   - `etl_api_error_total` (Alert if > 5%).
   - `cache_hit_ratio` (Target > 40%).
   - `llm_token_consumption_total` (Monitor daily cost).
   - `pageindex_tree_depth` (Monitor average navigation depth).
2. **Logging**: Ensure all queries and their routed paths are logged for auditing.
3. **Alerting**:
   - PagerDuty alert if `cache_hit_ratio` drops below 20% (means cost is spiking).
   - Alert if OpenKB compilation fails for 3 consecutive documents.

---

## 5. Data Migration Strategy (Re-indexing)

Since we are eradicating the vector DB, we must re-compile all existing documents into the OpenKB Wiki.

**Strategy:**
1. **Reuse existing discovery, don't rebuild it**: `compilation_bridge.py --all --dry-run` already gives you the exact document count and skip/dedup breakdown via `list_minio_pdfs` + the existing incremental-state check — no need for a separate inventory step.
2. **Staging Dry Run**: In staging, run `compilation_bridge.py --all` on the entire historical dataset (e.g., 5,000 PDFs).
3. **Parallel Processing**: Use the existing `ProcessPoolExecutor` batch runner (`--workers`) rather than introducing GNU `parallel`. Per Phase 2 note 6, this cap can likely go higher than 3 now that embedding is gone — validate against Groq rate limits in staging first.
4. **Estimated Time**: ~30 seconds per PDF (Groq compilation, network-bound rather than local-CPU-bound). For 5,000 PDFs, this takes ~40 hours at concurrency 1; scales down roughly linearly with worker count up to the Groq rate limit. Run this over a weekend.
5. **Verification**: Run `openkb lint` post-migration, and cross-check `compilation_bridge.py --stats` / `--report` against the pre-migration `ingest.py --stats` document counts to confirm no PDFs were silently dropped.

---

## 6. Handling Concurrency & High Latency (Production Readiness)

To ensure the system handles 100+ concurrent users effectively without the speed of vector search:

1. **Horizontal Pod Autoscaling (HPA)**:
   - Since OpenKB is stateless, scale pods up to 20 replicas during peak hours.
   - Each pod holds the index in memory.
2. **Request Batching**:
   - If the Router identifies a `NUMERICAL` query, it goes directly to ETL (sub-200ms).
   - Only `QUALITATIVE` and `HYBRID` hit the OpenKB cluster.
3. **Streaming**:
   - Stream the PageIndex reasoning steps back to the user interface (e.g., "Navigating to Section 3.2... found relevant data...").
   - This improves perceived performance even if total wall-clock time is ~5-8 seconds.
4. **Asynchronous Processing**:
   - For complex "Sector Analysis" queries, implement an async task queue (Celery). The user submits the job and receives a notification when complete.

---

## 7. Testing Checklist

| Test Category | Specific Test Cases | Pass Criteria |
| :--- | :--- | :--- |
| **Ingestion** | Add a 300-page PDF with complex tables. | Wiki generates tree with < 5% error rate. |
| **Ingestion harness parity** *(new)* | Run `compilation_bridge.py --symbol X --dry-run` and `--force`. | Dedup/incremental/validation behavior matches current `ingest.py` output exactly. |
| **Numerical Query** | "What was Reliance's Q3 2024 EBITA?" | Returns exact number from ETL API, not a hallucination. |
| **Qualitative Query** | "Explain Jio's telecom strategy." | Retrieves the correct section from OpenKB. |
| **Semantic-flag parity** *(new, only if Phase 2 option (b) chosen)* | Query relying on `forward_looking`/`contains_guidance` filtering. | Sidecar-tagged OpenKB pages return equivalent results to the old Qdrant payload filter. |
| **Hybrid Query** | "List software companies with > 20% margin and their AI strategy." | Correctly filters via ETL and retrieves descriptions via OpenKB. |
| **Caching** | Ask a query twice. | Second response time < 200ms. |
| **Fallback** | Take ETL API down. | System still returns an answer using OpenKB only. |
| **Compilation rate limits** *(new)* | Run `--workers 5` batch against Groq during business hours. | Circuit breaker / backoff on `openkb add` prevents cascading failures; no batch abort. |
| **Latency (p95)** | Simulate 50 concurrent users. | Average latency < 6 seconds (without cache). |

---

## 8. Rollback Plan (Contingency)

While we are eradicating the vector DB, we must have a rollback strategy if OpenKB fails catastrophically.

1. **Pre-rollback preparation**: Keep a backup of the last Qdrant persistent volume/snapshot for 1 month, and keep `ingest.py` (unmodified, pre-Phase-2) in a tagged branch rather than deleting it.
2. **Rollback Triggers**:
   - Error rate for retrieval exceeds 15%.
   - Latency exceeds 20 seconds for more than 10% of requests.
3. **Execution**:
   - Revert the `docker-compose` to the previous tag (which includes Qdrant).
   - Point the Query Router back to the Qdrant index.
   - Duration: < 10 minutes.

---

## 9. Timeline Summary

| Phase | Description | Effort | Days |
| :--- | :--- | :--- | :--- |
| **1** | OpenKB Setup & Initialization | 2 devs | 2 days |
| **2** | Eradicate Qdrant from Ingestion (tail-replace `ingest_pdf`, keep harness) | 2 devs | 4 days |
| **3** | Query Intent Router | 1 dev | 3 days |
| **4** | OpenKB Retriever Implementation | 2 devs | 3 days |
| **5** | ETL API Client Integration | 1 dev | 3 days |
| **6** | Fusion & Synthesis Engine | 2 devs | 4 days |
| **7** | Query Caching, vector-free (Redis) | 1 dev | 3 days |
| **8** | Production Deployment & Cutover | 2 devs | 4 days |
| **9** | Monitoring & Optimization | 1 dev | 2 days |
| **Total** | | | **~28 Days** |

---

## 10. Conclusion

This plan ensures a **complete, irreversible, and total shift away from vector databases** — Qdrant, embeddings, and vector similarity search are removed from every layer of the system, including the query cache, with no exceptions carried forward. By reusing (not discarding) the MinIO/MySQL/dedup/CLI harness already built in `ingest.py`, we simplify the architecture, eliminate chunking issues, and leverage the superior reasoning capabilities of OpenKB+PageIndex — while keeping the operational maturity (dry-run, incremental re-ingestion, batch reporting) that already exists.

**The Final Stack:**
- **Raw document storage:** MinIO — unchanged, still holds source PDFs (`annual-reports/{symbol}/`, `concall-transcripts/{symbol}/`).
- **Text Retrieval:** OpenKB (Reasoning Tree) + PageIndex. No vector index.
- **Number Retrieval:** Quant_CoPilot-ETL (SQL).
- **Cache:** Redis, structured/exact-key — no vector search, no embedding model.
- **Synthesis:** Groq API.
- **Document intake:** MinIO → Docling extraction → `compilation_bridge.py` (successor to `ingest.py`, same CLI, same dedup/incremental logic) → OpenKB compile.

With the caching and scaling strategies outlined above, the system will maintain sub-6-second latency for 95% of uncached queries while providing financial-grade accuracy that vector search simply cannot match.

---

## Appendix: Open Decision for the Team

Before starting Phase 2, decide explicitly on the chunk-level semantic-flag question (§Phase 2): **trust PageIndex reasoning implicitly**, or **carry forward a sidecar tagger** writing flags into OpenKB page frontmatter. This is the one place where the migration isn't a clean drop-in — everything else in the current harness (MinIO, MySQL document tracking, dedup, CLI, batching, reporting) maps over directly.