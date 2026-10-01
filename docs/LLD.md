# Low-Level Design (LLD) - Financial RAG Platform

## 1. Component: Atomic Decomposer (`backend/rag/rag_engine.py`)
- **Responsibility:** Parses the raw user query into `SqlAtom` and `VectorAtom` objects.
- **Logic:** Uses regex and NLP to detect specific financial metrics and time periods. It assigns expected document sections to the `VectorAtom` (e.g., if the user asks about risks, it targets the "Risk Factors" section).

## 2. Component: OpenKB Retriever (`backend/rag/retriever_openkb.py`)
- **Responsibility:** Executes the structurally selective retrieval.
- **Index Structure:** Documents are not just flat text; they are indexed with metadata: `doc_type`, `year`, `section_type`, and `heading`.
- **Execution Flow:**
  1. **BM25 & FAISS Hybrid Search:** Quickly computes cosine similarity using `all-MiniLM-L6-v2` against the constrained sections.
  2. **Candidate Capping:** Sorts by hybrid score and aggressively truncates the pool to **15 candidates** (down from 40).
  3. **Cross-Encoder Reranking:** Passes the 15 candidates through the `cross-encoder/ms-marco-MiniLM-L-6-v2` model. This reduces CPU load by 62% compared to the old 40-candidate approach.

## 3. Component: Fusion Layer (`backend/fusion/fusion_layer.py`)
- **Responsibility:** Merges SQL data and vector chunks, checks for contradictions, and enforces structural diversity.
- **Diversity Cap (`_MAX_CHUNKS_PER_SECTION = 2`):**
  - Iterates through the top-ranked chunks.
  - Keeps a counter for each `section_key` (e.g., "APOLLO_2025_Annual_RiskFactors").
  - Discards chunks if that section already has 2 chunks represented.
  - Ensures the final prompt doesn't get flooded with repetitive tables from the same disclosure.

## 4. Component: Prompt Builder (`backend/synthesis/prompt_builder.py`)
- **Responsibility:** Assembles the final string for the LLM.
- **Budgeting:** Calculates a dynamic `chunk_budget` based on the LLM's token limit (e.g., `_DEFAULT_MAX_CHARS = 80,000`). Because the fusion layer now passes far fewer chunks, the prompt string is naturally dense and well under the budget.

## 5. Component: LLM Agent / Orchestrator (`backend/server.py` & `backend/agent/graph.py`)
- **Responsibility:** Manages API communication and rate limits.
- **Handling 429 / 413 Errors:** 
  - The ReAct agent (Groq) is configured with `max_retries=0`. If the user hits a TPM limit, the `ainvoke` fails instantly.
  - `server.py` intercepts this exception in a `try/except` block and automatically routes the query to the legacy pipeline (`generate_answer()`) which uses DeepSeek.
  - DeepSeek operates flawlessly on the smaller, structurally selective prompt in ~3.5 seconds.
