"""Claude (Anthropic API) paths, exercised through the real SDK against a mock transport."""
import asyncio
import json

import anthropic
import httpx2
import pytest

import agents
import coding_agent
import llm_service as llm
import manager_model

USAGE = {"input_tokens": 10, "output_tokens": 5}


def message(content, stop_reason="end_turn", model="claude-opus-5-5"):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": model, "content": content,
            "stop_reason": stop_reason, "stop_sequence": None, "usage": USAGE}


def sse(content, stop_reason="end_turn"):
    """Stream one finished message as the events the API would send."""
    events = [{"type": "message_start", "message": message([], None)}]
    for index, block in enumerate(content):
        if block["type"] == "text":
            start, delta = {"type": "text", "text": ""}, {"type": "text_delta", "text": block["text"]}
        else:
            start = {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}
            delta = {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
        events += [{"type": "content_block_start", "index": index, "content_block": start},
                   {"type": "content_block_delta", "index": index, "delta": delta},
                   {"type": "content_block_stop", "index": index}]
    events += [{"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None}, "usage": {"output_tokens": 5}},
               {"type": "message_stop"}]
    text = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
    return httpx2.Response(200, text=text, headers={"content-type": "text/event-stream"})


def mock_claude(monkeypatch, handler):
    """Route Claude calls to handler(body, request); returns the list of request bodies seen."""
    bodies = []

    def handle(request):
        bodies.append(json.loads(request.content))
        return handler(bodies[-1], request)

    # A failing Claude call must fail the test, not quietly reach the real default provider.
    monkeypatch.setattr(llm, "mantle_config", lambda: {"key": None, "url": "", "project": ""})
    monkeypatch.setattr(llm, "anthropic_client", lambda: anthropic.AsyncAnthropic(
        api_key="test-secret", max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handle))))
    return bodies


def test_claude_json_request_shape_and_safe_logs(monkeypatch, caplog):
    seen = {}

    def handler(body, request):
        seen.update(path=request.url.path, headers=request.headers)
        return sse([{"type": "text", "text": '{"score": 80}'}])

    bodies = mock_claude(monkeypatch, handler)
    with caplog.at_level("INFO", logger="llm"):
        assert asyncio.run(llm.generate_json("claude-opus-5-5", "private company", "private transcript", max_tokens=1800)) == {"score": 80}
    assert len(bodies) == 1
    body = bodies[0]
    assert seen["path"] == "/v1/messages"
    assert seen["headers"]["authorization"] == "Bearer test-secret"
    assert "server-side-fallback-2026-07-01" in seen["headers"]["anthropic-beta"]
    assert body["model"] == "claude-opus-5-5"
    assert body["max_tokens"] == 1800 + llm.ANTHROPIC_THINKING_HEADROOM
    assert body["output_config"] == {"effort": "medium"}
    assert body["fallbacks"] == "default"
    assert "ONLY valid JSON" in body["system"]
    # Current Claude models reject sampling settings and manual thinking budgets.
    assert not {"temperature", "top_p", "thinking"} & set(body)
    assert "provider=anthropic" in caplog.text
    for secret in ("test-secret", "private company", "private transcript"):
        assert secret not in caplog.text


def test_haiku_has_no_server_side_fallback(monkeypatch):
    bodies = mock_claude(monkeypatch, lambda body, request: sse([{"type": "text", "text": "ok"}]))
    assert asyncio.run(llm.generate_text("claude-haiku-5-5", "system", "prompt")) == "ok"
    assert "fallbacks" not in bodies[0]


def test_claude_manager_stream_preserves_context(monkeypatch):
    bodies = mock_claude(monkeypatch, lambda body, request: sse([{"type": "text", "text": "17 leads"}]))

    async def run():
        return "".join([d async for d in agents.manager_chat_stream("claude-sonnet-5-5", {"business_profile": {"company_name": "Example Company"}}, {"strategy_summary": "Grow organically"}, [{"role": "user", "content": "Prior question"}], "CRM total: 17")])

    assert asyncio.run(run()) == "17 leads"
    assert bodies[0]["stream"] is True
    combined = json.dumps(bodies[0])
    for value in ("Example Company", "Grow organically", "Prior question", "CRM total: 17"):
        assert value in combined


def test_claude_refusal_and_http_failure_are_visible(monkeypatch):
    async def stream():
        return [d async for d in llm.stream_text("claude-opus-5-5", "system", "prompt")]

    mock_claude(monkeypatch, lambda body, request: sse([], stop_reason="refusal"))
    with pytest.raises(RuntimeError, match="declined"):
        asyncio.run(stream())
    mock_claude(monkeypatch, lambda body, request: httpx2.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}))
    with pytest.raises(anthropic.AuthenticationError):
        asyncio.run(stream())


