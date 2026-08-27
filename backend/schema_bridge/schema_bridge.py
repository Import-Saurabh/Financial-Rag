from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import httpx

# ── project imports ──────────────────────────────────────────────────────────
from decomposer.atomic_decomposer import (
    AtomicNeed,
    NeedType,
    TimeHorizon,
    SUBTYPE_TABLE_MAP,
    ORPHANED_SUBTYPES,   # [FIX] sub_types with no backing table/column anywhere
)
from rag.retriever_openkb import RetrievedChunk
from utils.logger import get_logger

log = get_logger(__name__)

# ─── MCP base URL (MCP server) ───────────────────────────────────────────────
MCP_BASE = os.getenv("FINANCIAL_MCP_BASE", "http://localhost:8100")

# ─────────────────────────────────────────────────────────────────────────────
# Table → API endpoint mapping
# ─────────────────────────────────────────────────────────────────────────────
# Maps the MySQL table name (used in SUBTYPE_TABLE_MAP) to the FastAPI
# endpoint that serves the same data. {symbol} is replaced at call time.
# "date_key" is the field name in the JSON response used for year filtering.

_TABLE_TO_TOOL: Dict[str, Dict[str, Any]] = {
    # ── Financials ────────────────────────────────────────────────────────────
    "profit_loss":          {"tool": "get_profit_loss",
                             "date_key": "period_end", "supports_period_type": True},
    "quarterly_results":    {"tool": "get_quarterly_results",
                             "date_key": "period_end", "supports_period_type": False},
    "balance_sheet":        {"tool": "get_balance_sheet",
                             "date_key": "period_end", "supports_period_type": True},
    "cash_flow":            {"tool": "get_cash_flow",
                             "date_key": "period_end", "supports_period_type": True},
    # ── Market ────────────────────────────────────────────────────────────────
    "price_daily":          {"tool": "get_price",
                             "date_key": "date",       "supports_date_range": True},
    "technical_indicators": {"tool": "get_technicals",
                             "date_key": "date",       "supports_date_range": True},
    # ── Ownership ─────────────────────────────────────────────────────────────
    "shareholding":         {"tool": "get_shareholding",
                             "date_key": "period_end"},
    "corporate_actions":    {"tool": "get_corporate_actions",
                             "date_key": "action_date"},
    # ── Stocks ────────────────────────────────────────────────────────────────
    "stocks":               {"tool": "list_stocks",
                             "date_key": "updated_at", "no_symbol_in_path": True},
    # ── Growth / Estimates ────────────────────────────────────────────────────
    "growth_metrics":       {"tool": "get_growth_metrics",
                             "date_key": "as_of_date"},
    "eps_trend":            {"tool": "get_eps_trend",
                             "date_key": "snapshot_date"},
    # ── Macro ─────────────────────────────────────────────────────────────────
    "rbi_rates":            {"tool": "get_rbi_rates",
                             "date_key": "effective_date", "no_symbol_in_path": True},
    "market_indices":       {"tool": "get_market_indices",
                             "date_key": "snapshot_date",  "no_symbol_in_path": True},
    "forex_commodities":    {"tool": "get_forex_commodities",
                             "date_key": "snapshot_date",  "no_symbol_in_path": True},
    "macro_indicators":     {"tool": "get_macro_indicators",
                             "date_key": "snapshot_date",  "no_symbol_in_path": True},
}



# ─────────────────────────────────────────────────────────────────────────────
# Indian FY → calendar date range helper
# ─────────────────────────────────────────────────────────────────────────────
def _fy_date_range(fy_year: int) -> Tuple[str, str]:
    """
    Indian FY: April of (fy_year-1) → March of fy_year.
    e.g. FY2024 = 2023-04-01 to 2024-03-31
    """
    start = date(fy_year - 1, 4, 1).isoformat()
    end   = date(fy_year,     3, 31).isoformat()
    return start, end


