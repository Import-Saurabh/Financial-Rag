# High-Level Design (HLD) - Financial RAG Platform

## 1. Introduction
The Financial RAG Platform is designed to answer complex financial queries by fusing qualitative text from earning calls/annual reports with hard quantitative data from SQL databases. 

## 2. Core Architecture Philosophy
To avoid the traditional pitfalls of "wall-of-text" Vector RAG systems, this platform employs **Structurally Selective Routing**. Rather than indiscriminately passing dozens of chunks to an LLM, the system leverages document hierarchies (e.g., specific sections of an Annual Report like "MD&A" or "Risk Factors") to narrow the search space *before* the expensive generation step.

## 3. High-Level Pipeline (The "Fast-Path")

1. **Query Router / Intent Decomposition**
   - The user query is analyzed to determine if it requires quantitative data (SQL), qualitative data (Text), or both.
2. **Parallel Retrieval**
   - **Quantitative (SQL/RDB):** The Schema Bridge calls out to an AWS Lambda API to fetch hard financial metrics (e.g., EBITDA, Revenue).
   - **Qualitative (Structurally Selective Tree Search):** Instead of retrieving 40 independent chunks from a flattened document, the system filters by *Document Type* and *Section Type*. It selects only the most relevant nodes/sections.
3. **Cross-Encoder Verification (Optional/Targeted)**
   - A PyTorch Cross-Encoder (`ms-marco-MiniLM-L-6-v2`) re-ranks a tightly constrained candidate pool (max 15 chunks) to ensure high precision without bottlenecking the CPU.
4. **Fusion & Context Building**
   - A diversity cap restricts the number of chunks from any single document section to 2. This creates a dense, diverse prompt (max 5-10 chunks) rather than a bloated one.
5. **LLM Synthesis**
   - The minimized prompt is sent to the LLM (DeepSeek / Groq), drastically reducing Time-To-First-Token (TTFT) and generating the final answer in ~3.5 seconds.

## 4. Performance Benchmarks
- **Average Total Latency:** ~6.5 seconds (post-cold start).
- **Retrieval & Structural Routing:** ~0.5s
- **SQL Data Fetch:** ~0.5s
- **Reranking:** ~0.5s
- **LLM Generation:** ~3.5 - 5.0s

This targeted, tree-aware retrieval makes the pipeline faster and more accurate than brute-force chunk retrieval systems (like PageIndex Chat AI).