def test_missing_claude_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        llm.anthropic_client()


TOOL = {"type": "function", "function": {"name": "search_leads", "description": "Search leads.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}


def test_claude_tool_turn_replays_reasoning_only_within_the_current_request(monkeypatch):
    replies = iter([
        message([{"type": "thinking", "thinking": "", "signature": "sig-1"},
                 {"type": "tool_use", "id": "toolu_1", "name": "search_leads", "input": {"query": "Asha"}}], "tool_use"),
        message([{"type": "text", "text": "Asha wants a villa."}]),
        message([{"type": "text", "text": "Yes."}]),
    ])
    bodies = mock_claude(monkeypatch, lambda body, request: httpx2.Response(200, json=next(replies)))
    messages = [{"role": "user", "content": "What does Asha want?"}]

    reply = asyncio.run(manager_model.tool_turn("claude-opus-5-5", "system", messages, [TOOL]))
    assert reply == {"role": "assistant", "content": "", "tool_calls": [{"id": "toolu_1", "type": "function", "function": {"name": "search_leads", "arguments": '{"query": "Asha"}'}}]}
    assert bodies[0]["tools"] == [{"name": "search_leads", "description": "Search leads.", "input_schema": TOOL["function"]["parameters"]}]
    assert bodies[0]["thinking"]["block_binding"] == {"prefix_mismatch_behavior": "drop_block"}
    assert "temperature" not in bodies[0] and "tool_choice" not in bodies[0]

    messages += [reply, {"role": "tool", "tool_call_id": "toolu_1", "content": '{"total": 1}'}]
    answer = asyncio.run(manager_model.tool_turn("claude-opus-5-5", "system", messages, [TOOL]))
    assert answer == {"role": "assistant", "content": "Asha wants a villa."}
    assistant, results = bodies[1]["messages"][1:]
    assert [block["type"] for block in assistant["content"]] == ["thinking", "tool_use"]
    assert assistant["content"][0]["signature"] == "sig-1"
    assert results == {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"total": 1}'}]}

    # A later request has a different history, so earlier reasoning is left out rather than replayed stale.
    messages += [answer, {"role": "user", "content": "Is that confirmed?"}]
    asyncio.run(manager_model.tool_turn("claude-opus-5-5", "system", messages, [TOOL]))
    assert [block["type"] for block in bodies[2]["messages"][1]["content"]] == ["tool_use"]


def test_claude_coding_agent_runs_tools_and_reports(monkeypatch):
    replies = iter([
        sse([{"type": "text", "text": "Reading."}, {"type": "tool_use", "id": "toolu_1", "name": "write_file", "input": {"path": "a.txt", "content": "hi"}},
             {"type": "tool_use", "id": "toolu_2", "name": "read_file", "input": {}}], "tool_use"),
        sse([{"type": "text", "text": "- Wrote a.txt"}]),
    ])
    bodies = mock_claude(monkeypatch, lambda body, request: next(replies))
    files = {}

    async def read_file(path):
        return files[path]

    async def write_file(path, content):
        files[path] = content

    async def run():
        history = [{"role": "assistant", "content": "Earlier summary"}, {"role": "user", "content": "Earlier ask"}]
        return [ev async for ev in coding_agent.run_agent({"read_file": read_file, "write_file": write_file}, "claude-opus-5-5", history, "Create a.txt")]

    events = asyncio.run(run())
    assert files == {"a.txt": "hi"}
    assert [ev["type"] for ev in events] == ["assistant_delta", "file_changed", "assistant_delta", "final_summary", "done"]
    assert events[-1]["summary"] == "- Wrote a.txt"
    assert bodies[0]["output_config"] == {"effort": "high"}
    assert all(tool["eager_input_streaming"] for tool in bodies[0]["tools"])
    # History must open with a user message; the incomplete read_file call is refused, not run.
    assert [m["role"] for m in bodies[0]["messages"]] == ["user", "user"]
    results = bodies[1]["messages"][-1]["content"]
    assert results[0] == {"type": "tool_result", "tool_use_id": "toolu_1", "content": "wrote a.txt"}
    assert results[1]["is_error"] is True


def test_only_bedrock_and_claude_are_registered():
    assert {m["provider"] for m in llm.MODELS} == {"bedrock_mantle", "bedrock", "anthropic"}
    assert {m["provider"] for m in coding_agent.CODING_MODELS} == {"bedrock", "anthropic"}
    assert coding_agent.CODING_MODEL_MAP[coding_agent.DEFAULT_CODING_MODEL]["provider"] == "bedrock"
