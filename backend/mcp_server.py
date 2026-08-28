"""
MCP Server for Financial-Rag API
================================
Exposes the FastAPI endpoints (financials, market, ownership, stocks)
as MCP tools so that AI assistants can call them.

Run:  python backend/mcp_server.py
Transport: stdio (default) – works with Cursor, Claude Desktop, etc.
"""

import json
import logging
import httpx
from mcp.server.mcpserver import MCPServer

# ── Configuration ────────────────────────────────────────────────────────────
API_BASE = "http://localhost:8000"
logger = logging.getLogger("mcp-financial-rag")

# ── MCP App ──────────────────────────────────────────────────────────────────
mcp = MCPServer(
    "Financial-RAG",
    description="Indian equity research tools – financials, market data, ownership & stock listings",
)

# ── Shared HTTP helper ───────────────────────────────────────────────────────

async def _get(path: str, params: dict | None = None) -> dict:
    """GET from the FastAPI backend and return JSON."""
    async with httpx.AsyncClient(base_url=API_BASE, timeout=30) as client:
        resp = await client.get(path, params={k: v for k, v in (params or {}).items() if v is not None})
        if resp.status_code != 200:
            return {"error": f"API Error {resp.status_code}", "detail": resp.text}
        return resp.json()


# ═══════════════════════════════════════════════════════════════════════════════
# FINANCIALS
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def get_profit_loss(
    symbol: str,
    period_type: str | None = None,
    consolidated: bool | None = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """
    Profit & Loss statements for a stock.

    Args:
        symbol: Stock ticker symbol (e.g. TCS, RELIANCE)
        period_type: annual | quarterly | ttm
        consolidated: True for consolidated statements
        limit: Max rows (1-100, default 20)
        offset: Pagination offset
    """
    data = await _get(
        f"/api/v1/stocks/{symbol}/profit-loss",
        {"period_type": period_type, "consolidated": consolidated, "limit": limit, "offset": offset},
    )
    return json.dumps(data, indent=2)


@mcp.tool()
async def get_profit_loss_items(
    symbol: str,
    period_type: str | None = None,
    period_end: str | None = None,
    parent_label: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    """
    Profit & Loss expandable sub-items (line-item detail).

    Args:
        symbol: Stock ticker symbol
        period_type: annual | quarterly | ttm
        period_end: Filter by period end date (YYYY-MM-DD)
        parent_label: Filter by parent line-item label
        limit: Max rows (1-500, default 100)
        offset: Pagination offset
    """
    data = await _get(
        f"/api/v1/stocks/{symbol}/profit-loss/items",
        {"period_type": period_type, "period_end": period_end, "parent_label": parent_label, "limit": limit, "offset": offset},
    )
    return json.dumps(data, indent=2)


@mcp.tool()
async def get_balance_sheet(
    symbol: str,
    period_type: str | None = None,
    consolidated: bool | None = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """
    Balance sheet statements for a stock.

    Args:
        symbol: Stock ticker symbol (e.g. TCS, RELIANCE)
        period_type: annual | quarterly
        consolidated: True for consolidated statements
        limit: Max rows (1-100, default 20)
        offset: Pagination offset
    """
    data = await _get(
        f"/api/v1/stocks/{symbol}/balance-sheet",
        {"period_type": period_type, "consolidated": consolidated, "limit": limit, "offset": offset},
    )
    return json.dumps(data, indent=2)


@mcp.tool()
async def get_balance_sheet_items(
    symbol: str,
    period_type: str | None = None,
    period_end: str | None = None,
    parent_label: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    """
    Balance sheet expandable sub-items (line-item detail).

    Args:
        symbol: Stock ticker symbol
        period_type: annual | quarterly
        period_end: Filter by period end date (YYYY-MM-DD)
        parent_label: Filter by parent line-item label
        limit: Max rows (1-500, default 100)
        offset: Pagination offset
    """
    data = await _get(
        f"/api/v1/stocks/{symbol}/balance-sheet/items",
        {"period_type": period_type, "period_end": period_end, "parent_label": parent_label, "limit": limit, "offset": offset},
    )
    return json.dumps(data, indent=2)


@mcp.tool()
async def get_cash_flow(
    symbol: str,
    period_type: str | None = None,
    consolidated: bool | None = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """
    Cash flow statements for a stock (CFO, CFI, CFF, capex, FCF).

    Args:
        symbol: Stock ticker symbol (e.g. TCS, RELIANCE)
        period_type: annual | quarterly | ttm
        consolidated: True for consolidated statements
        limit: Max rows (1-100, default 20)
        offset: Pagination offset
    """
    data = await _get(
        f"/api/v1/stocks/{symbol}/cash-flow",
        {"period_type": period_type, "consolidated": consolidated, "limit": limit, "offset": offset},
    )
    return json.dumps(data, indent=2)


@mcp.tool()
async def get_cash_flow_items(
    symbol: str,
    period_type: str | None = None,
    period_end: str | None = None,
    parent_label: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    """
    Cash flow expandable sub-items (line-item detail).

    Args:
        symbol: Stock ticker symbol
        period_type: annual | quarterly | ttm
        period_end: Filter by period end date (YYYY-MM-DD)
        parent_label: Filter by parent line-item label
        limit: Max rows (1-500, default 100)
        offset: Pagination offset
    """
    data = await _get(
        f"/api/v1/stocks/{symbol}/cash-flow/items",
        {"period_type": period_type, "period_end": period_end, "parent_label": parent_label, "limit": limit, "offset": offset},
    )
    return json.dumps(data, indent=2)


@mcp.tool()
async def get_quarterly_results(
    symbol: str,
    consolidated: bool | None = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """
    Quarterly results for a stock.

    Args:
        symbol: Stock ticker symbol (e.g. TCS, RELIANCE)
        consolidated: True for consolidated statements
        limit: Max rows (1-100, default 20)
        offset: Pagination offset
    """
    data = await _get(
        f"/api/v1/stocks/{symbol}/quarterly",
        {"consolidated": consolidated, "limit": limit, "offset": offset},
    )
    return json.dumps(data, indent=2)


@mcp.tool()
async def get_quarterly_items(
    symbol: str,
    period_end: str | None = None,
    parent_label: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    """
    Quarterly results expandable sub-items (line-item detail).

    Args:
        symbol: Stock ticker symbol
        period_end: Filter by period end date (YYYY-MM-DD)
        parent_label: Filter by parent line-item label
        limit: Max rows (1-500, default 100)
        offset: Pagination offset
    """
    data = await _get(
        f"/api/v1/stocks/{symbol}/quarterly/items",
        {"period_end": period_end, "parent_label": parent_label, "limit": limit, "offset": offset},
    )
    return json.dumps(data, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# MARKET
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def get_price(
    symbol: str,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 252,
    offset: int = 0,
) -> str:
    """
    Daily OHLCV price data for a stock.

    Args:
        symbol: Stock ticker symbol (e.g. TCS, RELIANCE)
        from_date: Start date YYYY-MM-DD
        to_date: End date YYYY-MM-DD
        limit: Max rows (1-2000, default 252 ≈ 1 trading year)
        offset: Pagination offset
    """
    data = await _get(
        f"/api/v1/stocks/{symbol}/price",
        {"from_date": from_date, "to_date": to_date, "limit": limit, "offset": offset},
    )
    return json.dumps(data, indent=2)


@mcp.tool()
async def get_technicals(
    symbol: str,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 252,
    offset: int = 0,
) -> str:
    """
    Technical indicators for a stock (RSI, MACD, Bollinger Bands, etc.).

    Args:
        symbol: Stock ticker symbol (e.g. TCS, RELIANCE)
        from_date: Start date YYYY-MM-DD
        to_date: End date YYYY-MM-DD
        limit: Max rows (1-2000, default 252)
        offset: Pagination offset
    """
    data = await _get(
        f"/api/v1/stocks/{symbol}/technicals",
        {"from_date": from_date, "to_date": to_date, "limit": limit, "offset": offset},
    )
    return json.dumps(data, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# OWNERSHIP
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def get_shareholding(
    symbol: str,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """
    Shareholding pattern for a stock (promoter / FII / DII / public breakdown).

    Args:
        symbol: Stock ticker symbol (e.g. TCS, RELIANCE)
        limit: Max rows (1-100, default 20)
        offset: Pagination offset
    """
    data = await _get(
        f"/api/v1/stocks/{symbol}/shareholding",
        {"limit": limit, "offset": offset},
    )
    return json.dumps(data, indent=2)


@mcp.tool()
async def get_corporate_actions(
    symbol: str,
    action_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """
    Corporate actions for a stock — dividends, splits, bonuses, etc.

    Args:
        symbol: Stock ticker symbol (e.g. TCS, RELIANCE)
        action_type: Filter by type: dividend | split | bonus
        limit: Max rows (1-200, default 50)
        offset: Pagination offset
    """
    data = await _get(
        f"/api/v1/stocks/{symbol}/corporate-actions",
        {"action_type": action_type, "limit": limit, "offset": offset},
    )
    return json.dumps(data, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# STOCKS
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def list_stocks(
    sector: str | None = None,
    exchange: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """
    List all available stocks in the database.

    Args:
        sector: Filter by sector (e.g. IT, Banking)
        exchange: Filter by exchange (NSE / BSE)
        limit: Max rows (1-500, default 50)
        offset: Pagination offset
    """
    data = await _get(
        "/api/v1/stocks",
        {"sector": sector, "exchange": exchange, "limit": limit, "offset": offset},
    )
    return json.dumps(data, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# GROWTH & MACRO (Added for internal RAG Pipeline)
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def get_growth_metrics(symbol: str, limit: int = 20) -> str:
    """Fetch CAGR and growth metrics for a stock."""
    data = await _get(f"/api/v1/stocks/{symbol}/growth", {"limit": limit})
    return json.dumps(data, indent=2)

@mcp.tool()
async def get_eps_trend(symbol: str, limit: int = 20) -> str:
    """Fetch EPS trends and revisions for a stock."""
    data = await _get(f"/api/v1/stocks/{symbol}/eps-trend", {"limit": limit})
    return json.dumps(data, indent=2)

@mcp.tool()
async def get_rbi_rates(limit: int = 20) -> str:
    """Fetch RBI repo rates and policy rates."""
    data = await _get("/api/v1/macro/rbi-rates", {"limit": limit})
    return json.dumps(data, indent=2)

@mcp.tool()
async def get_market_indices(index_name: str | None = None, limit: int = 20) -> str:
    """Fetch broad market index data."""
    data = await _get("/api/v1/macro/indices", {"index_name": index_name, "limit": limit})
    return json.dumps(data, indent=2)

@mcp.tool()
async def get_forex_commodities(instrument: str | None = None, limit: int = 20) -> str:
    """Fetch forex and commodity data."""
    data = await _get("/api/v1/macro/forex", {"instrument": instrument, "limit": limit})
    return json.dumps(data, indent=2)

@mcp.tool()
async def get_macro_indicators(indicator_name: str | None = None, limit: int = 20) -> str:
    """Fetch macroeconomic indicators (GDP, inflation, etc.)."""
    data = await _get("/api/v1/macro/indicators", {"indicator_name": indicator_name, "limit": limit})
    return json.dumps(data, indent=2)



# ── Entry point ──────────────────────────────────────────────────────────────
# Occupied ports (Docker): 8000, 8080, 8081, 3307, 9000
# MCP SSE port:            8100  (does NOT clash)
MCP_PORT = 8100

if __name__ == "__main__":
    import sys

    if "--sse" in sys.argv:
        # Run as SSE HTTP server on port 8100
        mcp.run(transport="sse", host="0.0.0.0", port=MCP_PORT)
    else:
        # Default: stdio transport (no port needed)
        mcp.run(transport="stdio")
