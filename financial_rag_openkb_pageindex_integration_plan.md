```markdown
# Integration Plan: Eradicating Vector DB & Deploying OpenKB + PageIndex with ETL API

**Version:** 2.0 (Production Ready)
**Goal:** Completely remove ChromaDB (Vector DB) and all embedding pipelines from the Financial-RAG system. Replace the entire semantic retrieval layer with **OpenKB + PageIndex** (Reasoning-based retrieval) while integrating the **Quant_CoPilot-ETL API** for deterministic numerical queries.

---

## 1. Executive Summary

### 1.1 The Strategic Shift
Currently, our system relies on ChromaDB and `all-MiniLM-L6-v2` embeddings. We are eradicating this vector-first approach and adopting a **reasoning-first, structure-aware** architecture.

**Why remove Vector DB entirely?**
1.  **Accuracy Ceiling:** Vector search caps at ~82% accuracy on complex financial benchmarks. PageIndex achieves **98.7%** on FinanceBench.
2.  **Context Loss:** Vector DB requires chunking, which breaks logical flows in 200+ page financial reports. PageIndex uses a hierarchical tree index, preserving the exact logical structure.
3.  **Hallucinations:** Vector similarity (semantic closeness) often retrieves irrelevant sections. PageIndex *reasons* through the document tree (Table of Contents → Sections → Subsections) like a human expert.
4.  **Obsolescence:** Maintaining two retrieval paths (ChromaDB + OpenKB) doubles complexity. We are committing to OpenKB as the single source of truth for textual/document reasoning.

### 1.2 The New Hybrid Architecture
We are replacing "Vector Similarity" with "Structured Reasoning".
- **Document Knowledge (Qualitative):** 100% handled by OpenKB + PageIndex.
- **Numerical Knowledge (Quantitative):** 100% handled by the Quant_CoPilot-ETL API (Pure SQL).
- **Fusion:** The LLM synthesizes reasoning from both sources to produce the final answer.

---

## 2. Target Architecture (Single Source of Truth)

```mermaid
flowchart TD
    User[User Query] --> Gateway[API Gateway / Rate Limiter]
    Gateway --> Cache{Redis Semantic Cache}
    
    Cache -- Cache Hit --> Response[Instant Response]
    Cache -- Cache Miss --> Router[Query Intent Router]
    
    Router -- "Numerical (e.g., Revenue, EBITA)" --> ETL[Quant_CoPilot-ETL API]
    Router -- "Qualitative (e.g., Business Model)" --> OpenKB[OpenKB + PageIndex Cluster]
    Router -- "Hybrid (e.g., High Margin + Strategy)" --> Parallel[Parallel Retrieval]
    
    ETL --> Fusion[Evidence Fusion & Reranker]
    OpenKB --> Fusion
    Parallel --> Fusion
    
    Fusion --> LLM[LLM Synthesis Layer<br>(Groq / Llama 3)]
    LLM --> Final[Verified Final Answer + Citations]
    Final --> Cache
