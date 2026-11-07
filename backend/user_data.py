"""
backend/user_data.py — User-Scoped Persistence for Chat History and Stock Watchlists.
Guarantees strict isolation of chat history and watchlists across every authenticated user.
"""

from __future__ import annotations

import os
import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"
CHATS_DIR = DATA_DIR / "chat_history"
USER_WATCHLIST_FILE = DATA_DIR / "user_watchlists.json"
CALENDAR_FILE = DATA_DIR / "corporate_calendar.json"

CHATS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 1. Chat History Management per User
# ---------------------------------------------------------------------------

def _get_chat_file(username: str) -> Path:
    clean_u = "".join(c for c in username.lower().strip() if c.isalnum() or c in ("_", "-"))
    if not clean_u:
        clean_u = "anonymous"
    return CHATS_DIR / f"{clean_u}.json"


def get_user_chats(username: str) -> List[Dict[str, Any]]:
    """Return the saved chat session list for the given user."""
    chat_file = _get_chat_file(username)
    if not chat_file.exists():
        return []
    try:
        with open(chat_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except Exception as exc:
        log.warning(f"[user_data] Failed to read chat history for {username}: {exc}")
        return []


def save_user_chats(username: str, chats: List[Dict[str, Any]]) -> bool:
    """Save full chat session list for the given user."""
    chat_file = _get_chat_file(username)
    try:
        chat_file.parent.mkdir(parents=True, exist_ok=True)
        with open(chat_file, "w", encoding="utf-8") as f:
            json.dump(chats, f, indent=2, ensure_ascii=False)
        return True
    except Exception as exc:
        log.error(f"[user_data] Failed to write chat history for {username}: {exc}")
        return False


def delete_user_chat(username: str, chat_id: str) -> bool:
    """Delete a specific chat session for the given user."""
    chats = get_user_chats(username)
    filtered = [c for c in chats if c.get("id") != chat_id]
    return save_user_chats(username, filtered)


# ---------------------------------------------------------------------------
# 2. Watchlist Management per User (with Corporate Calendar Enrichment)
# ---------------------------------------------------------------------------

def _load_all_user_watchlists() -> Dict[str, List[str]]:
    if not USER_WATCHLIST_FILE.exists():
        # Seed default watchlists for default accounts
        defaults = {
            "admin": ["HAL", "APOLLO", "MTAR"],
            "user": ["HAL", "APOLLO"]
        }
        _save_all_user_watchlists(defaults)
        return defaults
    try:
        with open(USER_WATCHLIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning(f"[user_data] Failed to load user watchlists: {exc}")
        return {}


def _save_all_user_watchlists(data: Dict[str, List[str]]) -> None:
    USER_WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USER_WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_user_watchlist_symbols(username: str) -> List[str]:
    """Return the list of stock symbols tracked by a web user."""
    all_wl = _load_all_user_watchlists()
    u = username.lower().strip()
    return all_wl.get(u, ["HAL", "APOLLO"])


def add_to_user_watchlist(username: str, symbol: str) -> List[str]:
    """Add a stock symbol to the user's watchlist."""
    all_wl = _load_all_user_watchlists()
    u = username.lower().strip()
    sym = symbol.upper().strip()
    if not sym:
        return all_wl.get(u, [])
    
    current = all_wl.get(u, ["HAL", "APOLLO"])
    if sym not in current:
        current.append(sym)
    all_wl[u] = current
    _save_all_user_watchlists(all_wl)
    return current


def remove_from_user_watchlist(username: str, symbol: str) -> List[str]:
    """Remove a stock symbol from the user's watchlist."""
    all_wl = _load_all_user_watchlists()
    u = username.lower().strip()
    sym = symbol.upper().strip()
    
    current = all_wl.get(u, [])
    current = [s for s in current if s != sym]
    all_wl[u] = current
    _save_all_user_watchlists(all_wl)
    return current


def get_user_watchlist_enriched(username: str) -> List[Dict[str, Any]]:
    """
    Return the user's tracked symbols with real-time corporate calendar events,
    upcoming concalls, meeting status, and annual report publication status.
    """
    symbols = get_user_watchlist_symbols(username)
    calendar_events = []
    if CALENDAR_FILE.exists():
        try:
            with open(CALENDAR_FILE, "r", encoding="utf-8") as f:
                calendar_events = json.load(f).get("events", [])
        except Exception as exc:
            log.warning(f"[user_data] Failed to read corporate calendar: {exc}")

    enriched = []
    for sym in symbols:
        # Find all calendar items matching this symbol
        matched_events = [e for e in calendar_events if e.get("symbol", "").upper() == sym]
        
        # Sort by scheduled_date descending
        matched_events.sort(key=lambda x: x.get("scheduled_date", ""), reverse=True)
        
        # Find next upcoming event or latest conducted event
        upcoming = next((e for e in matched_events if e.get("meeting_status") == "Scheduled"), None)
        latest_published = next((e for e in matched_events if "Published" in e.get("published_status", "")), None)
        
        primary_event = upcoming or (matched_events[0] if matched_events else None)
        
        enriched.append({
            "symbol": sym,
            "company_name": primary_event.get("company_name", sym) if primary_event else sym,
            "fiscal_period": primary_event.get("fiscal_period", "FY25") if primary_event else "N/A",
            "event_type": primary_event.get("event_type", "Management Concall") if primary_event else "Earnings Update",
            "scheduled_date": primary_event.get("scheduled_date", "TBD") if primary_event else "TBD",
            "scheduled_time": primary_event.get("scheduled_time", "TBD") if primary_event else "TBD",
            "meeting_status": primary_event.get("meeting_status", "Awaiting Schedule") if primary_event else "Unscheduled",
            "published_status": primary_event.get("published_status", "Pending") if primary_event else "Pending",
            "notes": primary_event.get("notes", "No active management notes available") if primary_event else "Filing monitor active.",
            "dial_in_info": primary_event.get("dial_in_info", "") if primary_event else "",
            "all_events": matched_events,
        })

    return enriched


def get_all_web_watchlists() -> Dict[str, List[str]]:
    """Return all web user watchlists for the Admin dashboard."""
    return _load_all_user_watchlists()
