"""
schema_bridge/schema_bridge.py

Layer 2 of the Quant CoPilot Intent Decomposition Pipeline.

Receives a list of AtomicNeed objects from the decomposer and translates
each one into a concrete data-fetch operation:

  QUANTITATIVE / TECHNICAL / MACRO / OWNERSHIP atoms
    → parameterized MySQL SELECT (table + columns from SUBTYPE_TABLE_MAP,
      filtered by symbol, fiscal year / date window)

  QUALITATIVE atoms
    → ChromaDB vector query via retrieve_annual()

  FORWARD_LOOKING atoms
    → ChromaDB concall query via retrieve_concall()

  COMPARATIVE atoms
    → both SQL and vector, one sub-call per symbol

All channels fire in parallel using concurrent.futures.ThreadPoolExecutor
so a mixed query (EBITDA + MD&A + guidance) costs roughly max(channel_latency)
instead of sum.

Returns a BridgeResult containing:
  sql_results    — list of SqlAtomResult (atom + rows fetched)
  vector_results — list of VectorAtomResult (atom + chunks fetched)
  errors         — any channel-level failures (non-fatal)

═══════════════════════════════════════════════════════════════════════════
Design principles
═══════════════════════════════════════════════════════════════════════════
1. ZERO hallucination surface — only columns that exist in SUBTYPE_TABLE_MAP
   and the actual DB schema are ever queried.  The bridge never generates
   free-form SQL; it assembles it from a whitelist.

2. Symbol filtering — every SQL query includes WHERE symbol = ? when a
   symbol is known.  Macro/rate tables (rbi_rates, forex_commodities,
   macro_indicators, market_indices) are symbol-free by design.

3. Year → date mapping
   FY year (e.g. 2024) maps to the date range [YYYY-04-01 … (YYYY+1)-03-31]
   for Indian financial year convention (Apr–Mar).
   "current" queries use ORDER BY <date_col> DESC LIMIT 1.

4. Period type routing
   annual    → profit_loss, balance_sheet (period_type='annual'), cash_flow
   quarterly → quarterly_results, balance_sheet (period_type='quarterly')
   ttm       → profit_loss, cash_flow (period_type='ttm')

5. Safety — all values are passed as SQL parameters (%s), never interpolated.
"""

from __future__ import annotations

import decimal   # [FIX] used in _execute_sql_atom but was never imported ->
                  # NameError on every row containing a DECIMAL column, i.e.
                  # almost every real query. This was silently killing SQL
                  # results even for correctly-mapped tables.
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import mysql.connector
from mysql.connector import Error as MySQLError

# ── project imports ──────────────────────────────────────────────────────────
from decomposer.atomic_decomposer import (
    AtomicNeed,
    NeedType,
    TimeHorizon,
    SUBTYPE_TABLE_MAP,
    ORPHANED_SUBTYPES,   # [FIX] sub_types with no backing table/column anywhere
)
from pipeline.retrieval.retriever import (
    RetrievedChunk,
    retrieve_annual,
    retrieve_concall,
)
from utils.logger import get_logger

log = get_logger(__name__)

# ─── MySQL connection defaults (can be overridden via env or constructor) ──
DEFAULT_MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", 3306)),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "ai_hedge_fund"),
    "charset": "utf8mb4",
    "use_unicode": True,
}


# ─────────────────────────────────────────────────────────────────────────────
# Table metadata: which column holds the date/period, and which holds symbol
# ─────────────────────────────────────────────────────────────────────────────

# Maps table_name → (date_column, has_symbol_column, has_period_type_column)
#   date_column        — used to filter by fiscal year or ORDER BY for "current"
#   has_symbol_column  — True when the table has a `symbol` TEXT column
#   has_period_type    — True when the table has a `period_type` TEXT column
#                        ('annual' / 'quarterly' / 'ttm')
_TABLE_META: Dict[str, Tuple[str, bool, bool]] = {
    # Financials – P&L
    "profit_loss":           ("period_end", True,  True),   # period_type: annual/quarterly/ttm
    # Balance Sheet
    "balance_sheet":         ("period_end", True,  True),   # period_type: annual/quarterly
    # Cash Flow
    "cash_flow":             ("period_end", True,  True),   # period_type: annual/quarterly/ttm
    # Quarterly Results (standalone, always quarterly)
    "quarterly_results":     ("period_end", True,  False),
    # Market data
    "price_daily":           ("date",       True,  False),
    "technical_indicators":  ("date",       True,  False),
    # Shareholding
    "shareholding":          ("period_end", True,  False),
    # Corporate actions
    "corporate_actions":     ("action_date", True,  False),
    # Growth & estimates
    "growth_metrics":        ("as_of_date", True,  False),
    "eps_trend":             ("snapshot_date", True, False),
    # [FIX] "stocks" was missing -> market_cap (stocks.market_cap_cr) had
    # nowhere to resolve to and would hit the same "Unknown table" error.
    # It's a static, symbol-keyed table with no period_end; updated_at is
    # the closest thing to a date column, and there's no period_type.
    "stocks":                ("updated_at", True,  False),
    # Macro / market tables — no symbol column
    "rbi_rates":             ("effective_date", False, False),
    "market_indices":        ("snapshot_date",  False, False),
    "forex_commodities":     ("snapshot_date",  False, False),
    "macro_indicators":      ("snapshot_date",  False, False),
}

