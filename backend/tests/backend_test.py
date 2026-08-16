"""Backend E2E tests for Arevei AI Manager.

Tests order matters (session-scoped `workspace` fixture is expensive):
- Auth flow
- Models registry
- Workspace + brain build
- Brain edit
- Roadmap + tasks
- Blog generate + edit + publish + public
- Public embed endpoints
- Manager chat stream

The workspace fixture is scoped session-wide so we don't pay for LLM crawl/brain multiple times.
"""
import os
import time
import uuid
import json
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ai-manager-auto.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@arevei.ai"
ADMIN_PASSWORD = "arevei123"


# -------------------- AUTH --------------------
class TestAuth:
    def test_admin_login(self, api_client):
        r = api_client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "token" in data and len(data["token"]) > 20
        assert data["user"]["email"] == ADMIN_EMAIL
        assert data["user"]["role"] == "admin"

    def test_login_bad_password(self, api_client):
        r = api_client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"})
        assert r.status_code == 401

    def test_register_new_user(self, api_client):
        email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        r = api_client.post(f"{API}/auth/register", json={"name": "Test", "email": email, "password": "test1234"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user"]["email"] == email
        assert "token" in data

    def test_register_duplicate(self, api_client):
        r = api_client.post(f"{API}/auth/register", json={"name": "A", "email": ADMIN_EMAIL, "password": "arevei123"})
        assert r.status_code == 400

    def test_me_with_bearer(self, auth_client):
        r = auth_client.get(f"{API}/auth/me")
        assert r.status_code == 200
        assert r.json()["email"] == ADMIN_EMAIL

    def test_me_unauth(self):
        r = requests.get(f"{API}/auth/me")
        assert r.status_code == 401


# -------------------- MODELS --------------------
class TestModels:
    def test_models_registry(self, auth_client):
        r = auth_client.get(f"{API}/models")
        assert r.status_code == 200
        data = r.json()
        assert "models" in data and "default" in data
        ids = [m["id"] for m in data["models"]]
        assert len(ids) == 6, f"expected 6 models, got {len(ids)}: {ids}"
        for expected in ["gpt-5.4", "claude-sonnet-4-6", "gemini-3-flash-preview",
                         "deepseek/deepseek-chat", "meta-llama/llama-3.3-70b-instruct",
                         "meta/llama-3.1-70b-instruct"]:
            assert expected in ids, f"model {expected} missing"


# -------------------- WORKSPACE + BRAIN --------------------
class TestWorkspaceBrain:
    def test_workspace_created_and_brain_ready(self, workspace):
        assert workspace["brain_status"] == "ready"
        assert workspace["website_url"].startswith("http")
        assert "public_key" in workspace and workspace["public_key"]

    def test_brain_domains(self, workspace):
        brain = workspace.get("brain", {})
        expected_domains = {"business_profile", "brand_identity", "audience", "goals_constraints", "evidence", "decision_memory"}
        present = expected_domains & set(brain.keys())
        assert present == expected_domains, f"missing brain domains: {expected_domains - present}"
        # Business profile should have real content
        assert brain["business_profile"].get("company_name"), "empty company_name"

    def test_patch_workspace_model(self, auth_client, workspace):
        r = auth_client.patch(f"{API}/workspaces/{workspace['id']}", json={"model_id": "claude-sonnet-4-6"})
        assert r.status_code == 200
        assert r.json()["model_id"] == "claude-sonnet-4-6"
        # revert
        auth_client.patch(f"{API}/workspaces/{workspace['id']}", json={"model_id": "gpt-5.4"})

    def test_edit_brain(self, auth_client, workspace):
        brain = dict(workspace["brain"])
        brain["business_profile"]["description"] = "EDITED_DESCRIPTION_TEST"
        r = auth_client.put(f"{API}/workspaces/{workspace['id']}/brain", json={"brain": brain})
        assert r.status_code == 200
        got = auth_client.get(f"{API}/workspaces/{workspace['id']}").json()
        assert got["brain"]["business_profile"]["description"] == "EDITED_DESCRIPTION_TEST"


# -------------------- ROADMAP + TASKS --------------------
class TestRoadmap:
    def test_generate_roadmap(self, auth_client, workspace):
        r = auth_client.post(f"{API}/workspaces/{workspace['id']}/roadmap", timeout=90)
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data.get("roadmap", [])) == 12, f"expected 12 months, got {len(data.get('roadmap', []))}"
        assert data.get("strategy_summary")

    def test_tasks_scheduled(self, auth_client, workspace):
        r = auth_client.get(f"{API}/workspaces/{workspace['id']}/tasks")
        assert r.status_code == 200
        tasks = r.json()
        assert len(tasks) >= 6, f"expected >=6 tasks, got {len(tasks)}"
        agents = {t["agent"] for t in tasks}
        assert "content" in agents


# -------------------- BLOG GENERATE / EDIT / PUBLISH --------------------
class TestBlog:
    @pytest.fixture(scope="class")
    def blog(self, auth_client, workspace):
        r = auth_client.post(f"{API}/workspaces/{workspace['id']}/blogs/generate",
                             json={"topic": "TEST Advanced growth strategies for SaaS websites"},
                             timeout=120)
        assert r.status_code == 200, r.text
        return r.json()

    def test_blog_generated_with_blocks(self, blog):
        assert blog.get("title")
        assert len(blog.get("blocks", [])) >= 5
        types = {b.get("type") for b in blog["blocks"]}
        assert "paragraph" in types

    def test_blog_edit(self, auth_client, blog):
        r = auth_client.put(f"{API}/blogs/{blog['id']}",
                            json={"title": "TEST Edited Title", "excerpt": "TEST excerpt"})
        assert r.status_code == 200
        got = auth_client.get(f"{API}/blogs/{blog['id']}").json()
        assert got["title"] == "TEST Edited Title"
        assert got["excerpt"] == "TEST excerpt"

    def test_blog_publish(self, auth_client, blog):
        r = auth_client.post(f"{API}/blogs/{blog['id']}/publish")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "published"
        assert data.get("published_at")

    def test_public_blog(self, api_client, auth_client, blog):
        # get slug
        got = auth_client.get(f"{API}/blogs/{blog['id']}").json()
        slug = got["slug"]
        r = api_client.get(f"{API}/public/blog/{slug}")
        assert r.status_code == 200
        pub = r.json()
        assert pub["title"] == got["title"]
        assert "blocks" in pub


# -------------------- PUBLIC EMBED --------------------
class TestEmbed:
    def test_public_blogs(self, api_client, workspace):
        r = api_client.get(f"{API}/public/blogs", params={"key": workspace["public_key"]})
        assert r.status_code == 200
        # may be empty depending on ordering; just assert list
        assert isinstance(r.json(), list)

    def test_widget_js(self, api_client, workspace):
        r = api_client.get(f"{API}/embed/widget.js", params={"key": workspace["public_key"]})
        assert r.status_code == 200
        assert "application/javascript" in r.headers.get("content-type", "")
        assert workspace["public_key"] in r.text
        assert "arevei-blog" in r.text


# -------------------- MANAGER CHAT (STREAM) --------------------
class TestManagerChat:
    def test_chat_streams_real_answer(self, auth_client, workspace):
        # Ask arithmetic question so we can validate real LLM output
        payload = {"message": "What is 17 + 26? Reply with just the number, nothing else.",
                   "history": [],
                   "model_id": workspace.get("model_id", "gpt-5.4")}
        url = f"{API}/workspaces/{workspace['id']}/chat"
        with requests.post(url, json=payload, headers=auth_client.headers, stream=True, timeout=90) as r:
            assert r.status_code == 200
            text = ""
            for chunk in r.iter_content(chunk_size=None):
                if chunk:
                    text += chunk.decode("utf-8", errors="ignore")
                if len(text) > 800:
                    break
        assert len(text) > 0, "empty stream"
        # Must contain 43
        assert "43" in text, f"LLM math check failed, got: {text[:300]}"
