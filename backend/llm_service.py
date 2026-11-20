import os
import re
import json
import logging
import httpx
import asyncio
import time
from dotenv import load_dotenv
from pathlib import Path
from ai_usage import normalize_usage, record_usage

load_dotenv(Path(__file__).parent / ".env", override=True)

logger = logging.getLogger("llm")

BEDROCK_KEY = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
AWS_REGION = os.environ.get("AWS_REGION") or "us-east-1"
BEDROCK_TEXT_MODEL_ID = os.environ.get("BEDROCK_TEXT_MODEL_ID") or "us.anthropic.claude-sonnet-4-6"
BEDROCK_VISION_MODEL_ID = os.environ.get("BEDROCK_VISION_MODEL_ID") or BEDROCK_TEXT_MODEL_ID

# Claude models always think, and thinking counts against max_tokens, so the budgets
# callers pass (sized for the visible answer) get this much room on top.
ANTHROPIC_THINKING_HEADROOM = 8000
# Models that can hand a declined request to another Claude model inside the same call.
ANTHROPIC_FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}

DEFAULT_MODEL = "openai.gpt-oss-120b"


def mantle_config():
    return {
        "key": os.environ.get("BEDROCK_MANTLE_API_KEY") or os.environ.get("AWS_BEARER_TOKEN_BEDROCK"),
        "url": (os.environ.get("BEDROCK_MANTLE_BASE_URL") or "https://bedrock-mantle.ap-south-1.api.aws/v1").rstrip("/") + "/chat/completions",
        "project": os.environ.get("BEDROCK_MANTLE_PROJECT") or "default",
    }

# Model registry surfaced to the UI model picker
MODELS = [
    {"id": "openai.gpt-oss-120b", "label": "GPT-OSS 120B — Amazon Bedrock", "real": "openai.gpt-oss-120b", "provider": "bedrock_mantle", "tier": "premium"},
    {"id": "bedrock-claude-sonnet", "label": "Bedrock Claude Sonnet", "real": BEDROCK_TEXT_MODEL_ID, "provider": "bedrock", "tier": "premium"},
    {"id": "bedrock-vision", "label": "Bedrock Vision", "real": BEDROCK_VISION_MODEL_ID, "provider": "bedrock", "tier": "premium", "vision": True},
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5 — Anthropic", "real": "claude-opus-5-5", "provider": "anthropic", "tier": "premium", "vision": True},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5 — Anthropic", "real": "claude-sonnet-5-5", "provider": "anthropic", "tier": "fast", "vision": True},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5 — Anthropic", "real": "claude-haiku-5-5", "provider": "anthropic", "tier": "cheap", "vision": True},
]
MODEL_MAP = {m["id"]: m for m in MODELS}


def _resolve(model_id):
    return MODEL_MAP.get(model_id) or MODEL_MAP[DEFAULT_MODEL]


async def _openai_compatible(url, key, model, system, prompt, temperature, max_tokens, project=None):
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if project:
        headers["OpenAI-Project"] = project
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if project:
        payload["max_completion_tokens"] = payload.pop("max_tokens")
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"], normalize_usage(data.get("usage"))


def anthropic_client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY is required")
    try:
        import anthropic
    except ModuleNotFoundError as exc:
        raise RuntimeError("Claude needs the anthropic Python package. Install backend requirements into the Python environment that runs uvicorn.") from exc
    return anthropic.AsyncAnthropic(api_key=key, timeout=float(os.environ.get("ANTHROPIC_TIMEOUT") or 120))


def anthropic_params(model, system, max_tokens, effort=None, replay_thinking=False):
    """Request settings shared by every Claude call. Sampling settings are not sent: current Claude models reject them."""
    params = {"model": model, "system": system, "max_tokens": max_tokens + ANTHROPIC_THINKING_HEADROOM,
              "output_config": {"effort": effort or os.environ.get("ANTHROPIC_EFFORT") or "medium"}}
    betas = []
    if model in ANTHROPIC_FALLBACK_MODELS:
        betas.append("server-side-fallback-2026-07-01")
        params["fallbacks"] = "default"
    if replay_thinking:
        # Tool loops send earlier reasoning back; if the history no longer matches it, drop that reasoning rather than fail.
        betas.append("thinking-binding-controls-2026-08-01")
        params["thinking"] = {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
    if betas:
        params["betas"] = betas
    return params


def anthropic_usage(usage):
    return normalize_usage({"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                            "cache_read_input_tokens": usage.cache_read_input_tokens or 0,
                            "cache_write_input_tokens": usage.cache_creation_input_tokens or 0})


def anthropic_text(response):
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined this request")
    return "".join(block.text for block in response.content if block.type == "text")


async def _anthropic_message(model, system, prompt, max_tokens):
    async with anthropic_client() as client:
        # Streamed so long answers never hit an HTTP timeout; only the finished message is used.
        async with client.beta.messages.stream(**anthropic_params(model, system, max_tokens),
                                               messages=[{"role": "user", "content": prompt}]) as stream:
            response = await stream.get_final_message()
    return anthropic_text(response), anthropic_usage(response.usage)


def _bedrock_client():
    try:
        import boto3
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Amazon Bedrock needs the boto3 Python package. Start the backend with scripts/start-backend.ps1, "
            "or install backend requirements into the Python environment that runs uvicorn."
        ) from exc

    return boto3.client("bedrock-runtime", region_name=AWS_REGION)


