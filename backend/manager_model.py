"""Native model tool calling using the application's provider configuration."""
import asyncio
import json
import time
from collections import OrderedDict
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


# Claude's own reply blocks (reasoning included) for recent tool rounds, keyed by the first tool call id.
# Sending them back unchanged lets Claude keep its reasoning across the rounds of one request.
_claude_turns = OrderedDict()


def anthropic_messages(messages):
    # Reasoning is only valid against the history it was produced in, so replay it for the
    # request in progress (everything after the latest user message) and nothing older.
    current = max((index for index, message in enumerate(messages) if message["role"] == "user"), default=-1)
    converted = []
    for index, message in enumerate(messages):
        role = "assistant" if message["role"] == "assistant" else "user"
        calls = message.get("tool_calls", [])
        if message["role"] == "tool":
            content = [{"type": "tool_result", "tool_use_id": message["tool_call_id"], "content": message["content"]}]
        elif calls and index > current and calls[0]["id"] in _claude_turns:
            content = list(_claude_turns[calls[0]["id"]])
        else:
            content = [{"type": "text", "text": message["content"]}] if message.get("content") else []
            content += [{"type": "tool_use", "id": call["id"], "name": call["function"]["name"],
                         "input": json.loads(call["function"]["arguments"])} for call in calls]
        if not content:
            continue
        if converted and converted[-1]["role"] == role:
            converted[-1]["content"].extend(content)
        else:
            converted.append({"role": role, "content": content})
    return converted


async def anthropic_tool_turn(model, system, messages, tools):
    async with llm.anthropic_client() as client:
        response = await client.beta.messages.create(
            **llm.anthropic_params(model["real"], system, 1800, replay_thinking=True),
            messages=anthropic_messages(messages),
            tools=[{"name": tool["function"]["name"], "description": tool["function"]["description"],
                    "input_schema": tool["function"]["parameters"]} for tool in tools])
    usage = llm.anthropic_usage(response.usage)
    text = llm.anthropic_text(response)
    calls = [{"id": block.id, "type": "function", "function": {"name": block.name, "arguments": json.dumps(block.input)}}
             for block in response.content if block.type == "tool_use"]
    if calls and response.stop_reason == "max_tokens":
        raise RuntimeError("Claude ran out of output budget while preparing an action")
    if calls:
        _claude_turns[calls[0]["id"]] = response.content
        while len(_claude_turns) > 200:
            _claude_turns.popitem(last=False)
    return {"role": "assistant", "content": text, **({"tool_calls": calls} if calls else {})}, usage


async def tool_turn(model_id, system, messages, tools):
    model = llm._resolve(model_id)
    started = time.monotonic()
    usage, status, error_type = {}, "success", ""
    try:
        if model["provider"] == "anthropic":
            reply, usage = await anthropic_tool_turn(model, system, messages, tools)
            return reply
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
        config = llm.mantle_config()
        url, key = config["url"], config["key"]
        if not key:
            raise ValueError("Configure credentials for the selected Agent Mode model")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "OpenAI-Project": config["project"]}
        payload = {"model": model["real"], "messages": [{"role": "system", "content": system}, *messages],
                   "tools": tools, "tool_choice": "auto", "temperature": 0.2, "max_completion_tokens": 1800}
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
