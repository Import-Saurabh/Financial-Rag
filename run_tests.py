import os
import sys
import time
import asyncio

# Ensure backend directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

from backend.server import QueryRequest, _run_query
import backend.config.settings as settings

queries = [
    "What was Apollo Micro Systems' revenue for FY2025-26?",
    "What was the company's net profit for FY2025-26?",
    "What was the EBITDA for FY2025-26?",
    "What was the total revenue from operations?",
    "What was the company's total assets at the end of FY2025-26?",
    "What was the EPS for FY2025-26?",
    "How did revenue change from FY2024-25 to FY2025-26?",
    "What was the percentage growth in revenue?",
    "How did net profit change year over year?",
    "What were Apollo Micro Systems' current assets and current liabilities?",
    "What was the company's operating cash flow?",
    "Did the company generate positive free cash flow?",
    "What was Apollo Micro Systems' gross profit margin?",
    "What was its operating profit margin?",
    "What was its ROE?",
    "What are Apollo Micro Systems' main business segments?",
    "What does management identify as the company's major growth opportunities?",
    "What major risks does management identify?",
    "What role does Apollo Micro Systems play in India's defence ecosystem?",
    "What defence products or systems does the company manufacture?",
    "Who is the Chairman of Apollo Micro Systems?",
    "Who are the members of the Audit Committee?",
    "Revenue increased during FY2025-26. Did net profit increase at the same rate? Explain the difference.",
    "What happened to receivables and inventory, and what does this imply about the company's working-capital position?",
    "What was Apollo Micro Systems' revenue growth percentage from FY2024-25 to FY2025-26?",
    "Calculate the difference between EBITDA and PAT for FY2025-26.",
    "What was the company's revenue? Cite the exact page/table.",
    "According to the MD&A, what were the key growth drivers? Cite the relevant paragraph.",
    "What was Apollo Micro Systems' revenue in FY2027-28?",
    "How many missiles did Apollo Micro Systems manufacture in FY2025-26?",
    "Analyze Apollo Micro Systems' FY2025-26 financial performance using revenue growth, EBITDA, PAT, margins, operating cash flow, debt, and working capital. Then connect these financial results with the company's order book, defence-sector strategy, growth opportunities, and risks mentioned in the annual report. Cite the specific sections/pages supporting each conclusion."
]

def run_tests():
    print("Starting tests...\n")
    
    with open("rag_test_results_v2.md", "w", encoding="utf-8") as f:
        f.write("# RAG Evaluation Results (V2)\n\n")
        
        for i, q in enumerate(queries, 1):
            print(f"Running Q{i}/31: {q}")
            start_t = time.time()
            
            try:
                req = QueryRequest(query=q)
                resp = _run_query(req)
                
                latency = time.time() - start_t
                
                f.write(f"### Q{i}: {q}\n")
                f.write(f"**Answer:**\n{resp.get('answer', 'ERROR')}\n\n")
                
                citations = resp.get('citations', 0)
                model_used = resp.get('model_used', 'Unknown')
                f.write(f"*Model: {model_used} | Latency: {latency:.2f}s | Citations: {citations}*\n\n")
                f.write("---\n\n")
                f.flush()
                
            except Exception as e:
                latency = time.time() - start_t
                f.write(f"### Q{i}: {q}\n")
                f.write(f"**ERROR:** {e}\n\n")
                f.write(f"*Latency: {latency:.2f}s*\n\n")
                f.write("---\n\n")
                f.flush()
                print(f"  Error: {e}")
                
            time.sleep(12)  # Pause to respect Groq TPM rate limits

if __name__ == "__main__":
    run_tests()
