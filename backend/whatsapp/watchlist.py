"""
backend/whatsapp/watchlist.py — WhatsApp Stock Watchlist & Corporate Concall Alert System
Allows WhatsApp users to maintain personal equity watchlists, track upcoming concall dates,
monitor annual report publication statuses, and receive instant management meeting alerts.
"""

import os
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WATCHLIST_FILE = DATA_DIR / "whatsapp_watchlists.json"
CALENDAR_FILE = DATA_DIR / "corporate_calendar.json"


class WatchlistManager:
    def __init__(self):
        self.watchlist_file = WATCHLIST_FILE
        self.calendar_file = CALENDAR_FILE
        self._ensure_storage()

    def _ensure_storage(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not self.watchlist_file.exists():
            with open(self.watchlist_file, "w", encoding="utf-8") as f:
                json.dump({}, f)
        if not self.calendar_file.exists():
            with open(self.calendar_file, "w", encoding="utf-8") as f:
                json.dump({"events": []}, f)

    def _clean_phone(self, phone: str) -> str:
        return phone.strip().replace("+", "").replace(" ", "").replace("-", "")

    def _load_watchlists(self) -> Dict[str, Any]:
        try:
            with open(self.watchlist_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"[watchlist] Error loading watchlists: {e}")
            return {}

    def _save_watchlists(self, data: Dict[str, Any]):
        try:
            with open(self.watchlist_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.error(f"[watchlist] Error saving watchlists: {e}")

    def load_calendar_events(self) -> List[Dict[str, Any]]:
        try:
            with open(self.calendar_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("events", [])
        except Exception as e:
            log.warning(f"[watchlist] Error loading calendar: {e}")
            return []

    def save_calendar_event(self, event: Dict[str, Any]):
        try:
            data = {"events": []}
            if self.calendar_file.exists():
                with open(self.calendar_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            events = data.get("events", [])
            # Update existing or append new
            idx = next((i for i, e in enumerate(events) if e.get("id") == event.get("id")), -1)
            if idx >= 0:
                events[idx] = event
            else:
                events.append(event)
            data["events"] = events
            with open(self.calendar_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.error(f"[watchlist] Error saving calendar event: {e}")

    def get_user_symbols(self, phone: str) -> List[str]:
        data = self._load_watchlists()
        phone_key = self._clean_phone(phone)
        return data.get(phone_key, {}).get("symbols", [])

    def add_to_watchlist(self, phone: str, symbol: str) -> Tuple[bool, str]:
        sym = symbol.upper().strip()
        phone_key = self._clean_phone(phone)
        data = self._load_watchlists()

        if phone_key not in data:
            data[phone_key] = {
                "phone": phone_key,
                "symbols": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "notifications_enabled": True
            }

        user_data = data[phone_key]
        if sym in user_data["symbols"]:
            return False, f"*{sym}* is already in your watchlist."

        user_data["symbols"].append(sym)
        user_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_watchlists(data)
        log.info(f"[watchlist] User {phone_key} added {sym}. Total: {user_data['symbols']}")
        return True, f"✅ Added *{sym}* to your personal watchlist! You will be tracked for upcoming concalls and report filings."

    def remove_from_watchlist(self, phone: str, symbol: str) -> Tuple[bool, str]:
        sym = symbol.upper().strip()
        phone_key = self._clean_phone(phone)
        data = self._load_watchlists()

        if phone_key not in data or sym not in data[phone_key].get("symbols", []):
            return False, f"*{sym}* is not in your watchlist."

        data[phone_key]["symbols"].remove(sym)
        data[phone_key]["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_watchlists(data)
        return True, f"🗑️ Removed *{sym}* from your watchlist."

    def detect_watchlist_intent(self, text: str) -> Optional[Tuple[str, Optional[str]]]:
        """
        Parses text for watchlist commands:
        Returns ('view', None), ('add', 'HAL'), ('remove', 'HAL'), ('schedule', None)
        """
        t = text.lower().strip()

        # View command
        if t in ("watchlist", "my watchlist", "show watchlist", "/watchlist", "list watchlist"):
            return ("view", None)

        if any(w in t for w in ["upcoming concall", "concall schedule", "concall calendar", "board meeting schedule"]):
            return ("schedule", None)

        # Add command: e.g. "add HAL to watchlist", "watchlist add HAL", "track HAL"
        m_add = re.search(r'\b(?:add\s+([A-Za-z0-9_-]+)\s+to\s+watchlist|watchlist\s+add\s+([A-Za-z0-9_-]+)|track\s+([A-Za-z0-9_-]+))\b', t)
        if m_add and not t.startswith("untrack"):
            sym = m_add.group(1) or m_add.group(2) or m_add.group(3)
            return ("add", sym.upper())

        # Remove command: e.g. "remove HAL from watchlist", "untrack HAL"
        m_rem = re.search(r'\b(?:remove\s+([A-Za-z0-9_-]+)\s+from\s+watchlist|watchlist\s+remove\s+([A-Za-z0-9_-]+)|untrack\s+([A-Za-z0-9_-]+))\b', t)
        if m_rem:
            sym = m_rem.group(1) or m_rem.group(2) or m_rem.group(3)
            return ("remove", sym.upper())

        return None

    def format_watchlist_status(self, phone: str) -> str:
        """
        Generates full WhatsApp report for user's tracked stocks with upcoming
        concall schedules and published status.
        """
        symbols = self.get_user_symbols(phone)
        all_events = self.load_calendar_events()

        if not symbols:
            return (
                "📋 *Your Equity Watchlist is Empty*\n\n"
                "Track companies to receive automated alerts for upcoming management concalls, "
                "audited results, and annual reports!\n\n"
                "💡 *Quick Commands:*\n"
                "• Send `track HAL` to track Hindustan Aeronautics\n"
                "• Send `track APOLLO` to track Apollo Micro Systems\n"
                "• Send `track BEL` to track Bharat Electronics\n"
                "• Send `concall schedule` to view all announced upcoming meets"
            )

        msg = f"📋 *Your Financial Watchlist ({len(symbols)} Stocks)*\n"
        msg += f"──────────────────────\n"

        for sym in symbols:
            sym_events = [e for e in all_events if e.get("symbol", "").upper() == sym]
            msg += f"\n🏢 *{sym}*\n"

            if not sym_events:
                msg += "  • _No corporate meetings announced yet._\n"
                msg += f"  • Latest filing status: Up to date in OpenKB index.\n"
                continue

            for ev in sym_events:
                status = ev.get("meeting_status", "Scheduled")
                ev_type = ev.get("event_type", "Earnings Concall")
                period = ev.get("fiscal_period", "")
                dt_str = ev.get("scheduled_date", "TBD")
                time_str = ev.get("scheduled_time", "")
                pub_status = ev.get("published_status", "")

                if status == "Scheduled":
                    status_badge = "📅 *SCHEDULED*"
                    action_text = f"Concall on *{dt_str}* at *{time_str}*"
                elif status == "Conducted":
                    status_badge = "✅ *CONDUCTED*"
                    action_text = f"Conducted on {dt_str} — *{pub_status}*"
                else:
                    status_badge = "📢 *ANNOUNCED*"
                    action_text = f"Target date: {dt_str}"

                msg += f"  {status_badge}: {ev_type} ({period})\n"
                msg += f"  ↳ {action_text}\n"
                if ev.get("dial_in_info"):
                    msg += f"  ↳ 📞 _{ev['dial_in_info']}_\n"

        msg += "\n──────────────────────\n"
        msg += "💡 _Ask: 'What is HAL's order outlook?' or 'track BEL'_"
        return msg

    def format_all_schedules(self) -> str:
        """Formats general corporate calendar of all announced upcoming concalls."""
        all_events = self.load_calendar_events()
        if not all_events:
            return "📅 No upcoming concall schedules currently registered."

        msg = "📅 *Announced Management Concalls & Filings*\n"
        msg += "──────────────────────\n"
        for ev in all_events:
            sym = ev.get("symbol", "")
            comp = ev.get("company_name", sym)
            ev_type = ev.get("event_type", "")
            period = ev.get("fiscal_period", "")
            dt_str = ev.get("scheduled_date", "")
            time_str = ev.get("scheduled_time", "")
            status = ev.get("meeting_status", "")
            pub = ev.get("published_status", "")

            icon = "📅" if status == "Scheduled" else "✅"
            msg += f"\n{icon} *{comp} ({sym})* — {period}\n"
            msg += f"• *Event:* {ev_type}\n"
            msg += f"• *Date & Time:* {dt_str} {time_str}\n"
            msg += f"• *Status:* {status} ({pub})\n"
            if ev.get("dial_in_info"):
                msg += f"• *Details:* _{ev['dial_in_info']}_\n"

        msg += "\n──────────────────────\n"
        msg += "💡 _Reply `track <SYMBOL>` to get direct alerts when this concall happens._"
        return msg

    def list_all_watchlists(self) -> List[Dict[str, Any]]:
        """Admin helper: list all user phone numbers and their watchlists."""
        data = self._load_watchlists()
        return list(data.values())


_watchlist_manager = WatchlistManager()

def get_watchlist_manager() -> WatchlistManager:
    return _watchlist_manager
