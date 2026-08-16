"""Streaming coding agent: LLM tool-calling loop over a Daytona sandbox."""
import os
import json
import logging
from openai import AsyncOpenAI

logger = logging.getLogger("coding_agent")

CODING_MODELS = [
    {"id": "gpt-4o", "label": "GPT-4o", "provider": "openai", "tier": "premium"},
    {"id": "gpt-4o-mini", "label": "GPT-4o mini", "provider": "openai", "tier": "cheap"},
    {"id": "anthropic/claude-3.5-sonnet", "label": "Claude 3.5 Sonnet", "provider": "openrouter", "tier": "premium"},
    {"id": "deepseek/deepseek-chat", "label": "DeepSeek V3", "provider": "openrouter", "tier": "cheap"},
    {"id": "qwen/qwen-2.5-coder-32b-instruct", "label": "Qwen2.5 Coder 32B", "provider": "openrouter", "tier": "cheap"},
]
CODING_MODEL_MAP = {m["id"]: m for m in CODING_MODELS}
DEFAULT_CODING_MODEL = "gpt-4o"


def _client(provider):
    if provider == "openrouter":
        return AsyncOpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url="https://openrouter.ai/api/v1")
    if provider == "nvidia":
        return AsyncOpenAI(api_key=os.environ["NVIDIA_NIM_API_KEY"], base_url="https://integrate.api.nvidia.com/v1")
    return AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])


TOOLS = [
    {"type": "function", "function": {
        "name": "list_files", "description": "List the project file tree.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "read_file", "description": "Read a file's contents.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "write_file", "description": "Create or overwrite a file with full contents.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
    }},
    {"type": "function", "function": {
        "name": "run_command", "description": "Run a shell command in the project root (e.g. npm install, ls). Avoid starting long-running dev servers.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
    }},
]

SYSTEM = """You are Arevei Coding Agent, an expert full-stack engineer working inside a live Daytona Linux sandbox.
The project lives at the project root (all paths are relative to it). It is a Vite + React (JavaScript) app; the dev server runs on port 5173.

Rules:
- Use the tools to inspect and edit the real filesystem. Always write COMPLETE file contents with write_file (never partial diffs).
- Before editing, read or list files when you are unsure of the current state.
- Keep changes minimal and focused on the user's request. Prefer editing src/App.jsx and src/ files.
- Do NOT run `npm run dev` yourself (the platform manages the dev server). You may run `npm install <pkg>` when adding dependencies.
- When done, reply with a SHORT summary (2-4 lines, markdown bullets) of exactly what you changed. Do not paste full file contents in the summary."""


async def run_agent(ops, model_id, history, user_message):
    """Async generator yielding SSE event dicts."""
    m = CODING_MODEL_MAP.get(model_id) or CODING_MODEL_MAP[DEFAULT_CODING_MODEL]
    client = _client(m["provider"])

    messages = [{"role": "system", "content": SYSTEM}]
    for h in history[-8:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_message})

    steps = []
    summary = ""
    try:
        for _ in range(14):
            resp = await client.chat.completions.create(
                model=m["id"], messages=messages, tools=TOOLS, tool_choice="auto", temperature=0.2,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                summary = msg.content or "Done."
                break
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [{"id": tc.id, "type": "function",
                                "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in msg.tool_calls],
            })
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                event = {"type": "tool", "name": name, "args": args}
                steps.append(event)
                yield event
                result, extra = await _execute(ops, name, args)
                if extra:
                    steps.append(extra)
                    yield extra
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result[:20000]})
        else:
            summary = "Reached step limit. Partial changes applied."
    except Exception as e:
        logger.exception("agent failed")
        yield {"type": "error", "message": str(e)[:300]}
        summary = f"Error: {str(e)[:200]}"

    yield {"type": "summary", "text": summary}
    yield {"type": "done", "steps": steps, "summary": summary}


async def _execute(ops, name, args):
    """Returns (tool_result_string, extra_event_or_None)."""
    try:
        if name == "list_files":
            tree = await ops["list_files"]()
            return json.dumps(tree)[:8000], {"type": "files_changed"}
        if name == "read_file":
            content = await ops["read_file"](args.get("path", ""))
            return content[:16000], None
        if name == "write_file":
            path = args.get("path", "")
            await ops["write_file"](path, args.get("content", ""))
            return f"wrote {path}", {"type": "file", "path": path}
        if name == "run_command":
            cmd = args.get("command", "")
            res = await ops["run_command"](cmd)
            return f"exit={res['exit_code']}\n{res['output'][:8000]}", {"type": "terminal", "command": cmd, "output": res["output"][:8000], "exit_code": res["exit_code"]}
        return "unknown tool", None
    except Exception as e:
        return f"tool error: {str(e)[:400]}", None
