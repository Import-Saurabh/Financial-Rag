import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from agent.graph import get_agent_graph

def run_test(query: str, symbol: str = None):
    print(f"\n{'='*50}\nTesting Query: '{query}' (Symbol: {symbol})\n{'='*50}")
    
    graph = get_agent_graph()
    
    initial_state = {
        "query": query,
        "symbol": symbol,
        "doc_type": "both",
        "provider": "auto",
        "year": None
    }
    
    try:
        result = graph.invoke(initial_state)
        print("\n--- AGENT STATE RESULTS ---")
        print(f"Intent: {result.get('intent')}")
        print(f"Extracted Symbols: {result.get('extracted_symbols')}")
        print(f"Needs SQL: {result.get('needs_sql')} | Needs Docs: {result.get('needs_docs')} | Live Price: {result.get('needs_live_price')}")
        print(f"Warnings: {result.get('warnings')}")
        print(f"Doc Chunks Retrieved: {len(result.get('doc_chunks', []))}")
        print(f"Live Price Data: {result.get('live_price_data')}")
        
        print("\n--- FINAL ANSWER ---")
        print(result.get('answer', 'No answer generated.'))
        
    except Exception as e:
        print(f"Error running test: {e}")

if __name__ == "__main__":
    # Test 1: The original bug (HAL query without HAL docs shouldn't pull Apollo docs)
    run_test("What is HAL's profit trend?", symbol="HAL")
    
    # Test 2: Live price query
    run_test("What is the current live price of RELIANCE?", symbol="RELIANCE")
