"""Streaming coding agent: token-level LLM tool-calling loop over a Daytona sandbox."""
import os
import json
import logging
from openai import AsyncOpenAI

logger = logging.getLogger("coding_agent")

# label = user-facing; real = provider model id; tier = speed grouping
CODING_MODELS = [
    {"id": "gpt-5.6-terra", "label": "GPT-5.6 Terra", "real": "gpt-4o", "provider": "openai", "tier": "premium", "capabilities": ["coding", "design", "terminal"]},
    {"id": "claude-sonnet-4.6", "label": "Claude Sonnet 4.6", "real": "anthropic/claude-sonnet-4.5", "provider": "openrouter", "tier": "premium", "capabilities": ["coding", "reasoning", "design"]},
    {"id": "gemini-3.1-pro", "label": "Gemini 3.1 Pro", "real": "google/gemini-2.5-pro", "provider": "openrouter", "tier": "balanced", "capabilities": ["coding", "long-context"]},
    {"id": "qwen-coder", "label": "Qwen2.5 Coder", "real": "qwen/qwen-2.5-coder-32b-instruct", "provider": "openrouter", "tier": "balanced", "capabilities": ["coding", "fast-edits"]},
    {"id": "deepseek-v3", "label": "DeepSeek V3", "real": "deepseek/deepseek-chat", "provider": "openrouter", "tier": "fast", "capabilities": ["coding", "cheap"]},
    {"id": "gpt-4o-mini", "label": "GPT-4o mini", "real": "gpt-4o-mini", "provider": "openai", "tier": "fast", "capabilities": ["coding", "cheap"]},
    {"id": "minimax-m1", "label": "MiniMax M1", "real": "minimax/minimax-m1", "provider": "openrouter", "tier": "cheap", "capabilities": ["coding", "cheap"]},
]
CODING_MODEL_MAP = {m["id"]: m for m in CODING_MODELS}
DEFAULT_CODING_MODEL = "gpt-5.6-terra"


def _client(provider):
    if provider == "openrouter":
        return AsyncOpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url="https://openrouter.ai/api/v1")
    if provider == "nvidia":
        return AsyncOpenAI(api_key=os.environ["NVIDIA_NIM_API_KEY"], base_url="https://integrate.api.nvidia.com/v1")
    return AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])


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

SYSTEM = """You are Arevei Coding Agent, an expert full-stack engineer working inside a live Daytona Linux sandbox.
The project lives at the project root (all paths are relative to it). It may be ANY language or framework — inspect the files first to learn the stack. A dev/web server, when relevant, listens on port 5173.

Narrate briefly what you are about to do BEFORE each tool call (one short sentence), so the user sees live progress.

Rules:
- Use the tools to inspect and edit the real filesystem. Always write COMPLETE file contents with write_file (never partial diffs).
- Before editing, list or read files to understand the current stack and state. Do not assume a fixed template or config.
- When building from a blank or starter app, make the UI feel polished by default: responsive layout, clear hierarchy, refined spacing, usable states, and real content. Do not leave generic placeholder pages unless the user explicitly asks for basic scaffolding.
- For website/app requests, plan the design, implement it, run the relevant install/build/test command when available, and summarize the result.
- If you need to use code or terminal tools, say what operation you are about to perform before the tool call.
- Keep changes focused on the user's request while still delivering a complete product-quality surface.
- Do NOT start a long-running dev server yourself (the platform manages it). You may run install commands.
- When completely done, end with a SHORT summary (2-4 markdown bullets) of exactly what you changed."""


async def run_agent(ops, model_id, history, user_message):
    """Async generator yielding SSE event dicts with token-level streaming."""
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
                    yield {"type": "text_delta", "text": delta.content}
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
                start_ev = {"type": "tool", "name": name, "args": args}
                steps.append(start_ev)
                yield start_ev
                result, extra = await _execute(ops, name, args)
                if extra:
                    steps.append(extra)
                    yield extra
                messages.append({"role": "tool", "tool_call_id": s["id"] or f"call_{i}", "content": result[:20000]})
        else:
            summary = "Reached step limit. Partial changes applied."
    except Exception as e:
        logger.exception("agent failed")
        raw = str(e)
        if "402" in raw or "more credits" in raw or "insufficient" in raw.lower():
            msg = f"The model '{m['label']}' needs OpenRouter credits (your OpenRouter account balance is too low). Add credits at openrouter.ai/settings/credits, or switch to an OpenAI-backed model like GPT-5.6 Terra or GPT-4o mini."
        elif "401" in raw or "invalid api key" in raw.lower():
            msg = f"Auth failed for '{m['label']}'. Check the provider API key."
        else:
            msg = raw[:300]
        yield {"type": "error", "message": msg}
        summary = summary or f"Could not complete: {msg}"

    yield {"type": "summary", "text": summary}
    yield {"type": "done", "steps": steps, "summary": summary}


async def _execute(ops, name, args):
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