# Columns always fetched in addition to the atom's requested columns.
# This lets the LLM know what period the data belongs to.
_ALWAYS_SELECT = ["symbol", "period_end", "as_of_date", "date",
                  "snapshot_date", "action_date", "effective_date"]

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
# SQL query builder
# ─────────────────────────────────────────────────────────────────────────────
def _build_sql(atom: AtomicNeed) -> Tuple[str, tuple]:
    """
    Build a parameterized SELECT for one SQL-backed AtomicNeed.

    Returns (sql_string, params_tuple).
    Raises ValueError if the table or columns cannot be resolved.
    """
    table   = atom.sql_table
    columns = list(atom.sql_columns) if atom.sql_columns else []

    if not table or table.startswith("chromadb:"):
        raise ValueError(f"Atom sub_type={atom.sub_type!r} is vector-backed; "
                         f"use vector channel instead.")

    # [FIX] Sub-types with no real column anywhere in the schema (see
    # ORPHANED_SUBTYPES in atomic_decomposer.py) must never reach SQL build --
    # they'd either raise or build a query selecting nothing but symbol/date.
    # Fail with a distinct, expected message instead of a scary stack trace.
    if atom.sub_type in ORPHANED_SUBTYPES:
        raise ValueError(
            f"sub_type={atom.sub_type!r} has no backing column in the current "
            f"schema (mysql_schema_v2.sql) — not a bug, just not tracked yet."
        )

    meta = _TABLE_META.get(table)
    if meta is None:
        raise ValueError(f"Unknown table {table!r} — add it to _TABLE_META.")

    date_col, has_symbol, has_period_type = meta

    # --- SELECT clause -------------------------------------------------------
    select_cols: List[str] = []
    if has_symbol:
        select_cols.append("symbol")
    if date_col not in select_cols:
        select_cols.append(date_col)
    if has_period_type:
        select_cols.append("period_type")
    # Requested metric columns (deduplicated, whitelisted)
    for col in columns:
        if col not in select_cols:
            select_cols.append(col)

    select_str = ", ".join(select_cols)

    # --- WHERE clause ---------------------------------------------------------
    conditions: List[str] = []
    params:     List[Any] = []

    # Symbol filter
    symbol = atom.symbol or (atom.symbols[0] if atom.symbols else None)
    if has_symbol and symbol:
        conditions.append("symbol = %s")
        params.append(symbol.upper())

    # Period type filter (only for tables that support it)
    if has_period_type:
        if atom.period_type == "quarterly":
            period_type_val = "quarterly"
        elif atom.period_type == "ttm":
            period_type_val = "ttm"
        else:
            period_type_val = "annual"
        conditions.append("period_type = %s")
        params.append(period_type_val)

    # Date / year filter
    if atom.years:
        if len(atom.years) == 1:
            fy = atom.years[0]
            start, end = _fy_date_range(fy)
            conditions.append(f"{date_col} BETWEEN %s AND %s")
            params.extend([start, end])
        else:
            # Multiple years: expand to full range
            min_fy, max_fy = min(atom.years), max(atom.years)
            start, _ = _fy_date_range(min_fy)
            _,   end = _fy_date_range(max_fy)
            conditions.append(f"{date_col} BETWEEN %s AND %s")
            params.extend([start, end])

    # Corporate actions: filter by action_type when the sub_type implies it
    if table == "corporate_actions" and atom.sub_type in ("dividend", "buyback",
                                                           "bonus", "split"):
        action_type_map = {
            "dividend": "Dividend",
            "buyback":  "Buyback",
            "bonus":    "Bonus",
            "split":    "Split",
        }
        conditions.append("action_type = %s")
        params.append(action_type_map[atom.sub_type])

    # Macro: filter by indicator_name when sub_type is "macro"
    if table == "macro_indicators" and atom.sub_type == "macro":
        if atom.raw_text and len(atom.raw_text) < 30:
            conditions.append("LOWER(indicator_name) LIKE %s")
            params.append(f"%{atom.raw_text.lower()}%")

    where_str = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # --- ORDER BY / LIMIT ----------------------------------------------------
    if atom.time_horizon == TimeHorizon.CURRENT and not atom.years:
        order_limit = f"ORDER BY {date_col} DESC LIMIT 5"
    elif atom.years:
        order_limit = f"ORDER BY {date_col} DESC"
    else:
        order_limit = f"ORDER BY {date_col} DESC LIMIT 10"

    sql = f"SELECT {select_str} FROM {table} {where_str} {order_limit}".strip()
    return sql, tuple(params)


