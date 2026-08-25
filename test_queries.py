import asyncio
import aiohttp
import time
import json
import os

QUERIES = [
    "What were the primary revenue drivers for Apollo Microsystems in FY25?",
    "How did the order book of Apollo Microsystems change between FY24 and FY25?",
    "What are the major supply chain challenges mentioned by Apollo's management?",
    "Detail the defense segment growth for Apollo Microsystems in the recent concall.",
    "Did Apollo Microsystems give any revenue guidance for FY26?",
    "What are Apollo Microsystems' capital expenditure plans for FY25 and FY26?",
    "How has the EBITDA margin of Apollo Microsystems trended recently?",
    "Summarize management's views on working capital requirements.",
    "What specific defense contracts did Apollo Microsystems win in FY25?",
    "What is the total order book value as of FY25 end?",
    "Are there any capacity expansion plans discussed in the 2026 concall?",
    "What is Apollo Microsystems' R&D spending strategy?",
    "Did management comment on any export opportunities?",
    "What are the key risks highlighted in Apollo's FY25 annual report?",
    "How is Apollo Microsystems funding its expansion?",
    "What was the dividend payout for Apollo Microsystems in FY25?",
    "What is the management's commentary on raw material price inflation?",
    "Are there any joint ventures or partnerships mentioned recently?",
    "What is the revenue breakdown between aerospace, defense, and space segments?",
    "How does Apollo Microsystems plan to improve its EBITDA margins?",
    "What was the free cash flow for Apollo Microsystems in FY25?",
    "Did the company face any execution delays in FY25?",
    "What is the management's perspective on the Make in India initiative?",
    "How has the employee headcount changed in FY25?",
    "What are the key technological advancements mentioned in the R&D section?",
    "Are there any changes in the senior management or board of directors?",
    "What is the debt-to-equity ratio as of FY25?",
    "What were the highlights of Apollo's Q4 FY26 concall?",
    "How is Apollo Microsystems managing its inventory levels?",
    "What are the long-term strategic goals for Apollo Microsystems?"
]

RESULTS_FILE = r"C:\Users\hp\.gemini\antigravity\brain\08fd438e-bc55-42d3-be6d-1ab57919cdd4\apollo_queries_results.md"

async def run_query(session, query, index):
    payload = {
        "query": query,
        "symbol": "APOLLO",
        "doc_type": "both",
        "provider": "auto"
    }
    start = time.time()
    try:
        async with session.post("http://127.0.0.1:5000/query", json=payload, timeout=60) as resp:
            data = await resp.json()
            ans = data.get("answer", "")
            elapsed = time.time() - start
            print(f"[{index}/30] SUCCESS ({elapsed:.2f}s) | Q: {query[:40]}...")
            return {"q": query, "a": ans, "time": elapsed}
    except Exception as e:
        elapsed = time.time() - start
        print(f"[{index}/30] FAILED ({elapsed:.2f}s) | Q: {query[:40]}... | Error: {e}")
        return {"q": query, "a": f"ERROR: {str(e)}", "time": elapsed}

async def main():
    print(f"Starting execution of {len(QUERIES)} production-grade queries for Apollo Microsystems...")
    start_time = time.time()
    
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        f.write("# Apollo Microsystems - 30 Production-Grade Queries\n\n")
        f.write("This document contains the output of 30 complex financial queries run through the new OpenKB + PageIndex RAG architecture.\n\n")

    async with aiohttp.ClientSession() as session:
        semaphore = asyncio.Semaphore(5)
        
        async def sem_task(q, i):
            async with semaphore:
                return await run_query(session, q, i)
        
        tasks = [sem_task(q, i+1) for i, q in enumerate(QUERIES)]
        results = await asyncio.gather(*tasks)
    
    # Save all results to markdown
    with open(RESULTS_FILE, "a", encoding="utf-8") as f:
        for res in results:
            if res:
                f.write(f"### Q: {res['q']}\n")
                f.write(f"**Time:** {res['time']:.2f}s\n\n")
                f.write(f"**Answer:**\n{res['a']}\n\n")
                f.write("---\n\n")
    
    total_time = time.time() - start_time
    success_count = sum(1 for r in results if not r['a'].startswith('ERROR'))
    print(f"\nCompleted! {success_count}/{len(QUERIES)} succeeded in {total_time:.2f} seconds.")

if __name__ == "__main__":
    asyncio.run(main())
