from typing import List, Dict, Any

def compute_metrics(pl_rows: List[Dict[str, Any]], bs_rows: List[Dict[str, Any]], cf_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """
    Computes derived financial metrics from base Schema Bridge data.
    
    Args:
        pl_rows: List of Profit & Loss rows.
        bs_rows: List of Balance Sheet rows.
        cf_rows: List of Cash Flow rows.
        
    Returns:
        Dict keyed by period_end with computed metrics:
        - EBITDA = Operating Profit + Depreciation
        - ROE = Net Profit / Total Equity × 100
        - Net Profit Margin = Net Profit / Revenue × 100
        - Debt/Equity = Total Borrowings / Total Equity
    """
    metrics_by_period: Dict[str, Dict[str, float]] = {}
    
    # Organize data by period_end
    data_by_period: Dict[str, Dict[str, Any]] = {}
    
    for row in pl_rows:
        period = row.get("period_end")
        if period:
            data_by_period.setdefault(period, {}).update(row)
            
    for row in bs_rows:
        period = row.get("period_end")
        if period:
            data_by_period.setdefault(period, {}).update(row)
            
    for row in cf_rows:
        period = row.get("period_end")
        if period:
            data_by_period.setdefault(period, {}).update(row)
            
    for period, data in data_by_period.items():
        computed: Dict[str, float] = {}
        
        # P&L Base
        op_profit = data.get("operating_profit")
        depreciation = data.get("depreciation")
        net_profit = data.get("net_profit")
        sales = data.get("sales")
        eps = data.get("eps")
        
        # Balance Sheet Base
        total_equity = data.get("total_equity")
        total_borrowings = data.get("total_borrowings")
        
        # EBITDA = Operating Profit + Depreciation
        if op_profit is not None and depreciation is not None:
            try:
                computed["EBITDA"] = float(op_profit) + float(depreciation)
            except (ValueError, TypeError):
                pass
            
        # ROE = Net Profit / Total Equity × 100
        if net_profit is not None and total_equity is not None:
            try:
                eq = float(total_equity)
                if eq != 0:
                    computed["ROE"] = (float(net_profit) / eq) * 100.0
            except (ValueError, TypeError):
                pass
            
        # Net Profit Margin = Net Profit / Sales × 100
        if net_profit is not None and sales is not None:
            try:
                rev = float(sales)
                if rev != 0:
                    computed["Net Profit Margin"] = (float(net_profit) / rev) * 100.0
            except (ValueError, TypeError):
                pass

        # Operating Profit Margin = Operating Profit / Sales × 100
        if op_profit is not None and sales is not None:
            try:
                rev = float(sales)
                if rev != 0:
                    computed["Operating Profit Margin"] = (float(op_profit) / rev) * 100.0
            except (ValueError, TypeError):
                pass
            
        # Debt/Equity = Total Borrowings / Total Equity
        if total_borrowings is not None and total_equity is not None:
            try:
                eq = float(total_equity)
                if eq != 0:
                    computed["Debt/Equity"] = float(total_borrowings) / eq
            except (ValueError, TypeError):
                pass
            
        metrics_by_period[period] = computed
        
    return metrics_by_period
