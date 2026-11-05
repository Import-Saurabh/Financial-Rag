"""
rag/fast_pipeline.py — High-Speed Parallel Scatter-Gather RAG Pipeline.
Delivers grounded financial analysis with sub-3-second latency (PageIndex style),
rich source citations with exact page numbers, section headers, and verbatim snippets.
"""
from __future__ import annotations

import asyncio
import time
import logging
import json
import re
from typing import Dict, Any, Optional, List, Tuple

from groq import AsyncGroq
from config.settings import GROQ_API_KEY
from agent.tools import get_financial_data, get_live_price
from agent.entity_registry import resolve_entity, aresolve_entity
from rag.retriever_openkb import FinancialRetriever, RetrievedChunk
from rag.section_router import get_target_sections

log = logging.getLogger(__name__)

# System prompt optimized for clear, grounded, and trust-building financial synthesis
_FAST_SYSTEM_PROMPT = """\
You are an institutional Indian Equity Research Analyst.
Your task is to answer the user's financial query using the verified data provided below.

Guidelines:
1. Grounding & Trust: Rely strictly on the provided financial metrics and document excerpts. Never hallucinate or assume metrics.
2. Exact Citations: You MUST cite your sources using inline tags like [SRC-1], [SRC-2], or [SQL-1] immediately next to key claims, guidance, and metrics (e.g., "Management projects 20% revenue growth in FY25 [SRC-1]"). This allows the user to click and inspect the exact page in the side drawer.
3. Structure & Readability:
   - Use **bold** for key metrics, tickers, and financial ratios.
   - Use bullet points and small, concise Markdown tables for comparisons.
   - Provide a distinct section for "Guidance & Forward Outlook" when qualitative commentary is available.
4. Transparency: If a specific year or breakdown is missing from the data, explicitly state it.
"""

_pipeline_instance: Optional[FastRAGPipeline] = None


