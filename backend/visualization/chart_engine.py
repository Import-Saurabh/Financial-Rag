from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    import plotly.graph_objects as go
    import plotly.express as px
    _HAS_PLOTLY = True
except ImportError:
    _HAS_PLOTLY = False

try:
    from utils.logger import get_logger
    log = get_logger(__name__)
except Exception:
    import logging
    log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Professional Financial Color Palettes
# ─────────────────────────────────────────────────────────────────────────────
PALETTES = {
    "profit": {
        "primary": "#10B981",    # Emerald
        "secondary": "#059669",
        "light": "rgba(16, 185, 129, 0.2)",
        "gradient": ["#10B981", "#34D399", "#6EE7B7"],
    },
    "revenue": {
        "primary": "#3B82F6",    # Sapphire Blue
        "secondary": "#1D4ED8",
        "light": "rgba(59, 130, 246, 0.2)",
        "gradient": ["#3B82F6", "#60A5FA", "#93C5FD"],
    },
    "ebitda": {
        "primary": "#6366F1",    # Indigo
        "secondary": "#4338CA",
        "light": "rgba(99, 102, 241, 0.2)",
        "gradient": ["#6366F1", "#818CF8", "#A5B4FC"],
    },
    "cashflow": {
        "primary": "#8B5CF6",    # Violet Purple
        "secondary": "#6D28D9",
        "light": "rgba(139, 92, 246, 0.2)",
        "gradient": ["#8B5CF6", "#A78BFA", "#C4B5FD"],
    },
    "expense": {
        "primary": "#EF4444",    # Crimson
        "secondary": "#DC2626",
        "light": "rgba(239, 68, 68, 0.2)",
        "gradient": ["#EF4444", "#F87171", "#FCA5A5"],
    },
    "debt": {
        "primary": "#F59E0B",    # Amber Gold
        "secondary": "#D97706",
        "light": "rgba(245, 158, 11, 0.2)",
        "gradient": ["#F59E0B", "#FBBF24", "#FDE68A"],
    },
    "margin": {
        "primary": "#06B6D4",    # Cyan / Teal
        "secondary": "#0891B2",
        "light": "rgba(6, 182, 212, 0.2)",
        "gradient": ["#06B6D4", "#22D3EE", "#67E8F9"],
    },
    "shareholding": [
        "#3B82F6",  # Promoter (Blue)
        "#10B981",  # FII (Emerald)
        "#F59E0B",  # DII (Amber)
        "#8B5CF6",  # Public (Purple)
        "#06B6D4",  # Others (Cyan)
    ],
    "multi_series": [
        "#10B981", "#3B82F6", "#F59E0B", "#8B5CF6", "#06B6D4", "#EC4899", "#14B8A6"
    ]
}


def _get_metric_palette(sub_type: str) -> Dict[str, Any]:
    st = sub_type.lower()
    if any(k in st for k in ["profit", "pat", "net_profit", "pbt", "eps"]):
        return PALETTES["profit"]
    if any(k in st for k in ["revenue", "sales", "topline", "turnover"]):
        return PALETTES["revenue"]
    if any(k in st for k in ["ebitda", "ebit", "opm", "operating_profit"]):
        return PALETTES["ebitda"]
    if any(k in st for k in ["cash", "cfo", "cfi", "cff", "fcf", "flow"]):
        return PALETTES["cashflow"]
    if any(k in st for k in ["expense", "tax", "depreciation", "interest"]):
        return PALETTES["expense"]
    if any(k in st for k in ["debt", "borrowing", "liability", "liabilities"]):
        return PALETTES["debt"]
    if any(k in st for k in ["margin", "ratio", "roe", "roce", "roa"]):
        return PALETTES["margin"]
    return PALETTES["revenue"]


# ─────────────────────────────────────────────────────────────────────────────
# Financial KPI Calculations
# ─────────────────────────────────────────────────────────────────────────────

def calculate_cagr(start_val: float, end_val: float, periods: int) -> Optional[float]:
    """Calculate Compound Annual Growth Rate in percentage."""
    if periods <= 0 or start_val <= 0 or end_val <= 0:
        return None
    try:
        cagr = ((end_val / start_val) ** (1.0 / periods) - 1.0) * 100.0
        return round(cagr, 2)
    except Exception:
        return None


