"""
backend/alerts/unified_alerts.py — Unified NSE & BSE Regulatory Alerts Aggregator.
Merges live disclosure feeds from both exchanges, performs cross-exchange deduplication,
matches user watchlists, and formats WhatsApp & Web intelligence notifications.
"""

from __future__ import annotations

import os
import re
import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Set

from .nse_alerts import get_nse_collector, fetch_all_nse_alerts
from .bse_alerts import get_bse_collector, fetch_all_bse_alerts

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
USER_WATCHLIST_FILE = DATA_DIR / "user_watchlists.json"
WA_WATCHLIST_FILE = DATA_DIR / "whatsapp_watchlists.json"
CALENDAR_FILE = DATA_DIR / "corporate_calendar.json"


def _clean_str(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '')).strip()


def merge_and_deduplicate(nse_alerts: List[Dict[str, Any]], bse_alerts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge alerts from NSE and BSE.
    If the same company files the same corporate action or announcement on both
    exchanges within a 1-hour window, merge them into a single dual-exchange alert.
    """
    combined = list(nse_alerts) + list(bse_alerts)
    combined.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

    merged: List[Dict[str, Any]] = []
    seen_fingerprints: Dict[str, Dict[str, Any]] = {}

    for alert in combined:
        sym = alert.get("symbol", "GENERAL").upper()
        # Create a fuzzy fingerprint based on symbol, category, and date hour
        ts = alert.get("timestamp", 0)
        hour_bucket = ts // 3600
        desc_snippet = _clean_str(alert.get("description", ""))[:30].lower()
        title_snippet = _clean_str(alert.get("title", ""))[:30].lower()
        
        fp = f"{sym}:{alert.get('category_key')}:{hour_bucket}:{desc_snippet or title_snippet}"

        if fp in seen_fingerprints and sym != "GENERAL":
            # Merge with existing
            existing = seen_fingerprints[fp]
            if alert["exchange"] not in existing["exchanges"]:
                existing["exchanges"].append(alert["exchange"])
            
            # Attach secondary link if available
            if not existing.get("secondary_link") and alert.get("link") != existing.get("link"):
                existing["secondary_link"] = alert.get("link")
                existing["secondary_exchange"] = alert["exchange"]
            if not existing.get("attachment_url") and alert.get("attachment_url"):
                existing["attachment_url"] = alert["attachment_url"]
        else:
            alert_copy = dict(alert)
            alert_copy["exchanges"] = [alert["exchange"]]
            seen_fingerprints[fp] = alert_copy
            merged.append(alert_copy)

    # Re-sort final list
    merged.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return merged


class UnifiedAlertsManager:
    """Manages multi-exchange alert polling, filtering, and distribution."""

    def __init__(self):
        self.nse_collector = get_nse_collector()
        self.bse_collector = get_bse_collector()

    def get_live_alerts(
        self,
        exchange: str = "ALL",  # "ALL", "NSE", "BSE"
        category: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 50,
        force_refresh: bool = False
    ) -> List[Dict[str, Any]]:
        """Fetch and return unified live alerts filtered by exchange, category, or symbol."""
        nse_items: List[Dict[str, Any]] = []
        bse_items: List[Dict[str, Any]] = []

        if exchange in ("ALL", "NSE"):
            if category:
                nse_items = self.nse_collector.fetch_category(category, force_refresh=force_refresh)
            else:
                nse_items = self.nse_collector.fetch_all(limit_per_category=15, force_refresh=force_refresh)

        if exchange in ("ALL", "BSE"):
            if category:
                bse_items = self.bse_collector.fetch_category(category, force_refresh=force_refresh)
            else:
                bse_items = self.bse_collector.fetch_all(limit_per_category=15, force_refresh=force_refresh)

        merged = merge_and_deduplicate(nse_items, bse_items)

        # Filter by symbol if specified
        if symbol:
            sym_clean = symbol.upper().strip()
            merged = [a for a in merged if a.get("symbol", "").upper() == sym_clean]

        return merged[:limit]

    def filter_by_watchlist(self, alerts: List[Dict[str, Any]], symbols: List[str]) -> List[Dict[str, Any]]:
        """Filter alerts list to only include equities in the provided watchlist."""
        if not symbols:
            return []
        sym_set = {s.upper().strip() for s in symbols}
        return [a for a in alerts if a.get("symbol", "").upper() in sym_set]

    def get_alerts_for_user(self, username: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Retrieve real-time alerts tailored to a specific web user's watchlist."""
        user_symbols: List[str] = []
        if USER_WATCHLIST_FILE.exists():
            try:
                with open(USER_WATCHLIST_FILE, "r", encoding="utf-8") as f:
                    all_wl = json.load(f)
                    user_symbols = all_wl.get(username.lower().strip(), ["HAL", "APOLLO"])
            except Exception as e:
                log.warning(f"[unified_alerts] Error reading user watchlists: {e}")

        all_live = self.get_live_alerts(limit=100)
        matched = self.filter_by_watchlist(all_live, user_symbols)
        return matched[:limit]

    def get_alerts_for_whatsapp_phone(self, phone: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Retrieve real-time alerts tailored to a WhatsApp user's tracked symbols."""
        clean_p = "".join(c for c in phone if c.isdigit())
        user_symbols: List[str] = []
        if WA_WATCHLIST_FILE.exists():
            try:
                with open(WA_WATCHLIST_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    user_symbols = data.get("watchlists", {}).get(clean_p, [])
            except Exception as e:
                log.warning(f"[unified_alerts] Error reading whatsapp watchlists: {e}")

        all_live = self.get_live_alerts(limit=100)
        return self.filter_by_watchlist(all_live, user_symbols)[:limit]

    def format_whatsapp_notification(self, alert: Dict[str, Any]) -> str:
        """Format an alert into a clean, professional WhatsApp broadcast notification."""
        sym = alert.get("symbol", "EQUITY")
        exchanges = "/".join(alert.get("exchanges", [alert.get("exchange", "BSE/NSE")]))
        category = alert.get("category", "Corporate Filing")
        title = alert.get("title", "")
        desc = alert.get("description", "")
        pub_date = alert.get("pub_date", "")
        attachment = alert.get("attachment_url") or alert.get("link", "")

        msg = (
            f"🔔 *REGULATORY ALERT: {sym}*\n"
            f"🏛 *Exchange:* {exchanges} | *Category:* {category}\n"
            f"📅 *Filed:* {pub_date}\n\n"
            f"📌 *Subject:* {title}\n"
        )
        if desc and desc != title:
            clean_d = desc[:300] + ("..." if len(desc) > 300 else "")
            msg += f"📝 *Details:* {clean_d}\n\n"

        if attachment:
            msg += f"📎 *Filing Document:* {attachment}\n\n"

        msg += "⚡ _Powered by Nifty Financial Rag Telemetry_"
        return msg

    def sync_to_corporate_calendar(self, alert: Dict[str, Any]) -> bool:
        """
        Auto-sync detected board meetings or earnings announcements into
        the central corporate calendar.
        """
        category_key = alert.get("category_key", "")
        if category_key not in ("board_meetings", "financial_results", "annual_reports"):
            return False

        sym = alert.get("symbol", "").upper()
        if sym in ("GENERAL", "UNKNOWN", ""):
            return False

        try:
            events: List[Dict[str, Any]] = []
            if CALENDAR_FILE.exists():
                with open(CALENDAR_FILE, "r", encoding="utf-8") as f:
                    events = json.load(f).get("events", [])

            # Check if event already exists
            event_id = f"EVT-AUTO-{sym}-{alert.get('id')}"
            if any(e.get("id") == event_id for e in events):
                return False

            new_event = {
                "id": event_id,
                "symbol": sym,
                "company_name": alert.get("company_name", sym),
                "event_type": alert.get("category", "Corporate Event"),
                "fiscal_period": "Upcoming",
                "scheduled_date": alert.get("pub_date", "").split(" ")[0],
                "scheduled_time": "Exchange Notification",
                "meeting_status": "Scheduled" if "meeting" in category_key else "Conducted",
                "announcement_date": alert.get("pub_date", "").split(" ")[0],
                "published_status": "Notice Filed" if "meeting" in category_key else "Results Filed",
                "report_type": "concall" if "results" in category_key else "annual_report",
                "dial_in_info": f"Filing URL: {alert.get('link', '')}",
                "notes": alert.get("description", alert.get("title", ""))[:250],
            }

            events.insert(0, new_event)
            CALENDAR_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CALENDAR_FILE, "w", encoding="utf-8") as f:
                json.dump({"events": events}, f, indent=2)

            log.info(f"[unified_alerts] Synced alert to calendar: {sym} - {new_event['event_type']}")
            return True
        except Exception as exc:
            log.warning(f"[unified_alerts] Failed to sync alert to calendar: {exc}")
            return False


_manager_instance: Optional[UnifiedAlertsManager] = None


def get_unified_alerts_manager() -> UnifiedAlertsManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = UnifiedAlertsManager()
    return _manager_instance


def get_live_alerts(
    exchange: str = "ALL",
    category: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Convenience helper to retrieve unified live alerts."""
    manager = get_unified_alerts_manager()
    return manager.get_live_alerts(exchange=exchange, category=category, symbol=symbol, limit=limit)