def _bedrock_converse(model, system, prompt, temperature, max_tokens):
    response = _bedrock_client().converse(
        modelId=model,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"temperature": temperature, "maxTokens": max_tokens},
    )
    parts = response.get("output", {}).get("message", {}).get("content", [])
    return "".join(part.get("text", "") for part in parts if part.get("text")), normalize_usage(response.get("usage"))


async def generate_text(model_id, system, prompt, temperature=0.7, max_tokens=4000):
    m = _resolve(model_id)
    started = time.monotonic()
    usage = {}
    status, error_type = "success", ""
    logger.info("AI request start provider=%s model=%s mode=text", m["provider"], m["real"])
    try:
        if m["provider"] == "bedrock_mantle":
            cfg = mantle_config()
            if not cfg["key"]:
                raise ValueError("BEDROCK_MANTLE_API_KEY or AWS_BEARER_TOKEN_BEDROCK is required")
            text, usage = await _openai_compatible(cfg["url"], cfg["key"], m["real"], system, prompt, temperature, max_tokens, project=cfg["project"])
            return text
        if m["provider"] == "anthropic":
            text, usage = await _anthropic_message(m["real"], system, prompt, max_tokens)
            return text
        text, usage = await asyncio.to_thread(_bedrock_converse, m["real"], system, prompt, temperature, max_tokens)
        return text
    except Exception as e:
        status, error_type = "failed", type(e).__name__
        logger.warning("AI request error provider=%s model=%s error_type=%s", m["provider"], m["real"], type(e).__name__)
        # Gracefully retry with the configured default model.
        if model_id != DEFAULT_MODEL:
            return await generate_text(DEFAULT_MODEL, system, prompt, temperature, max_tokens)
        raise
    finally:
        latency_ms = (time.monotonic() - started) * 1000
        await record_usage(m["provider"], m["real"], usage, latency_ms, status, error_type)
        logger.info("AI request finished provider=%s model=%s latency_ms=%.0f", m["provider"], m["real"], latency_ms)


def parse_json(text):
    """Extract and parse a JSON object/array from an LLM response."""
    if not text:
        raise ValueError("empty response")
    cleaned = text.strip()
    cleaned = re.sub(r"^```(json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    # find first { or [ and match
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except Exception:
                continue
    raise ValueError("Could not parse JSON from model output")


async def generate_json(model_id, system, prompt, temperature=0.5, max_tokens=6000):
    sys = system + "\n\nYou MUST respond with ONLY valid JSON. No prose, no markdown fences."
    text = await generate_text(model_id, sys, prompt, temperature, max_tokens)
    return parse_json(text)


async def stream_text(model_id, system, prompt, max_tokens=None):
    m = _resolve(model_id)
    started = time.monotonic()
    usage = {}
    status, error_type = "success", ""
    logger.info("AI request start provider=%s model=%s mode=stream", m["provider"], m["real"])
    try:
        async for delta in _stream_text(model_id, system, prompt, max_tokens=max_tokens, usage=usage):
            yield delta
    except Exception as exc:
        status, error_type = "failed", type(exc).__name__
        logger.warning("AI request error provider=%s model=%s error_type=%s", m["provider"], m["real"], type(exc).__name__)
        raise
    finally:
        latency_ms = (time.monotonic() - started) * 1000
        await record_usage(m["provider"], m["real"], usage, latency_ms, status, error_type)
        logger.info("AI request finished provider=%s model=%s latency_ms=%.0f", m["provider"], m["real"], latency_ms)


async def _stream_text(model_id, system, prompt, max_tokens=None, usage=None):
    usage = usage if usage is not None else {}
    m = _resolve(model_id)
    if m["provider"] == "bedrock":
        stream = await asyncio.to_thread(
            lambda: _bedrock_client().converse_stream(
                modelId=m["real"],
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"temperature": 0.7, **({"maxTokens": max_tokens} if max_tokens else {})},
            )
        )
        for event in stream.get("stream", []):
            if event.get("metadata", {}).get("usage"):
                usage.update(normalize_usage(event["metadata"]["usage"]))
            delta = event.get("contentBlockDelta", {}).get("delta", {})
            if delta.get("text"):
                yield delta["text"]
        return
    if m["provider"] == "anthropic":
        async with anthropic_client() as client:
            async with client.beta.messages.stream(**anthropic_params(m["real"], system, max_tokens or 8000),
                                                   messages=[{"role": "user", "content": prompt}]) as stream:
                async for text in stream.text_stream:
                    yield text
                response = await stream.get_final_message()
        usage.update(anthropic_usage(response.usage))
        if response.stop_reason == "refusal":
            raise RuntimeError("Claude declined this request")
        return
    if m["provider"] == "bedrock_mantle":
        cfg = mantle_config()
        url, key = cfg["url"], cfg["key"]
        if not key:
            raise ValueError("BEDROCK_MANTLE_API_KEY or AWS_BEARER_TOKEN_BEDROCK is required")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "OpenAI-Project": cfg["project"]}
        payload = {
            "model": m["real"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if max_tokens:
            payload["max_completion_tokens"] = max_tokens
        async with httpx.AsyncClient(timeout=120) as c:
            async with c.stream("POST", url, headers=headers, json=payload) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    chunk = line[6:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        event = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    if event.get("error"):
                        raise RuntimeError("AI provider returned a streaming error")
                    if event.get("usage"):
                        usage.update(normalize_usage(event["usage"]))
                    try:
                        delta = event["choices"][0]["delta"].get("content")
                        if delta:
                            yield delta
                    except Exception:
                        continue
