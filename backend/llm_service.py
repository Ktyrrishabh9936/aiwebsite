import os
import re
import json
import logging
import httpx
import asyncio
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

DEFAULT_MODEL = "gemini-3-flash-preview"

# Model registry surfaced to the UI model picker
MODELS = [
    {"id": "bedrock-claude-sonnet", "label": "Bedrock Claude Sonnet", "real": BEDROCK_TEXT_MODEL_ID, "provider": "bedrock", "tier": "premium"},
    {"id": "bedrock-vision", "label": "Bedrock Vision", "real": BEDROCK_VISION_MODEL_ID, "provider": "bedrock", "tier": "premium", "vision": True},
    {"id": "gemini-3-flash-preview", "label": "Gemini 3 Flash", "real": "google/gemini-2.5-flash", "provider": "openrouter", "tier": "fast"},
    {"id": "deepseek/deepseek-chat", "label": "DeepSeek V3", "real": "deepseek/deepseek-chat", "provider": "openrouter", "tier": "cheap"},
    {"id": "meta-llama/llama-3.3-70b-instruct", "label": "Llama 3.3 70B", "real": "meta-llama/llama-3.3-70b-instruct", "provider": "openrouter", "tier": "cheap"},
]
MODEL_MAP = {m["id"]: m for m in MODELS}


def _resolve(model_id):
    return MODEL_MAP.get(model_id) or MODEL_MAP[DEFAULT_MODEL]


async def _openai_compatible(url, key, model, system, prompt, temperature, max_tokens):
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
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
    try:
        if m["provider"] == "openrouter":
            return await _openai_compatible(OPENROUTER_URL, OPENROUTER_KEY, m["real"], system, prompt, temperature, max_tokens)
        if m["provider"] == "bedrock":
            return await asyncio.to_thread(_bedrock_converse, m["real"], system, prompt, temperature, max_tokens)
        else:
            return await _openai_compatible(NVIDIA_URL, NVIDIA_KEY, m["id"], system, prompt, temperature, max_tokens)
    except Exception as e:
        logger.exception("generate_text failed")
        # Gracefully retry with the configured default model.
        if model_id != DEFAULT_MODEL:
            return await generate_text(DEFAULT_MODEL, system, prompt, temperature, max_tokens)
        raise


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


async def stream_text(model_id, system, prompt):
    m = _resolve(model_id)
    if m["provider"] == "bedrock":
        stream = await asyncio.to_thread(
            lambda: _bedrock_client().converse_stream(
                modelId=m["real"],
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"temperature": 0.7},
            )
        )
        for event in stream.get("stream", []):
            delta = event.get("contentBlockDelta", {}).get("delta", {})
            if delta.get("text"):
                yield delta["text"]
        return
    if m["provider"] == "openrouter" or m["provider"] == "nvidia":
        url, key = (OPENROUTER_URL, OPENROUTER_KEY) if m["provider"] == "openrouter" else (NVIDIA_URL, NVIDIA_KEY)
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": m.get("real", m["id"]),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=120) as c:
            async with c.stream("POST", url, headers=headers, json=payload) as r:
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    chunk = line[6:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0]["delta"].get("content")
                        if delta:
                            yield delta
                    except Exception:
                        continue
