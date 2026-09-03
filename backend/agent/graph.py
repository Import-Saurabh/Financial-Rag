"""
agent/graph.py — Native Tool-Calling LLM Agent (ReAct)
"""

import logging
from langgraph.prebuilt import create_react_agent
from langchain_groq import ChatGroq

from agent.tools import get_live_price, get_financial_data, search_company_documents

log = logging.getLogger(__name__)

# System prompt that governs the agent's behavior
_SYSTEM_PROMPT = """\
You are an expert Indian Equity Research Assistant. Your job is to answer the user's financial queries by autonomously utilizing the tools provided to you.

You have access to three tools:
1. `get_financial_data`: Use this to get structured numbers (revenue, profit, EBITDA, margins, etc.) from the SQL database.
2. `search_company_documents`: Use this to get qualitative management commentary, outlook, and guidance from Annual Reports and Concalls.
3. `get_live_price`: Use this to get the real-time stock price and day change.

Rules:
- ALWAYS extract the correct stock symbol (e.g., HAL, RELIANCE, TCS) from the user's query and pass it to the tools.
- You can call multiple tools if needed (e.g., fetch both SQL data and qualitative docs to build a comprehensive answer).
- If the user asks for "current price", use `get_live_price`.
- Synthesize the final answer beautifully using markdown tables, bullet points, and clear headings based on the data the tools return.
- If a tool returns an error or no data, politely inform the user that the specific data is unavailable, but use whatever data you DO have.
"""

_compiled_agent = None

def get_agent_graph():
    """Build and return the LangChain ReAct agent."""
    global _compiled_agent
    
    if _compiled_agent is None:
        from config.settings import GROQ_API_KEY
        
        if not GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is not set. Cannot initialize Tool-Calling Agent.")
            
        # Initialize the ChatGroq model (requires tool-calling support, openai/gpt-oss-120b or openai/gpt-oss-20b)
        # Using 8b-instant for speed or 70b if available.
        # Let's use 3.1-8b-instant since it was working in our previous test.
        llm = ChatGroq(
            api_key=GROQ_API_KEY,
            model="openai/gpt-oss-20b",
            temperature=0.0,
            max_retries=2
        )
        
        tools = [get_live_price, get_financial_data, search_company_documents]
        
        # create_react_agent wires up the internal Thought->Action->Observation loop
        _compiled_agent = create_react_agent(
            llm, 
            tools=tools, 
            prompt=_SYSTEM_PROMPT
        )
        log.info("[agent] Native Tool-Calling ReAct Agent initialized successfully.")
        
    return _compiled_agent
