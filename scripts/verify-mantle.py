"""Opt-in live verification. Uses configured secrets; prints no CRM data or credentials."""
import asyncio
import json
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import llm_service as llm
from plivo_calls import run_ai_qualification


async def main():
    result = await llm.generate_text(llm.DEFAULT_MODEL, "Follow the instruction exactly.", "Reply with exactly BEDROCK_APP_OK")
    print("AI_SERVICE", "PASS" if result.strip() == "BEDROCK_APP_OK" else "FAIL unexpected response")
    if result.strip() != "BEDROCK_APP_OK":
        raise RuntimeError("Basic service verification failed")
    cfg = {"is_enabled": True, "passing_score": 70, "criteria": [{"field": "budget", "condition": "contains", "value": "90 lakh", "weight": 30}, {"field": "location", "condition": "contains", "value": "Gurgaon", "weight": 25}, {"field": "timeline", "condition": "contains", "value": "this week", "weight": 20}]}
    q = await run_ai_qualification("I want a family home in Gurgaon. My budget is 90 lakh and I can visit this week.", cfg, model_id=llm.DEFAULT_MODEL)
    ok = isinstance(q.get("score"), int) and q.get("status") == "qualified" and isinstance(q.get("tags"), list) and bool(q.get("summary")) and not q.get("manual_review")
    print("QUALIFICATION", "PASS" if ok else "FAIL structured qualification")
    if not ok:
        raise RuntimeError("Qualification verification failed")
    try:
        # Direct adapter call prevents a fallback from masquerading as OpenRouter success.
        r = await llm._openai_compatible(llm.OPENROUTER_URL, llm.OPENROUTER_KEY, "google/gemini-2.5-flash", "Follow instructions.", "Reply with exactly OPENROUTER_OK", 0.2, 128)
        print("OPENROUTER", "PASS" if r.strip() == "OPENROUTER_OK" else "FAIL unexpected response")
    except httpx.HTTPStatusError as exc:
        print("OPENROUTER FAIL HTTP", exc.response.status_code)
        try:
            err = exc.response.json().get("error", {})
            print("OPENROUTER_ERROR", str(err.get("message", ""))[:300])
        except ValueError:
            pass
    frontend = dotenv_values(ROOT / "frontend" / ".env")
    backend = dotenv_values(ROOT / "backend" / ".env")
    base = frontend.get("REACT_APP_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
    async with httpx.AsyncClient(base_url=base + "/api/", timeout=120) as client:
        catalog = await client.get("models")
        catalog.raise_for_status()
        data = catalog.json()
        visible = any(m["id"] == llm.DEFAULT_MODEL and m.get("configured") for m in data["models"])
        print("RUNNING_CATALOG", "PASS" if visible else "FAIL Mantle absent or unconfigured")
        if not visible:
            return
        login = await client.post("auth/login", json={"email": backend["ADMIN_EMAIL"], "password": backend["ADMIN_PASSWORD"]})
        login.raise_for_status()
        client.headers["Authorization"] = "Bearer " + login.json()["token"]
        response = await client.get("workspaces")
        response.raise_for_status()
        workspaces = response.json()
        print("WORKSPACE_COUNT", len(workspaces))
        if not workspaces:
            print("CONTEXT_TESTS BLOCKED no existing workspace")
            return
        ws = next((w for w in workspaces if w.get("brain", {}).get("business_profile", {}).get("company_name")), workspaces[0])
        # Existing Manager API, including its real database context and streaming response.
        async def chat(prompt, override=True):
            body = {"message": prompt, "history": []}
            if override:
                body["model_id"] = llm.DEFAULT_MODEL
            async with client.stream("POST", f"workspaces/{ws['id']}/chat", json=body) as resp:
                resp.raise_for_status()
                chunks = [chunk async for chunk in resp.aiter_text()]
                text = "".join(chunks)
                if "[error:" in text:
                    raise RuntimeError("Manager returned an error response")
                return text
        company = ws.get("brain", {}).get("business_profile", {}).get("company_name", "")
        answer = await chat("What is the company name in our business profile? Reply with only that name.")
        print("MANAGER_BRAIN", "PASS" if company and company.lower() in answer.lower() else "FAIL company context mismatch")
        # Read the same workspace-scoped analytics independently from MongoDB.
        import server
        import logging
        logging.getLogger("httpx").setLevel(logging.WARNING)
        _, _, analytics, _ = await server.crm_manager_context(ws["id"])
        expected = analytics.get("totals", {}).get("leads")
        answer = await chat("How many leads are currently in the CRM? Reply with only the numeric total from CRM analytics.")
        import re
        numbers = re.findall(r"\d+", answer.replace(",", ""))
        print("CRM_CONTEXT", "PASS" if expected is not None and str(expected) in numbers else "FAIL CRM count mismatch")
        # Opt-in activation uses the existing configuration API, never bulk-rewrites IDs.
        if "--activate" in sys.argv:
            if not (ok and company and company.lower() in (await chat("What is the company name in our business profile? Reply with only that name.")).lower() and expected is not None and str(expected) in numbers):
                raise RuntimeError("Activation blocked by context verification")
            changed = await client.patch(f"workspaces/{ws['id']}", json={"model_id": llm.DEFAULT_MODEL})
            changed.raise_for_status()
            print("WORKSPACE_PRIMARY", "PASS" if changed.json()["model_id"] == llm.DEFAULT_MODEL else "FAIL")
        if ws.get("model_id") == llm.DEFAULT_MODEL or "--activate" in sys.argv:
            answer = await chat("What is the company name in our business profile? Reply with only that name.", override=False)
            print("SAVED_WORKSPACE_ROUTING", "PASS" if company and company.lower() in answer.lower() else "FAIL context mismatch")
        server.client.close()


if __name__ == "__main__":
    asyncio.run(main())