```

**Key Architectural Change:**
- **ChromaDB is removed** from `requirements.txt` and all import statements.
- **All embedding models** (sentence-transformers) are removed from the retrieval pipeline.
- Retrieval now relies **solely** on OpenKB's tree traversal.

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

---

## 4. Step-by-Step Integration & Migration Plan

### Phase 1: OpenKB Wiki Initialization & Configuration (Day 1-2)

**Goal:** Set up the OpenKB environment and validate the tree index generation.

**Steps:**
1.  **Install OpenKB**:
    ```bash
    pip install openkb
    # Ensure PageIndex is installed as a dependency
    ```
2.  **Initialize the Wiki Directory**:
    ```bash
    mkdir -p /data/openkb_wiki
    cd /data/openkb_wiki
    openkb init
    ```
3.  **Configure `config.yaml`** in the wiki root:
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
4.  **Test Compilation**: Add a sample 100-page PDF.
    ```bash
    openkb add sample_annual_report.pdf
    ```
5.  **Verify**: Check the `pages/` directory. Ensure the tree hierarchy is correctly generated.

---

### Phase 2: Eradicating Vector DB from Ingestion Pipeline (Day 3-5)

**Goal:** Remove ChromaDB and embedding generation logic entirely from `ingest.py`.

**Detailed Actions:**
1.  **Remove Dependencies**: Delete `chromadb`, `sentence-transformers`, and `langchain-vectorstores` from `requirements.txt`.
2.  **Rewrite `ingest.py`**:
    - **OLD Logic**: Parse PDF → Chunk → Generate Embeddings → Store in ChromaDB + SQLite.
    - **NEW Logic**: Parse PDF → Extract Text/Metadata → Call `openkb add` via subprocess or Python SDK.
3.  **Implement the Bridge**: Create `compilation_bridge.py`:
    - Listens to the `./raw` directory.
    - For each new PDF:
      a. Extract Ticker, Year, Document Type from filename.
      b. Run `openkb add {pdf_path}`.
      c. Run `openkb lint` to check for contradictions.
      d. Push extracted **structured tables** to the ETL API.
4.  **Drop SQLite Tables**: Remove the old vector metadata tables (do not drop the tables used by the business logic for ticker mapping, just the embedding-related ones).
5.  **Validation**: Run the pipeline on a batch of 50 documents. Ensure all are compiled into Wiki and no ChromaDB errors appear.

---

### Phase 3: Building the Query Intent Router (Day 6-8)

**Goal:** Replace the old "Hybrid Search" dispatcher with a new Intent Router. Since we have no Vector DB, we must classify queries to route between OpenKB (text) and ETL (numbers).

**Detailed Actions:**
1.  **Define Query Categories**:
    - `NUMERICAL`: "What was Q3 revenue?", "EBITDA for 2024".
    - `QUALITATIVE`: "Explain the business model", "What are the risks?".
    - `COMPARISON`: "Compare Company A and B margins" (Hybrid).
    - `AGGREGATION`: "Total revenue of tech sector" (ETL).
2.  **Implement `router.py`**:
    - Use a **rule-based regex** matcher for speed (sub-5ms) or a **small LLM (Groq-Llama-3.1-8b)** for complex disambiguation.
    - **Regex Rules**:
      - If contains `$`, `%`, `crore`, `million`, `revenue`, `profit`, `quarter` → `NUMERICAL`.
      - If contains `business`, `strategy`, `model`, `risk`, `competitor` → `QUALITATIVE`.
      - If contains multiple tickers (`and`, `vs`, `compare`) → `COMPARISON`.
3.  **Create Routing Decision Map**:
    ```json
    {
      "NUMERICAL": { "use_etl": true, "use_openkb": false },
      "QUALITATIVE": { "use_etl": false, "use_openkb": true },
      "HYBRID": { "use_etl": true, "use_openkb": true, "primary": "etl_filter_then_openkb" }
    }
    ```

---

### Phase 4: OpenKB Retriever Implementation (Day 9-11)

**Goal:** Replace the ChromaDB similarity search with the PageIndex reasoning search.

**Detailed Actions:**
1.  **Implement `retriever_openkb.py`**:
    - Method: `retrieve(question, top_k=5)`.
    - Call `openkb query "{question}" --json` via subprocess.
    - Parse the JSON output. OpenKB outputs page IDs, summaries, and relevance paths.
    - **Fallback Logic**: If `openkb query` times out (>10s) or returns empty, fallback to simple keyword search on the text files within the wiki.
2.  **Extract Metadata**:
    - Pull `source_file`, `page_number`, `section_title` from the result.
    - Store this in the `evidence` object for citations.
3.  **Performance Tuning**:
    - Set `max_depth` to 5 to prevent overly deep tree traversal.
    - Pre-load the wiki index into memory for faster subprocess response.

---

### Phase 5: ETL API Client Integration (Day 12-14)

**Goal:** Securely connect to the Quant_CoPilot-ETL API for structured data.

**Detailed Actions:**
1.  **Implement `etl_client.py`**:
    - `get_metric(ticker, metric, year, quarter)` → Calls `/api/v1/financials/metric`.
    - `get_trend(ticker, metric, quarters)` → Calls `/api/v1/financials/trend`.
    - `compare_peers(tickers, metric)` → Calls `/api/v1/financials/compare`.
2.  **Resilience Engineering**:
    - Implement **Circuit Breaker** (fail after 3 consecutive errors).
    - Implement **Retry with Backoff** (exponential: 1s, 2s, 4s).
    - Cache frequent ETL calls (e.g., "RELIANCE Revenue 2024") in Redis for 1 hour to avoid rate limits.
3.  **Validation**: Ensure the API returns exact numeric JSON. The LLM will use this directly without performing any calculations.

---

### Phase 6: Enhanced Fusion & Synthesis Engine (Day 15-18)

**Goal:** Combine results from OpenKB and ETL and generate the final answer. **No vector reranker** is needed now, but we keep the cross-encoder for ranking *text* evidence.

**Detailed Actions:**
1.  **Fuse Evidence**:
    - If `NUMERICAL`: Build context directly from ETL JSON + maybe a small snippet from OpenKB for context.
    - If `QUALITATIVE`: Use only OpenKB page texts.
    - If `HYBRID`: 
      1. Query ETL to get the list of qualifying tickers (e.g., "margin > 40%").
      2. Pass these tickers to OpenKB to fetch their business model pages.
2.  **Prompt Engineering** (Update `prompts.py`):
    - Create distinct prompts:
      - `PROMPT_NUMERICAL`: "You are given exact JSON data. State the numbers clearly. Do not recalculate."
      - `PROMPT_QUALITATIVE`: "Synthesize the following extracted pages from the annual report."
      - `PROMPT_HYBRID`: "Here are the financial filters (JSON) and the relevant business descriptions. Explain why these companies match the criteria."
3.  **Synthesis**:
    - Connect to Groq.
    - Generate the answer.
    - Attach metadata: `sources` (page numbers from OpenKB) and `data_sources` (ETL database tables).

---

### Phase 7: Semantic Caching Layer (Day 19-21)

**Goal:** To manage concurrency and reduce LLM costs without a vector DB, we implement a **Semantic Cache** using Redis (which internally uses vector search for similar queries).

**Detailed Actions:**
1.  **Setup Redis Stack** (Ensure the `redisearch` module is loaded).
2.  **Implement `semantic_cache.py`**:
    - **Embedding for Cache**: Use `all-MiniLM-L6-v2` *only* for caching lookups (this is a local, fast, small model used exclusively to check similarity, not for retrieval).
    - **Cache Lookup**:
      - Encode incoming query.
      - Query Redis Vector Index (`FT.SEARCH`) for similar queries.
      - If similarity > `0.92`, return the cached response (sub-100ms latency).
    - **Cache Store**:
      - Store the query, response, and embedding with a TTL of 24h.
3.  **Wiring**: Wrap the `EnhancedRAGEngine.query()` method with the cache check.

---

### Phase 8: Production Deployment & Zero-Downtime Cutover (Day 22-25)

**Goal:** Deploy to production and completely disable the old vector services.

**Detailed Actions:**
1.  **Dockerize**:
    - Create `Dockerfile` with OpenKB pre-installed.
    - Ensure the Wiki directory is mounted as a persistent volume.
2.  **Kubernetes Configuration**:
    - Deploy **OpenKB Retriever** as a Stateless Deployment.
    - Set `HPA (Horizontal Pod Autoscaler)` to scale based on `cpu` or `custom_qps`.
    - Load the entire OpenKB Wiki into a `emptyDir` or shared volume to ensure fast pod startup.
3.  **Traffic Switching**:
    - **Step 1**: Deploy the new service alongside the old one.
    - **Step 2**: Route 10% of traffic to the new OpenKB path. Monitor error rates and latency.
    - **Step 3**: If stable for 2 hours, ramp up to 100%.
    - **Step 4**: **Shut down** the ChromaDB container and the old embedding generation cron jobs.
4.  **Cleanup**: Delete the old ChromaDB persistent volumes to free up storage.

---

### Phase 9: Monitoring & Cost Observability (Day 26-27)

**Goal:** Set up dashboards to monitor the new architecture.

**Detailed Actions:**
1.  **Metrics to Track**:
    - `openkb_query_duration_seconds` (Alert if > 8s).
    - `etl_api_error_total` (Alert if > 5%).
    - `cache_hit_ratio` (Target > 40%).
    - `llm_token_consumption_total` (Monitor daily cost).
    - `pageindex_tree_depth` (Monitor average navigation depth).
2.  **Logging**: Ensure all queries and their routed paths are logged for auditing.
3.  **Alerting**:
    - PagerDuty alert if `cache_hit_ratio` drops below 20% (means cost is spiking).
    - Alert if OpenKB compilation fails for 3 consecutive documents.

---

## 5. Data Migration Strategy (Re-indexing)

Since we are eradicating the vector DB, we must re-compile all existing documents into the OpenKB Wiki.

**Strategy:**
1.  **Staging Dry Run**: In staging, run `openkb add` on the entire historical dataset (e.g., 5,000 PDFs).
2.  **Parallel Processing**: Use GNU `parallel` or Python `multiprocessing` to run 4-8 compilations simultaneously (OpenKB handles concurrency well).
3.  **Estimated Time**: ~30 seconds per PDF. For 5,000 PDFs, this takes ~40 hours. Run this over a weekend.
4.  **Verification**: Run `openkb lint` post-migration to identify any corrupted or blank pages and re-process them.

---

## 6. Handling Concurrency & High Latency (Production Readiness)

To ensure the system handles 100+ concurrent users effectively without the speed of vector search:

1.  **Horizontal Pod Autoscaling (HPA)**:
    - Since OpenKB is stateless, scale pods up to 20 replicas during peak hours.
    - Each pod holds the index in memory.
2.  **Request Batching**:
    - If the Router identifies a `NUMERICAL` query, it goes directly to ETL (sub-200ms).
    - Only `QUALITATIVE` and `HYBRID` hit the OpenKB cluster.
3.  **Streaming**:
    - Stream the PageIndex reasoning steps back to the user interface (e.g., "Navigating to Section 3.2... found relevant data...").
    - This improves perceived performance even if total wall-clock time is ~5-8 seconds.
4.  **Asynchronous Processing**:
    - For complex "Sector Analysis" queries, implement an async task queue (Celery). The user submits the job and receives a notification when complete.

---

## 7. Testing Checklist

| Test Category | Specific Test Cases | Pass Criteria |
| :--- | :--- | :--- |
| **Ingestion** | Add a 300-page PDF with complex tables. | Wiki generates tree with < 5% error rate. |
| **Numerical Query** | "What was Reliance's Q3 2024 EBITA?" | Returns exact number from ETL API, not a hallucination. |
| **Qualitative Query** | "Explain Jio's telecom strategy." | Retrieves the correct section from OpenKB. |
| **Hybrid Query** | "List software companies with > 20% margin and their AI strategy." | Correctly filters via ETL and retrieves descriptions via OpenKB. |
| **Caching** | Ask a query twice. | Second response time < 200ms. |
| **Fallback** | Take ETL API down. | System still returns an answer using OpenKB only. |
| **Latency (p95)** | Simulate 50 concurrent users. | Average latency < 6 seconds (without cache). |

---

## 8. Rollback Plan (Contingency)

While we are eradicating the vector DB, we must have a rollback strategy if OpenKB fails catastrophically.

1.  **Pre-rollback preparation**: Keep a backup of the last ChromaDB persistent volume for 1 month.
2.  **Rollback Triggers**:
    - Error rate for retrieval exceeds 15%.
    - Latency exceeds 20 seconds for more than 10% of requests.
3.  **Execution**:
    - Revert the `docker-compose` to the previous tag (which includes ChromaDB).
    - Point the Query Router back to the ChromaDB index.
    - Duration: < 10 minutes.

---

## 9. Timeline Summary

| Phase | Description | Effort | Days |
| :--- | :--- | :--- | :--- |
| **1** | OpenKB Setup & Initialization | 2 devs | 2 days |
| **2** | Eradicate Vector DB from Ingestion | 2 devs | 3 days |
| **3** | Query Intent Router | 1 dev | 3 days |
| **4** | OpenKB Retriever Implementation | 2 devs | 3 days |
| **5** | ETL API Client Integration | 1 dev | 3 days |
| **6** | Fusion & Synthesis Engine | 2 devs | 4 days |
| **7** | Semantic Caching (Redis) | 1 dev | 3 days |
| **8** | Production Deployment & Cutover | 2 devs | 4 days |
| **9** | Monitoring & Optimization | 1 dev | 2 days |
| **Total** | | | **~27 Days** |

---

## 10. Conclusion

This plan ensures a **complete, irreversible shift** away from vector databases. By eradicating ChromaDB, we simplify the architecture, eliminate chunking issues, and leverage the superior reasoning capabilities of OpenKB+PageIndex.

**The Final Stack:**
- **Text Retrieval:** OpenKB (Reasoning Tree) + PageIndex.
- **Number Retrieval:** Quant_CoPilot-ETL (SQL).
- **Cache:** Redis (Semantic).
- **Synthesis:** Groq API.

With the caching and scaling strategies outlined above, the system will maintain sub-6-second latency for 95% of uncached queries while providing financial-grade accuracy that vector search simply cannot match.
```