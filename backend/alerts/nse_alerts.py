"""
backend/alerts/nse_alerts.py — NSE Regulatory Announcements & Disclosures Feed Collector.
Fetches, parses, and normalizes live RSS feeds from the National Stock Exchange of India (NSE).
"""

from __future__ import annotations

import os
import re
import time
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Any, Optional
import requests

log = logging.getLogger(__name__)

# Official NSE RSS Feeds
NSE_FEED_URLS: Dict[str, str] = {
    "corporate_announcements": "https://archives.nseindia.com/content/RSS/Online_announcements.xml",
    "financial_results": "https://archives.nseindia.com/content/RSS/Financial_Results.xml",
    "annual_reports": "https://archives.nseindia.com/content/RSS/Annual_Reports.xml",
    "board_meetings": "https://archives.nseindia.com/content/RSS/Board_Meetings.xml",
    "corporate_actions": "https://archives.nseindia.com/content/RSS/Corporate_action.xml",
    "shareholding_patterns": "https://archives.nseindia.com/content/RSS/Shareholding_Pattern.xml",
    "circulars": "https://archives.nseindia.com/content/RSS/Circulars.xml",
}

CATEGORY_LABELS: Dict[str, str] = {
    "corporate_announcements": "Corporate Announcements",
    "financial_results": "Financial Results",
    "annual_reports": "Annual Reports",
    "board_meetings": "Board Meetings",
    "corporate_actions": "Corporate Actions",
    "shareholding_patterns": "Shareholding Patterns",
    "circulars": "Circulars & Notices",
}

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

# Known company name -> symbol mapping for NSE
NAME_TO_SYMBOL_MAP: Dict[str, str] = {
    "HINDUSTAN AERONAUTICS": "HAL",
    "HINDUSTAN AERONAUTICS LIMITED": "HAL",
    "APOLLO MICRO SYSTEMS": "APOLLO",
    "APOLLO MICRO SYSTEMS LIMITED": "APOLLO",
    "MTAR TECHNOLOGIES": "MTAR",
    "MTAR TECHNOLOGIES LIMITED": "MTAR",
    "BHARAT ELECTRONICS": "BEL",
    "BHARAT ELECTRONICS LIMITED": "BEL",
    "RELIANCE INDUSTRIES": "RELIANCE",
    "TATA CONSULTANCY SERVICES": "TCS",
    "INFOSYS": "INFY",
    "STATE BANK OF INDIA": "SBIN",
    "HDFC BANK": "HDFCBANK",
    "ICICI BANK": "ICICIBANK",
}

# Cache to avoid excessive requests: category -> (timestamp, list of items)
_NSE_CACHE: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
CACHE_TTL_SECONDS = 120  # 2 minutes


def _parse_timestamp(date_str: str) -> tuple[int, str]:
    """Parse date string into (unix_epoch, formatted_iso_or_clean)."""
    if not date_str:
        now = int(time.time())
        return now, datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")

    date_str = date_str.strip()
    formats = [
        "%d-%b-%Y %H:%M:%S",
        "%d-%b-%Y %H:%M",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return int(dt.timestamp()), dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    now = int(time.time())
    return now, date_str


def _extract_symbol_from_nse(title: str, link: str, description: str) -> str:
    """Extract stock symbol from PDF URL, title, or description."""
    # 1. From attachment URL: /corporate/KAYA_08112026151751...
    if link:
        m = re.search(r'/corporate/([A-Za-z0-9]+)_', link)
        if m:
            sym = m.group(1).upper()
            if len(sym) >= 2 and not sym.isdigit():
                return sym

    # 2. Known company names
    norm_title = title.upper()
    for name, sym in NAME_TO_SYMBOL_MAP.items():
        if name in norm_title:
            return sym

    # 3. First uppercase word of title if clean ticker format
    words = title.strip().split()
    if words:
        first = words[0].upper().replace(",", "").replace(".", "")
        if first.isalnum() and 2 <= len(first) <= 12 and not first.isdigit():
            return first

    return "GENERAL"


class NSEAlertsCollector:
    """Collector for NSE regulatory and corporate RSS alerts."""

    def __init__(self, timeout: int = 8):
        self.timeout = timeout

    def fetch_category(self, category_key: str, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Fetch and parse a single NSE RSS feed category."""
        url = NSE_FEED_URLS.get(category_key)
        if not url:
            log.warning(f"[NSE] Unknown category key: {category_key}")
            return []

        # Check cache
        if not force_refresh and category_key in _NSE_CACHE:
            cached_time, cached_items = _NSE_CACHE[category_key]
            if time.time() - cached_time < CACHE_TTL_SECONDS:
                return cached_items

        try:
            res = requests.get(url, headers=REQUEST_HEADERS, timeout=self.timeout)
            if res.status_code != 200:
                log.warning(f"[NSE] Feed {category_key} returned HTTP {res.status_code}")
                return []

            root = ET.fromstring(res.content)
            channel = root.find("channel")
            if channel is None:
                return []

            items = channel.findall("item")
            parsed_alerts: List[Dict[str, Any]] = []

            for idx, item in enumerate(items):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                description = (item.findtext("description") or "").strip()
                pub_date = (item.findtext("pubDate") or "").strip()
                guid = (item.findtext("guid") or f"nse-{category_key}-{idx}-{hash(link or title)}").strip()

                epoch_ts, clean_date = _parse_timestamp(pub_date)
                symbol = _extract_symbol_from_nse(title, link, description)

                # Company name cleanup
                company_name = title.split("has informed")[0].strip() if "has informed" in title else title

                parsed_alerts.append({
                    "id": f"NSE-{hash(guid) & 0xFFFFFFFF:08x}",
                    "exchange": "NSE",
                    "category": CATEGORY_LABELS.get(category_key, category_key.title()),
                    "category_key": category_key,
                    "symbol": symbol,
                    "company_name": company_name,
                    "title": title,
                    "description": description or f"NSE Regulatory Filing for {company_name}",
                    "pub_date": clean_date,
                    "timestamp": epoch_ts,
                    "link": link,
                    "attachment_url": link if link.lower().endswith(".pdf") else "",
                    "guid": guid,
                })

            _NSE_CACHE[category_key] = (time.time(), parsed_alerts)
            return parsed_alerts

        except Exception as exc:
            log.warning(f"[NSE] Failed to fetch {category_key}: {exc}")
            # Fallback to cached if available
            if category_key in _NSE_CACHE:
                return _NSE_CACHE[category_key][1]
            return []

    def fetch_all(self, limit_per_category: int = 15, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Fetch all configured NSE categories, merge and sort chronologically."""
        all_alerts: List[Dict[str, Any]] = []
        for cat in NSE_FEED_URLS.keys():
            items = self.fetch_category(cat, force_refresh=force_refresh)
            all_alerts.extend(items[:limit_per_category])

        all_alerts.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return all_alerts


_collector_instance: Optional[NSEAlertsCollector] = None


def get_nse_collector() -> NSEAlertsCollector:
    global _collector_instance
    if _collector_instance is None:
        _collector_instance = NSEAlertsCollector()
    return _collector_instance


def fetch_all_nse_alerts(limit: int = 50) -> List[Dict[str, Any]]:
    """Convenience helper to retrieve latest NSE alerts."""
    collector = get_nse_collector()
    return collector.fetch_all()[:limit]
