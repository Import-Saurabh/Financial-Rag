"""
backend/whatsapp/credits.py — WhatsApp User Credit & Token Quota System
Enforces daily token limits (aligned with Groq free-tier constraints) to prevent
credit exhaustion, while supporting multi-LLM provider fallback.
"""

import os
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional

log = logging.getLogger(__name__)

CREDITS_FILE = Path(__file__).resolve().parent.parent / "data" / "whatsapp_credits.json"

# Default daily limit: 10,000 tokens per user per day (~25-30 complex queries)
DEFAULT_DAILY_TOKEN_LIMIT = int(os.getenv("WHATSAPP_DAILY_TOKEN_LIMIT", "10000"))


class WhatsAppCreditManager:
    def __init__(self, file_path: Optional[Path] = None):
        self.file_path = file_path or CREDITS_FILE
        self._ensure_storage()

    def _ensure_storage(self):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump({}, f)

    def _load_data(self) -> Dict[str, Any]:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"[credits] Could not load credits file: {e}")
            return {}

    def _save_data(self, data: Dict[str, Any]):
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.error(f"[credits] Could not save credits file: {e}")

    def _get_today_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def get_or_create_user(self, phone: str) -> Dict[str, Any]:
        data = self._load_data()
        phone_key = phone.strip().replace("+", "").replace(" ", "").replace("-", "")
        today = self._get_today_str()

        if phone_key not in data:
            data[phone_key] = {
                "phone": phone_key,
                "daily_limit": DEFAULT_DAILY_TOKEN_LIMIT,
                "tokens_used_today": 0,
                "total_tokens_all_time": 0,
                "queries_today": 0,
                "total_queries_all_time": 0,
                "last_active_date": today,
                "is_whitelisted": False,
                "first_seen": datetime.now(timezone.utc).isoformat(),
            }
            self._save_data(data)
            return data[phone_key]

        user = data[phone_key]
        # Check if new day has started -> reset daily counter
        if user.get("last_active_date") != today:
            user["tokens_used_today"] = 0
            user["queries_today"] = 0
            user["last_active_date"] = today
            self._save_data(data)

        return user

    def check_quota(self, phone: str, estimated_tokens: int = 500) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Checks if user has enough tokens remaining for a query.
        Returns (is_allowed, denial_reason_or_none, user_stats).
        """
        user = self.get_or_create_user(phone)
        
        # Whitelisted or unlimited users bypass check
        if user.get("is_whitelisted", False) or user.get("daily_limit", 0) <= 0:
            return True, None, user

        used = user.get("tokens_used_today", 0)
        limit = user.get("daily_limit", DEFAULT_DAILY_TOKEN_LIMIT)

        if used + estimated_tokens > limit:
            remaining = max(0, limit - used)
            msg = (
                f"⚠️ *Daily Research Limit Reached*\n\n"
                f"You have used *{used:,}* of your *{limit:,}* free daily tokens.\n\n"
                f"• *Tokens remaining today:* {remaining}\n"
                f"• *Quota resets:* Midnight UTC\n\n"
                f"💡 _Tip: For unrestricted institutional equity research, visit our visual desktop portal at:_\n"
                f"https://financial-nifty-rag.duckdns.org"
            )
            return False, msg, user

        return True, None, user

    def record_usage(self, phone: str, tokens_consumed: int, query: str = ""):
        """Records token consumption after LLM generation completes."""
        data = self._load_data()
        phone_key = phone.strip().replace("+", "").replace(" ", "").replace("-", "")
        today = self._get_today_str()

        if phone_key not in data:
            self.get_or_create_user(phone_key)
            data = self._load_data()

        user = data[phone_key]
        if user.get("last_active_date") != today:
            user["tokens_used_today"] = 0
            user["queries_today"] = 0
            user["last_active_date"] = today

        user["tokens_used_today"] = user.get("tokens_used_today", 0) + tokens_consumed
        user["total_tokens_all_time"] = user.get("total_tokens_all_time", 0) + tokens_consumed
        user["queries_today"] = user.get("queries_today", 0) + 1
        user["total_queries_all_time"] = user.get("total_queries_all_time", 0) + 1
        user["last_query_at"] = datetime.now(timezone.utc).isoformat()
        if query:
            user["last_query"] = query[:100]

        self._save_data(data)
        log.info(f"[credits] Recorded {tokens_consumed} tokens for {phone_key}. Today: {user['tokens_used_today']}/{user.get('daily_limit')}")

    def list_users(self) -> List[Dict[str, Any]]:
        """Admin helper: list all tracked WhatsApp users and their consumption."""
        data = self._load_data()
        today = self._get_today_str()
        results = []
        for phone, info in data.items():
            if info.get("last_active_date") != today:
                info["tokens_used_today"] = 0
                info["queries_today"] = 0
            results.append(info)
        return results

    def set_user_limit(self, phone: str, limit: int, whitelist: bool = False):
        """Admin helper: set custom token quota or whitelist a user."""
        data = self._load_data()
        phone_key = phone.strip().replace("+", "").replace(" ", "").replace("-", "")
        if phone_key not in data:
            self.get_or_create_user(phone_key)
            data = self._load_data()

        data[phone_key]["daily_limit"] = limit
        data[phone_key]["is_whitelisted"] = whitelist
        self._save_data(data)
        log.info(f"[credits] Updated {phone_key}: limit={limit}, whitelist={whitelist}")


_credit_manager = WhatsAppCreditManager()

def get_credit_manager() -> WhatsAppCreditManager:
    return _credit_manager