# ─────────────────────────────────────────────────────────────────────────────
# SQL executor (MySQL)
# ─────────────────────────────────────────────────────────────────────────────
def _execute_sql_atom(atom: AtomicNeed, db_config: Dict[str, Any]) -> SqlAtomResult:
    """
    Run the SQL for one atom against MySQL, return SqlAtomResult (never raises).
    """
    try:
        sql, params = _build_sql(atom)
    except ValueError as e:
        log.warning(f"  [bridge] SQL build failed for {atom.sub_type}: {e}")
        return SqlAtomResult(atom=atom, error=str(e))

    log.debug(f"  [bridge] SQL: {sql} | params={params}")

    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        # Convert Decimal and date types to native Python types for JSON serialization
        for row in rows:
            for k, v in row.items():
                if hasattr(v, 'isoformat'):  # date/datetime
                    row[k] = v.isoformat()
                elif isinstance(v, decimal.Decimal):
                    row[k] = float(v) if v is not None else None
        log.info(f"  [bridge] {atom.sub_type}: {len(rows)} row(s) from {atom.sql_table}")
        return SqlAtomResult(atom=atom, rows=rows, sql=sql, params=params)

    except MySQLError as e:
        msg = f"MySQL error for {atom.sub_type} ({atom.sql_table}): {e}"
        log.error(f"  [bridge] {msg}")
        return SqlAtomResult(atom=atom, sql=sql, params=params, error=msg)
    except Exception as e:
        msg = f"Unexpected error for {atom.sub_type}: {e}"
        log.error(f"  [bridge] {msg}")
        return SqlAtomResult(atom=atom, sql=sql, params=params, error=msg)
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Vector executor
# ─────────────────────────────────────────────────────────────────────────────
def _execute_vector_atom(atom: AtomicNeed) -> VectorAtomResult:
    """Run a ChromaDB vector query for one atom, return VectorAtomResult."""
    query  = atom.metric        # human-readable label is a good base query
    raw    = atom.raw_text or ""
    if raw and raw.lower() not in query.lower():
        query = f"{query} {raw}"   # enrich with original phrasing

    symbol = atom.symbol or (atom.symbols[0] if atom.symbols else None)
    years  = atom.years or None

    try:
        if atom.need_type == NeedType.FORWARD_LOOKING or \
                (atom.sql_table or "").startswith("chromadb:concalls"):
            chunks = retrieve_concall(query, symbol=symbol, years=years)
        else:
            # QUALITATIVE or fallback
            chunks = retrieve_annual(query, symbol=symbol, years=years)

        log.info(f"  [bridge] {atom.sub_type}: {len(chunks)} chunk(s) from vector store")
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
        mysql_config: Optional[Dict[str, Any]] = None,
        max_workers: int = 8,
    ):
        """
        :param mysql_config: MySQL connection parameters (host, port, user,
                             password, database). If None, uses defaults from
                             environment or DEFAULT_MYSQL_CONFIG.
        :param max_workers:  Maximum threads for parallel fetching.
        """
        self.mysql_config = mysql_config or DEFAULT_MYSQL_CONFIG.copy()
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

        # Step 3: fire all tasks in parallel
        sql_results:    List[SqlAtomResult]    = []
        vector_results: List[VectorAtomResult] = []
        errors:         List[str]              = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {}

            for atom in sql_atoms:
                # Pass the mysql_config to each task
                f = pool.submit(self._safe_sql, atom)
                futures[f] = ("sql", atom)

            for atom in vector_atoms:
                f = pool.submit(self._safe_vector, atom)
                futures[f] = ("vec", atom)

            for fut in as_completed(futures):
                kind, atom = futures[fut]
                try:
                    result = fut.result()
                    if kind == "sql":
                        sql_results.append(result)
                    else:
                        vector_results.append(result)
                    if result.error:
                        errors.append(result.error)
                except Exception as e:
                    msg = f"Unexpected failure in bridge ({atom.sub_type}): {e}"
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

    def _safe_sql(self, atom: AtomicNeed) -> SqlAtomResult:
        return _execute_sql_atom(atom, self.mysql_config)

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