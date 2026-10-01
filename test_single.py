import os
import sys
import time
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))
from backend.server import QueryRequest, _run_query

async def main():
    q = "What was Apollo Micro Systems' revenue for FY2025-26?"
    print(f"Running: {q}")
    start_t = time.time()
    req = QueryRequest(query=q)
    resp = await _run_query(req)
    latency = time.time() - start_t
    print(f"Answer: {resp.get('answer')[:100]}...")
    print(f"Latency: {latency:.2f}s")

if __name__ == "__main__":
    asyncio.run(main())
