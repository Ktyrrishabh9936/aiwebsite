"""Native model tool calling using the application's provider configuration."""
import asyncio
import json
import time
import httpx
import llm_service as llm
from ai_usage import normalize_usage, record_usage


def bedrock_messages(messages):
    converted = []
    for message in messages:
        role = "user" if message["role"] == "tool" else message["role"]
        content = []
        if message["role"] == "tool":
            content.append({"toolResult": {"toolUseId": message["tool_call_id"], "content": [{"text": message["content"]}]}})
        else:
            if message.get("content"):
                content.append({"text": message["content"]})
            for call in message.get("tool_calls", []):
                content.append({"toolUse": {"toolUseId": call["id"], "name": call["function"]["name"],
                                            "input": json.loads(call["function"]["arguments"])}})
        if not content:
            continue
        if converted and converted[-1]["role"] == role:
            converted[-1]["content"].extend(content)
        else:
            converted.append({"role": role, "content": content})
    return converted


async def tool_turn(model_id, system, messages, tools):
    model = llm._resolve(model_id)
    started = time.monotonic()
    usage, status, error_type = {}, "success", ""
    try:
        if model["provider"] == "bedrock":
            def converse():
                return llm._bedrock_client().converse(
                    modelId=model["real"], system=[{"text": system}], messages=bedrock_messages(messages),
                    toolConfig={"tools": [{"toolSpec": {"name": tool["function"]["name"],
                        "description": tool["function"]["description"],
                        "inputSchema": {"json": tool["function"]["parameters"]}}} for tool in tools]},
                    inferenceConfig={"maxTokens": 1800, "temperature": 0.2})
            response = await asyncio.to_thread(converse)
            usage = normalize_usage(response.get("usage"))
            content, calls = [], []
            for block in response["output"]["message"]["content"]:
                if "text" in block: content.append(block["text"])
                if "toolUse" in block:
                    call = block["toolUse"]
                    calls.append({"id": call["toolUseId"], "type": "function", "function": {
                        "name": call["name"], "arguments": json.dumps(call["input"])}})
            return {"role": "assistant", "content": "\n".join(content), **({"tool_calls": calls} if calls else {})}
        if model["provider"] == "bedrock_mantle":
            config = llm.mantle_config()
            url, key = config["url"], config["key"]
        elif model["provider"] == "openrouter":
            url, key = llm.OPENROUTER_URL, llm.OPENROUTER_KEY
        else:
            url, key = llm.NVIDIA_URL, llm.NVIDIA_KEY
        if not key:
            raise ValueError("Configure credentials for the selected Agent Mode model")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": model["real"], "messages": [{"role": "system", "content": system}, *messages],
                   "tools": tools, "tool_choice": "auto", "temperature": 0.2}
        if model["provider"] == "bedrock_mantle":
            headers["OpenAI-Project"] = config["project"]
            payload["max_completion_tokens"] = 1800
        else:
            payload["max_tokens"] = 1800
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        usage = normalize_usage(data.get("usage"))
        result = data["choices"][0]["message"]
        return {"role": "assistant", "content": result.get("content") or "",
                **({"tool_calls": result["tool_calls"]} if result.get("tool_calls") else {})}
    except Exception as error:
        status, error_type = "failed", type(error).__name__
        raise
    finally:
        await record_usage(model["provider"], model["real"], usage, (time.monotonic() - started) * 1000, status, error_type)
