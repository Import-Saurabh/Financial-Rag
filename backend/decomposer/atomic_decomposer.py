from __future__ import annotations
import json
import os
import re
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Optional, Dict, Any

import requests

# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class NeedType(str, Enum):
    QUANTITATIVE    = "quantitative"
    QUALITATIVE     = "qualitative"
    FORWARD_LOOKING = "forward_looking"
    COMPARATIVE     = "comparative"
    TECHNICAL       = "technical"
    MACRO           = "macro"
    OWNERSHIP       = "ownership"


class TimeHorizon(str, Enum):
    HISTORICAL      = "historical"
    CURRENT         = "current"
    FORWARD_LOOKING = "forward_looking"


# ─────────────────────────────────────────────────────────────────────────────
# Sub-type catalogue
# ─────────────────────────────────────────────────────────────────────────────

SUBTYPE_TABLE_MAP: Dict[str, tuple] = {
    # ── Income statement ──────────────────────────────────────────────────────
    # [FIX] "annual_results" was never a real table -> it's `profit_loss`
    # (period_type='annual'|'quarterly'|'ttm' distinguishes the row set).
    "revenue":          ("profit_loss",       ["sales"]),
    "revenue_q":        ("quarterly_results", ["sales"]),
    "operating_profit": ("profit_loss",       ["operating_profit", "opm_pct"]),
    "net_profit":       ("profit_loss",       ["net_profit", "eps"]),
    "net_profit_q":     ("quarterly_results", ["net_profit", "eps"]),
    # [FIX] no `fundamentals` table exists anywhere in mysql_schema_v2.sql, and
    # there is no stored EBITDA column. Use the operating_profit+depreciation
    # proxy (same as ebitda_proxy) so the LLM computes EBITDA itself.
    "ebitda":           ("profit_loss",       ["operating_profit", "depreciation"]),
    # [BUG-EBITDA-CAGR] proxy via profit_loss for per-year EBITDA calculation
    "ebitda_proxy":     ("profit_loss",       ["operating_profit", "depreciation"]),
    "ebit":             ("profit_loss",       []),   # [ORPHANED] see ORPHANED_SUBTYPES
    "depreciation":     ("profit_loss",       ["depreciation"]),
    "interest":         ("profit_loss",       ["interest"]),
    "pbt":              ("profit_loss",       ["profit_before_tax"]),
    "opm":              ("profit_loss",       ["opm_pct"]),
    # [FIX] eps_annual/ttm_eps never existed; profit_loss.eps is the real column
    "eps":              ("profit_loss",       ["eps"]),
    "eps_q":            ("quarterly_results", ["eps"]),
    "tax":              ("profit_loss",       ["tax_pct"]),

    # ── Balance sheet ─────────────────────────────────────────────────────────
    "total_assets":     ("balance_sheet",     ["total_assets"]),
    "total_equity":     ("balance_sheet",     ["total_equity", "equity_capital", "reserves"]),
    "net_worth":        ("balance_sheet",     ["total_equity"]),
    "borrowings":       ("balance_sheet",     ["borrowings", "lt_borrowings", "st_borrowings"]),
    "net_debt":         ("balance_sheet",     ["net_debt"]),
    "cash":             ("balance_sheet",     ["cash_equivalents"]),
    "trade_receivables":("balance_sheet",     ["trade_receivables"]),
    "inventories":      ("balance_sheet",     ["inventories"]),
    "cwip":             ("balance_sheet",     ["cwip"]),
    "fixed_assets":     ("balance_sheet",     ["fixed_assets"]),
    "investments":      ("balance_sheet",     ["investments"]),

    # ── Cash flow ─────────────────────────────────────────────────────────────
    "ocf":              ("cash_flow",         ["cfo"]),
    "cfi":              ("cash_flow",         ["cfi"]),
    "cff":              ("cash_flow",         ["cff"]),
    "capex":            ("cash_flow",         ["capex"]),
    "fcf":              ("cash_flow",         ["free_cash_flow"]),
    "net_cashflow":     ("cash_flow",         ["net_cash_flow"]),
    "fcf_margin":       ("cash_flow",         []),   # [ORPHANED] see ORPHANED_SUBTYPES

    # ── Ratios & valuation ────────────────────────────────────────────────────
    # [FIX] `fundamentals` does not exist anywhere in mysql_schema_v2.sql -- there
    # is no dedicated ratios/valuation table at all. Only two of these have a
    # real home; the rest are flagged in ORPHANED_SUBTYPES instead of pointing
    # at a table that was never created.
    "roe":              ("growth_metrics",    ["roe_last"]),   # latest snapshot only
    "roce":             ("growth_metrics",    []),   # [ORPHANED]
    "roa":              ("growth_metrics",    []),   # [ORPHANED]
    "pe":               ("stocks",            []),   # [ORPHANED]
    "pb":               ("stocks",             []),  # [ORPHANED]
    "ev_ebitda":        ("stocks",            []),   # [ORPHANED]
    "ev_revenue":       ("stocks",            []),   # [ORPHANED]
    "book_value":       ("balance_sheet",     []),   # [ORPHANED]
    "graham_number":    ("stocks",            []),   # [ORPHANED]
    "dividend_yield":   ("stocks",            []),   # [ORPHANED]
    "dividend_payout":  ("profit_loss",       ["dividend_payout_pct"]),  # [FIX] real column
    "debt_equity":      ("balance_sheet",     []),   # [ORPHANED]
    "current_ratio":    ("balance_sheet",     []),   # [ORPHANED]
    "quick_ratio":      ("balance_sheet",     []),   # [ORPHANED]
    "interest_coverage":("profit_loss",       []),   # [ORPHANED]
    "market_cap":       ("stocks",            ["market_cap_cr"]),  # [FIX] real column
    "ev":               ("stocks",            []),   # [ORPHANED]
    "gross_margin":     ("profit_loss",       []),   # [ORPHANED]
    "net_margin":       ("profit_loss",       []),   # [ORPHANED]
    "ebitda_margin":    ("profit_loss",       []),   # [ORPHANED]

    # ── Working capital ───────────────────────────────────────────────────────
    # [ORPHANED] no working-capital-days table/columns exist anywhere in v2.
    "dso":              ("balance_sheet",     []),
    "dio":              ("balance_sheet",     []),
    "dpo":              ("balance_sheet",     []),
    "ccc":              ("balance_sheet",     []),
    "working_capital":  ("balance_sheet",     []),

    # ── Growth metrics ────────────────────────────────────────────────────────
    "revenue_cagr":     ("growth_metrics",    ["sales_cagr_3y", "sales_cagr_5y", "sales_cagr_10y"]),
    "profit_cagr":      ("growth_metrics",    ["profit_cagr_3y", "profit_cagr_5y", "profit_cagr_10y"]),
    "eps_cagr":         ("growth_metrics",    []),   # [ORPHANED] no eps_cagr_* column
    "ebitda_cagr":      ("growth_metrics",    []),   # [ORPHANED] no ebitda_cagr_* column
    "fcf_cagr":         ("growth_metrics",    []),   # [ORPHANED] no fcf_cagr_* column
    "stock_cagr":       ("growth_metrics",    ["stock_cagr_3y", "stock_cagr_5y", "stock_cagr_10y"]),
    "roe_avg":          ("growth_metrics",    ["roe_3y", "roe_5y", "roe_10y"]),

    # ── Price & technicals ────────────────────────────────────────────────────
    "price":            ("price_daily",       ["close", "adj_close"]),
    "price_intraday":   ("price_daily",       []),   # [ORPHANED] no intraday table
    "52w_high":         ("price_daily",       []),   # [ORPHANED] no 52w columns
    "52w_low":          ("price_daily",       []),   # [ORPHANED] no 52w columns
    "rsi":              ("technical_indicators", ["rsi_14"]),
    "macd":             ("technical_indicators", ["macd", "macd_signal", "macd_hist"]),
    "sma":              ("technical_indicators", ["sma_50", "sma_200"]),
    "ema":              ("technical_indicators", ["ema_21"]),
    "bb":               ("technical_indicators", ["bb_upper", "bb_mid", "bb_lower"]),
    "atr":              ("technical_indicators", ["atr_14"]),
    "adx":              ("technical_indicators", ["adx_14"]),
    "supertrend":       ("technical_indicators", ["supertrend", "supertrend_dir"]),
    "vwap":             ("technical_indicators", ["vwap_14"]),
    "obv":              ("technical_indicators", ["obv"]),

    # ── Macro / rates ─────────────────────────────────────────────────────────
    "repo_rate":        ("rbi_rates",         ["repo_rate"]),
    "rbi_policy":       ("rbi_rates",         ["repo_rate", "reverse_repo", "crr", "slr"]),
    "forex":            ("forex_commodities", ["last_price", "change_pct"]),
    "macro":            ("macro_indicators",  ["value", "unit"]),
    "market_index":     ("market_indices",    ["last_price", "change_pct"]),

    # ── Ownership ─────────────────────────────────────────────────────────────
    # [FIX] "ownership"/"ownership_history" were never real tables -> the
    # actual table is `shareholding`, and its %-columns are named directly
    # (fii_pct/dii_pct), not fii_fpi_pct/fii_net_buy_cr which don't exist.
    "promoter":         ("shareholding",      ["promoter_pct"]),
    "fii":              ("shareholding",      ["fii_pct"]),
    "dii":              ("shareholding",      ["dii_pct"]),
    "institutional":    ("shareholding",      ["total_institutional_pct"]),
    "shareholders":     ("shareholding",      ["num_shareholders"]),

    # ── Corporate actions ─────────────────────────────────────────────────────
    "dividend":         ("corporate_actions", ["value"]),
    "buyback":          ("corporate_actions", ["value", "notes"]),
    "split":            ("corporate_actions", ["value", "notes"]),
    "bonus":            ("corporate_actions", ["value", "notes"]),

    # ── Earnings estimates ────────────────────────────────────────────────────
    # [FIX] earnings_estimates/earnings_history/eps_revisions don't exist.
    # The real table is `eps_trend` (current_est vs N-days-ago snapshots).
    "eps_estimate":     ("eps_trend",         ["current_est"]),
    "eps_surprise":     ("eps_trend",         []),   # [ORPHANED] no actual-vs-estimate data
    "eps_revision":     ("eps_trend",         ["current_est", "seven_days_ago", "thirty_days_ago"]),

    # ── Qualitative (vector) ──────────────────────────────────────────────────
    "mda":              ("chromadb:annual_reports", []),
    "risk_factors":     ("chromadb:annual_reports", []),
    "strategy":         ("chromadb:annual_reports", []),
    "business_overview":("chromadb:annual_reports", []),
    "concall_guidance": ("chromadb:concalls",       []),
    "concall_mgmt":     ("chromadb:concalls",       []),
    "concall_outlook":  ("chromadb:concalls",       []),
    "concall_capex":    ("chromadb:concalls",       []),
    "concall_margin":   ("chromadb:concalls",       []),
}