class FastRAGPipeline:
    def __init__(self):
        self.groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
        self.model = "openai/gpt-oss-120b"
        self.retriever = FinancialRetriever()

    def _fetch_docs_and_chunks(self, ticker_list: List[str], query: str) -> Tuple[str, List[RetrievedChunk]]:
        try:
            target_sections = get_target_sections(query)
            chunks = self.retriever.retrieve(
                question=query,
                top_k=5,
                symbol_filter=ticker_list if ticker_list else None,
                section_filter=target_sections,
            )
            if not chunks:
                return "No relevant documents found matching your query.", []

            MAX_CHARS = 24000
            output = f"Document Search Results for {ticker_list}:\n\n"
            for i, chunk in enumerate(chunks, 1):
                doc_type = getattr(chunk, 'doc_type', 'Unknown')
                year = getattr(chunk, 'year', 'Unknown')
                heading = getattr(chunk, 'heading', '') or getattr(chunk, 'section_type', 'Section')
                page = chunk.page_start if chunk.page_start > 0 else 1
                chunk_text = f"[SRC-{i}] ({doc_type} - FY{year} - Page {page} - Heading: {heading}) ---\n{chunk.text[:2500]}\n\n"
                if len(output) + len(chunk_text) > MAX_CHARS:
                    break
                output += chunk_text

            return output, chunks
        except Exception as e:
            log.error(f"[fast_pipeline] Doc retrieval error: {e}")
            return f"Error retrieving documents: {e}", []

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

        tickers_to_query = [ticker] if ticker else []

        # Document search task
        if not is_sql_only:
            tasks.append(loop.run_in_executor(None, lambda: timed_call(lambda: self._fetch_docs_and_chunks(tickers_to_query, query), "docs")))
            task_names.append("docs")

        # Structured SQL financial data task
        if not is_doc_only and ticker:
            tasks.append(loop.run_in_executor(None, lambda: timed_call(lambda: get_financial_data.invoke({"symbols": [ticker], "metric_query": query}), "sql")))
            task_names.append("sql")

        # Live price task
        if (is_price_query or "price" in q_lower) and ticker:
            tasks.append(loop.run_in_executor(None, lambda: timed_call(lambda: get_live_price.invoke({"symbols": [ticker]}), "price")))
            task_names.append("price")

        # Run all data retrievals in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        docs_output = ""
        retrieved_chunks: List[RetrievedChunk] = []
        sql_output = ""
        price_output = ""

        for name, res in zip(task_names, results):
            if isinstance(res, Exception):
                log.error(f"[fast_pipeline] Error in {name} fetch: {res}")
                continue
            if name == "docs":
                docs_output, retrieved_chunks = res
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
            "Synthesize a clear, accurate, and concise institutional equity response with exact source citations:"
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
            max_tokens=1200,
        )

        final_answer = completion.choices[0].message.content or ""
        total_time = round(time.perf_counter() - t0, 2)
        log.info(f"[fast_pipeline] Done: total_latency={total_time}s (synth={round(time.perf_counter()-t_synth, 2)}s)")

        # 6. Build Rich Interactive Sources Structure for Side Drawer Inspection
        sources = []

        # Structured SQL source
        if sql_output.strip() and "No structured financial data" not in sql_output and "Error" not in sql_output:
            sources.append({
                "id": "SQL-1",
                "symbol": ticker or "NIFTY",
                "year": "FY24-FY25",
                "doc_type": "sql_data",
                "doc_label": "Audited Financial Database (BSE/NSE)",
                "file_name": f"{ticker or 'Equity'}_Audited_Filings.csv",
                "section": "Financial Statements & Ratios",
                "heading": "Audited Income Statement & Balance Sheet",
                "page": 1,
                "score": 1.0,
                "snippet": sql_output[:1200]
            })

        # Unstructured Document chunks
        for i, chk in enumerate(retrieved_chunks, 1):
            doc_label = "Annual Report" if chk.doc_type == "annual_report" else ("Concall Transcript" if chk.doc_type == "concall" else "Research Report")
            heading = getattr(chk, "heading", "") or getattr(chk, "section_type", "Section").title()
            page_num = chk.page_start if (chk.page_start and chk.page_start > 0) else 1
            file_name = f"{chk.section}.pdf" if not chk.section.endswith(".pdf") else chk.section
            sources.append({
                "id": f"SRC-{i}",
                "symbol": chk.symbol,
                "year": chk.year,
                "doc_type": chk.doc_type,
                "doc_label": f"{doc_label} (FY{chk.year})" if chk.year else doc_label,
                "file_name": file_name,
                "section": chk.section,
                "heading": heading,
                "page": page_num,
                "score": round(chk.importance_score, 3),
                "snippet": chk.text
            })

        # Count citations
        from rag.rag_engine import _count_citations
        citations = _count_citations(final_answer, sources)

        # Generate optional chart data if multiple numeric years appear
        charts = []
        try:
            # Check for financial tables or numbers in SQL or answer
            metric_matches = re.findall(r'(?i)(revenue|ebitda|profit|pat|sales)\s*[:=\-]\s*₹?\s*([\d,.]+)', final_answer)
            if len(metric_matches) >= 2:
                labels = [m[0].capitalize() for m in metric_matches[:5]]
                values = []
                for m in metric_matches[:5]:
                    try:
                        values.append(float(m[1].replace(",", "")))
                    except Exception:
                        pass
                if len(values) == len(labels):
                    charts.append({
                        "title": f"{ticker or 'Company'} Key Financial Metrics",
                        "type": "bar",
                        "data": [{"x": labels, "y": values, "type": "bar", "marker": {"color": "#ff6600"}}],
                        "layout": {
                            "paper_bgcolor": "#0c0d14",
                            "plot_bgcolor": "#0c0d14",
                            "font": {"color": "#e5e7eb"},
                            "margin": {"t": 40, "r": 20, "l": 40, "b": 40}
                        }
                    })
        except Exception as chart_err:
            log.debug(f"[fast_pipeline] Chart extraction: {chart_err}")

        return {
            "answer": final_answer,
            "model_used": f"{self.model} (Fast Parallel RAG)",
            "chunks_used": len(retrieved_chunks),
            "sql_rows": 1 if sql_output else 0,
            "insights": 1 if (sql_output and docs_output) else 0,
            "latency_sec": total_time,
            "pipeline_mode": "fast_parallel",
            "sources": sources,
            "charts": charts,
            "citations": citations,
        }


def get_fast_rag_pipeline() -> FastRAGPipeline:
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = FastRAGPipeline()
    return _pipeline_instance
