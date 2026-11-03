"""
rag/fast_pipeline.py — High-Speed Parallel Scatter-Gather RAG Pipeline.
Delivers grounded financial analysis with sub-3-second latency (PageIndex style).
"""
from __future__ import annotations

import asyncio
import time
import logging
from typing import Dict, Any, Optional, List

from groq import AsyncGroq
from config.settings import GROQ_API_KEY
from agent.tools import get_financial_data, search_company_documents, get_live_price
from agent.entity_registry import resolve_entity, aresolve_entity

log = logging.getLogger(__name__)

# System prompt optimized for clear, grounded, WhatsApp-friendly financial synthesis
_FAST_SYSTEM_PROMPT = """\
You are an expert Indian Equity Research Assistant.
Your task is to answer the user's financial query using the verified data provided below.

Guidelines:
1. Grounding: Rely strictly on the provided financial metrics and document excerpts. Do not invent numbers.
2. Structure: Format with WhatsApp-friendly markdown:
   - Use *bold* for key numbers, metrics, and headings.
   - Use clean bullet points and small, concise text tables if comparing metrics.
3. Citations: Reference sources concisely, e.g., 【SQL】 for audited financials or 【SRC-1】 for concalls/reports.
4. Transparency: If a specific year or breakdown was requested but is not in the data, state it politely.
"""

_pipeline_instance: Optional[FastRAGPipeline] = None


class FastRAGPipeline:
    def __init__(self):
        self.groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
        # Using openai/gpt-oss-120b for high financial reasoning at ~1.5s single-shot
        self.model = "openai/gpt-oss-120b"

    async def execute_query(
        self,
        query: str,
        symbol: Optional[str] = None,
        doc_type: str = "both",
        year: Optional[int] = None,
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()
        loop = asyncio.get_event_loop()

        # 1. Resolve Entity
        ticker = symbol.upper() if symbol else None
        company_name = ticker or "the company"
        if not ticker:
            try:
                resolved = await aresolve_entity(query)
                if resolved:
                    ticker, company_name = resolved
            except Exception as e:
                log.warning(f"[fast_pipeline] Entity resolution error: {e}")

        # 2. Determine needed components
        q_lower = query.lower()
        is_price_query = any(w in q_lower for w in ["price", "cmp", "trading at", "quote", "52 week", "high", "low"])
        is_doc_only = any(w in q_lower for w in ["risk", "guidance", "management", "concall", "transcript", "strategy", "who is", "chairman"])
        is_sql_only = any(w in q_lower for w in ["ebitda", "pe ratio", "balance sheet", "cash flow", "roe", "roce"]) and not is_doc_only

        # 3. Parallel Scatter (Fetch relevant sources concurrently)
        tasks = []
        task_names = []

        def timed_call(fn, name):
            t_sub = time.perf_counter()
            res = fn()
            log.info(f"[fast_pipeline] Sub-task '{name}' completed in {time.perf_counter() - t_sub:.2f}s")
            return res

        if ticker:
            # Document search task
            if not is_sql_only:
                tasks.append(loop.run_in_executor(None, lambda: timed_call(lambda: search_company_documents.invoke({"symbols": [ticker], "query": query}), "docs")))
                task_names.append("docs")

            # Structured SQL financial data task
            if not is_doc_only:
                tasks.append(loop.run_in_executor(None, lambda: timed_call(lambda: get_financial_data.invoke({"symbols": [ticker], "metric_query": query}), "sql")))
                task_names.append("sql")

            # Live price task
            if is_price_query or "price" in q_lower:
                tasks.append(loop.run_in_executor(None, lambda: timed_call(lambda: get_live_price.invoke({"symbols": [ticker]}), "price")))
                task_names.append("price")
        else:
            # Fallback when no ticker detected: search documents broadly
            tasks.append(loop.run_in_executor(None, lambda: timed_call(lambda: search_company_documents.invoke({"symbols": [], "query": query}), "docs")))
            task_names.append("docs")

        # Run all data retrievals in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        docs_output = ""
        sql_output = ""
        price_output = ""

        for name, res in zip(task_names, results):
            if isinstance(res, Exception):
                log.error(f"[fast_pipeline] Error in {name} fetch: {res}")
                continue
            if name == "docs":
                docs_output = str(res)
            elif name == "sql":
                sql_output = str(res)
            elif name == "price":
                price_output = str(res)

        fetch_time = time.perf_counter() - t0
        log.info(f"[fast_pipeline] Parallel gather finished in {fetch_time:.2f}s (ticker={ticker})")

        # 4. Build prompt
        context_parts = []
        if price_output.strip() and "Error" not in price_output:
            context_parts.append(f"=== LIVE MARKET DATA ===\n{price_output.strip()}")
        if sql_output.strip() and "No structured financial data" not in sql_output and "Error" not in sql_output:
            context_parts.append(f"=== AUDITED FINANCIAL DATA (SQL) ===\n{sql_output.strip()}")
        if docs_output.strip() and "No relevant documents" not in docs_output and "Error" not in docs_output:
            context_parts.append(f"=== COMPANY FILINGS & CONCALL COMMENTARY ===\n{docs_output.strip()}")

        context_str = "\n\n".join(context_parts)
        if not context_str.strip():
            context_str = "No specific company reports or financial records were found for this query in the database."

        user_content = (
            f"User Query: {query}\n"
            f"Subject: {company_name} ({ticker if ticker else 'Unknown'})\n\n"
            f"{context_str}\n\n"
            "Synthesize a clear, accurate, and concise response for the user:"
        )

        # 5. Single-shot synthesis on Groq
        t_synth = time.perf_counter()
        if not self.groq_client:
            raise ValueError("GROQ_API_KEY is not set.")

        completion = await self.groq_client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _FAST_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            max_tokens=1000,
        )

        final_answer = completion.choices[0].message.content or ""
        total_time = round(time.perf_counter() - t0, 2)
        log.info(f"[fast_pipeline] Done: total_latency={total_time}s (synth={round(time.perf_counter()-t_synth, 2)}s)")

        from rag.rag_engine import _count_citations, _build_sources_list
        sources = _build_sources_list([], symbol=ticker)
        citations = _count_citations(final_answer, sources)

        return {
            "answer": final_answer,
            "model_used": f"{self.model} (Fast Parallel RAG)",
            "chunks_used": len(docs_output) // 500 if docs_output else 0,
            "sql_rows": 1 if sql_output else 0,
            "insights": 1 if (sql_output and docs_output) else 0,
            "latency_sec": total_time,
            "pipeline_mode": "fast_parallel",
            "sources": sources,
            "charts": [],
            "citations": citations,
        }


def get_fast_rag_pipeline() -> FastRAGPipeline:
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = FastRAGPipeline()
    return _pipeline_instance
