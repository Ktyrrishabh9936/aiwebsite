"""Streaming coding agent: token-level LLM tool-calling loop over a Daytona sandbox."""
import os
import json
import logging
import asyncio
import base64
import difflib
from openai import AsyncOpenAI

logger = logging.getLogger("coding_agent")

# label = user-facing; real = provider model id; tier = speed grouping
CODING_MODELS = [
    {"id": "bedrock-claude-sonnet", "label": "Bedrock Claude Sonnet", "real": os.environ.get("BEDROCK_CODE_MODEL_ID") or "us.anthropic.claude-sonnet-4-6", "provider": "bedrock", "tier": "premium", "capabilities": ["coding", "reasoning", "design"]},
    {"id": "bedrock-vision", "label": "Bedrock Vision", "real": os.environ.get("BEDROCK_VISION_MODEL_ID") or os.environ.get("BEDROCK_CODE_MODEL_ID") or "us.anthropic.claude-sonnet-4-6", "provider": "bedrock", "tier": "premium", "capabilities": ["coding", "design", "vision"], "vision": True},
    {"id": "gpt-5.6-terra", "label": "GPT-4o Terra", "real": "gpt-4o", "provider": "openai", "tier": "premium", "capabilities": ["coding", "design", "terminal", "vision"], "vision": True},
    {"id": "claude-sonnet-4.6", "label": "Claude Sonnet 4.6", "real": "anthropic/claude-sonnet-4.5", "provider": "openrouter", "tier": "premium", "capabilities": ["coding", "reasoning", "design", "vision"], "vision": True},
    {"id": "deepseek-v3", "label": "DeepSeek V3", "real": "deepseek/deepseek-chat", "provider": "openrouter", "tier": "fast", "capabilities": ["coding", "cheap"]},
    {"id": "gpt-4o-mini", "label": "GPT-4o mini", "real": "gpt-4o-mini", "provider": "openai", "tier": "fast", "capabilities": ["coding", "cheap"]},
    {"id": "minimax-m1", "label": "MiniMax M1", "real": "minimax/minimax-m1", "provider": "openrouter", "tier": "cheap", "capabilities": ["coding", "cheap"]},
]
CODING_MODEL_MAP = {m["id"]: m for m in CODING_MODELS}
DEFAULT_CODING_MODEL = "gpt-5.6-terra"
AWS_REGION = os.environ.get("AWS_REGION") or "us-east-1"
TREE_HINT_FILES = {
    "package.json", "vite.config.js", "vite.config.ts", "next.config.js", "next.config.mjs",
    "src/App.jsx", "src/App.tsx", "src/main.jsx", "src/main.tsx", "src/index.js",
    "app/page.tsx", "pages/index.js", "pages/index.tsx", "index.html", "README.md",
}


def _client(provider):
    if provider == "openrouter":
        return AsyncOpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url="https://openrouter.ai/api/v1")
    if provider == "nvidia":
        return AsyncOpenAI(api_key=os.environ["NVIDIA_NIM_API_KEY"], base_url="https://integrate.api.nvidia.com/v1")
    return AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])


def _bedrock_client():
    try:
        import boto3
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Amazon Bedrock needs the boto3 Python package. Start the backend with scripts/start-backend.ps1, "
            "or install backend requirements into the Python environment that runs uvicorn."
        ) from exc

    return boto3.client("bedrock-runtime", region_name=AWS_REGION)


