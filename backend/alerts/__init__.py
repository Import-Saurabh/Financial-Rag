"""
backend/alerts package — NSE & BSE Regulatory Alerts Aggregator.
"""

from .nse_alerts import (
    NSE_FEED_URLS,
    NSEAlertsCollector,
    get_nse_collector,
    fetch_all_nse_alerts,
)
from .bse_alerts import (
    BSE_FEED_URLS,
    BSEAlertsCollector,
    get_bse_collector,
    fetch_all_bse_alerts,
)
from .unified_alerts import (
    UnifiedAlertsManager,
    get_unified_alerts_manager,
    get_live_alerts,
    merge_and_deduplicate,
)

__all__ = [
    "NSE_FEED_URLS",
    "BSE_FEED_URLS",
    "NSEAlertsCollector",
    "BSEAlertsCollector",
    "UnifiedAlertsManager",
    "get_nse_collector",
    "get_bse_collector",
    "get_unified_alerts_manager",
    "fetch_all_nse_alerts",
    "fetch_all_bse_alerts",
    "get_live_alerts",
    "merge_and_deduplicate",
]
