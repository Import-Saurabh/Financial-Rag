import requests
import json
import time

API_URL = "http://localhost:5000/query"
SYMBOL = "APOLLO"
YEAR = 2026

TEST_CASES = {
    "1. Basic factual retrieval": [
        "What was Apollo Micro Systems' revenue for FY2025-26?",
        "What was the company's net profit for FY2025-26?",
        "What was the EBITDA for FY2025-26?",
        "What was the total revenue from operations?",
        "What was the company's total assets at the end of FY2025-26?",
        "What was the EPS for FY2025-26?",
    ],
    "2. Year-over-year comparison": [
        "How did revenue change from FY2024-25 to FY2025-26?",
        "What was the percentage growth in revenue?",
        "How did net profit change year over year?",
    ],
    "3. Financial statement questions": [
        "What were Apollo Micro Systems' current assets and current liabilities?",
        "What was the company's operating cash flow?",
        "Did the company generate positive free cash flow?",
    ],
    "4. Profitability analysis": [
        "What was Apollo Micro Systems' gross profit margin?",
        "What was its operating profit margin?",
        "What was its ROE?",
    ],
    "5. Business / management discussion": [
        "What are Apollo Micro Systems' main business segments?",
        "What does management identify as the company's major growth opportunities?",
        "What major risks does management identify?",
    ],
    "6. Defence-related questions": [
        "What role does Apollo Micro Systems play in India's defence ecosystem?",
        "What defence products or systems does the company manufacture?",
    ],
    "7. Corporate governance": [
        "Who is the Chairman of Apollo Micro Systems?",
        "Who are the members of the Audit Committee?",
    ],
    "8. Multi-hop RAG tests": [
        "Revenue increased during FY2025-26. Did net profit increase at the same rate? Explain the difference.",
        "What happened to receivables and inventory, and what does this imply about the company's working-capital position?",
    ],
    "9. Numerical reasoning tests": [
        "What was Apollo Micro Systems' revenue growth percentage from FY2024-25 to FY2025-26?",
        "Calculate the difference between EBITDA and PAT for FY2025-26."
    ],
    "10. Citation / grounding tests": [
        "What was the company's revenue? Cite the exact page/table.",
        "According to the MD&A, what were the key growth drivers? Cite the relevant paragraph."
    ],
    "11. Negative / hallucination tests": [
        "What was Apollo Micro Systems' revenue in FY2027-28?",
        "How many missiles did Apollo Micro Systems manufacture in FY2025-26?"
    ],
    "12. Hardest test - cross-section synthesis": [
        "Analyze Apollo Micro Systems' FY2025-26 financial performance using revenue growth, EBITDA, PAT, margins, operating cash flow, debt, and working capital. Then connect these financial results with the company's order book, defence-sector strategy, growth opportunities, and risks mentioned in the annual report. Cite the specific sections/pages supporting each conclusion."
    ]
}

def run_tests():
    print("==================================================")
    print("🚀 STARTING RAG EVALUATION BENCHMARK")
    print(f"Target: {SYMBOL} (FY{YEAR})")
    print(f"Endpoint: {API_URL}")
    print("Provider: Groq (via backend config)")
    print("==================================================\n")

    results_md = "# RAG Evaluation Results\n\n"
    total_queries = sum(len(queries) for queries in TEST_CASES.values())
    current = 0

    for category, queries in TEST_CASES.items():
        print(f"\n## {category}")
        results_md += f"## {category}\n\n"
        
        for q in queries:
            current += 1
            print(f"[{current}/{total_queries}] Query: {q}")
            
            payload = {
                "query": q,
                "symbol": SYMBOL,
                "year": YEAR,
                "doc_type": "both",
                "provider": "groq-llama"
            }
            
            t0 = time.time()
            try:
                resp = requests.post(API_URL, json=payload, timeout=120)
                resp.raise_for_status()
                data = resp.json()
                answer = data.get("answer", "")
                model_used = data.get("model_used", "unknown")
                citations = data.get("citations", [])
                
                t1 = time.time()
                elapsed = round(t1 - t0, 2)
                
                print(f"  -> Done in {elapsed}s (Model: {model_used})")
                
                results_md += f"### Q: {q}\n"
                results_md += f"**Answer:** {answer}\n\n"
                results_md += f"*Model: {model_used} | Latency: {elapsed}s | Citations: {len(citations)}*\n\n"
                results_md += "---\n\n"
                
            except Exception as e:
                print(f"  -> ERROR: {e}")
                results_md += f"### Q: {q}\n"
                results_md += f"**ERROR:** {e}\n\n"
                results_md += "---\n\n"
                
    with open("rag_test_results.md", "w", encoding="utf-8") as f:
        f.write(results_md)
        
    print("\n✅ Benchmark complete! Results saved to rag_test_results.md")

if __name__ == "__main__":
    run_tests()
