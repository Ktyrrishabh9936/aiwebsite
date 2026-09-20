import os
import re
import json
import logging
import httpx
import asyncio
import time
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env", override=True)

logger = logging.getLogger("llm")

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
NVIDIA_KEY = os.environ.get("NVIDIA_NIM_API_KEY")
BEDROCK_KEY = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
AWS_REGION = os.environ.get("AWS_REGION") or "us-east-1"
BEDROCK_TEXT_MODEL_ID = os.environ.get("BEDROCK_TEXT_MODEL_ID") or "us.anthropic.claude-sonnet-4-6"
BEDROCK_VISION_MODEL_ID = os.environ.get("BEDROCK_VISION_MODEL_ID") or BEDROCK_TEXT_MODEL_ID

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

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
    {"id": "gemini-3-flash-preview", "label": "Gemini 3 Flash", "real": "google/gemini-2.5-flash", "provider": "openrouter", "tier": "fast"},
    {"id": "deepseek/deepseek-chat", "label": "DeepSeek V3", "real": "deepseek/deepseek-chat", "provider": "openrouter", "tier": "cheap"},
    {"id": "meta-llama/llama-3.3-70b-instruct", "label": "Llama 3.3 70B", "real": "meta-llama/llama-3.3-70b-instruct", "provider": "openrouter", "tier": "cheap"},
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
        return data["choices"][0]["message"]["content"]


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
    return "".join(part.get("text", "") for part in parts if part.get("text"))


async def generate_text(model_id, system, prompt, temperature=0.7, max_tokens=4000):
    m = _resolve(model_id)
    started = time.monotonic()
    logger.info("AI request start provider=%s model=%s mode=text", m["provider"], m["real"])
    try:
        if m["provider"] == "bedrock_mantle":
            cfg = mantle_config()
            if not cfg["key"]:
                raise ValueError("BEDROCK_MANTLE_API_KEY or AWS_BEARER_TOKEN_BEDROCK is required")
            return await _openai_compatible(cfg["url"], cfg["key"], m["real"], system, prompt, temperature, max_tokens, project=cfg["project"])
        if m["provider"] == "openrouter":
            return await _openai_compatible(OPENROUTER_URL, OPENROUTER_KEY, m["real"], system, prompt, temperature, max_tokens)
        if m["provider"] == "bedrock":
            return await asyncio.to_thread(_bedrock_converse, m["real"], system, prompt, temperature, max_tokens)
        else:
            return await _openai_compatible(NVIDIA_URL, NVIDIA_KEY, m["id"], system, prompt, temperature, max_tokens)
    except Exception as e:
        logger.warning("AI request error provider=%s model=%s error_type=%s", m["provider"], m["real"], type(e).__name__)
        # Gracefully retry with the configured default model.
        if model_id != DEFAULT_MODEL:
            return await generate_text(DEFAULT_MODEL, system, prompt, temperature, max_tokens)
        raise
    finally:
        logger.info("AI request finished provider=%s model=%s latency_ms=%.0f", m["provider"], m["real"], (time.monotonic() - started) * 1000)


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
    logger.info("AI request start provider=%s model=%s mode=stream", m["provider"], m["real"])
    try:
        async for delta in _stream_text(model_id, system, prompt, max_tokens=max_tokens):
            yield delta
    except Exception as exc:
        logger.warning("AI request error provider=%s model=%s error_type=%s", m["provider"], m["real"], type(exc).__name__)
        raise
    finally:
        logger.info("AI request finished provider=%s model=%s latency_ms=%.0f", m["provider"], m["real"], (time.monotonic() - started) * 1000)


async def _stream_text(model_id, system, prompt, max_tokens=None):
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
            delta = event.get("contentBlockDelta", {}).get("delta", {})
            if delta.get("text"):
                yield delta["text"]
        return
    if m["provider"] in {"openrouter", "nvidia", "bedrock_mantle"}:
        url, key = (OPENROUTER_URL, OPENROUTER_KEY) if m["provider"] == "openrouter" else (NVIDIA_URL, NVIDIA_KEY)
        if m["provider"] == "bedrock_mantle":
            cfg = mantle_config()
            url, key = cfg["url"], cfg["key"]
            if not key:
                raise ValueError("BEDROCK_MANTLE_API_KEY or AWS_BEARER_TOKEN_BEDROCK is required")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if m["provider"] == "bedrock_mantle":
            headers["OpenAI-Project"] = cfg["project"]
        payload = {
            "model": m.get("real", m["id"]),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "stream": True,
        }
        if max_tokens:
            payload["max_completion_tokens" if m["provider"] == "bedrock_mantle" else "max_tokens"] = max_tokens
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
                    try:
                        delta = event["choices"][0]["delta"].get("content")
                        if delta:
                            yield delta
                    except Exception:
                        continue
