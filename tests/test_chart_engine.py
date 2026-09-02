import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from visualization.chart_engine import FinancialChartEngine, calculate_cagr, calculate_yoy_growth

def test_chart_engine():
    engine = FinancialChartEngine()

    print("--- Test 1: Profit CAGR & Trend ---")
    profit_rows = [
        {"symbol": "APOLLO", "sub_type": "net_profit", "metric": "Net Profit", "year": 2023, "period": "2023-03-31", "value": 18.7, "unit": "crore"},
        {"symbol": "APOLLO", "sub_type": "net_profit", "metric": "Net Profit", "year": 2024, "period": "2024-03-31", "value": 24.3, "unit": "crore"},
        {"symbol": "APOLLO", "sub_type": "net_profit", "metric": "Net Profit", "year": 2025, "period": "2025-03-31", "value": 31.1, "unit": "crore"},
    ]
    charts = engine.generate_charts("What is the profit CAGR for APOLLO from FY23 to FY25?", metric_rows=profit_rows)
    assert len(charts) > 0, "No chart generated for profit CAGR"
    c1 = charts[0]
    print(f"Chart Title: {c1['title']}")
    print(f"Chart Type: {c1['type']}")
    print(f"CAGR: {c1['cagr']}%")
    print(f"YoY Growth: {c1['yoy_growth']}")
    print(f"KPIs: {c1['kpis']}")
    assert c1['cagr'] is not None
    assert c1['type'] == 'bar'
    print("PASS Test 1\n")

    print("--- Test 2: Shareholding Donut Chart ---")
    sh_rows = [
        {"symbol": "BEL", "sub_type": "promoter", "metric": "Promoter Holding", "value": 51.14, "unit": "%"},
        {"symbol": "BEL", "sub_type": "fii", "metric": "FII Holding", "value": 17.52, "unit": "%"},
        {"symbol": "BEL", "sub_type": "dii", "metric": "DII Holding", "value": 19.34, "unit": "%"},
        {"symbol": "BEL", "sub_type": "public", "metric": "Public Holding", "value": 12.00, "unit": "%"},
    ]
    charts_sh = engine.generate_charts("What is the shareholding pattern of BEL?", metric_rows=sh_rows)
    assert len(charts_sh) > 0, "No shareholding chart generated"
    sh_chart = next((c for c in charts_sh if c['type'] == 'donut'), None)
    assert sh_chart is not None, "Donut chart not found in output"
    print(f"Shareholding Title: {sh_chart['title']}")
    print(f"Labels: {sh_chart['labels']}")
    print(f"Values: {sh_chart['values']}")
    print("PASS Test 2\n")

    print("--- Test 3: P&L Waterfall Bridge ---")
    pl_rows = [
        {"symbol": "HAL", "sub_type": "sales", "metric": "Sales / Revenue", "value": 30381.0, "unit": "crore"},
        {"symbol": "HAL", "sub_type": "expenses", "metric": "Expenses", "value": 20450.0, "unit": "crore"},
        {"symbol": "HAL", "sub_type": "operating_profit", "metric": "Operating Profit", "value": 9931.0, "unit": "crore"},
        {"symbol": "HAL", "sub_type": "profit_before_tax", "metric": "Profit Before Tax (PBT)", "value": 10200.0, "unit": "crore"},
        {"symbol": "HAL", "sub_type": "net_profit", "metric": "Net Profit", "value": 7595.0, "unit": "crore"},
    ]
    charts_pl = engine.generate_charts("Show P&L waterfall breakdown for HAL", metric_rows=pl_rows)
    wf_chart = next((c for c in charts_pl if c['type'] == 'waterfall'), None)
    assert wf_chart is not None, "Waterfall chart not found"
    print(f"Waterfall Title: {wf_chart['title']}")
    print(f"Waterfall Labels: {wf_chart['labels']}")
    print(f"Waterfall Values: {wf_chart['values']}")
    print("PASS Test 3\n")

    print("--- Test 4: Financial Health Radar ---")
    radar_rows = [
        {"symbol": "TCS", "sub_type": "roe", "metric": "ROE %", "value": 48.5, "unit": "%"},
        {"symbol": "TCS", "sub_type": "roce", "metric": "ROCE %", "value": 62.1, "unit": "%"},
        {"symbol": "TCS", "sub_type": "opm", "metric": "Operating Margin %", "value": 26.2, "unit": "%"},
        {"symbol": "TCS", "sub_type": "net_margin", "metric": "Net Margin %", "value": 19.8, "unit": "%"},
        {"symbol": "TCS", "sub_type": "revenue_cagr", "metric": "Revenue Growth %", "value": 14.5, "unit": "%"},
    ]
    charts_rad = engine.generate_charts("Show financial health radar overview for TCS", metric_rows=radar_rows)
    rad_chart = next((c for c in charts_rad if c['type'] == 'radar'), None)
    assert rad_chart is not None, "Radar chart not found"
    print(f"Radar Title: {rad_chart['title']}")
    print(f"Radar Labels: {rad_chart['labels']}")
    print(f"Radar Values: {rad_chart['values']}")
    print("PASS Test 4\n")

    print("ALL TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_chart_engine()
