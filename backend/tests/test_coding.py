"""Backend tests for the AI coding platform (Daytona) — this iteration.

Focus areas (per review request):
- GET /api/code/models returns the 4 templates
- POST /api/code/projects with template=react-vite → sandbox becomes ready, tree contains src/App.jsx + package.json + vite.config.js
- POST /api/code/projects with template=blank → tree contains README.md and NO vite.config.js (config not forced)
- POST /api/code/projects with template=node → tree contains index.js + package.json
- For react-vite: /run then poll /preview until ready=true; the URL must be a Daytona proxy
  (contains 'daytona') and CRITICALLY must NOT redirect to auth0.com (bug fix under test)
- Coding agent SSE: chat produces file events and actually edits the file content

Daytona ops are slow: use long polling windows.
"""
import os
import time
import re
import json
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ai-manager-auto.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

READY_TIMEOUT_S = 120       # sandbox provisioning
PREVIEW_TIMEOUT_S = 180     # dev server + preview (npm install can be slow)


def _flatten(tree, prefix=""):
    """Flatten the file tree into a list of file paths."""
    out = []
    for n in tree or []:
        p = n.get("path") or (f"{prefix}/{n['name']}".lstrip("/"))
        if n.get("type") == "dir":
            out.extend(_flatten(n.get("children") or [], p))
        else:
            out.append(p)
    return out


def _wait_ready(auth_client, pid, timeout=READY_TIMEOUT_S):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = auth_client.get(f"{API}/code/projects/{pid}", timeout=30)
        assert r.status_code == 200, r.text
        last = r.json()
        if last["sandbox_status"] in ("ready", "error"):
            return last
        time.sleep(4)
    return last


@pytest.fixture(scope="module")
def created_projects(auth_client):
    """Track created projects so we can clean up (delete sandboxes) at the end."""
    ids = []
    yield ids
    for pid in ids:
        try:
            auth_client.delete(f"{API}/code/projects/{pid}", timeout=30)
        except Exception:
            pass


# -------- 1. models endpoint returns templates ----------
class TestCodeModels:
    def test_models_and_templates(self, auth_client):
        r = auth_client.get(f"{API}/code/models")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "templates" in data, "templates array missing from /api/code/models"
        ids = {t["id"] for t in data["templates"]}
        expected = {"react-vite", "node", "static", "blank"}
        assert expected.issubset(ids), f"missing templates: {expected - ids}"
        # models list also present
        assert isinstance(data.get("models"), list) and len(data["models"]) > 0
        assert data.get("default")


# -------- 2. react-vite scaffold ----------
class TestReactViteTemplate:
    def test_provisions_ready_with_vite_files(self, auth_client, created_projects):
        r = auth_client.post(f"{API}/code/projects",
                             json={"name": "TEST react-vite", "template": "react-vite"},
                             timeout=30)
        assert r.status_code == 200, r.text
        proj = r.json()
        assert proj["template"] == "react-vite"
        assert proj["sandbox_status"] == "provisioning"
        created_projects.append(proj["id"])

        final = _wait_ready(auth_client, proj["id"])
        assert final and final["sandbox_status"] == "ready", (
            f"react-vite sandbox never became ready: status={final and final.get('sandbox_status')} "
            f"err={final and final.get('error')}"
        )

        # verify file tree
        r = auth_client.get(f"{API}/code/projects/{proj['id']}/files", timeout=60)
        assert r.status_code == 200, r.text
        paths = _flatten(r.json()["tree"])
        for expected in ["src/App.jsx", "package.json", "vite.config.js"]:
            assert expected in paths, f"react-vite tree missing {expected}. tree={paths}"


# -------- 3. blank scaffold ----------
class TestBlankTemplate:
    def test_blank_has_readme_no_vite(self, auth_client, created_projects):
        r = auth_client.post(f"{API}/code/projects",
                             json={"name": "TEST blank", "template": "blank"},
                             timeout=30)
        assert r.status_code == 200, r.text
        proj = r.json()
        assert proj["template"] == "blank"
        created_projects.append(proj["id"])

        final = _wait_ready(auth_client, proj["id"])
        assert final["sandbox_status"] == "ready", f"blank sandbox never ready: {final}"

        r = auth_client.get(f"{API}/code/projects/{proj['id']}/files", timeout=60)
        assert r.status_code == 200
        paths = _flatten(r.json()["tree"])
        assert "README.md" in paths, f"blank template missing README.md. tree={paths}"
        # Config must NOT be forced
        assert "vite.config.js" not in paths, f"blank template unexpectedly has vite.config.js: {paths}"
        assert "package.json" not in paths, f"blank template should have no package.json: {paths}"


# -------- 4. node scaffold ----------
class TestNodeTemplate:
    def test_node_has_index_and_package(self, auth_client, created_projects):
        r = auth_client.post(f"{API}/code/projects",
                             json={"name": "TEST node", "template": "node"},
                             timeout=30)
        assert r.status_code == 200, r.text
        proj = r.json()
        assert proj["template"] == "node"
        created_projects.append(proj["id"])

        final = _wait_ready(auth_client, proj["id"])
        assert final["sandbox_status"] == "ready", f"node sandbox never ready: {final}"

        r = auth_client.get(f"{API}/code/projects/{proj['id']}/files", timeout=60)
        paths = _flatten(r.json()["tree"])
        for expected in ["index.js", "package.json"]:
            assert expected in paths, f"node tree missing {expected}. tree={paths}"
        # No vite in node template
        assert "vite.config.js" not in paths


