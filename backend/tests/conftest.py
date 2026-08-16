import os
import time
import uuid
import requests
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else "https://ai-manager-auto.preview.emergentagent.com"
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@arevei.ai"
ADMIN_PASSWORD = "arevei123"


@pytest.fixture(scope="session")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_token(api_client):
    r = api_client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def auth_client(api_client, admin_token):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {admin_token}"})
    return s


@pytest.fixture(scope="session")
def workspace(auth_client):
    """Create workspace once and wait for brain to be ready."""
    r = auth_client.post(f"{API}/workspaces", json={"website_url": "https://stripe.com", "model_id": "gpt-5.4"})
    assert r.status_code == 200, r.text
    ws = r.json()
    ws_id = ws["id"]
    # poll for brain ready
    deadline = time.time() + 90
    while time.time() < deadline:
        r = auth_client.get(f"{API}/workspaces/{ws_id}")
        assert r.status_code == 200, r.text
        ws = r.json()
        if ws.get("brain_status") in ("ready", "error"):
            break
        time.sleep(4)
    assert ws.get("brain_status") == "ready", f"Brain did not become ready: status={ws.get('brain_status')}"
    return ws
