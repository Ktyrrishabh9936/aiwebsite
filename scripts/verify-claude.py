"""Opt-in live check of the Claude (Anthropic API) paths. Needs ANTHROPIC_API_KEY in backend/.env.

Makes a few small billable requests. Uses a synthetic transcript; reads and writes no CRM data.
Calls the Claude adapters directly so a fallback to Bedrock cannot pass for a Claude success.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import llm_service as llm
import manager_model
from plivo_calls import run_ai_qualification

TOOL = {"type": "function", "function": {"name": "count_leads", "description": "Return how many leads the workspace has.",
        "parameters": {"type": "object", "properties": {}}}}


async def main():
    failed = False
    for model in [m for m in llm.MODELS if m["provider"] == "anthropic"]:
        try:
            text, usage = await llm._anthropic_message(model["real"], "Follow the instruction exactly.", "Reply with exactly CLAUDE_OK", 200)
            ok = text.strip() == "CLAUDE_OK"
            print(model["id"], "TEXT", "PASS" if ok else f"FAIL unexpected response: {text[:80]!r}", f"tokens={usage['total_tokens']}")
        except Exception as error:
            ok = False
            print(model["id"], "TEXT FAIL", type(error).__name__, str(error)[:300])
        failed = failed or not ok

    model_id = "claude-opus-5-5"
    try:
        chunks = [d async for d in llm._stream_text(model_id, "Follow the instruction exactly.", "Reply with exactly STREAM_OK", max_tokens=200)]
        print("STREAM", "PASS" if "".join(chunks).strip() == "STREAM_OK" else "FAIL unexpected response")
    except Exception as error:
        failed = True
        print("STREAM FAIL", type(error).__name__, str(error)[:300])

    try:
        # Two rounds: Claude asks for the tool, then answers from its result with its reasoning sent back.
        messages = [{"role": "user", "content": "How many leads do we have? Use the tool, then answer with just the number."}]
        reply = await manager_model.tool_turn(model_id, "You answer workspace questions using tools.", messages, [TOOL])
        calls = reply.get("tool_calls") or []
        messages += [reply, *[{"role": "tool", "tool_call_id": call["id"], "content": '{"total": 17}'} for call in calls]]
        answer = await manager_model.tool_turn(model_id, "You answer workspace questions using tools.", messages, [TOOL]) if calls else reply
        ok = bool(calls) and "17" in (answer.get("content") or "")
        print("AGENT_TOOLS", "PASS" if ok else "FAIL tool round trip")
        failed = failed or not ok
    except Exception as error:
        failed = True
        print("AGENT_TOOLS FAIL", type(error).__name__, str(error)[:300])

    cfg = {"is_enabled": True, "passing_score": 70, "criteria": [{"field": "budget", "condition": "contains", "value": "90 lakh", "weight": 30}, {"field": "location", "condition": "contains", "value": "Gurgaon", "weight": 25}, {"field": "timeline", "condition": "contains", "value": "this week", "weight": 20}]}
    # Qualification retries failures on the default model; make Claude the default here so a failure shows.
    llm.DEFAULT_MODEL = model_id
    q = await run_ai_qualification("I want a family home in Gurgaon. My budget is 90 lakh and I can visit this week.", cfg, model_id=model_id)
    ok = isinstance(q.get("score"), int) and q.get("status") == "qualified" and bool(q.get("summary")) and not q.get("manual_review")
    print("QUALIFICATION", "PASS" if ok else "FAIL structured qualification")
    if failed or not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
