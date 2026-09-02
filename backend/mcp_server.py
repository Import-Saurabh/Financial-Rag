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
from mcp.server.fastmcp import FastMCP

# ── Configuration ────────────────────────────────────────────────────────────
API_BASE = "http://localhost:8000"
logger = logging.getLogger("mcp-financial-rag")

# ── MCP App ──────────────────────────────────────────────────────────────────
mcp = FastMCP(
    "Financial-RAG",
    instructions="Indian equity research tools – financials, market data, ownership & stock listings",
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

@mcp.tool()
async def get_stock(symbol: str) -> str:
    """
    Get detailed information for a single stock.

    Args:
        symbol: Stock ticker symbol (e.g. TCS, RELIANCE, APOLLO)
    """
    data = await _get(f"/api/v1/stocks/{symbol}")
    return json.dumps(data, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# LIVE MARKET DATA (yfinance)
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def get_live_market_data(
    symbols: str,
    include_indices: bool = False,
) -> str:
    """
    Fetch live/current market data for stocks and indices using yfinance.
    Returns current price, previous close, day change %, 52-week high/low,
    market cap, and volume for each symbol.

    Args:
        symbols: Comma-separated stock symbols (e.g. 'HAL,RELIANCE,TCS').
                 For Indian NSE stocks, '.NS' suffix is added automatically.
                 For indices, use: NIFTY50, SENSEX, BANKNIFTY.
        include_indices: If True, also fetch Nifty 50 and Sensex data alongside the stocks.
    """
    import yfinance as yf

    INDEX_MAP = {
        "NIFTY50": "^NSEI",
        "NIFTY": "^NSEI",
        "SENSEX": "^BSESN",
        "BANKNIFTY": "^NSEBANK",
    }

    raw_symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]

    yf_tickers: list[str] = []
    for s in raw_symbols:
        if s in INDEX_MAP:
            yf_tickers.append(INDEX_MAP[s])
        elif s.startswith("^"):
            yf_tickers.append(s)
        elif ".NS" in s or ".BO" in s:
            yf_tickers.append(s)
        else:
            yf_tickers.append(f"{s}.NS")

    if include_indices:
        for idx_ticker in ["^NSEI", "^BSESN"]:
            if idx_ticker not in yf_tickers:
                yf_tickers.append(idx_ticker)

    results = []
    for ticker_str in yf_tickers:
        try:
            ticker = yf.Ticker(ticker_str)
            info = ticker.info
            current = info.get("currentPrice") or info.get("regularMarketPrice")
            prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
            day_change_pct = (
                round((current - prev_close) / prev_close * 100, 2)
                if current and prev_close
                else None
            )
            results.append({
                "symbol": ticker_str,
                "name": info.get("shortName") or info.get("longName", ticker_str),
                "current_price": current,
                "previous_close": prev_close,
                "day_change_pct": day_change_pct,
                "day_high": info.get("dayHigh") or info.get("regularMarketDayHigh"),
                "day_low": info.get("dayLow") or info.get("regularMarketDayLow"),
                "52_week_high": info.get("fiftyTwoWeekHigh"),
                "52_week_low": info.get("fiftyTwoWeekLow"),
                "market_cap": info.get("marketCap"),
                "volume": info.get("volume") or info.get("regularMarketVolume"),
                "currency": info.get("currency", "INR"),
            })
        except Exception as e:
            results.append({"symbol": ticker_str, "error": str(e)})

    return json.dumps(
        {"live_data": results, "timestamp": str(__import__("datetime").datetime.now())},
        indent=2,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DOCUMENTS
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def get_documents(
    symbol: str,
    doc_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """
    Annual reports & concall transcripts stored in MinIO.

    Args:
        symbol: Stock ticker symbol (e.g. TCS, RELIANCE, APOLLO)
        doc_type: Filter by type: annual_report | concall
        limit: Max rows (1-200, default 50)
        offset: Pagination offset
    """
    data = await _get(
        f"/api/v1/stocks/{symbol}/documents",
        {"doc_type": doc_type, "limit": limit, "offset": offset},
    )
    return json.dumps(data, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# OPERATIONS & HEALTH
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def get_health() -> str:
    """Liveness probe / system health check."""
    data = await _get("/api/v1/health")
    return json.dumps(data, indent=2)


@mcp.tool()
async def get_etl_logs(
    symbol: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """
    ETL run log — per-symbol pipeline execution history.

    Args:
        symbol: Filter by stock symbol
        status: Filter by status (success | failed | running)
        limit: Max rows (1-200, default 50)
        offset: Pagination offset
    """
    data = await _get(
        "/api/v1/ops/etl-logs",
        {"symbol": symbol, "status": status, "limit": limit, "offset": offset},
    )
    return json.dumps(data, indent=2)


@mcp.tool()
async def get_quality_logs(
    symbol: str | None = None,
    table_name: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """
    Data quality log — completeness & null-heavy rows per ETL run.

    Args:
        symbol: Filter by stock symbol
        table_name: Filter by target table name
        limit: Max rows (1-200, default 50)
        offset: Pagination offset
    """
    data = await _get(
        "/api/v1/ops/quality-logs",
        {"symbol": symbol, "table_name": table_name, "limit": limit, "offset": offset},
    )
    return json.dumps(data, indent=2)



# ── Entry point ──────────────────────────────────────────────────────────────
# Occupied ports (Docker): 8000, 8080, 8081, 3307, 9000
# MCP SSE port:            8100  (does NOT clash)
MCP_PORT = 8100

if __name__ == "__main__":
    import sys

    if "--sse" in sys.argv:
        # Run as SSE HTTP server
        mcp.settings.port = MCP_PORT
        mcp.run(transport="sse")
    else:
        # Default: stdio transport (no port needed)
        mcp.run(transport="stdio")