# ─────────────────────────────────────────────────────────────────────────────
# [FIX] Sub-types with no backing table/column anywhere in mysql_schema_v2.sql.
# There is genuinely nowhere for these to come from until a ratios/valuation
# table (or equivalent columns) is added to the schema. schema_bridge.py should
# check this set BEFORE calling _build_sql() and skip straight to "no data
# available for this metric" instead of raising/looking like a broken query.
# Any sub_type mapped above with an empty column list is in this set.
# ─────────────────────────────────────────────────────────────────────────────
ORPHANED_SUBTYPES = frozenset(
    sub_type for sub_type, (table, cols) in SUBTYPE_TABLE_MAP.items()
    if not cols and not table.startswith("chromadb:")
)


# ─────────────────────────────────────────────────────────────────────────────
# AtomicNeed dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AtomicNeed:
    need_type:     NeedType
    sub_type:      str
    metric:        str
    symbol:        Optional[str]  = None
    symbols:       List[str]      = field(default_factory=list)
    years:         List[int]      = field(default_factory=list)
    time_horizon:  TimeHorizon    = TimeHorizon.CURRENT
    period_type:   str            = "annual"
    raw_text:      str            = ""
    confidence:    float          = 1.0
    source:        str            = "rule"
    sql_table:     Optional[str]  = None
    sql_columns:   List[str]      = field(default_factory=list)

    def resolve_schema(self):
        entry = SUBTYPE_TABLE_MAP.get(self.sub_type)
        if entry:
            self.sql_table, self.sql_columns = entry

    def to_dict(self) -> dict:
        d = asdict(self)
        d["need_type"]    = self.need_type.value
        d["time_horizon"] = self.time_horizon.value
        return d


