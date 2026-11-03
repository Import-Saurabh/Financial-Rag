import os
import sys
import time
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "backend")))
from backend.server import QueryRequest, _run_query

async def main():
    print("Pre-warming retriever & models...")
    from rag.retriever_openkb import FinancialRetriever
    FinancialRetriever()
    print("Pre-warm ready. Testing production queries:")

    q = "What was Apollo Micro Systems' revenue for FY2025-26?"
    print(f"Query: {q}")
    print("=" * 60)

    # Turn 1
    t0 = time.time()
    req = QueryRequest(query=q)
    resp = await _run_query(req)
    t1 = time.time() - t0
    print(f"[Turn 1] Latency: {t1:.2f}s | Pipeline Mode: {resp.get('pipeline_mode')}")

    # Turn 2 (Steady-State / In-Memory Warm)
    t0 = time.time()
    resp2 = await _run_query(req)
    t2 = time.time() - t0
    print(f"[Turn 2] Latency: {t2:.2f}s | Pipeline Mode: {resp2.get('pipeline_mode')}")
    print("=" * 60)
    print("ANSWER:")
    print(resp2.get("answer"))

if __name__ == "__main__":
    asyncio.run(main())