def calculate_yoy_growth(series: List[float]) -> List[Optional[float]]:
    """Compute YoY % changes across a chronological series."""
    growth = [None]
    for i in range(1, len(series)):
        prev = series[i - 1]
        curr = series[i]
        if prev and prev != 0:
            pct = ((curr - prev) / abs(prev)) * 100.0
            growth.append(round(pct, 1))
        else:
            growth.append(None)
    return growth


def format_currency_value(val: Optional[float], unit: str = "crore") -> str:
    """Format numerical value with proper financial notation."""
    if val is None or math.isnan(val):
        return "N/A"
    unit_lower = unit.lower()
    if unit_lower in ("%", "pct"):
        return f"{val:.1f}%"
    if unit_lower in ("x", "times"):
        return f"{val:.2f}x"
    if unit_lower in ("rs", "₹", "inr"):
        return f"₹{val:,.2f}"
    if unit_lower in ("crore", "cr"):
        if abs(val) >= 1000:
            return f"₹{val:,.1f} Cr"
        return f"₹{val:.2f} Cr"
    if unit_lower in ("lakh", "lac"):
        return f"₹{val:,.2f} Lakh"
    return f"{val:,.2f} {unit}".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Financial Chart Engine
# ─────────────────────────────────────────────────────────────────────────────

