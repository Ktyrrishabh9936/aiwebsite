import asyncio
from datetime import datetime, timezone

import httpx

import ai_usage
import llm_service


class Events:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        self.docs.append(doc)


class Db:
    def __init__(self):
        self.ai_usage_events = Events()


def test_usage_summary_groups_days_processes_and_models():
    events = [
        {"day": "2026-09-20", "process": "manager_chat", "provider": "bedrock_mantle", "model": "gpt", "input_tokens": 80, "output_tokens": 20, "total_tokens": 100, "metered": True, "latency_ms": 900, "status": "success"},
        {"day": "2026-09-21", "process": "blog_generation", "provider": "bedrock_mantle", "model": "gpt", "input_tokens": 200, "output_tokens": 300, "total_tokens": 500, "metered": True, "latency_ms": 1100, "status": "success"},
    ]
    report = ai_usage.summarize_usage(events, 2, datetime(2026, 9, 21, tzinfo=timezone.utc))
    assert report["totals"] == {"input_tokens": 280, "output_tokens": 320, "total_tokens": 600, "calls": 2, "failed_calls": 0, "metered_calls": 2, "average_latency_ms": 1000}
    assert [row["day"] for row in report["daily"]] == ["2026-09-20", "2026-09-21"]
    assert report["processes"][0]["label"] == "Blog generation"


def test_llm_provider_usage_is_persisted_without_prompt_content(monkeypatch):
    database = Db()
    ai_usage.configure_usage(database)
    monkeypatch.setenv("BEDROCK_MANTLE_API_KEY", "test")
    original = llm_service.httpx.AsyncClient

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16}})

    monkeypatch.setattr(llm_service.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler)))
    try:
        with ai_usage.usage_scope("workspace", "manager_chat"):
            assert asyncio.run(llm_service.generate_text(llm_service.DEFAULT_MODEL, "private system", "private prompt")) == "ok"
        event = database.ai_usage_events.docs[0]
        assert event["workspace_id"] == "workspace"
        assert event["process"] == "manager_chat"
        assert event["total_tokens"] == 16
        assert "prompt" not in event and "response" not in event
    finally:
        ai_usage.configure_usage(None)
