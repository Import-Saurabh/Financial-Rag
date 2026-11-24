"""
backend/alerts/bse_alerts.py — BSE Regulatory Disclosures & Corporate Filings Feed Collector.
Fetches, parses, and normalizes live RSS feeds from the Bombay Stock Exchange (BSE).
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

# Official BSE RSS Feeds
BSE_FEED_URLS: Dict[str, str] = {
    "corporate_announcements": "https://www.bseindia.com/data/xml/announcements.aspx",
    "financial_results": "https://www.bseindia.com/Data/XML/FinancialResultsFeed.aspx",
    "annual_reports": "https://www.bseindia.com/Data/XML/AnnualReportFeed.aspx",
    "board_meetings": "https://beta.bseindia.com/Data/XML/BoardMeetingsFeed.xml",
    "corporate_actions": "https://www.bseindia.com/data/XML/CorpActionFeed.aspx",
    "notices": "https://www.bseindia.com/data/xml/notices.xml",
    "insider_trading": "https://www.bseindia.com/Data/XML/InsiderTradingFeed.aspx",
    "shareholding_patterns": "https://www.bseindia.com/Data/XML/ShareholdingPattern_Feed.aspx",
    "voting_results": "https://beta.bseindia.com/data/XML/VotingResultFeed.xml",
}

CATEGORY_LABELS: Dict[str, str] = {
    "corporate_announcements": "Corporate Announcements",
    "financial_results": "Financial Results",
    "annual_reports": "Annual Reports",
    "board_meetings": "Board Meetings",
    "corporate_actions": "Corporate Actions",
    "notices": "Exchange Notices",
    "insider_trading": "Insider Trading Disclosures",
    "shareholding_patterns": "Shareholding Patterns",
    "voting_results": "Voting Results",
}

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
}

# BSE Scrip Code -> Symbol mappings for key equities
SCRIP_CODE_TO_SYMBOL: Dict[str, str] = {
    "541154": "HAL",
    "532974": "APOLLO",
    "540064": "MTAR",
    "500049": "BEL",
    "500325": "RELIANCE",
    "532540": "TCS",
    "500209": "INFY",
    "500112": "SBIN",
    "500180": "HDFCBANK",
    "532174": "ICICIBANK",
    "539276": "KAYA",
}

NAME_TO_SYMBOL_MAP: Dict[str, str] = {
    "HINDUSTAN AERONAUTICS": "HAL",
    "APOLLO MICRO SYSTEMS": "APOLLO",
    "MTAR TECHNOLOGIES": "MTAR",
    "BHARAT ELECTRONICS": "BEL",
    "RELIANCE": "RELIANCE",
    "TATA CONSULTANCY": "TCS",
    "INFOSYS": "INFY",
    "STATE BANK OF INDIA": "SBIN",
}

_BSE_CACHE: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
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


def _extract_symbol_from_bse(title: str, scrip_code: str) -> str:
    """Extract symbol using scrip code or company name."""
    if scrip_code and scrip_code in SCRIP_CODE_TO_SYMBOL:
        return SCRIP_CODE_TO_SYMBOL[scrip_code]

    # Check title for scrip code e.g. "Kaya Ltd (539276)"
    m = re.search(r'\((\d{5,6})\)', title)
    if m:
        code = m.group(1)
        if code in SCRIP_CODE_TO_SYMBOL:
            return SCRIP_CODE_TO_SYMBOL[code]

    norm_title = title.upper()
    for name, sym in NAME_TO_SYMBOL_MAP.items():
        if name in norm_title:
            return sym

    # Fallback to cleaned first word
    clean_name = re.sub(r'\s*\(\d{5,6}\)', '', title).strip()
    words = clean_name.split()
    if words:
        first = words[0].upper().replace(",", "").replace(".", "")
        if first.isalnum() and 2 <= len(first) <= 12 and not first.isdigit():
            return first

    return "GENERAL"


class BSEAlertsCollector:
    """Collector for BSE corporate announcements and regulatory feeds."""

    def __init__(self, timeout: int = 8):
        self.timeout = timeout

    def fetch_category(self, category_key: str, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Fetch and parse a single BSE RSS feed category."""
        url = BSE_FEED_URLS.get(category_key)
        if not url:
            log.warning(f"[BSE] Unknown category key: {category_key}")
            return []

        # Check cache
        if not force_refresh and category_key in _BSE_CACHE:
            cached_time, cached_items = _BSE_CACHE[category_key]
            if time.time() - cached_time < CACHE_TTL_SECONDS:
                return cached_items

        try:
            res = requests.get(url, headers=REQUEST_HEADERS, timeout=self.timeout)
            if res.status_code != 200:
                log.warning(f"[BSE] Feed {category_key} returned HTTP {res.status_code}")
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
                scrip_code = (item.findtext("scripcode") or "").strip()
                guid = (item.findtext("guid") or f"bse-{category_key}-{idx}-{hash(link or title)}").strip()

                epoch_ts, clean_date = _parse_timestamp(pub_date)
                symbol = _extract_symbol_from_bse(title, scrip_code)

                # Clean company name by removing scrip code suffix e.g. "Kaya Ltd (539276)" -> "Kaya Ltd"
                company_name = re.sub(r'\s*\(\d{5,6}\)', '', title).strip() or title

                parsed_alerts.append({
                    "id": f"BSE-{hash(guid) & 0xFFFFFFFF:08x}",
                    "exchange": "BSE",
                    "category": CATEGORY_LABELS.get(category_key, category_key.title()),
                    "category_key": category_key,
                    "symbol": symbol,
                    "scrip_code": scrip_code,
                    "company_name": company_name,
                    "title": title,
                    "description": description or f"BSE Corporate Filing for {company_name}",
                    "pub_date": clean_date,
                    "timestamp": epoch_ts,
                    "link": link,
                    "attachment_url": link if link.lower().endswith(".pdf") else "",
                    "guid": guid,
                })

            _BSE_CACHE[category_key] = (time.time(), parsed_alerts)
            return parsed_alerts

        except Exception as exc:
            log.warning(f"[BSE] Failed to fetch {category_key}: {exc}")
            if category_key in _BSE_CACHE:
                return _BSE_CACHE[category_key][1]
            return []

    def fetch_all(self, limit_per_category: int = 15, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Fetch all configured BSE categories, merge and sort chronologically."""
        all_alerts: List[Dict[str, Any]] = []
        for cat in BSE_FEED_URLS.keys():
            items = self.fetch_category(cat, force_refresh=force_refresh)
            all_alerts.extend(items[:limit_per_category])

        all_alerts.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return all_alerts


_collector_instance: Optional[BSEAlertsCollector] = None


def get_bse_collector() -> BSEAlertsCollector:
    global _collector_instance
    if _collector_instance is None:
        _collector_instance = BSEAlertsCollector()
    return _collector_instance


def fetch_all_bse_alerts(limit: int = 50) -> List[Dict[str, Any]]:
    """Convenience helper to retrieve latest BSE alerts."""
    collector = get_bse_collector()
    return collector.fetch_all()[:limit]
