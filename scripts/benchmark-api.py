"""Measure Arevei's production login/workspace/CRM latency without writing data.

Required environment variables:
  PERF_BASE_URL=https://backend.example.com/api
  PERF_EMAIL=dedicated-performance-account@example.com
  PERF_PASSWORD=...

Optional:
  PERF_WORKSPACE_ID=...  (otherwise uses login's default_workspace_id)
  PERF_RUNS=30

The script never prints credentials, tokens, or response bodies.
"""

import os
import statistics
import time

import httpx


def percentile(values, percentile_value):
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((percentile_value / 100) * (len(ordered) - 1))))
    return ordered[index]


def request_ms(client, method, path, **kwargs):
    started = time.perf_counter()
    response = client.request(method, path, **kwargs)
    elapsed = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    return elapsed, response


def summarize(label, values):
    print(
        f"{label}: runs={len(values)} min={min(values):.1f}ms "
        f"p50={statistics.median(values):.1f}ms p95={percentile(values, 95):.1f}ms "
        f"max={max(values):.1f}ms"
    )


def main():
    base_url = os.environ["PERF_BASE_URL"].rstrip("/")
    email = os.environ["PERF_EMAIL"]
    password = os.environ["PERF_PASSWORD"]
    runs = max(1, int(os.environ.get("PERF_RUNS", "30")))

    with httpx.Client(base_url=base_url, timeout=30, follow_redirects=False) as client:
        cold_login_ms, login = request_ms(client, "POST", "/auth/login", json={"email": email, "password": password})
        login_data = login.json()
        token = login_data["token"]
        workspace_id = os.environ.get("PERF_WORKSPACE_ID") or login_data.get("default_workspace_id")
        if not workspace_id:
            raise RuntimeError("Performance account has no workspace; set PERF_WORKSPACE_ID")
        client.headers["Authorization"] = f"Bearer {token}"
        print(f"first login: {cold_login_ms:.1f}ms")

        routes = {
            "login": ("POST", "/auth/login", {"json": {"email": email, "password": password}}),
            "session": ("GET", "/auth/me", {}),
            "workspace bootstrap": ("GET", f"/workspaces/{workspace_id}/bootstrap", {}),
            "CRM bootstrap": ("GET", f"/workspaces/{workspace_id}/crm/bootstrap?page=1&limit=10", {}),
        }
        for label, (method, path, options) in routes.items():
            values = []
            for _ in range(runs):
                elapsed, _ = request_ms(client, method, path, **options)
                values.append(elapsed)
            summarize(label, values)


if __name__ == "__main__":
    main()