TOOLS = [
    {"type": "function", "function": {"name": "list_files", "description": "List the project file tree.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a file's contents.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Create or overwrite a file with full contents.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "run_command", "description": "Run a shell command in the project root (e.g. npm install, ls). Avoid long-running dev servers.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
]

BEDROCK_TOOLS = [
    {
        "toolSpec": {
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "inputSchema": {"json": t["function"]["parameters"]},
        }
    }
    for t in TOOLS
]

SYSTEM = """You are Arevei Coding Agent, an expert full-stack engineer working inside a live Daytona Linux sandbox.
The project lives at the project root (all paths are relative to it). It may be ANY language or framework — inspect the files first to learn the stack. A dev/web server, when relevant, listens on port 5173.

Rules:
- Use the tools to inspect and edit the real filesystem. Always write COMPLETE file contents with write_file (never partial diffs).
- Inspect the file tree at most once per user request. After list_files, read specific likely entry files instead of listing again.
- Before editing, read files to understand the current stack and state. Do not assume a fixed template or config.
- When building from a blank or starter app, make the UI feel polished by default: responsive layout, clear hierarchy, refined spacing, usable states, and real content. Do not leave generic placeholder pages unless the user explicitly asks for basic scaffolding.
- For website/app requests, plan the design, implement it, run the relevant install/build/test command when available, and summarize the result.
- Keep progress narration brief and only when it adds useful context. Do not narrate repeated exploration.
- Keep changes focused on the user's request while still delivering a complete product-quality surface.
- Do NOT start a long-running dev server yourself (the platform manages it). You may run install commands.
- When completely done, end with a SHORT summary (2-4 markdown bullets) of exactly what you changed."""


def _openai_user_content(user_message, attachments):
    content = [{"type": "text", "text": user_message}]
    for item in attachments or []:
        mime = item.get("mime_type") or ""
        data = item.get("data_base64") or ""
        if mime.startswith("image/") and data:
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
    return content if len(content) > 1 else user_message


def _bedrock_user_content(user_message, attachments):
    content = [{"text": user_message}]
    for item in attachments or []:
        mime = item.get("mime_type") or ""
        data = item.get("data_base64") or ""
        if not mime.startswith("image/") or not data:
            continue
        fmt = {"image/png": "png", "image/jpeg": "jpeg", "image/webp": "webp"}.get(mime)
        if not fmt:
            continue
        content.append({"image": {"format": fmt, "source": {"bytes": base64.b64decode(data)}}})
    return content


def _bedrock_messages(history, user_message, attachments):
    messages = []
    for h in history[-8:]:
        role = "assistant" if h["role"] == "assistant" else "user"
        messages.append({"role": role, "content": [{"text": h["content"] or ""}]})
    messages.append({"role": "user", "content": _bedrock_user_content(user_message, attachments)})
    return messages


class AgentTurnState:
    def __init__(self):
        self.file_tree_listed = False
        self.file_tree_summary = ""
        self.file_count = 0


def _collect_bedrock_stream(client, **kwargs):
    response = client.converse_stream(**kwargs)
    message = {"role": "assistant", "content": []}
    text_parts = []
    tool_parts = {}
    stop_reason = None
    for event in response.get("stream", []):
        if "contentBlockStart" in event:
            start = event["contentBlockStart"].get("start", {})
            if "toolUse" in start:
                idx = event["contentBlockStart"]["contentBlockIndex"]
                tool_parts[idx] = {"toolUseId": start["toolUse"]["toolUseId"], "name": start["toolUse"]["name"], "input": ""}
        elif "contentBlockDelta" in event:
            idx = event["contentBlockDelta"]["contentBlockIndex"]
            delta = event["contentBlockDelta"].get("delta", {})
            if delta.get("text"):
                text_parts.append(delta["text"])
            if delta.get("toolUse", {}).get("input") is not None:
                tool_parts.setdefault(idx, {})["input"] = tool_parts.setdefault(idx, {}).get("input", "") + delta["toolUse"]["input"]
        elif "messageStop" in event:
            stop_reason = event["messageStop"].get("stopReason")
    if text_parts:
        message["content"].append({"text": "".join(text_parts)})
    for idx in sorted(tool_parts):
        tool = tool_parts[idx]
        try:
            parsed = json.loads(tool.get("input") or "{}")
        except Exception:
            parsed = {}
        message["content"].append({"toolUse": {"toolUseId": tool.get("toolUseId"), "name": tool.get("name"), "input": parsed}})
    return message, stop_reason


async def _run_bedrock_agent(ops, m, history, user_message, attachments):
    client = _bedrock_client()
    messages = _bedrock_messages(history, user_message, attachments)
    steps = []
    changed_files = {}
    summary = ""
    state = AgentTurnState()
    try:
        for _ in range(14):
            response = await asyncio.to_thread(
                lambda: client.converse_stream(
                    modelId=m["real"],
                    system=[{"text": SYSTEM}],
                    messages=messages,
                    toolConfig={"tools": BEDROCK_TOOLS},
                    inferenceConfig={"temperature": 0.2, "maxTokens": 8000},
                )
            )
            assistant_msg = {"role": "assistant", "content": []}
            text_parts = []
            tool_parts = {}
            stop_reason = None
            for event in response.get("stream", []):
                if "contentBlockStart" in event:
                    start = event["contentBlockStart"].get("start", {})
                    if "toolUse" in start:
                        idx = event["contentBlockStart"]["contentBlockIndex"]
                        tool_parts[idx] = {"toolUseId": start["toolUse"]["toolUseId"], "name": start["toolUse"]["name"], "input": ""}
                elif "contentBlockDelta" in event:
                    idx = event["contentBlockDelta"]["contentBlockIndex"]
                    delta = event["contentBlockDelta"].get("delta", {})
                    if delta.get("text"):
                        text_parts.append(delta["text"])
                        yield {"type": "assistant_delta", "text": delta["text"]}
                    if delta.get("toolUse", {}).get("input") is not None:
                        tool_parts.setdefault(idx, {})["input"] = tool_parts.setdefault(idx, {}).get("input", "") + delta["toolUse"]["input"]
                elif "messageStop" in event:
                    stop_reason = event["messageStop"].get("stopReason")
            if text_parts:
                summary = "".join(text_parts)
                assistant_msg["content"].append({"text": summary})
            for idx in sorted(tool_parts):
                tool = tool_parts[idx]
                try:
                    parsed = json.loads(tool.get("input") or "{}")
                except Exception:
                    parsed = {}
                assistant_msg["content"].append({"toolUse": {"toolUseId": tool.get("toolUseId"), "name": tool.get("name"), "input": parsed}})
            messages.append(assistant_msg)
            tool_uses = [part["toolUse"] for part in assistant_msg.get("content", []) if "toolUse" in part]
            if not tool_uses:
                break
            results = []
            for tool_use in tool_uses:
                result, extra = await _execute(ops, tool_use.get("name"), tool_use.get("input") or {}, state)
                if extra:
                    steps.append(extra)
                    if extra["type"] == "file_changed":
                        changed_files[extra["path"]] = extra
                    yield extra
                results.append({
                    "toolResult": {
                        "toolUseId": tool_use["toolUseId"],
                        "content": [{"text": result[:20000]}],
                    }
                })
            messages.append({"role": "user", "content": results})
            if stop_reason != "tool_use":
                break
        else:
            summary = "Reached step limit. Partial changes applied."
    except Exception as e:
        logger.exception("bedrock agent failed")
        yield {"type": "error", "message": str(e)[:300]}
        summary = summary or f"Could not complete: {str(e)[:300]}"

    final = {"type": "final_summary", "text": summary or "Done.", "changed_files": list(changed_files.values())}
    yield final
    yield {"type": "done", "steps": steps, "summary": final["text"], "changed_files": final["changed_files"]}


async def run_agent(ops, model_id, history, user_message, attachments=None):
    """Async generator yielding SSE event dicts with token-level streaming."""
    m = CODING_MODEL_MAP.get(model_id) or CODING_MODEL_MAP[DEFAULT_CODING_MODEL]
    if m["provider"] == "bedrock":
        async for ev in _run_bedrock_agent(ops, m, history, user_message, attachments or []):
            yield ev
        return
    client = _client(m["provider"])

    messages = [{"role": "system", "content": SYSTEM}]
    for h in history[-8:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": _openai_user_content(user_message, attachments or [])})

    steps = []
    changed_files = {}
    summary = ""
    state = AgentTurnState()
    try:
        for _ in range(14):
            stream = await client.chat.completions.create(
                model=m["real"], messages=messages, tools=TOOLS, tool_choice="auto",
                temperature=0.2, stream=True, max_tokens=8000,
            )
            content_buf = ""
            tool_calls = {}
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if getattr(delta, "content", None):
                    content_buf += delta.content
                    yield {"type": "assistant_delta", "text": delta.content}
                if getattr(delta, "tool_calls", None):
                    for tc in delta.tool_calls:
                        slot = tool_calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function and tc.function.name:
                            slot["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            slot["args"] += tc.function.arguments

            if not tool_calls:
                summary = content_buf or "Done."
                break

            messages.append({
                "role": "assistant", "content": content_buf or "",
                "tool_calls": [{"id": s["id"] or f"call_{i}", "type": "function",
                                "function": {"name": s["name"], "arguments": s["args"] or "{}"}}
                               for i, s in sorted(tool_calls.items())],
            })
            for i, s in sorted(tool_calls.items()):
                name = s["name"]
                try:
                    args = json.loads(s["args"] or "{}")
                except Exception:
                    args = {}
                result, extra = await _execute(ops, name, args, state)
                if extra:
                    steps.append(extra)
                    if extra["type"] == "file_changed":
                        changed_files[extra["path"]] = extra
                    yield extra
                messages.append({"role": "tool", "tool_call_id": s["id"] or f"call_{i}", "content": result[:20000]})
        else:
            summary = "Reached step limit. Partial changes applied."
    except Exception as e:
        logger.exception("agent failed")
        raw = str(e)
        if "402" in raw or "more credits" in raw or "insufficient" in raw.lower():
            msg = f"The model '{m['label']}' needs OpenRouter credits (your OpenRouter account balance is too low). Add credits at openrouter.ai/settings/credits, or switch to an OpenAI-backed model like GPT-4o Terra or GPT-4o mini."
        elif "401" in raw or "invalid api key" in raw.lower():
            msg = f"Auth failed for '{m['label']}'. Check the provider API key."
        else:
            msg = raw[:300]
        yield {"type": "error", "message": msg}
        summary = summary or f"Could not complete: {msg}"

    final = {"type": "final_summary", "text": summary, "changed_files": list(changed_files.values())}
    yield final
    yield {"type": "done", "steps": steps, "summary": summary, "changed_files": final["changed_files"]}


async def _execute(ops, name, args, state=None):
    try:
        if name == "list_files":
            if state and state.file_tree_listed:
                return "File tree already listed. Read specific files next, such as package.json, routing files, or likely entry files.", None
            tree = await ops["list_files"]()
            count = _count_files(tree)
            summary = _summarize_tree(tree)
            if state:
                state.file_tree_listed = True
                state.file_tree_summary = summary
                state.file_count = count
            return summary, {"type": "activity_finished", "kind": "explore", "label": f"Explored {count} files", "count": count}
        if name == "read_file":
            path = args.get("path", "")
            content = await ops["read_file"](path)
            return content[:16000], {"type": "activity_finished", "kind": "read", "path": path, "label": f"Read {path}"}
        if name == "write_file":
            path = args.get("path", "")
            before = ""
            try:
                before = await ops["read_file"](path)
            except Exception:
                before = ""
            await ops["write_file"](path, args.get("content", ""))
            stats = _diff_stats(before, args.get("content", ""))
            return f"wrote {path}", {"type": "file_changed", "path": path, "label": f"Edited {path}", **stats}
        if name == "run_command":
            cmd = args.get("command", "")
            res = await ops["run_command"](cmd)
            return f"exit={res['exit_code']}\n{res['output'][:8000]}", {"type": "terminal_result", "command": cmd, "label": f"Ran {cmd}", "output": res["output"][:8000], "exit_code": res["exit_code"]}
        return "unknown tool", None
    except Exception as e:
        return f"tool error: {str(e)[:400]}", None


def _count_files(nodes):
    total = 0
    for node in nodes or []:
        if node.get("type") == "dir":
            total += _count_files(node.get("children") or [])
        else:
            total += 1
    return total


def _flatten_tree(nodes):
    paths = []
    for node in nodes or []:
        path = node.get("path") or node.get("name") or ""
        if node.get("type") == "dir":
            paths.extend(_flatten_tree(node.get("children") or []))
        elif path:
            paths.append(path)
    return paths


def _summarize_tree(tree):
    paths = sorted(_flatten_tree(tree))
    top_dirs = []
    top_files = []
    for node in tree or []:
        name = node.get("name") or node.get("path") or ""
        if not name:
            continue
        if node.get("type") == "dir":
            top_dirs.append(name)
        else:
            top_files.append(name)
    key_files = [path for path in paths if path in TREE_HINT_FILES]
    if len(key_files) < 24:
        key_files.extend(path for path in paths if path not in key_files and _looks_like_entry_file(path))
    key_files = key_files[:30]
    return json.dumps({
        "summary": "Project file tree summarized. Read specific files next; do not call list_files again.",
        "file_count": len(paths),
        "top_level_dirs": top_dirs[:30],
        "top_level_files": top_files[:30],
        "key_files": key_files,
    }, ensure_ascii=False)


def _looks_like_entry_file(path):
    lowered = path.lower()
    name = lowered.rsplit("/", 1)[-1]
    if name in {"app.jsx", "app.tsx", "main.jsx", "main.tsx", "index.jsx", "index.tsx", "router.jsx", "router.tsx"}:
        return True
    if lowered.endswith(("/routes.jsx", "/routes.tsx", "/layout.tsx", "/page.tsx")):
        return True
    return False


def _diff_stats(before, after):
    added = 0
    removed = 0
    for line in difflib.ndiff((before or "").splitlines(), (after or "").splitlines()):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    return {"added": added, "removed": removed}
