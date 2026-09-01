import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ai-manager-auto.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

class TestLeadConnector:
    def test_workflow_list(self, auth_client, workspace):
        ws_id = workspace["id"]
        r = auth_client.get(f"{API}/workspaces/{ws_id}/workflows")
        assert r.status_code == 200, r.text
        wfs = r.json()
        assert len(wfs) >= 1
        ads_wf = next((w for w in wfs if w["kind"] == "ads_to_crm"), None)
        assert ads_wf is not None
        assert ads_wf["status"] == "draft"

    def test_google_connection_status(self, auth_client, workspace):
        ws_id = workspace["id"]
        r = auth_client.get(f"{API}/google/workspaces/{ws_id}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["connected"] is False

    def test_column_mapping_requires_phone(self, auth_client):
        ws_id = "000000000000000000000001"
        r = auth_client.patch(
            f"{API}/google/workspaces/{ws_id}/column_map",
            json={"column_map": {"email": "Email"}},
        )
        assert r.status_code == 400
        assert "Phone column mapping is required" in r.text

    def test_crm_leads_empty(self, auth_client, workspace):
        ws_id = workspace["id"]
        r = auth_client.get(f"{API}/workspaces/{ws_id}/crm/leads")
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)
        assert len(r.json()) == 0

    def test_publish_fails_without_bind(self, auth_client, workspace):
        ws_id = workspace["id"]
        # publishing should fail with 400 since no sheet is bound
        r = auth_client.post(f"{API}/workspaces/{ws_id}/workflows/ads-to-crm/publish")
        assert r.status_code == 400
        assert "bind" in r.text or "connect" in r.text
