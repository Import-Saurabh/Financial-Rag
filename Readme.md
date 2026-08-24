# Financial RAG — Equity Research System (v4.0)

A completely vector-free financial RAG system, leveraging OpenKB + PageIndex for qualitative document reasoning, and Quant_CoPilot ETL for structured numerical data.

## Stack
| Component | Tool |
|---|---|
| Document Knowledge | OpenKB + PageIndex (Tree-based retrieval) |
| Numerical Knowledge | Quant_CoPilot ETL API (Pure SQL) |
| Metadata / Ingestion DB | MySQL |
| PDF Storage | MinIO |
| LLM Synthesis | Groq API (llama-3.3-70b) / OpenRouter |
| Cache | Redis (Exact/Structured-Key Cache) |

## Architecture

```text
                         USER QUERY
                             │
                             ▼
                    API Gateway / Router
                             │
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
       STRUCTURED QUERY              DOCUMENT QUERY
              │                             │
              ▼                             ▼
     Quant_CoPilot ETL API                OpenKB
              │                             │
              ▼                             ▼
           MySQL                       PageIndex
              │                             │
              ▼                             ▼
      Financial Evidence             Document Evidence
              │                             │
              └──────────────┬──────────────┘
                             ▼
                      Evidence Fusion
                             │
                             ▼
                   Evidence Verification
                             │
                             ▼
                   Financial LLM Reasoner
                             │
                             ▼
                    Answer + Citations
```

This target architecture removes all vector databases and embeddings. It utilizes atomic decomposition to route queries through a gateway: routing numerical questions to an ETL API (SQL) and qualitative document reasoning to OpenKB (tree search). By executing parallel retrievals and using a dedicated Fusion Layer to cross-reference quantitative stats with qualitative narratives, the system ensures high-fidelity attribution without the semantic hallucinations typical of vector search.

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set environment variables in .env
# Example: GROQ_API_KEY, MySQL, MinIO, Redis configurations

# 3. Ingest documents via OpenKB
python compilation_bridge.py --symbol RELIANCE

# 4. Start the query server
python server.py

# 5. Execute queries using the client
python query_client.py --symbol RELIANCE "What is the revenue growth trend over last 3 years?"
```