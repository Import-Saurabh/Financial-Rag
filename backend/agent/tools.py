"""
tools.py — The toolbox for our native Tool-Calling LLM.
"""

from typing import List, Optional
from langchain_core.tools import tool
import logging

log = logging.getLogger(__name__)

@tool
def get_live_price(symbols: List[str]) -> str:
    """
    Fetches the live, real-time market price and basic statistics for one or more stock symbols or indices.
    Use this ONLY when the user asks for current price, live price, or today's market performance.
    Do NOT use this for historical metrics like profit, revenue, or margins.
    
    Args:
        symbols: A list of stock symbols (e.g., ["RELIANCE", "HAL"]) or indices.
    """
    log.info(f"[tools] get_live_price invoked for {symbols}")
    
    # We call the exact same MCP yfinance tool logic we added earlier
    try:
        import yfinance as yf
        results = []
        for sym in symbols:
            ticker_str = f"{sym}.NS" if not sym.startswith("^") else sym
            try:
                ticker = yf.Ticker(ticker_str)
                info = ticker.info
                current = info.get("currentPrice") or info.get("regularMarketPrice", 0)
                prev = info.get("previousClose") or info.get("regularMarketPreviousClose", 1)
                
                results.append({
                    "symbol": sym,
                    "current_price": current,
                    "previous_close": prev,
                    "day_change_pct": round((current - prev) / prev * 100, 2) if prev else None,
                    "52_week_high": info.get("fiftyTwoWeekHigh"),
                    "52_week_low": info.get("fiftyTwoWeekLow"),
                    "market_cap": info.get("marketCap"),
                })
            except Exception as e:
                results.append({"symbol": sym, "error": str(e)})
                
        # Format as a clean string for the LLM
        output = "Live Market Data Results:\n"
        for r in results:
            if "error" in r:
                output += f"- {r['symbol']}: Error fetching data ({r['error']})\n"
            else:
                output += (
                    f"- {r['symbol']}: ₹{r['current_price']} "
                    f"(Day Change: {r['day_change_pct']}%, "
                    f"52W High: {r['52_week_high']}, "
                    f"52W Low: {r['52_week_low']})\n"
                )
        return output
    except Exception as e:
        return f"Error fetching live prices: {str(e)}"


@tool
def get_financial_data(symbols: List[str], metric_query: str) -> str:
    """
    Fetches quantitative, structured financial data from the SQL database for given companies.
    Use this to get revenue, profit, EBITDA, margins, ratios, balance sheets, and cash flows.
    
    Args:
        symbols: List of stock symbols (e.g., ["HAL", "TCS"]). If comparing multiple, include all.
        metric_query: The specific metrics you want (e.g., "net profit for FY23 and FY24" or "revenue trend").
    """
    log.info(f"[tools] get_financial_data invoked for {symbols} with query: {metric_query}")
    
    try:
        from rag.rag_engine import _get_synthesis_pipeline
        pipeline = _get_synthesis_pipeline()
        
        # If multiple symbols, just use the first one for the primary symbol
        # The pipeline handles dynamic atomic dispatch internally
        primary_symbol = symbols[0] if symbols else None
        
        # The synthesis pipeline requires `query` to figure out what data to extract
        result = pipeline.run(
            query=metric_query,
            chunks=[], # We are not passing vector chunks here, this is pure SQL synthesis
            symbol=primary_symbol,
            explicit_years=None
        )
        
        # We return the markdown representation of the SQL data fetched
        if not result.markdown_context.strip():
            return "No structured financial data was found for this query."
            
        return result.markdown_context
    except Exception as e:
        log.error(f"[tools] get_financial_data error: {e}")
        return f"Error retrieving financial data: {e}"


@tool
def search_company_documents(symbols: List[str], query: str) -> str:
    """
    Searches unstructured textual documents (Annual Reports, Concall Transcripts, Management Commentary) 
    for qualitative insights, strategy, guidance, and management outlook.
    Use this when the user asks 'why' something happened, or asks for management's view, strategy, or guidance.
    
    Args:
        symbols: List of stock symbols to filter by (e.g., ["HAL"]). This ensures you only get docs for this company.
        query: What to search for inside the documents (e.g., "defense order book outlook").
    """
    log.info(f"[tools] search_company_documents invoked for {symbols} with query: {query}")
    
    try:
        from rag.retriever_openkb import OpenKBRetriever
        retriever = OpenKBRetriever()
        
        # Retrieve chunks, explicitly passing the symbols to prevent cross-pollination
        chunks = retriever.retrieve(
            question=query, 
            top_k=5, 
            symbol_filter=symbols if symbols else None
        )
        
        if not chunks:
            return f"No relevant documents found for {symbols} matching your query."
            
        # Format the retrieved chunks for the LLM
        output = f"Document Search Results for {symbols}:\n\n"
        for i, chunk in enumerate(chunks, 1):
            doc_type = getattr(chunk, 'doc_type', 'Unknown')
            year = getattr(chunk, 'year', 'Unknown')
            output += f"--- Source {i} ({doc_type} - {year}) ---\n"
            output += f"{chunk.text}\n\n"
            
        return output
    except Exception as e:
        log.error(f"[tools] search_company_documents error: {e}")
        return f"Error retrieving documents: {e}"