# ─────────────────────────────────────────────────────────────────────────────
# Year extraction helpers  [BUG-YOY-MULTI-YEAR] [BUG-CAGR-YEAR-PARSE]
# ─────────────────────────────────────────────────────────────────────────────

def _extract_years(query: str) -> List[int]:
    """
    Extract all fiscal years mentioned in the query and expand ranges.

    Handles:
      FY25, FY2025, 2025
      FY23-25, FY2023-25, FY23 to FY25, FY2023 to FY2025
      "financial year 2023-25", "FY23-FY25"
    """
    q = query.upper()
    years: set = set()

    # ── Explicit range: "FY23-25", "FY2023-25", "FY23-FY25" ─────────────────
    # Pattern: FY\d{2,4}[-–to]+(?:FY)?\d{2,4}
    for m in re.finditer(
        r"FY(\d{2,4})\s*[-–to]+\s*(?:FY)?(\d{2,4})", q
    ):
        y1 = _normalise_fy(m.group(1))
        y2 = _normalise_fy(m.group(2))
        if y1 and y2 and y1 <= y2:
            years.update(range(y1, y2 + 1))

    # ── "financial year YYYY-YY" ──────────────────────────────────────────────
    for m in re.finditer(r"(?:FINANCIAL\s+YEAR|FY)\s*(\d{4})\s*[-–]\s*(\d{2,4})", q):
        y1 = int(m.group(1))
        y2_raw = m.group(2)
        y2 = y1 + 1 if len(y2_raw) == 2 else int(y2_raw)
        if y2 < y1:
            y2 += (y1 // 100) * 100
        years.update(range(y1, y2 + 1))

    # ── Individual FY mentions ────────────────────────────────────────────────
    for m in re.finditer(r"FY\s*(\d{2,4})", q):
        y = _normalise_fy(m.group(1))
        if y:
            years.add(y)

    # ── Bare 4-digit years 20xx ───────────────────────────────────────────────
    for m in re.finditer(r"\b(20\d{2})\b", q):
        years.add(int(m.group(1)))

    return sorted(years)


def _normalise_fy(s: str) -> Optional[int]:
    """Convert "23", "2023", "25" → fiscal year int (e.g. 2023, 2025)."""
    n = int(s)
    if n < 100:                      # 2-digit short form e.g. "25" → 2025
        n += 2000
    if 2000 <= n <= 2099:
        return n
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Rule-based pattern library
# ─────────────────────────────────────────────────────────────────────────────

_RULES: List[tuple] = [
    # Revenue / Sales
    (r"\b(revenue|sales|topline|top[\s\-]line|income from operations)\b",
     NeedType.QUANTITATIVE, "revenue", "Revenue", None),
    (r"\bquarterly\s+(revenue|sales)\b",
     NeedType.QUANTITATIVE, "revenue_q", "Quarterly Revenue", None),

    # Profit
    (r"\b(net\s+profit|pat|profit\s+after\s+tax|net\s+income|bottom[\s\-]?line)\b",
     NeedType.QUANTITATIVE, "net_profit", "Net Profit", None),
    (r"\b(quarterly\s+profit|quarterly\s+pat|quarterly\s+net\s+profit)\b",
     NeedType.QUANTITATIVE, "net_profit_q", "Quarterly Net Profit", None),
    # [FIX] bare "profit" (e.g. "what is the profit this quarter") never
    # matched anything above -> decompose() returned 0 atoms. This is a
    # deliberately loose fallback, so it excludes phrases already owned by a
    # more specific rule (operating profit, gross profit, profit before tax,
    # profit cagr/margin/estimate) to avoid double-firing both atoms.
    (r"(?<!operating\s)(?<!gross\s)\bprofit\b(?!\s*(before\s+tax|margin|cagr|estimate|surprise|revision))",
     NeedType.QUANTITATIVE, "net_profit", "Net Profit", None),
    (r"\b(pbt|profit\s+before\s+tax)\b",
     NeedType.QUANTITATIVE, "pbt", "PBT", None),
    (r"\b(operating\s+profit|ebit(?!da)|earnings\s+before\s+interest\s+and\s+tax)\b",
     NeedType.QUANTITATIVE, "operating_profit", "Operating Profit / EBIT", None),
    (r"\b(ebitda|earnings\s+before\s+interest.{0,6}tax.{0,6}depreciation)\b",
     NeedType.QUANTITATIVE, "ebitda", "EBITDA", None),

    # Margins
    (r"\b(opm|operating\s+margin|operating\s+profit\s+margin)\b",
     NeedType.QUANTITATIVE, "opm", "OPM %", None),
    (r"\b(ebitda\s+margin)\b",
     NeedType.QUANTITATIVE, "ebitda_margin", "EBITDA Margin %", None),
    (r"\b(net\s+(profit\s+)?margin|npm)\b",
     NeedType.QUANTITATIVE, "net_margin", "Net Margin %", None),
    (r"\b(gross\s+margin)\b",
     NeedType.QUANTITATIVE, "gross_margin", "Gross Margin %", None),
    (r"\bebit\s+margin\b",
     NeedType.QUANTITATIVE, "ebit", "EBIT Margin %", None),

    # EPS
    (r"\b(eps|earnings\s+per\s+share|diluted\s+eps|basic\s+eps)\b",
     NeedType.QUANTITATIVE, "eps", "EPS", None),
    (r"\b(eps\s+estimate|forward\s+eps|projected\s+eps|consensus\s+eps)\b",
     NeedType.QUANTITATIVE, "eps_estimate", "EPS Estimate", TimeHorizon.FORWARD_LOOKING),
    (r"\b(eps\s+surprise|beat|miss)\b",
     NeedType.QUANTITATIVE, "eps_surprise", "EPS Surprise", None),
    (r"\b(eps\s+revision)\b",
     NeedType.QUANTITATIVE, "eps_revision", "EPS Revision", None),

    # Balance sheet
    (r"\b(total\s+assets?)\b",
     NeedType.QUANTITATIVE, "total_assets", "Total Assets", None),
    (r"\b(shareholders[\s\']*\s*equity|net\s+worth|book\s+equity|total\s+equity)\b",
     NeedType.QUANTITATIVE, "total_equity", "Total Equity / Net Worth", None),
    (r"\b(net\s+debt)\b",
     NeedType.QUANTITATIVE, "net_debt", "Net Debt", None),
    (r"\b(total\s+(?:debt|borrowings?)|long[\s\-]term\s+debt|lt\s+borrowings?|borrowings?(?:\s+and)?)\b",
     NeedType.QUANTITATIVE, "borrowings", "Total Borrowings", None),
    (r"\b(cash\s+(?:and\s+(?:cash\s+)?equivalents?)?|cash\s+on\s+hand)\b",
     NeedType.QUANTITATIVE, "cash", "Cash & Equivalents", None),
    (r"\b(trade\s+receivables?|debtors?)\b",
     NeedType.QUANTITATIVE, "trade_receivables", "Trade Receivables", None),
    (r"\b(inventori(?:es|y)|stock[\s\-]in[\s\-]trade)\b",
     NeedType.QUANTITATIVE, "inventories", "Inventories", None),
    (r"\b(cwip|capital\s+work[\s\-]+in[\s\-]+progress)\b",
     NeedType.QUANTITATIVE, "cwip", "CWIP", None),
    (r"\b(fixed\s+assets?|net\s+block|property\s+plant\s+equipment|ppe)\b",
     NeedType.QUANTITATIVE, "fixed_assets", "Fixed Assets / Net Block", None),
    (r"\b(investments?)\b",
     NeedType.QUANTITATIVE, "investments", "Investments", None),

    # Cash flow
    (r"\b(ocf|operating\s+cash\s+flow|cash\s+from\s+operations?|cfo)\b",
     NeedType.QUANTITATIVE, "ocf", "Operating Cash Flow", None),
    (r"\b(capex|capital\s+expenditure|cap(?:ital)?\s+ex)\b",
     NeedType.QUANTITATIVE, "capex", "Capex", None),
    (r"\b(fcf|free\s+cash\s+flow)\b",
     NeedType.QUANTITATIVE, "fcf", "Free Cash Flow", None),
    (r"\b(cfi|cash\s+from\s+investing)\b",
     NeedType.QUANTITATIVE, "cfi", "Cash from Investing", None),
    (r"\b(cff|cash\s+from\s+financing)\b",
     NeedType.QUANTITATIVE, "cff", "Cash from Financing", None),
    (r"\b(fcf\s+margin)\b",
     NeedType.QUANTITATIVE, "fcf_margin", "FCF Margin %", None),

    # Growth / CAGR
    (r"\b(revenue\s+cagr|sales\s+cagr|revenue\s+growth)\b",
     NeedType.QUANTITATIVE, "revenue_cagr", "Revenue CAGR", None),
    (r"\b(profit\s+cagr|earnings\s+cagr|pat\s+cagr)\b",
     NeedType.QUANTITATIVE, "profit_cagr", "Profit CAGR", None),
    (r"\b(eps\s+cagr|eps\s+growth)\b",
     NeedType.QUANTITATIVE, "eps_cagr", "EPS CAGR", None),
    (r"\b(ebitda\s+cagr|ebitda\s+growth)\b",
     NeedType.QUANTITATIVE, "ebitda_cagr", "EBITDA CAGR", None),
    (r"\b(stock\s+(?:price\s+)?cagr|price\s+cagr|stock\s+return)\b",
     NeedType.QUANTITATIVE, "stock_cagr", "Stock Price CAGR", None),

    # Return ratios
    (r"\b(roe|return\s+on\s+equity|return\s+on\s+net\s+worth|ronw)\b",
     NeedType.QUANTITATIVE, "roe", "ROE", None),
    (r"\b(roce|return\s+on\s+capital\s+employed)\b",
     NeedType.QUANTITATIVE, "roce", "ROCE", None),
    (r"\b(roa|return\s+on\s+assets?)\b",
     NeedType.QUANTITATIVE, "roa", "ROA", None),

    # Valuation
    (r"\b(p/?e\s+ratio|price\s+to\s+earnings|pe\s+multiple|ttm\s+pe|forward\s+pe)\b",
     NeedType.QUANTITATIVE, "pe", "P/E Ratio", None),
    (r"\b(p[/\s]b(?:\s+(?:ratio|multiple))?|price[\s\-]to[\s\-]book|pb\s+(?:ratio|multiple)|price\s+to\s+book)\b",
     NeedType.QUANTITATIVE, "pb", "P/B Ratio", None),
    (r"\b(ev[/\s]ebitda|enterprise\s+value\s+to\s+ebitda)\b",
     NeedType.QUANTITATIVE, "ev_ebitda", "EV/EBITDA", None),
    (r"\b(market\s+cap(?:italisation)?|mcap)\b",
     NeedType.QUANTITATIVE, "market_cap", "Market Cap", None),
    (r"\b(graham\s+number)\b",
     NeedType.QUANTITATIVE, "graham_number", "Graham Number", None),
    (r"\b(book\s+value(?:\s+per\s+share)?|bvps)\b",
     NeedType.QUANTITATIVE, "book_value", "Book Value", None),
    (r"\b(dividend\s+yield)\b",
     NeedType.QUANTITATIVE, "dividend_yield", "Dividend Yield", None),
    (r"\b(dividend\s+payout)\b",
     NeedType.QUANTITATIVE, "dividend_payout", "Dividend Payout %", None),

    # Leverage
    (r"\b(debt[\s\-]to[\s\-]equity|d[/\s]e\s+ratio|leverage\s+ratio)\b",
     NeedType.QUANTITATIVE, "debt_equity", "D/E Ratio", None),
    (r"\b(current\s+ratio)\b",
     NeedType.QUANTITATIVE, "current_ratio", "Current Ratio", None),
    (r"\b(quick\s+ratio|acid\s+test)\b",
     NeedType.QUANTITATIVE, "quick_ratio", "Quick Ratio", None),
    (r"\b(interest\s+coverage)\b",
     NeedType.QUANTITATIVE, "interest_coverage", "Interest Coverage", None),

    # Working capital
    (r"\b(dso|debtor\s+days?|days?\s+sales?\s+outstanding)\b",
     NeedType.QUANTITATIVE, "dso", "DSO (Days)", None),
    (r"\b(dio|inventory\s+days?|days?\s+inventory\s+outstanding)\b",
     NeedType.QUANTITATIVE, "dio", "DIO (Days)", None),
    (r"\b(dpo|payable\s+days?|days?\s+payable\s+outstanding)\b",
     NeedType.QUANTITATIVE, "dpo", "DPO (Days)", None),
    (r"\b(ccc|cash\s+conversion\s+cycle)\b",
     NeedType.QUANTITATIVE, "ccc", "Cash Conversion Cycle", None),
    (r"\b(working\s+capital\s+days?)\b",
     NeedType.QUANTITATIVE, "working_capital", "Working Capital Days", None),

    # Technicals
    (r"\b(52[\s\-]week\s+(?:high|low)|52[\s\-]?w[\s\-]?(?:high|low))\b",
     NeedType.TECHNICAL, "52w_high", "52-Week High/Low", TimeHorizon.CURRENT),
    (r"\b(rsi(?:[\s\-]14)?)\b",
     NeedType.TECHNICAL, "rsi", "RSI(14)", TimeHorizon.CURRENT),
    (r"\b(macd)\b",
     NeedType.TECHNICAL, "macd", "MACD", TimeHorizon.CURRENT),
    (r"\b(sma[\s\-]?50|50[\s\-](?:day\s+)?sma)\b",
     NeedType.TECHNICAL, "sma", "SMA-50", TimeHorizon.CURRENT),
    (r"\b(sma[\s\-]?200|200[\s\-](?:day\s+)?sma)\b",
     NeedType.TECHNICAL, "sma", "SMA-200", TimeHorizon.CURRENT),
    (r"\b(ema[\s\-]?21|21[\s\-]day\s+ema)\b",
     NeedType.TECHNICAL, "ema", "EMA-21", TimeHorizon.CURRENT),
    (r"\b(supertrend)\b",
     NeedType.TECHNICAL, "supertrend", "Supertrend", TimeHorizon.CURRENT),
    (r"\b(atr|average\s+true\s+range)\b",
     NeedType.TECHNICAL, "atr", "ATR(14)", TimeHorizon.CURRENT),
    (r"\b(adx)\b",
     NeedType.TECHNICAL, "adx", "ADX(14)", TimeHorizon.CURRENT),
    (r"\b(vwap)\b",
     NeedType.TECHNICAL, "vwap", "VWAP", TimeHorizon.CURRENT),
    (r"\b(obv|on[\s\-]balance\s+volume)\b",
     NeedType.TECHNICAL, "obv", "OBV", TimeHorizon.CURRENT),
    (r"\b(current\s+price|stock\s+price|share\s+price|cmp|ltp)\b",
     NeedType.TECHNICAL, "price", "Current Price", TimeHorizon.CURRENT),

    # Macro
    (r"\b(repo\s+rate|rbi\s+rate|policy\s+rate)\b",
     NeedType.MACRO, "repo_rate", "Repo Rate", TimeHorizon.CURRENT),
    (r"\b(rbi\s+policy|monetary\s+policy)\b",
     NeedType.MACRO, "rbi_policy", "RBI Policy", TimeHorizon.CURRENT),
    (r"\b(usd[/\-]inr|dollar[\s\-]rupee|forex|currency)\b",
     NeedType.MACRO, "forex", "Forex / USD-INR", TimeHorizon.CURRENT),
    (r"\b(gdp|gross\s+domestic\s+product)\b",
     NeedType.MACRO, "macro", "GDP", None),
    (r"\b(inflation|cpi|wpi)\b",
     NeedType.MACRO, "macro", "Inflation", None),
    (r"\b(nifty|sensex|market\s+index)\b",
     NeedType.MACRO, "market_index", "Market Index", TimeHorizon.CURRENT),

    # Ownership
    (r"\b(promoter\s+(?:holding|stake|pledging?|ownership))\b",
     NeedType.OWNERSHIP, "promoter", "Promoter Holding", None),
    (r"\b(fii\s+(?:holding|stake|buying|selling|flow)|foreign\s+institutional)\b",
     NeedType.OWNERSHIP, "fii", "FII Holding", None),
    (r"\b(dii\s+(?:holding|stake|buying|selling|flow)|domestic\s+institutional)\b",
     NeedType.OWNERSHIP, "dii", "DII Holding", None),
    (r"\b(institutional\s+(?:holding|ownership))\b",
     NeedType.OWNERSHIP, "institutional", "Institutional Holding", None),

    # Corporate actions
    (r"\b(dividends?(?:\s+(?:history|declared|per\s+share|paid))?|dps)\b",
     NeedType.QUANTITATIVE, "dividend", "Dividend", None),
    (r"\b(buyback|buy[\s\-]back|share\s+repurchase)\b",
     NeedType.QUANTITATIVE, "buyback", "Buyback", None),
    (r"\b(bonus\s+(?:share|issue))\b",
     NeedType.QUANTITATIVE, "bonus", "Bonus Issue", None),
    (r"\b(stock\s+split|share\s+split)\b",
     NeedType.QUANTITATIVE, "split", "Stock Split", None),

    # Qualitative / forward-looking
    (r"\b(risk\s+(?:factors?|management|disclos))\b",
     NeedType.QUALITATIVE, "risk_factors", "Risk Factors", None),
    (r"\b(management\s+(?:discussion|analysis|commentary)|mda)\b",
     NeedType.QUALITATIVE, "mda", "MD&A", None),
    (r"\b(business\s+(?:overview|model|strategy|segment))\b",
     NeedType.QUALITATIVE, "business_overview", "Business Overview", None),
    (r"\b(strategy|strategic\s+(?:plan|initiative|direction))\b",
     NeedType.QUALITATIVE, "strategy", "Strategy", None),
    (r"\b(outlook|guidance|demand\s+environment|going\s+forward|forecast|expect)\b",
     NeedType.FORWARD_LOOKING, "concall_outlook", "Outlook / Guidance", TimeHorizon.FORWARD_LOOKING),
    (r"\b(management\s+(?:commentary|view|stance)|concall|earnings\s+call)\b",
     NeedType.FORWARD_LOOKING, "concall_mgmt", "Management Commentary", TimeHorizon.FORWARD_LOOKING),
    (r"\b(capex\s+(?:guidance|plan|target))\b",
     NeedType.FORWARD_LOOKING, "concall_capex", "Capex Guidance", TimeHorizon.FORWARD_LOOKING),
    (r"\b(margin\s+(?:guidance|target|outlook))\b",
     NeedType.FORWARD_LOOKING, "concall_margin", "Margin Guidance", TimeHorizon.FORWARD_LOOKING),
]

# Compile once
_COMPILED_RULES = [(re.compile(pat, re.IGNORECASE), nt, st, metric, hint)
                   for pat, nt, st, metric, hint in _RULES]


# ─────────────────────────────────────────────────────────────────────────────
# [BUG-EBITDA-CAGR] EBITDA multi-year detection
# ─────────────────────────────────────────────────────────────────────────────

def _is_ebitda_multi_year_query(query: str, years: List[int]) -> bool:
    """
    Returns True when the query asks for EBITDA across multiple years
    (CAGR, YoY, trend, comparison) and the fundamentals table won't
    have the per-year data.
    """
    q = query.lower()
    is_multi_year = len(years) > 1 or bool(re.search(
        r'\b(cagr|yoy|year[\s\-]on[\s\-]year|trend|comparison|compare|growth|'
        r'fy2[0-9]\d?\s*[-–to]+\s*(?:fy)?2[0-9])\b', q
    ))
    has_ebitda = bool(re.search(r'\bebitda\b', q))
    return has_ebitda and is_multi_year


# ─────────────────────────────────────────────────────────────────────────────
# Rule-based decomposer
# ─────────────────────────────────────────────────────────────────────────────

def _rule_based_decompose(query: str, symbol: Optional[str] = None) -> List[AtomicNeed]:
    q_lower  = query.lower()
    years    = _extract_years(query)
    horizon  = (
        TimeHorizon.FORWARD_LOOKING
        if any(kw in q_lower for kw in ["outlook", "guidance", "expect", "h1 fy", "h2 fy",
                                         "going forward", "forecast", "next year"])
        else TimeHorizon.HISTORICAL if years else TimeHorizon.CURRENT
    )

    # [FIX] period_type was hardcoded to "annual" below regardless of query
    # content -> "what is the profit THIS QUARTER" would silently fetch
    # annual data. Detect quarter-phrasing here and (a) set period_type so
    # tables that support it (profit_loss/cash_flow/balance_sheet) filter
    # correctly, and (b) remap sub_types that have a dedicated quarterly
    # table (revenue->revenue_q, net_profit->net_profit_q, eps->eps_q).
    is_quarterly = bool(re.search(
        r"\b(this\s+quarter|last\s+quarter|latest\s+quarter|current\s+quarter|"
        r"quarterly|q[1-4]\s*fy?\s*\d{0,4}|qoq)\b", q_lower))
    _QUARTERLY_REMAP = {"revenue": "revenue_q", "net_profit": "net_profit_q", "eps": "eps_q"}

    seen:  set          = set()
    atoms: List[AtomicNeed] = []

    for compiled_pat, need_type, sub_type, metric, time_hint in _COMPILED_RULES:
        if not compiled_pat.search(query):
            continue

        effective_sub_type = sub_type
        if is_quarterly and sub_type in _QUARTERLY_REMAP:
            effective_sub_type = _QUARTERLY_REMAP[sub_type]

        if effective_sub_type in seen:
            continue
        seen.add(effective_sub_type)

        effective_horizon = time_hint if time_hint else horizon
        atom = AtomicNeed(
            need_type    = need_type,
            sub_type     = effective_sub_type,
            metric       = metric,
            symbol       = symbol,
            years        = years,
            time_horizon = effective_horizon,
            period_type  = "quarterly" if is_quarterly else "annual",
            raw_text     = query[:80],
            source       = "rule",
        )
        atom.resolve_schema()
        atoms.append(atom)

    # [BUG-EBITDA-CAGR] If EBITDA is requested across multiple years,
    # also add an ebitda_proxy atom pointing to annual_results so the
    # bridge can fetch per-year operating_profit + depreciation
    if _is_ebitda_multi_year_query(query, years) and "ebitda_proxy" not in seen:
        proxy = AtomicNeed(
            need_type    = NeedType.QUANTITATIVE,
            sub_type     = "ebitda_proxy",
            metric       = "EBITDA (Operating Profit + Depreciation)",
            symbol       = symbol,
            years        = years,
            time_horizon = TimeHorizon.HISTORICAL,
            period_type  = "annual",
            raw_text     = query[:80],
            source       = "rule",
        )
        proxy.resolve_schema()
        atoms.append(proxy)

    return atoms


# ─────────────────────────────────────────────────────────────────────────────
# LLM system prompt for fallback decomposition
# ─────────────────────────────────────────────────────────────────────────────

_LLM_SYSTEM_PROMPT = """You decompose financial queries into atomic needs.
Return ONLY a JSON array (no markdown, no explanation).
Each element must have exactly these fields:
  need_type: "quantitative"|"qualitative"|"forward_looking"|"comparative"|"technical"|"macro"|"ownership"
  sub_type:  (key from the schema map — e.g. "revenue","net_profit","ebitda","roce","mda","concall_outlook")
  metric:    (human label, e.g. "Revenue", "EBITDA", "ROCE")
  symbol:    company ticker or null
  years:     list of ints (fiscal year end, e.g. [2023,2024,2025]) or []
  time_horizon: "historical"|"current"|"forward_looking"
  period_type: "annual"|"quarterly"|"ttm"
  confidence: 0.0-1.0
  raw_text: short phrase from query
Example output:
[{"need_type":"quantitative","sub_type":"revenue","metric":"Revenue","symbol":"RELIANCE",
  "years":[2024,2025],"time_horizon":"historical","period_type":"annual",
  "confidence":1.0,"raw_text":"revenue FY24-25"}]"""


def _llm_decompose(
    query:   str,
    api_key: str,
    api_url: str,
    model:   str,
) -> List[AtomicNeed]:
    try:
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {api_key}"}
        if "openrouter" in api_url:
            headers["HTTP-Referer"] = "https://github.com/QuantCoPilot"
            headers["X-Title"]      = "Quant CoPilot Decomposer"

        payload = {
            "model":    model,
            "messages": [
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {"role": "user",   "content": f"Query: {query}"},
            ],
            "max_tokens":  800,
            "temperature": 0.0,
        }
        resp = requests.post(api_url, json=payload, headers=headers, timeout=20)
        resp.raise_for_status()

        raw_text = resp.json()["choices"][0]["message"]["content"].strip()
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

        items = json.loads(raw_text)
        atoms = []
        for item in items:
            atom = AtomicNeed(
                need_type    = NeedType(item.get("need_type", "qualitative")),
                sub_type     = item.get("sub_type", "mda"),
                metric       = item.get("metric", ""),
                symbol       = item.get("symbol"),
                symbols      = item.get("symbols", []),
                years        = item.get("years", []),
                time_horizon = TimeHorizon(item.get("time_horizon", "current")),
                period_type  = item.get("period_type", "annual"),
                raw_text     = item.get("raw_text", ""),
                confidence   = float(item.get("confidence", 0.8)),
                source       = "llm",
            )
            atom.resolve_schema()
            atoms.append(atom)
        return atoms

    except Exception as e:
        log.error(f"LLM Decompose Error: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# AtomicDecomposer  (public interface)
# ─────────────────────────────────────────────────────────────────────────────

class AtomicDecomposer:
    """
    Main decomposer class.

    Usage:
        decomposer = AtomicDecomposer()
        atoms = decomposer.decompose("What is ADANIPORTS EBITDA CAGR FY23-25?",
                                     symbol="ADANIPORTS")
    """

    def __init__(
        self,
        api_key:        Optional[str] = None,
        api_url:        Optional[str] = None,
        model:          Optional[str] = None,
        min_rule_atoms: int = 1,
    ):
        self.api_key  = api_key  or os.getenv("DEEPSEEK_API_KEY", "") \
                                 or os.getenv("OPENROUTER_API_KEY", "")
        self.api_url  = api_url  or (
            "https://api.deepseek.com/chat/completions"
            if os.getenv("DEEPSEEK_API_KEY")
            else "https://openrouter.ai/api/v1/chat/completions"
        )
        self.model    = model or (
            "deepseek-chat"
            if os.getenv("DEEPSEEK_API_KEY")
            else "qwen/qwen3-8b:free"
        )
        self.min_rule_atoms = min_rule_atoms

    def decompose(
        self,
        query:  str,
        symbol: Optional[str] = None,   # [BUG-SYMBOL-NOT-INJECTED] new param
    ) -> List[AtomicNeed]:
        """
        Decompose a user query into a list of AtomicNeed objects.
        symbol is stamped onto every atom that has symbol=None.
        """
        rule_atoms = _rule_based_decompose(query, symbol=symbol)

        if len(rule_atoms) >= self.min_rule_atoms:
            atoms = rule_atoms
        elif self.api_key:
            llm_atoms  = _llm_decompose(query, self.api_key, self.api_url, self.model)
            seen       = {a.sub_type for a in rule_atoms}
            merged     = list(rule_atoms)
            for atom in llm_atoms:
                if atom.sub_type not in seen:
                    merged.append(atom)
                    seen.add(atom.sub_type)
            atoms = merged
        else:
            atoms = rule_atoms

        # [BUG-SYMBOL-NOT-INJECTED] stamp symbol onto atoms that don't have one
        if symbol:
            for atom in atoms:
                if not atom.symbol:
                    atom.symbol = symbol

        return atoms

    def decompose_verbose(self, query: str, symbol: Optional[str] = None) -> dict:
        t0    = time.perf_counter()
        atoms = self.decompose(query, symbol=symbol)
        elapsed = time.perf_counter() - t0

        need_type_counts: Dict[str, int] = {}
        symbols_seen: set = set()
        years_seen:   set = set()
        channels:     set = set()

        for atom in atoms:
            k = atom.need_type.value
            need_type_counts[k] = need_type_counts.get(k, 0) + 1
            if atom.symbol:
                symbols_seen.add(atom.symbol)
            symbols_seen.update(atom.symbols)
            years_seen.update(atom.years)
            if atom.need_type in (NeedType.QUANTITATIVE, NeedType.OWNERSHIP,
                                   NeedType.MACRO, NeedType.TECHNICAL):
                channels.add("sql")
            if atom.need_type == NeedType.QUALITATIVE:
                channels.add("vector")
            if atom.need_type == NeedType.FORWARD_LOOKING:
                channels.add("concall")
            if atom.need_type == NeedType.COMPARATIVE:
                channels.update(["sql", "vector"])

        return {
            "query":       query,
            "atoms":       [a.to_dict() for a in atoms],
            "atom_count":  len(atoms),
            "need_types":  need_type_counts,
            "channels":    sorted(channels),
            "symbols":     sorted(symbols_seen),
            "years":       sorted(years_seen),
            "elapsed_ms":  round(elapsed * 1000, 2),
        }