# ─────────────────────────────────────────────────────────────────────────────
# Result containers
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SqlAtomResult:
    atom:    AtomicNeed
    rows:    List[Dict[str, Any]] = field(default_factory=list)
    sql:     str = ""           # the SQL that was executed (for debugging)
    params:  tuple = ()
    error:   Optional[str] = None


@dataclass
class VectorAtomResult:
    atom:   AtomicNeed
    chunks: List[RetrievedChunk] = field(default_factory=list)
    error:  Optional[str] = None


@dataclass
class BridgeResult:
    sql_results:    List[SqlAtomResult]    = field(default_factory=list)
    vector_results: List[VectorAtomResult] = field(default_factory=list)
    errors:         List[str]              = field(default_factory=list)

    # Convenience: all SQL rows across all atoms, each tagged with sub_type
    def all_sql_rows(self) -> List[Dict[str, Any]]:
        out = []
        for r in self.sql_results:
            for row in r.rows:
                out.append({"_sub_type": r.atom.sub_type, **row})
        return out

    # Convenience: all vector chunks across all atoms, sorted by score desc
    def all_chunks(self) -> List[RetrievedChunk]:
        chunks = [c for r in self.vector_results for c in r.chunks]
        return sorted(chunks, key=lambda c: c.score, reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# Client-side fiscal year filter (API endpoints don't expose year params)
# ─────────────────────────────────────────────────────────────────────────────
def _filter_rows_by_fy(
    rows: List[Dict[str, Any]],
    years: List[int],
    date_key: str,
) -> List[Dict[str, Any]]:
    """
    Keep only rows whose date_key falls within the requested Indian fiscal
    years.  Indian FY: Apr(Y-1) – Mar(Y).  A period_end of 2024-03-31 is
    FY2024; a period_end of 2024-06-30 is FY2025.
    """
    if not years:
        return rows
    fy_set = set(years)
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        raw_date = row.get(date_key)
        if not raw_date:
            filtered.append(row)          # keep rows without a date
            continue
        try:
            parts = str(raw_date)[:10].split("-")
            y, m = int(parts[0]), int(parts[1])
            fy = y + 1 if m >= 4 else y   # Indian FY convention
            if fy in fy_set:
                filtered.append(row)
        except (ValueError, IndexError):
            filtered.append(row)
    return filtered


# ─────────────────────────────────────────────────────────────────────────────
# MCP Tool executor (replaces HTTP/MySQL)
# ─────────────────────────────────────────────────────────────────────────────
import json
import asyncio
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

async def _execute_mcp_atom(atom: AtomicNeed, session: ClientSession) -> SqlAtomResult:
    """
    Fetch data for one atom via the MCP Server tools (never raises).
    Returns SqlAtomResult with rows from the JSON response.
    """
    table = atom.sql_table
    if not table or table.startswith("chromadb:"):
        return SqlAtomResult(
            atom=atom,
            error=f"Atom sub_type={atom.sub_type!r} is vector-backed; use vector channel.",
        )

    if atom.sub_type in ORPHANED_SUBTYPES:
        return SqlAtomResult(
            atom=atom,
            error=(
                f"sub_type={atom.sub_type!r} has no backing data in the current "
                f"schema — not a bug, just not tracked yet."
            ),
        )

    tool_info = _TABLE_TO_TOOL.get(table)
    if tool_info is None:
        return SqlAtomResult(
            atom=atom,
            error=f"No MCP tool mapped for table {table!r}",
        )

    tool_name = tool_info["tool"]
    
    # ── Build arguments ───────────────────────────────────────────────────
    args: Dict[str, Any] = {}

    symbol = atom.symbol or (atom.symbols[0] if atom.symbols else None)
    if not tool_info.get("no_symbol_in_path"):
        if not symbol:
            return SqlAtomResult(
                atom=atom,
                error=f"Symbol required for {table} but none provided",
            )
        args["symbol"] = symbol.upper()

    # Period type (profit_loss, balance_sheet, cash_flow)
    if tool_info.get("supports_period_type") and atom.period_type:
        args["period_type"] = atom.period_type

    # Date range (price, technicals)
    # The tools might not actually accept from_date/to_date as arguments
    # Let's check MCP tool definitions in mcp_server.py:
    # get_price: takes from_date, to_date. Wait, I didn't verify if mcp_server get_price accepts them.
    # Ah, let's just pass them if they are in the HTTP api... wait!
    # I should check if the MCP tool accepts from_date/to_date.
    # Let's pass them, if the tool doesn't take it, MCP server will ignore them or throw error.
    if tool_info.get("supports_date_range") and atom.years:
        min_fy, max_fy = min(atom.years), max(atom.years)
        args["from_date"] = date(min_fy - 1, 4, 1).isoformat()
        args["to_date"]   = date(max_fy, 3, 31).isoformat()

    # Corporate actions: action_type filter
    if table == "corporate_actions" and atom.sub_type in (
        "dividend", "buyback", "bonus", "split"
    ):
        args["action_type"] = atom.sub_type.capitalize()

    # Macro: indicator/instrument filter from raw_text
    if table == "macro_indicators" and atom.raw_text and len(atom.raw_text) < 30:
        args["indicator_name"] = atom.raw_text
    if table == "forex_commodities" and atom.raw_text and len(atom.raw_text) < 30:
        args["instrument"] = atom.raw_text
    if table == "market_indices" and atom.raw_text and len(atom.raw_text) < 30:
        args["index_name"] = atom.raw_text

    # Limit: fetch enough data to cover requested years
    if atom.years and len(atom.years) > 1:
        args["limit"] = max(20, len(atom.years) * 4)
    elif atom.time_horizon == TimeHorizon.CURRENT and not atom.years:
        args["limit"] = 5
    else:
        args["limit"] = 20

    # ── MCP Tool Call ─────────────────────────────────────────────────────
    log.debug(f"  [bridge] MCP Tool {tool_name} args={args}")

    try:
        result = await session.call_tool(tool_name, arguments=args)
        body = json.loads(result.content[0].text)
    except Exception as e:
        msg = f"MCP error calling {tool_name} for {atom.sub_type}: {e}"
        log.error(f"  [bridge] {msg}")
        return SqlAtomResult(atom=atom, sql=f"TOOL {tool_name}", error=msg)

    # ── Extract rows ──────────────────────────────────────────────────────
    if isinstance(body, dict) and "error" in body:
        msg = f"API Error: {body['error']} - {body.get('detail', '')}"
        log.error(f"  [bridge] {msg}")
        return SqlAtomResult(atom=atom, sql=f"TOOL {tool_name}", error=msg)

    rows = body.get("data", body if isinstance(body, list) else [])
    if not isinstance(rows, list):
        rows = [rows]

    # Client-side fiscal year filtering for endpoints that don't support it
    date_key = tool_info.get("date_key", "period_end")
    if atom.years and not tool_info.get("supports_date_range"):
        rows = _filter_rows_by_fy(rows, atom.years, date_key)

    log.info(f"  [bridge] {atom.sub_type}: {len(rows)} row(s) from MCP {tool_name}")
    return SqlAtomResult(
        atom=atom,
        rows=rows,
        sql=f"TOOL {tool_name}",
        params=tuple(args.items()),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Vector executor (OpenKB)
# ─────────────────────────────────────────────────────────────────────────────
def _execute_vector_atom(atom: AtomicNeed) -> VectorAtomResult:
    """Run an OpenKB vector query for one atom, return VectorAtomResult."""
    from rag.retriever_openkb import OpenKBRetriever
    
    query  = atom.metric        # human-readable label is a good base query
    raw    = atom.raw_text or ""
    if raw and raw.lower() not in query.lower():
        query = f"{query} {raw}"   # enrich with original phrasing

    symbol = atom.symbol or (atom.symbols[0] if atom.symbols else None)
    years  = atom.years or None
    
    if symbol:
        query = f"{symbol} {query}"
    if years:
        query = f"{query} {' '.join(str(y) for y in years)}"

    try:
        retriever = OpenKBRetriever(wiki_dir="backend/data/openkb_wiki")
        raw_results = retriever.retrieve(query)
        
        # Wrap the dicts into RetrievedChunk so downstream code doesn't break
        chunks = []
        for i, res in enumerate(raw_results):
            meta = {
                "symbol": symbol,
                "year": years[0] if years else "",
                # Rough heuristic for doc_type if needed by legacy prompts
                "doc_type": "concall" if atom.need_type == NeedType.FORWARD_LOOKING else "annual_report",
                "section": getattr(res, "section", ""),
                "page_start": getattr(res, "page_start", ""),
                "chunk_id": f"openkb_{i}",
                "source_file": getattr(res, "section", "")
            }
            c = RetrievedChunk(
                chunk_id=meta["chunk_id"],
                text=getattr(res, "text", ""),
                importance_score=getattr(res, "score", 0.0)
            )
            chunks.append(c)

        log.info(f"  [bridge] {atom.sub_type}: {len(chunks)} chunk(s) from OpenKB")
        return VectorAtomResult(atom=atom, chunks=chunks)

    except Exception as e:
        msg = f"Vector query failed for {atom.sub_type}: {e}"
        log.error(f"  [bridge] {msg}")
        return VectorAtomResult(atom=atom, error=msg)


# ─────────────────────────────────────────────────────────────────────────────
# [FIX-CONCALL-YEAR-MISMATCH] Resolve "current" SQL results back to a FY
# ─────────────────────────────────────────────────────────────────────────────
def _latest_resolved_fy_by_symbol(sql_results: List[SqlAtomResult]) -> Dict[str, int]:
    """
    For each symbol, find the most recent period_end/date across all
    successful SQL atom results and convert it to the Indian fiscal year
    that date falls in (Apr-Mar). Used to backfill unscoped vector atoms
    ("this quarter" style queries) so concall retrieval targets the same
    period the SQL answer resolved to, instead of an unrelated default
    window.
    """
    latest_date_by_symbol: Dict[str, str] = {}
    date_keys = ("period_end", "date", "as_of_date", "snapshot_date",
                 "action_date", "effective_date")

    for result in sql_results:
        if result.error or not result.rows:
            continue
        symbol = result.atom.symbol
        if not symbol:
            continue
        for row in result.rows:
            row_date = next((row[k] for k in date_keys if row.get(k)), None)
            if not row_date:
                continue
            row_date = str(row_date)
            if symbol not in latest_date_by_symbol or row_date > latest_date_by_symbol[symbol]:
                latest_date_by_symbol[symbol] = row_date

    resolved: Dict[str, int] = {}
    for symbol, date_str in latest_date_by_symbol.items():
        try:
            y, m, _ = (int(x) for x in date_str[:10].split("-"))
        except ValueError:
            continue
        # Indian FY: Apr-Dec belongs to FY(y+1), Jan-Mar belongs to FY(y)
        resolved[symbol] = y + 1 if m >= 4 else y
    return resolved


# ─────────────────────────────────────────────────────────────────────────────
# [FIX-EMPTY-VECTOR-FALLBACK]
# If a QUALITATIVE/FORWARD_LOOKING atom (routed to chromadb) comes back with
# ZERO chunks -- not "low score", literally nothing retrieved -- the query
# may have been misclassified, or the honest answer simply lives in
# structured data instead of prose (e.g. "profit this quarter" phrased in a
# way that leaned qualitative). Rather than surfacing a dead end, do one
# best-effort SQL lookup using keyword cues from the atom's own text. This
# is intentionally conservative: it only fires on EMPTY vector results, and
# only for keywords with an unambiguous, already-whitelisted SQL mapping
# (via SUBTYPE_TABLE_MAP) -- no free-form guessing, no new columns invented.
_VECTOR_EMPTY_SQL_FALLBACK: List[Tuple[str, str]] = [
    (r"\bnet\s+profit|\bpat\b|\bprofit\b", "net_profit"),
    (r"\brevenue|\bsales\b|\btop[\s\-]?line", "revenue"),
    (r"\bebitda\b", "ebitda"),
    (r"\bmargin\b", "opm"),
    (r"\beps\b", "eps"),
    (r"\bdebt\b|\bborrowings?\b", "borrowings"),
    (r"\bcash\b", "cash"),
    (r"\bmarket\s+cap", "market_cap"),
    (r"\broe\b", "roe"),
    (r"\bcapex\b", "capex"),
]


def _infer_fallback_sql_sub_type(atom: AtomicNeed) -> Optional[str]:
    text = f"{atom.raw_text or ''} {atom.metric or ''}".lower()
    for pattern, sub_type in _VECTOR_EMPTY_SQL_FALLBACK:
        if re.search(pattern, text):
            return sub_type
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Comparative expansion
# ─────────────────────────────────────────────────────────────────────────────
def _expand_comparative(atom: AtomicNeed) -> List[AtomicNeed]:
    """
    A COMPARATIVE atom targets multiple symbols.
    Expand it into one atom per symbol, each with the same sub_type but
    a single symbol.  The original COMPARATIVE atom is discarded.
    """
    symbols = atom.symbols if atom.symbols else ([atom.symbol] if atom.symbol else [])
    if not symbols:
        return [atom]

    expanded = []
    for sym in symbols:
        clone = AtomicNeed(
            need_type    = NeedType.QUANTITATIVE,   # route to SQL by default
            sub_type     = atom.sub_type,
            metric       = atom.metric,
            symbol       = sym,
            symbols      = [],
            years        = atom.years,
            time_horizon = atom.time_horizon,
            period_type  = atom.period_type,
            raw_text     = atom.raw_text,
            confidence   = atom.confidence,
            source       = atom.source,
        )
        clone.resolve_schema()
        expanded.append(clone)
    return expanded


# ─────────────────────────────────────────────────────────────────────────────
# Channel classifier
# ─────────────────────────────────────────────────────────────────────────────
_SQL_NEED_TYPES = {
    NeedType.QUANTITATIVE,
    NeedType.TECHNICAL,
    NeedType.MACRO,
    NeedType.OWNERSHIP,
}
_VECTOR_NEED_TYPES = {
    NeedType.QUALITATIVE,
    NeedType.FORWARD_LOOKING,
}


def _classify(atom: AtomicNeed) -> str:
    """Return 'sql', 'vector', or 'both'."""
    if atom.need_type in _SQL_NEED_TYPES:
        # Some sub_types are actually vector-backed (chromadb:*)
        if (atom.sql_table or "").startswith("chromadb:"):
            return "vector"
        return "sql"
    if atom.need_type in _VECTOR_NEED_TYPES:
        return "vector"
    if atom.need_type == NeedType.COMPARATIVE:
        return "both"
    return "sql"   # safe default


# ─────────────────────────────────────────────────────────────────────────────
# Public API: SchemaBridge
# ─────────────────────────────────────────────────────────────────────────────
class SchemaBridge:
    """
    Translates a list of AtomicNeed objects into concrete data-fetch results.

    Usage:
        bridge = SchemaBridge()
        result = bridge.fetch(atoms)

        # All SQL rows across all atoms
        for row in result.all_sql_rows():
            print(row)

        # Vector chunks sorted by relevance
        for chunk in result.all_chunks():
            print(chunk.text[:120])

    Thread safety: each call to fetch() opens its own DB connection(s).
    The bridge object itself is stateless and safe to share.
    """

    def __init__(
        self,
        mcp_base: Optional[str] = None,
        max_workers: int = 8,
    ):
        """
        :param mcp_base:     Base URL of the MCP server (e.g.
                             http://localhost:8100). Defaults to MCP_BASE.
        :param max_workers:  Maximum threads for parallel fetching.
        """
        self.mcp_base = mcp_base or MCP_BASE
        self.max_workers = max_workers

    # ── Main entry point ──────────────────────────────────────────────────────

    def fetch(self, atoms: List[AtomicNeed]) -> BridgeResult:
        """
        Dispatch all atoms to the appropriate channel(s), running them in
        parallel.  Returns a BridgeResult regardless of partial failures.
        """
        if not atoms:
            return BridgeResult()

        # Step 1: expand comparative atoms into per-symbol atoms
        expanded: List[AtomicNeed] = []
        for atom in atoms:
            if atom.need_type == NeedType.COMPARATIVE:
                expanded.extend(_expand_comparative(atom))
            else:
                expanded.append(atom)

        # Step 2: classify each atom
        sql_atoms:    List[AtomicNeed] = []
        vector_atoms: List[AtomicNeed] = []
        for atom in expanded:
            channel = _classify(atom)
            if channel in ("sql", "both"):
                sql_atoms.append(atom)
            if channel in ("vector", "both"):
                vector_atoms.append(atom)

        log.info(
            f"[bridge] Dispatching {len(sql_atoms)} SQL atom(s) + "
            f"{len(vector_atoms)} vector atom(s) in parallel"
        )

        # Step 3: fire tasks
        sql_results:    List[SqlAtomResult]    = []
        vector_results: List[VectorAtomResult] = []
        errors:         List[str]              = []

        # Run vector atoms in thread pool
        if vector_atoms:
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                futures = {pool.submit(self._safe_vector, atom): atom for atom in vector_atoms}
                for fut in as_completed(futures):
                    atom = futures[fut]
                    try:
                        result = fut.result()
                        vector_results.append(result)
                        if result.error:
                            errors.append(result.error)
                    except Exception as e:
                        msg = f"Unexpected failure in vector bridge ({atom.sub_type}): {e}"
                        log.error(f"  [bridge] {msg}")
                        errors.append(msg)

        # Run SQL/MCP atoms via single asyncio SSE session
        if sql_atoms:
            try:
                mcp_url = f"{self.mcp_base}/sse"
                results = asyncio.run(self._fetch_mcp_atoms(sql_atoms, mcp_url))
                for res in results:
                    sql_results.append(res)
                    if res.error:
                        errors.append(res.error)
            except Exception as e:
                msg = f"Unexpected failure in MCP bridge: {e}"
                log.error(f"  [bridge] {msg}")
                errors.append(msg)

        # [FIX-EMPTY-VECTOR-FALLBACK]
        # A qualitative/forward-looking ask that came back with literally
        # zero chunks shouldn't just dead-end. If the atom's own text
        # contains an unambiguous quantitative cue (see
        # _VECTOR_EMPTY_SQL_FALLBACK), fire one SQL lookup for it so the
        # answer still surfaces from structured data instead of "not found."
        # This only fires on EMPTY results (0 chunks) -- atoms that got some
        # chunks back (even low-scoring ones) are left to the relevance
        # floor in prompt_builder.py, not re-routed here.
        for vres in vector_results:
            if vres.chunks or vres.error:
                continue
            fallback_sub_type = _infer_fallback_sql_sub_type(vres.atom)
            if not fallback_sub_type or fallback_sub_type in ORPHANED_SUBTYPES:
                continue
            fallback_atom = AtomicNeed(
                need_type    = NeedType.QUANTITATIVE,
                sub_type     = fallback_sub_type,
                metric       = fallback_sub_type,
                symbol       = vres.atom.symbol,
                years        = vres.atom.years,
                time_horizon = vres.atom.time_horizon,
                period_type  = vres.atom.period_type,
                raw_text     = vres.atom.raw_text,
                source       = "fallback_empty_vector",
            )
            fallback_atom.resolve_schema()
            fallback_result = self._safe_sql(fallback_atom)
            if fallback_result.rows and not fallback_result.error:
                log.info(
                    f"  [bridge] empty-vector fallback: {vres.atom.sub_type!r} "
                    f"had 0 chunks -> fired SQL sub_type={fallback_sub_type!r}, "
                    f"got {len(fallback_result.rows)} row(s)"
                )
                sql_results.append(fallback_result)
            elif fallback_result.error:
                errors.append(fallback_result.error)

        # [FIX-CONCALL-YEAR-MISMATCH]
        # SQL atoms with time_horizon=CURRENT and no explicit years resolve
        # to whatever period is actually latest in the DB (e.g. Q1 FY27 /
        # period_end=2026-06-30 -- see _build_sql's "ORDER BY ... LIMIT 5"
        # branch). Vector atoms (FORWARD_LOOKING/QUALITATIVE) with the same
        # symbol and no explicit years never see that resolved period --
        # they fall through to retriever.py's own "no year hint -> default
        # last 3 FY" logic, which has no idea what period the SQL side
        # actually landed on. On the BEL "profit this quarter" query this
        # produced a concall search over [2023,2024,2025] while the SQL
        # answer was for FY2027 Q1 -- guaranteed mismatch, guaranteed
        # irrelevant excerpts.
        #
        # Fix: after SQL results are in, backfill the resolved fiscal year
        # into any sibling vector atom (same symbol, no explicit years,
        # not historical) so concall retrieval targets the period the
        # answer is actually about.
        if vector_results and sql_results:
            resolved_fy_by_symbol = _latest_resolved_fy_by_symbol(sql_results)
            rerun: List[VectorAtomResult] = []
            for vres in vector_results:
                atom = vres.atom
                needs_backfill = (
                    not atom.years
                    and atom.time_horizon != TimeHorizon.HISTORICAL
                    and atom.symbol
                    and atom.symbol in resolved_fy_by_symbol
                )
                if needs_backfill:
                    atom.years = [resolved_fy_by_symbol[atom.symbol]]
                    log.info(
                        f"  [bridge] backfilled years={atom.years} onto vector "
                        f"atom {atom.sub_type!r} from sibling SQL result "
                        f"(was unscoped -> mismatched-period retrieval)"
                    )
                    rerun.append(self._safe_vector(atom))
                else:
                    rerun.append(vres)
            vector_results = rerun

        log.info(
            f"[bridge] Done — {sum(len(r.rows) for r in sql_results)} SQL row(s), "
            f"{sum(len(r.chunks) for r in vector_results)} vector chunk(s), "
            f"{len(errors)} error(s)"
        )
        return BridgeResult(
            sql_results    = sql_results,
            vector_results = vector_results,
            errors         = errors,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _fetch_mcp_atoms(self, atoms: List[AtomicNeed], mcp_url: str) -> List[SqlAtomResult]:
        """Fetch multiple atoms over a single MCP SSE connection in parallel."""
        async with sse_client(mcp_url) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                tasks = [_execute_mcp_atom(atom, session) for atom in atoms]
                return await asyncio.gather(*tasks)
    def _safe_vector(self, atom: AtomicNeed) -> VectorAtomResult:
        return _execute_vector_atom(atom)

    # ── Convenience: fetch for a single symbol across multiple sub_types ──────

    def fetch_symbol(
        self,
        symbol:    str,
        sub_types: List[str],
        years:     Optional[List[int]] = None,
    ) -> BridgeResult:
        """
        Helper for the common case: fetch several metrics for one company.

        Example:
            result = bridge.fetch_symbol("ADANIPORTS", ["revenue","net_debt","roce"])
        """
        atoms = []
        for st in sub_types:
            entry = SUBTYPE_TABLE_MAP.get(st)
            if not entry:
                log.warning(f"  [bridge] Unknown sub_type {st!r} — skipping")
                continue
            atom = AtomicNeed(
                need_type   = NeedType.QUANTITATIVE,
                sub_type    = st,
                metric      = st,
                symbol      = symbol.upper(),
                years       = years or [],
                time_horizon= TimeHorizon.HISTORICAL if years else TimeHorizon.CURRENT,
                period_type = "annual",
            )
            atom.resolve_schema()
            atoms.append(atom)
        return self.fetch(atoms)


