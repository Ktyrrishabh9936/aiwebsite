import asyncio
import json

import httpx
import pytest

import agents
import llm_service as llm


def test_manager_crm_analytics_with_zero_payments():
    from crm import build_crm_analytics
    analytics = build_crm_analytics([])
    assert analytics["totals"]["payments_collected"] == "0"
    assert analytics["totals"]["leads"] == 0


def mock_http(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("BEDROCK_MANTLE_API_KEY", "test-secret")


def test_mantle_json_request_and_safe_logs(monkeypatch, caplog):
    def handler(request):
        assert str(request.url) == "https://bedrock-mantle.ap-south-1.api.aws/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-secret"
        assert request.headers["openai-project"] == "default"
        body = json.loads(request.content)
        assert body["model"] == "openai.gpt-oss-120b"
        assert body["max_completion_tokens"] == 1800
        assert "max_tokens" not in body
        assert "ONLY valid JSON" in body["messages"][0]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"score": 80}'}}]})

    mock_http(monkeypatch, handler)
    with caplog.at_level("INFO", logger="llm"):
        assert asyncio.run(llm.generate_json(llm.DEFAULT_MODEL, "private company", "private transcript", max_tokens=1800)) == {"score": 80}
    assert "bedrock_mantle" in caplog.text
    assert "latency_ms" in caplog.text
    for secret in ("test-secret", "private company", "private transcript"):
        assert secret not in caplog.text


def test_mantle_manager_stream_preserves_context(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body["stream"] is True
        combined = json.dumps(body["messages"])
        for value in ("Example Company", "Grow organically", "Prior question", "CRM total: 17"):
            assert value in combined
        return httpx.Response(200, text='data: {"choices":[{"delta":{"reasoning":"hidden"}}]}\n\ndata: {"choices":[{"delta":{"content":"17 leads"}}]}\n\ndata: [DONE]\n\n')

    mock_http(monkeypatch, handler)

    async def run():
        return "".join([d async for d in agents.manager_chat_stream(llm.DEFAULT_MODEL, {"business_profile": {"company_name": "Example Company"}}, {"strategy_summary": "Grow organically"}, [{"role": "user", "content": "Prior question"}], "CRM total: 17")])

    assert asyncio.run(run()) == "17 leads"


def test_stream_http_failure_is_visible(monkeypatch):
    mock_http(monkeypatch, lambda r: httpx.Response(401, json={"error": "unauthorized"}))

    async def run():
        return [d async for d in llm.stream_text(llm.DEFAULT_MODEL, "system", "prompt")]

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(run())


def test_openrouter_request_and_existing_default_fallback(monkeypatch):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body["model"])
        if request.url.host == "openrouter.ai":
            assert "max_tokens" in body
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    mock_http(monkeypatch, handler)
    assert asyncio.run(llm.generate_text("deepseek/deepseek-chat", "system", "prompt")) == "ok"
    assert calls == ["deepseek/deepseek-chat", "openai.gpt-oss-120b"]


def test_missing_mantle_key(monkeypatch):
    monkeypatch.delenv("BEDROCK_MANTLE_API_KEY", raising=False)
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    with pytest.raises(ValueError, match="BEDROCK_MANTLE_API_KEY"):
        asyncio.run(llm.generate_text(llm.DEFAULT_MODEL, "system", "prompt"))


def test_qualification_uses_selected_model_without_changing_result(monkeypatch):
    import plivo_calls
    calls = []

    async def generate(model_id, *args, **kwargs):
        calls.append(model_id)
        return {"score": 80, "status": "qualified", "tags": ["Fit"], "summary": "Matches criteria"}

    monkeypatch.setattr(plivo_calls, "generate_json", generate)
    config = {"is_enabled": True, "passing_score": 70, "criteria": []}
    for selected in (None, "deepseek/deepseek-chat"):
        result = asyncio.run(plivo_calls.run_ai_qualification("Synthetic transcript", config, model_id=selected))
        assert result["status"] == "qualified"
        assert result["score"] == 80
    assert calls == [llm.DEFAULT_MODEL, "deepseek/deepseek-chat"]