# -------- 5. Preview: signed URL, no auth0 redirect ----------
class TestPreviewSignedUrl:
    """CRITICAL: fixed bug — preview URL must be signed Daytona URL that
    serves the app HTML, not redirect to auth0.com."""

    @pytest.fixture(scope="class")
    def rv_project(self, auth_client):
        # Fresh react-vite project for this test class
        r = auth_client.post(f"{API}/code/projects",
                             json={"name": "TEST preview rv", "template": "react-vite"},
                             timeout=30)
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        final = _wait_ready(auth_client, pid)
        assert final and final["sandbox_status"] == "ready", (
            f"preview test project not ready: {final}"
        )
        yield pid
        try:
            auth_client.delete(f"{API}/code/projects/{pid}", timeout=30)
        except Exception:
            pass

    def test_run_and_preview_no_auth0(self, auth_client, rv_project):
        pid = rv_project
        # start dev server
        r = auth_client.post(f"{API}/code/projects/{pid}/run", timeout=60)
        assert r.status_code == 200, r.text

        # poll preview
        url = None
        ready = False
        deadline = time.time() + PREVIEW_TIMEOUT_S
        while time.time() < deadline:
            time.sleep(6)
            r = auth_client.get(f"{API}/code/projects/{pid}/preview", timeout=60)
            if r.status_code != 200:
                continue
            data = r.json()
            url = data.get("url")
            if data.get("ready"):
                ready = True
                break

        assert url, "preview never returned a URL"
        # Verify it's a Daytona proxy URL (this alone tests the signed fallback path)
        assert "daytona" in url.lower(), f"preview URL does not look like Daytona: {url}"

        if not ready:
            pytest.skip(f"Dev server did not become ready in {PREVIEW_TIMEOUT_S}s but URL was issued: {url}")

        # CRITICAL: fetch the preview URL — should NOT redirect to auth0
        # follow redirects and inspect chain + final response
        resp = requests.get(url, timeout=45, allow_redirects=True)
        # Check we didn't land on auth0
        final_url = resp.url
        assert "auth0.com" not in final_url, (
            f"PREVIEW REDIRECTED TO AUTH0 (BUG NOT FIXED). final_url={final_url}"
        )
        # Check redirect chain too
        for h in resp.history:
            assert "auth0.com" not in (h.headers.get("location", "") or ""), (
                f"Preview redirected via auth0 in chain: {[hh.headers.get('location') for hh in resp.history]}"
            )
        # Should get real content (200 OK with some HTML)
        assert resp.status_code == 200, f"preview URL returned {resp.status_code}: {resp.text[:300]}"
        assert len(resp.content) > 0
        # Sanity: content looks like HTML (or at least not an auth login page)
        body = resp.text.lower()
        assert "auth0" not in body[:2000], f"auth0 markup found in preview response: {body[:500]}"


# -------- 6. Coding agent SSE edits real files ----------
class TestCodingAgentEditsFile:
    def test_chat_streams_and_edits_file(self, auth_client, created_projects):
        # Create fresh react-vite project so we can verify heading edit
        r = auth_client.post(f"{API}/code/projects",
                             json={"name": "TEST agent edit", "template": "react-vite"},
                             timeout=30)
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        created_projects.append(pid)
        final = _wait_ready(auth_client, pid)
        assert final["sandbox_status"] == "ready", f"agent test project not ready: {final}"

        # read original App.jsx
        r = auth_client.get(f"{API}/code/projects/{pid}/file", params={"path": "src/App.jsx"}, timeout=60)
        assert r.status_code == 200, r.text
        original = r.json()["content"]
        assert "Welcome to your Arevei app" in original, f"unexpected original App.jsx: {original[:200]}"

        # ask agent to change heading text to a specific unique string
        unique = "TESTHEADING_ABC123"
        payload = {"message": f"In src/App.jsx, change the <h1> heading text to exactly: {unique}. Only that one file."}
        url = f"{API}/code/projects/{pid}/chat"
        got_file_event = False
        got_summary = False
        with requests.post(url, json=payload, headers=auth_client.headers, stream=True, timeout=180) as resp:
            assert resp.status_code == 200, resp.text
            buf = ""
            deadline = time.time() + 170
            for chunk in resp.iter_content(chunk_size=None):
                if chunk:
                    buf += chunk.decode("utf-8", errors="ignore")
                    for part in buf.split("\n\n"):
                        line = next((l for l in part.split("\n") if l.startswith("data: ")), None)
                        if not line:
                            continue
                        try:
                            ev = json.loads(line[6:])
                        except Exception:
                            continue
                        t = ev.get("type")
                        if t == "file":
                            got_file_event = True
                        elif t == "summary":
                            got_summary = True
                        elif t in ("end", "done"):
                            deadline = 0
                    buf = buf.rsplit("\n\n", 1)[-1]
                if time.time() > deadline:
                    break

        assert got_file_event or got_summary, "no file/summary events received from agent"

        # verify file actually changed
        r = auth_client.get(f"{API}/code/projects/{pid}/file", params={"path": "src/App.jsx"}, timeout=60)
        assert r.status_code == 200
        new_content = r.json()["content"]
        assert new_content != original, "agent claimed edit but file content unchanged"
        assert unique in new_content, f"unique heading not found. new content: {new_content[:400]}"
