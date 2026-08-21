import os
import re
import json
import logging
import httpx
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

logger = logging.getLogger("llm")

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
NVIDIA_KEY = os.environ.get("NVIDIA_NIM_API_KEY")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

DEFAULT_MODEL = "gpt-5.4"

# Model registry surfaced to the UI model picker
MODELS = [
    {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6", "real": "anthropic/claude-sonnet-4.5", "provider": "openrouter", "tier": "premium"},
    {"id": "gpt-5.4", "label": "GPT-5.4", "real": "openai/gpt-5.4", "provider": "openrouter", "tier": "premium"},
    {"id": "gemini-3-flash-preview", "label": "Gemini 3 Flash", "real": "google/gemini-2.5-flash", "provider": "openrouter", "tier": "fast"},
    {"id": "deepseek/deepseek-chat", "label": "DeepSeek V3", "real": "deepseek/deepseek-chat", "provider": "openrouter", "tier": "cheap"},
    {"id": "meta-llama/llama-3.3-70b-instruct", "label": "Llama 3.3 70B", "real": "meta-llama/llama-3.3-70b-instruct", "provider": "openrouter", "tier": "cheap"},
    {"id": "meta/llama-3.1-70b-instruct", "label": "NVIDIA Llama 3.1 70B", "real": "meta/llama-3.1-70b-instruct", "provider": "nvidia", "tier": "cheap"},
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


async def generate_text(model_id, system, prompt, temperature=0.7, max_tokens=4000):
    m = _resolve(model_id)
    try:
        if m["provider"] == "openrouter":
            return await _openai_compatible(OPENROUTER_URL, OPENROUTER_KEY, m["real"], system, prompt, temperature, max_tokens)
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
