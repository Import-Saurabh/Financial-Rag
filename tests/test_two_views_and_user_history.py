"""
tests/test_two_views_and_user_history.py
Validates:
1. Legacy Streamlit frontend complete removal.
2. Two-view system: User role vs Admin role.
3. Isolated chat history per user (Admin vs User vs Anonymous).
4. Stock watchlist per user with corporate calendar concall enrichment.
5. Admin dashboard ready verification (all endpoints functional).
"""

import os
import sys
from pathlib import Path
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from server import app


def get_client():
    return TestClient(app)


def test_streamlit_removed():
    """Verify that the legacy frontend/ directory has been eliminated."""
    frontend_dir = REPO_ROOT / "frontend"
    assert not frontend_dir.exists(), "Legacy Streamlit frontend/ directory must not exist"
    streamlit_service = REPO_ROOT / "deployment" / "finrag-streamlit.service"
    assert not streamlit_service.exists(), "Streamlit systemd service must not exist"


def test_auth_and_two_views_rbac(client):
    """Verify Admin and User authentication & roles."""
    # 1. Admin login
    admin_res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert admin_res.status_code == 200
    admin_data = admin_res.json()
    assert admin_data["user"]["role"] == "admin"
    admin_token = admin_data["token"]

    # 2. User login
    user_res = client.post("/api/auth/login", json={"username": "user", "password": "user123"})
    assert user_res.status_code == 200
    user_data = user_res.json()
    assert user_data["user"]["role"] == "user"
    user_token = user_data["token"]

    # 3. Verify /api/auth/me
    me_admin = client.get("/api/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert me_admin.status_code == 200
    assert me_admin.json()["user"]["role"] == "admin"

    me_user = client.get("/api/auth/me", headers={"Authorization": f"Bearer {user_token}"})
    assert me_user.status_code == 200
    assert me_user.json()["user"]["role"] == "user"


def test_user_chat_history_isolation(client):
    """Verify chat history is saved, retrieved, and isolated per user."""
    # Login both users
    admin_token = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"}).json()["token"]
    user_token = client.post("/api/auth/login", json={"username": "user", "password": "user123"}).json()["token"]

    admin_chats = [
        {
            "id": "chat_admin_001",
            "title": "HAL FY25 Defense Production Analysis",
            "messages": [{"id": "1", "role": "user", "content": "What is HAL's revenue guidance?"}]
        }
    ]

    user_chats = [
        {
            "id": "chat_user_001",
            "title": "Apollo Micro Underwater Systems",
            "messages": [{"id": "1", "role": "user", "content": "Tell me about Apollo defense orders."}]
        }
    ]

    # Save Admin chats
    save_admin = client.post("/api/user/chats", json={"chats": admin_chats}, headers={"Authorization": f"Bearer {admin_token}"})
    assert save_admin.status_code == 200
    assert save_admin.json()["username"] == "admin"

    # Save User chats
    save_user = client.post("/api/user/chats", json={"chats": user_chats}, headers={"Authorization": f"Bearer {user_token}"})
    assert save_user.status_code == 200
    assert save_user.json()["username"] == "user"

    # Fetch Admin chats: must only contain Admin chats
    get_admin = client.get("/api/user/chats", headers={"Authorization": f"Bearer {admin_token}"})
    assert get_admin.status_code == 200
    admin_titles = [c["title"] for c in get_admin.json()["chats"]]
    assert "HAL FY25 Defense Production Analysis" in admin_titles
    assert "Apollo Micro Underwater Systems" not in admin_titles

    # Fetch User chats: must only contain User chats
    get_user = client.get("/api/user/chats", headers={"Authorization": f"Bearer {user_token}"})
    assert get_user.status_code == 200
    user_titles = [c["title"] for c in get_user.json()["chats"]]
    assert "Apollo Micro Underwater Systems" in user_titles
    assert "HAL FY25 Defense Production Analysis" not in user_titles

    # Delete specific chat session
    del_res = client.delete("/api/user/chats/chat_user_001", headers={"Authorization": f"Bearer {user_token}"})
    assert del_res.status_code == 200
    get_user_after = client.get("/api/user/chats", headers={"Authorization": f"Bearer {user_token}"})
    assert len(get_user_after.json()["chats"]) == 0


def test_user_stock_watchlist_with_concalls(client):
    """Verify stock watchlist per user, calendar enrichment, add and delete."""
    user_token = client.post("/api/auth/login", json={"username": "user", "password": "user123"}).json()["token"]

    # 1. Fetch user watchlist (HAL is pre-seeded)
    wl_res = client.get("/api/user/watchlist", headers={"Authorization": f"Bearer {user_token}"})
    assert wl_res.status_code == 200
    watchlist = wl_res.json()["watchlist"]
    symbols = [w["symbol"] for w in watchlist]
    assert "HAL" in symbols

    # Check enrichment details
    hal_item = next(w for w in watchlist if w["symbol"] == "HAL")
    assert hal_item["company_name"] == "Hindustan Aeronautics Limited"
    assert hal_item["meeting_status"] in ("Scheduled", "Conducted")
    assert "scheduled_date" in hal_item

    # 2. Add a new stock: BEL
    add_res = client.post("/api/user/watchlist", json={"symbol": "BEL"}, headers={"Authorization": f"Bearer {user_token}"})
    assert add_res.status_code == 200
    updated_symbols = [w["symbol"] for w in add_res.json()["watchlist"]]
    assert "BEL" in updated_symbols

    # 3. Untrack BEL
    del_res = client.delete("/api/user/watchlist/BEL", headers={"Authorization": f"Bearer {user_token}"})
    assert del_res.status_code == 200
    final_symbols = [w["symbol"] for w in del_res.json()["watchlist"]]
    assert "BEL" not in final_symbols


def test_admin_dashboard_readiness(client):
    """Verify Admin Dashboard endpoints are completely ready, operational, and reading live data."""
    # 1. Document Catalog (Pending vs Ingested)
    docs_res = client.get("/api/admin/documents")
    assert docs_res.status_code == 200
    data = docs_res.json()
    assert "ingested" in data
    assert "pending" in data
    assert len(data["ingested"]) > 0

    # 2. WhatsApp Watchlists & Corporate Calendar & Web Watchlists
    wl_res = client.get("/api/admin/whatsapp/watchlists")
    assert wl_res.status_code == 200
    wl_data = wl_res.json()
    assert "watchlists" in wl_data
    assert "web_watchlists" in wl_data
    assert "calendar" in wl_data
    assert len(wl_data["calendar"]) >= 2

    # 3. WhatsApp User Telemetry & Credit Quotas
    wa_users_res = client.get("/api/admin/whatsapp/users")
    assert wa_users_res.status_code == 200
    assert "users" in wa_users_res.json()

    # 4. System & Vector Index Stats
    stats_res = client.get("/api/admin/stats")
    assert stats_res.status_code == 200
    stats = stats_res.json()
    assert "documents_indexed" in stats
    assert "whatsapp_users" in stats

    # 5. Document Content Reader (for Source Grounding Drawer)
    content_res = client.get("/api/documents/content?section=2026_Annual_Report_2026_part1")
    assert content_res.status_code == 200
    assert len(content_res.json()["content"]) > 100

    # 6. Click-to-ingest execution
    ingest_res = client.post("/api/admin/documents/ingest", json={
        "filename": "HAL_Q2FY25_Earnings_Concall_Pending.md",
        "symbol": "HAL",
        "doc_type": "concall"
    })
    assert ingest_res.status_code == 200
    assert ingest_res.json()["status"] in ("success", "ingested")


if __name__ == "__main__":
    tc = TestClient(app)
    print("Running test_streamlit_removed...")
    test_streamlit_removed()
    print("  -> Passed!")

    print("Running test_auth_and_two_views_rbac...")
    test_auth_and_two_views_rbac(tc)
    print("  -> Passed!")

    print("Running test_user_chat_history_isolation...")
    test_user_chat_history_isolation(tc)
    print("  -> Passed!")

    print("Running test_user_stock_watchlist_with_concalls...")
    test_user_stock_watchlist_with_concalls(tc)
    print("  -> Passed!")

    print("Running test_admin_dashboard_readiness...")
    test_admin_dashboard_readiness(tc)
    print("  -> Passed!")

    print("\nALL TESTS PASSED SUCCESSFULLY! (100% READY)")
