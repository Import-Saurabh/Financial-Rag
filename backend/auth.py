"""
backend/auth.py — Role-Based Authentication & Token Management (RBAC)
Supports 'admin' and 'user' roles with secure PBKDF2 password hashing and signed tokens.
"""

import os
import hmac
import json
import time
import base64
import hashlib
import secrets
import logging
from typing import Optional, Dict, Any
from pathlib import Path

log = logging.getLogger(__name__)

# Secret key for signing tokens
JWT_SECRET = os.getenv("JWT_SECRET", "nifty_rag_super_secret_signing_key_2026")
USERS_FILE = Path(__file__).resolve().parent / "data" / "users.json"


def _hash_password(password: str, salt: Optional[str] = None) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256."""
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    ).hex()
    return f"{salt}${hashed}"


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored salt$hash."""
    try:
        salt, expected_hash = stored_hash.split("$", 1)
        actual_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
        ).hex()
        return hmac.compare_digest(actual_hash, expected_hash)
    except Exception:
        return False


def _create_token(payload: Dict[str, Any], expires_in_seconds: int = 86400 * 7) -> str:
    """Generate a signed URL-safe token with expiration."""
    data = dict(payload)
    data["exp"] = int(time.time()) + expires_in_seconds
    data["iat"] = int(time.time())

    encoded_payload = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    signature = hmac.new(
        JWT_SECRET.encode(), encoded_payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{encoded_payload}.{signature}"


def _verify_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify signature and expiration of token."""
    try:
        if "." not in token:
            return None
        encoded_payload, signature = token.split(".", 1)

        expected_sig = hmac.new(
            JWT_SECRET.encode(), encoded_payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None

        # Add padding back
        padded = encoded_payload + "=" * ((4 - len(encoded_payload) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())

        if payload.get("exp", 0) < time.time():
            return None

        return payload
    except Exception as e:
        log.debug(f"[auth] Token verification failed: {e}")
        return None


class UserManager:
    def __init__(self):
        self.file_path = USERS_FILE
        self._ensure_users_file()

    def _ensure_users_file(self):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            default_users = {
                "admin": {
                    "username": "admin",
                    "name": "Nifty Senior Admin",
                    "email": "admin@niftyrag.local",
                    "role": "admin",
                    "password_hash": _hash_password("admin123"),
                    "created_at": time.time(),
                },
                "user": {
                    "username": "user",
                    "name": "Research Analyst",
                    "email": "analyst@niftyrag.local",
                    "role": "user",
                    "password_hash": _hash_password("user123"),
                    "created_at": time.time(),
                },
            }
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(default_users, f, indent=2)

    def _load_users(self) -> Dict[str, Any]:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_users(self, users: Dict[str, Any]):
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)

    def authenticate(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        users = self._load_users()
        user = users.get(username.lower().strip())
        if not user:
            return None
        if not _verify_password(password, user["password_hash"]):
            return None

        return {
            "username": user["username"],
            "name": user.get("name", user["username"]),
            "email": user.get("email", ""),
            "role": user.get("role", "user"),
        }

    def register(self, username: str, password: str, name: str = "", role: str = "user") -> Optional[Dict[str, Any]]:
        users = self._load_users()
        u_clean = username.lower().strip()
        if u_clean in users:
            return None  # already exists

        user_data = {
            "username": u_clean,
            "name": name.strip() or u_clean.capitalize(),
            "email": f"{u_clean}@niftyrag.local",
            "role": role if role in ("admin", "user") else "user",
            "password_hash": _hash_password(password),
            "created_at": time.time(),
        }
        users[u_clean] = user_data
        self._save_users(users)

        return {
            "username": user_data["username"],
            "name": user_data["name"],
            "email": user_data["email"],
            "role": user_data["role"],
        }

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        users = self._load_users()
        user = users.get(username.lower().strip())
        if not user:
            return None
        return {
            "username": user["username"],
            "name": user.get("name", user["username"]),
            "email": user.get("email", ""),
            "role": user.get("role", "user"),
        }


_user_manager = UserManager()


def login_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    user = _user_manager.authenticate(username, password)
    if not user:
        return None
    token = _create_token(user)
    return {"token": token, "user": user}


def register_user(username: str, password: str, name: str = "", role: str = "user") -> Optional[Dict[str, Any]]:
    user = _user_manager.register(username, password, name=name, role=role)
    if not user:
        return None
    token = _create_token(user)
    return {"token": token, "user": user}


def verify_auth_token(token: str) -> Optional[Dict[str, Any]]:
    return _verify_token(token)