class FinancialChartEngine:
    """
    Analyzes SQL financial data and query intent to generate visually appealing,
    interactive financial charts (Bar, Line, Area, Waterfall, Donut, Stacked Bar, Radar).
    """

    def __init__(self):
        pass

    def generate_charts(
        self,
        query: str,
        metric_rows: Optional[List[Any]] = None,
        sql_results: Optional[List[Any]] = None,
        symbol: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Main entry point to detect and generate appropriate financial charts.
        Returns a list of structured chart objects.
        """
        charts: List[Dict[str, Any]] = []
        q_lower = query.lower()

        # Extract metric rows from FusionResult or direct list
        rows = self._extract_clean_rows(metric_rows, sql_results)
        if not rows:
            return charts

        sym = symbol or self._detect_symbol(rows, query)

        # 1. Check for Shareholding breakdown (Donut / Pie)
        shareholding_chart = self._try_build_shareholding_chart(rows, sym, q_lower)
        if shareholding_chart:
            charts.append(shareholding_chart)

        # 2. Check for P&L Waterfall breakdown
        waterfall_chart = self._try_build_waterfall_chart(rows, sym, q_lower)
        if waterfall_chart:
            charts.append(waterfall_chart)

        # 3. Check for Multi-year Time Series / Trend / CAGR Charts (Bar & Line)
        # Skip redundant percentage bar charts if shareholding donut already present and user didn't ask for trend
        if not shareholding_chart or any(k in q_lower for k in ["trend", "cagr", "growth", "history"]):
            trend_charts = self._build_time_series_charts(rows, sym, q_lower)
            if trend_charts:
                charts.extend(trend_charts)

        # 4. Check for Multi-metric Financial Health Profile (Radar / Grouped Bar)
        if any(k in q_lower for k in ["radar", "health", "scorecard", "ratios", "overview", "fundamentals"]):
            radar_chart = self._try_build_radar_chart(rows, sym)
            if radar_chart:
                charts.append(radar_chart)

        return charts

    # ── Data Extraction & Grouping ────────────────────────────────────────────

    def _extract_clean_rows(
        self, metric_rows: Optional[List[Any]], sql_results: Optional[List[Any]]
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []

        if metric_rows:
            for r in metric_rows:
                if isinstance(r, dict):
                    out.append(r)
                else:
                    # Dataclass MetricRow
                    out.append({
                        "symbol": getattr(r, "symbol", ""),
                        "sub_type": getattr(r, "sub_type", ""),
                        "metric": getattr(r, "metric", ""),
                        "year": getattr(r, "year", None),
                        "period": getattr(r, "period", ""),
                        "value": getattr(r, "value", None),
                        "unit": getattr(r, "unit", "crore"),
                        "raw_row": getattr(r, "raw_row", {}),
                    })

        if not out and sql_results:
            for sr in sql_results:
                if getattr(sr, "error", None) or not getattr(sr, "rows", None):
                    continue
                atom = getattr(sr, "atom", None)
                sub_type = getattr(atom, "sub_type", "") if atom else ""
                metric_name = getattr(atom, "metric", sub_type) if atom else sub_type
                for raw in sr.rows:
                    out.append({
                        "symbol": raw.get("symbol", getattr(atom, "symbol", "")),
                        "sub_type": sub_type,
                        "metric": metric_name,
                        "year": raw.get("year"),
                        "period": raw.get("period_end") or raw.get("date") or "",
                        "value": raw.get("value") or raw.get("sales") or raw.get("net_profit"),
                        "unit": "crore",
                        "raw_row": raw,
                    })

        return out

    def _detect_symbol(self, rows: List[Dict[str, Any]], query: str) -> str:
        for r in rows:
            sym = r.get("symbol")
            if sym and sym.upper() != "UNKNOWN":
                return sym.upper()
        # Fallback from query
        match = re.search(r'\b([A-Z]{2,15})\b', query)
        return match.group(1) if match else "COMPANY"

    # ── Chart Builders ────────────────────────────────────────────────────────

    def _build_time_series_charts(
        self, rows: List[Dict[str, Any]], symbol: str, query: str
    ) -> List[Dict[str, Any]]:
        """
        Group rows by metric / sub_type across years and build interactive bar/line trend charts.
        """
        charts: List[Dict[str, Any]] = []
        q_lower = query.lower()

        # Group rows by sub_type
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            val = r.get("value")
            if val is None or (isinstance(val, float) and math.isnan(val)):
                continue
            st = r.get("sub_type") or r.get("metric", "Metric")
            grouped.setdefault(st, []).append(r)

        # Filter & prioritize metrics to prevent generating 10+ charts on statement dumps
        priority_keys = ["net_profit", "sales", "revenue", "operating_profit", "ebitda", "cfo", "free_cash_flow", "eps"]
        
        # If specific metric is in query, prioritize it
        matching_st = [st for st in grouped.keys() if st.lower() in q_lower or any(w in st.lower() for w in q_lower.split())]
        ordered_st = matching_st + [k for k in priority_keys if k in grouped and k not in matching_st]
        # Fallback to remaining
        for k in grouped.keys():
            if k not in ordered_st:
                ordered_st.append(k)

        # Cap number of trend charts to 2 (or 1 if waterfall already present)
        max_trend_charts = 1 if "waterfall" in q_lower else 2

        for st in ordered_st:
            if len(charts) >= max_trend_charts:
                break

            item_rows = grouped[st]
            # Skip if only 1 row or non-chronological unless explicitly single
            # Filter rows with valid year / period
            valid_rows = [
                r for r in item_rows
                if r.get("year") is not None or r.get("period")
            ]
            if not valid_rows:
                continue

            # Sort chronologically by year / period
            def _sort_key(x):
                y = x.get("year") or 0
                p = str(x.get("period") or "")
                return (y, p)

            valid_rows = sorted(valid_rows, key=_sort_key)
            
            # Deduplicate by year/period if multiple rows exist
            dedup_rows: List[Dict[str, Any]] = []
            seen_periods = set()
            for r in valid_rows:
                k = r.get("year") or r.get("period")
                if k not in seen_periods:
                    seen_periods.add(k)
                    dedup_rows.append(r)

            if len(dedup_rows) < 2 and "trend" not in query and "cagr" not in query and "growth" not in query:
                # If only 1 data point and query didn't ask for trend, skip time-series chart
                continue

            labels = [
                f"FY{r.get('year')}" if r.get("year") else str(r.get("period", ""))[:7]
                for r in dedup_rows
            ]
            values = [float(r.get("value", 0.0)) for r in dedup_rows]
            metric_label = dedup_rows[0].get("metric") or st.replace("_", " ").title()
            unit = dedup_rows[0].get("unit", "crore")
            palette = _get_metric_palette(st)

            # Calculate CAGR & YoY Growth
            cagr = None
            if len(values) >= 2 and values[0] > 0 and values[-1] > 0:
                cagr = calculate_cagr(values[0], values[-1], len(values) - 1)

            yoy_growth = calculate_yoy_growth(values)
            peak_val = max(values)
            peak_idx = values.index(peak_val)
            peak_label = labels[peak_idx]

            total_growth_pct = None
            if values[0] != 0:
                total_growth_pct = round(((values[-1] - values[0]) / abs(values[0])) * 100.0, 1)

            # Build KPIs
            kpis = []
            if cagr is not None:
                kpis.append({
                    "label": f"CAGR ({labels[0]}-{labels[-1]})",
                    "value": f"{'+' if cagr > 0 else ''}{cagr:.1f}%",
                    "type": "positive" if cagr > 0 else "negative",
                })
            if total_growth_pct is not None and len(values) > 2:
                kpis.append({
                    "label": f"Total Growth",
                    "value": f"{'+' if total_growth_pct > 0 else ''}{total_growth_pct:.1f}%",
                    "type": "positive" if total_growth_pct > 0 else "negative",
                })
            kpis.append({
                "label": f"Peak ({peak_label})",
                "value": format_currency_value(peak_val, unit),
                "type": "neutral",
            })

            # Determine chart type: 'bar' for revenue/profit/cagr/ebitda, 'line'/'area' for ratios or continuous prices
            is_cagr_or_bar = any(
                k in query for k in ["cagr", "growth", "bar", "profit", "revenue", "sales", "ebitda", "pat"]
            ) or st in ["profit_loss", "revenue", "net_profit", "sales", "ebitda", "capex", "fcf"]

            chart_type = "bar" if is_cagr_or_bar else "line"

            # Create Plotly Figure
            plotly_fig = None
            if _HAS_PLOTLY:
                plotly_fig = self._create_plotly_trend_fig(
                    labels=labels,
                    values=values,
                    yoy_growth=yoy_growth,
                    metric_label=metric_label,
                    symbol=symbol,
                    unit=unit,
                    palette=palette,
                    chart_type=chart_type,
                    cagr=cagr,
                )

            chart_obj = {
                "id": f"chart_{st}_{len(charts)+1}",
                "type": chart_type,
                "title": f"{symbol} - {metric_label} Trend ({labels[0]} – {labels[-1]})",
                "subtitle": f"Historical performance in {unit.upper()}",
                "symbol": symbol,
                "metric": metric_label,
                "unit": unit,
                "labels": labels,
                "values": values,
                "yoy_growth": yoy_growth,
                "cagr": cagr,
                "kpis": kpis,
                "color": palette["primary"],
                "plotly_fig": plotly_fig.to_dict() if plotly_fig else None,
            }
            charts.append(chart_obj)

        return charts

    def _create_plotly_trend_fig(
        self,
        labels: List[str],
        values: List[float],
        yoy_growth: List[Optional[float]],
        metric_label: str,
        symbol: str,
        unit: str,
        palette: Dict[str, Any],
        chart_type: str = "bar",
        cagr: Optional[float] = None,
    ) -> "go.Figure":
        fig = go.Figure()

        # Hover text with formatted values and YoY %
        hover_texts = []
        for i, val in enumerate(values):
            formatted_val = format_currency_value(val, unit)
            growth_txt = f"<br><b>YoY Growth:</b> {'+' if (yoy_growth[i] or 0) > 0 else ''}{yoy_growth[i]}%" if yoy_growth[i] is not None else ""
            hover_texts.append(
                f"<b>{symbol} | {labels[i]}</b><br>"
                f"<b>{metric_label}:</b> {formatted_val}"
                f"{growth_txt}"
            )

        if chart_type == "bar":
            # Bar Chart with gradient colors and rounded corners
            bar_colors = [
                palette["secondary"] if (yoy or 0) < 0 else palette["primary"]
                for yoy in yoy_growth
            ]
            
            # Value annotations on top of bars
            text_labels = [format_currency_value(v, unit) for v in values]

            fig.add_trace(go.Bar(
                x=labels,
                y=values,
                text=text_labels,
                textposition="outside",
                textfont=dict(size=12, color="#1F2937", family="sans-serif"),
                marker=dict(
                    color=bar_colors,
                    line=dict(color=palette["secondary"], width=1.5),
                    opacity=0.9,
                ),
                hovertext=hover_texts,
                hoverinfo="text",
                name=metric_label,
            ))

            # Optional trendline overlay for multi-period growth
            if len(values) >= 3:
                fig.add_trace(go.Scatter(
                    x=labels,
                    y=values,
                    mode="lines+markers",
                    line=dict(color="#1E293B", width=2, dash="dot"),
                    marker=dict(size=6, color="#1E293B"),
                    hoverinfo="skip",
                    showlegend=False,
                ))

        else:
            # Smooth Line / Area Chart
            fig.add_trace(go.Scatter(
                x=labels,
                y=values,
                mode="lines+markers+text",
                text=[format_currency_value(v, unit) for v in values],
                textposition="top center",
                line=dict(color=palette["primary"], width=3, shape="spline"),
                marker=dict(size=8, color=palette["secondary"], line=dict(color="#FFFFFF", width=2)),
                fill="tozeroy",
                fillcolor=palette["light"],
                hovertext=hover_texts,
                hoverinfo="text",
                name=metric_label,
            ))

        # Title and CAGR annotation
        cagr_badge = f" | CAGR: {'+' if (cagr or 0) > 0 else ''}{cagr:.1f}%" if cagr is not None else ""
        title_text = f"<b>{symbol} {metric_label}</b> ({labels[0]}–{labels[-1]}){cagr_badge}"

        fig.update_layout(
            title=dict(
                text=title_text,
                font=dict(size=15, color="#111827", family="sans-serif"),
                x=0.02,
                y=0.95,
            ),
            margin=dict(l=40, r=40, t=60, b=40),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(243, 244, 246, 0.4)",
            xaxis=dict(
                showgrid=False,
                tickfont=dict(size=12, color="#4B5563", family="sans-serif"),
                linecolor="#D1D5DB",
            ),
            yaxis=dict(
                showgrid=True,
                gridcolor="rgba(209, 213, 219, 0.5)",
                tickfont=dict(size=11, color="#4B5563"),
                title=dict(text=f"Amount ({unit})", font=dict(size=12, color="#4B5563")),
            ),
            hoverlabel=dict(
                bgcolor="#1E293B",
                font_size=12,
                font_color="#FFFFFF",
                font_family="sans-serif",
            ),
            showlegend=False,
            height=340,
        )

        return fig

    def _try_build_shareholding_chart(
        self, rows: List[Dict[str, Any]], symbol: str, query: str
    ) -> Optional[Dict[str, Any]]:
        """
        Build an interactive Donut chart for shareholding breakdown (Promoter, FII, DII, Public).
        """
        # Look for shareholding sub_types or columns in raw_row
        sh_keys = [
            ("promoter", "promoter_pct", "Promoter"),
            ("fii", "fii_pct", "FII / FPI"),
            ("dii", "dii_pct", "DII (Mutual Funds/Ins)"),
            ("public", "public_pct", "Public / Retail"),
        ]

        slices = []
        for st_name, col_name, label in sh_keys:
            found = False
            # Find in metric rows
            for r in rows:
                st = (r.get("sub_type") or "").lower()
                val = r.get("value")
                if (st in (st_name, col_name, st_name + "_pct", col_name.replace("_pct", "")) or st_name in st) and val is not None:
                    try:
                        slices.append((label, float(val)))
                        found = True
                        break
                    except (ValueError, TypeError):
                        pass

            if not found:
                # Find in raw_row columns
                for r in rows:
                    raw = r.get("raw_row", {})
                    for candidate_col in (col_name, st_name, col_name.replace("_pct", ""), st_name + "_pct"):
                        if candidate_col in raw and raw[candidate_col] is not None:
                            try:
                                slices.append((label, float(raw[candidate_col])))
                                found = True
                                break
                            except (ValueError, TypeError):
                                pass
                    if found:
                        break

        if len(slices) < 2:
            return None

        labels = [s[0] for s in slices]
        values = [s[1] for s in slices]
        colors = PALETTES["shareholding"][:len(labels)]

        plotly_fig = None
        if _HAS_PLOTLY:
            fig = go.Figure(data=[go.Pie(
                labels=labels,
                values=values,
                hole=0.55,
                marker=dict(colors=colors, line=dict(color="#FFFFFF", width=2)),
                textinfo="label+percent",
                textfont=dict(size=12, color="#1F2937"),
                hoverinfo="label+value+percent",
            )])
            fig.update_layout(
                title=dict(
                    text=f"<b>{symbol} Shareholding Pattern</b>",
                    font=dict(size=15, color="#111827"),
                    x=0.05,
                ),
                margin=dict(l=20, r=20, t=50, b=20),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
                height=320,
            )
            plotly_fig = fig

        return {
            "id": "chart_shareholding",
            "type": "donut",
            "title": f"{symbol} - Shareholding Distribution",
            "subtitle": "Ownership Breakdown (%)",
            "symbol": symbol,
            "metric": "Shareholding",
            "unit": "%",
            "labels": labels,
            "values": values,
            "colors": colors,
            "kpis": [
                {"label": "Promoter Holding", "value": f"{values[0]:.1f}%", "type": "neutral"},
                {"label": "Institutional Stake", "value": f"{(sum(values[1:3])):.1f}%", "type": "positive"},
            ],
            "plotly_fig": plotly_fig.to_dict() if plotly_fig else None,
        }

    def _try_build_waterfall_chart(
        self, rows: List[Dict[str, Any]], symbol: str, query: str
    ) -> Optional[Dict[str, Any]]:
        """
        Build an interactive financial Waterfall Bridge chart (Revenue -> Expenses -> EBITDA/PBT -> Net Profit).
        """
        # Look for complete P&L statement items in raw_row or metric rows
        pl_map = {}
        for r in rows:
            st = r.get("sub_type", "").lower()
            val = r.get("value")
            if val is not None:
                pl_map[st] = float(val)

        # Check required fields
        sales = pl_map.get("sales") or pl_map.get("revenue")
        expenses = pl_map.get("expenses")
        op_profit = pl_map.get("operating_profit")
        net_profit = pl_map.get("net_profit")

        if not (sales and net_profit):
            return None

        # Build Waterfall measures
        measures = []
        x_labels = []
        y_vals = []
        text_vals = []

        x_labels.append("Gross Sales")
        y_vals.append(sales)
        measures.append("relative")
        text_vals.append(format_currency_value(sales, "crore"))

        if expenses:
            exp_val = -abs(expenses)
            x_labels.append("Operating Expenses")
            y_vals.append(exp_val)
            measures.append("relative")
            text_vals.append(format_currency_value(exp_val, "crore"))
        elif op_profit:
            exp_diff = -(sales - op_profit)
            x_labels.append("Operating Expenses")
            y_vals.append(exp_diff)
            measures.append("relative")
            text_vals.append(format_currency_value(exp_diff, "crore"))

        if op_profit:
            x_labels.append("Operating Profit")
            y_vals.append(op_profit)
            measures.append("total")
            text_vals.append(format_currency_value(op_profit, "crore"))

        pbt = pl_map.get("profit_before_tax") or pl_map.get("pbt")
        if pbt and op_profit and pbt != op_profit:
            diff = pbt - op_profit
            x_labels.append("Interest & Other" if diff < 0 else "Other Income")
            y_vals.append(diff)
            measures.append("relative")
            text_vals.append(format_currency_value(diff, "crore"))

        if pbt and net_profit:
            tax_diff = -(pbt - net_profit)
            x_labels.append("Tax & D&A")
            y_vals.append(tax_diff)
            measures.append("relative")
            text_vals.append(format_currency_value(tax_diff, "crore"))

        x_labels.append("Net Profit (PAT)")
        y_vals.append(net_profit)
        measures.append("total")
        text_vals.append(format_currency_value(net_profit, "crore"))

        plotly_fig = None
        if _HAS_PLOTLY:
            fig = go.Figure(go.Waterfall(
                name="P&L Bridge",
                orientation="v",
                measure=measures,
                x=x_labels,
                y=y_vals,
                text=text_vals,
                textposition="outside",
                connector=dict(line=dict(color="#9CA3AF", dash="dot")),
                decreasing=dict(marker=dict(color="#EF4444")),
                increasing=dict(marker=dict(color="#10B981")),
                totals=dict(marker=dict(color="#3B82F6")),
            ))
            fig.update_layout(
                title=dict(
                    text=f"<b>{symbol} Profit & Loss Waterfall Bridge</b>",
                    font=dict(size=15, color="#111827"),
                    x=0.02,
                ),
                margin=dict(l=40, r=40, t=50, b=40),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(243, 244, 246, 0.4)",
                yaxis=dict(title="₹ Crore", showgrid=True, gridcolor="rgba(209, 213, 219, 0.5)"),
                height=340,
            )
            plotly_fig = fig

        margin_pct = round((net_profit / sales) * 100.0, 1) if sales else 0.0

        return {
            "id": "chart_waterfall_pnl",
            "type": "waterfall",
            "title": f"{symbol} - P&L Financial Bridge",
            "subtitle": "Revenue to Net Income Cascade (₹ Crore)",
            "symbol": symbol,
            "metric": "P&L Waterfall",
            "unit": "crore",
            "labels": x_labels,
            "values": y_vals,
            "kpis": [
                {"label": "Gross Revenue", "value": format_currency_value(sales, "crore"), "type": "neutral"},
                {"label": "Net Margin (PAT)", "value": f"{margin_pct}%", "type": "positive" if margin_pct > 10 else "neutral"},
                {"label": "Final Net Profit", "value": format_currency_value(net_profit, "crore"), "type": "positive"},
            ],
            "plotly_fig": plotly_fig.to_dict() if plotly_fig else None,
        }

    def _try_build_radar_chart(
        self, rows: List[Dict[str, Any]], symbol: str
    ) -> Optional[Dict[str, Any]]:
        """
        Build an interactive Spider / Radar chart for multi-metric financial scorecard.
        """
        categories = []
        values = []

        target_metrics = [
            ("roe", "ROE %", 15.0),
            ("roce", "ROCE %", 18.0),
            ("opm", "Operating Margin %", 20.0),
            ("net_margin", "Net Margin %", 12.0),
            ("revenue_cagr", "Revenue Growth %", 15.0),
            ("profit_cagr", "Profit Growth %", 20.0),
        ]

        row_dict = {r.get("sub_type", "").lower(): r.get("value") for r in rows if r.get("value") is not None}

        for st, label, benchmark in target_metrics:
            val = row_dict.get(st)
            if val is not None:
                categories.append(label)
                values.append(float(val))

        if len(categories) < 3:
            return None

        # Close radar loop
        rad_cats = categories + [categories[0]]
        rad_vals = values + [values[0]]

        plotly_fig = None
        if _HAS_PLOTLY:
            fig = go.Figure()
            fig.add_trace(go.Scatterpolar(
                r=rad_vals,
                theta=rad_cats,
                fill="toself",
                fillcolor="rgba(16, 185, 129, 0.25)",
                line=dict(color="#10B981", width=2.5),
                marker=dict(size=6, color="#059669"),
                name=symbol,
            ))
            fig.update_layout(
                polar=dict(
                    radialaxis=dict(visible=True, range=[0, max(values) * 1.2]),
                ),
                title=dict(text=f"<b>{symbol} Financial Health Radar</b>", font=dict(size=14), x=0.05),
                margin=dict(l=40, r=40, t=50, b=40),
                paper_bgcolor="rgba(0,0,0,0)",
                height=320,
            )
            plotly_fig = fig

        return {
            "id": "chart_radar_health",
            "type": "radar",
            "title": f"{symbol} - Financial Health Radar",
            "subtitle": "Multivariate Profitability & Growth Profile",
            "symbol": symbol,
            "metric": "Financial Scorecard",
            "unit": "%",
            "labels": categories,
            "values": values,
            "kpis": [
                {"label": "Key Strengths", "value": f"{len(categories)} Metrics Tracked", "type": "positive"},
            ],
            "plotly_fig": plotly_fig.to_dict() if plotly_fig else None,
        }


# Global singleton instance
_CHART_ENGINE = FinancialChartEngine()

def generate_financial_charts(
    query: str,
    metric_rows: Optional[List[Any]] = None,
    sql_results: Optional[List[Any]] = None,
    symbol: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Helper function to generate charts directly."""
    return _CHART_ENGINE.generate_charts(query, metric_rows, sql_results, symbol)
