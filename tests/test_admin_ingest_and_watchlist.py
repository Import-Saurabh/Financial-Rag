"""
tests/test_admin_ingest_and_watchlist.py — End-to-End Verification for:
1. Ingested vs Pending Document Catalog & Interactive Click-to-Ingest
2. WhatsApp Stock Watchlist Management & Concall Schedule Alerts
"""

import os
import sys
from pathlib import Path

# Add project root and backend to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from server import app
from whatsapp.watchlist import get_watchlist_manager


def test_document_catalog_and_ingestion():
    client = TestClient(app)
    
    # 1. Fetch document catalog
    res = client.get("/api/admin/documents")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    
    assert "ingested" in data, "Response missing 'ingested' list"
    assert "pending" in data, "Response missing 'pending' list"
    
    ingested_count = len(data["ingested"])
    pending_count = len(data["pending"])
    print(f"[TEST] Catalog loaded: {ingested_count} Ingested, {pending_count} Pending")
    assert ingested_count > 0, "Expected at least one ingested document"
    
    # 2. Select a pending document to ingest
    if pending_count > 0:
        doc_to_ingest = data["pending"][0]
        filename = doc_to_ingest["file_name"]
        sym = doc_to_ingest.get("symbol") or "HAL"
        print(f"[TEST] Triggering click-to-ingest for pending file: {filename} (symbol={sym})")
        
        ingest_res = client.post(
            "/api/admin/documents/ingest",
            json={
                "filename": filename,
                "symbol": sym,
                "doc_type": "concall"
            }
        )
        assert ingest_res.status_code == 200, f"Ingest failed: {ingest_res.text}"
        ingest_data = ingest_res.json()
        assert ingest_data["status"] == "success", "Expected status 'success'"
        print(f"[TEST] Ingestion succeeded: {ingest_data['message']}")
        
        # 3. Verify it is now in ingested catalog
        refreshed_res = client.get("/api/admin/documents")
        refreshed_data = refreshed_res.json()
        stem = os.path.splitext(filename)[0]
        is_now_ingested = any(stem.lower() in d["file_name"].lower() for d in refreshed_data["ingested"])
        assert is_now_ingested, f"File {filename} was not found in refreshed ingested list!"
        print(f"[TEST] Verification passed: {filename} successfully moved to Live Ingested catalog!")
    else:
        print("[TEST] No pending files; tested catalog retrieval.")


def test_whatsapp_watchlist_and_concall_alerts():
    wm = get_watchlist_manager()
    test_phone = "919999888877"
    
    # 1. Add HAL to watchlist
    ok, msg = wm.add_to_watchlist(test_phone, "HAL")
    print(f"[TEST] Add HAL to watchlist: {msg}")
    assert "HAL" in wm.get_user_symbols(test_phone)
    
    # 2. Add APOLLO to watchlist
    ok, msg = wm.add_to_watchlist(test_phone, "APOLLO")
    print(f"[TEST] Add APOLLO to watchlist: {msg}")
    assert "APOLLO" in wm.get_user_symbols(test_phone)
    
    # 3. Verify formatted report contains upcoming concalls and published reports
    report = wm.format_watchlist_status(test_phone)
    print(f"[TEST] Formatted WhatsApp Watchlist Report:\n{report}")
    assert "HAL" in report
    assert "APOLLO" in report
    assert "SCHEDULED" in report or "CONDUCTED" in report
    
    # 4. Test Intent Detector
    assert wm.detect_watchlist_intent("my watchlist") == ("view", None)
    assert wm.detect_watchlist_intent("track BEL") == ("add", "BEL")
    assert wm.detect_watchlist_intent("untrack HAL") == ("remove", "HAL")
    assert wm.detect_watchlist_intent("concall schedule") == ("schedule", None)
    print("[TEST] Watchlist intent detection passed!")
    
    # 5. Clean up / untrack
    wm.remove_from_watchlist(test_phone, "APOLLO")
    assert "APOLLO" not in wm.get_user_symbols(test_phone)
    print("[TEST] Watchlist removal verified!")


if __name__ == "__main__":
    print("=== Running Ingestion & Watchlist Tests ===")
    test_document_catalog_and_ingestion()
    test_whatsapp_watchlist_and_concall_alerts()
    print("\n✅ ALL ADMIN INGESTION & WHATSAPP WATCHLIST TESTS PASSED SUCCESSFULLY!")
