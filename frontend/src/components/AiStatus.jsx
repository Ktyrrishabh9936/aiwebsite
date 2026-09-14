import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Radio } from "lucide-react";
import api, { API } from "../lib/api";

export const providerName = (provider) => ({ bedrock_mantle: "Amazon Bedrock", bedrock: "Amazon Bedrock", openrouter: "OpenRouter", openai: "OpenAI", nvidia: "NVIDIA" }[provider] || provider || "Unknown provider");

export function aiErrorMessage(error) {
  const text = String(error?.message || error || "");
  if (/402|payment required|credits/i.test(text)) return "Provider credits exhausted. Choose another model or add provider credits.";
  if (/401|403|unauthoriz|forbidden/i.test(text)) return "Access denied. Check your sign-in and provider credentials.";
  if (/timeout|timed out/i.test(text)) return "The AI request timed out. Please try again.";
  if (/empty response/i.test(text)) return "The AI returned no answer. Please try again.";
  return "Could not complete the AI request. Please retry or choose another model.";
}

// The API streams plain text, including an in-band error marker on provider failure.
export async function streamManager(wsId, message, history, onText = () => {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60000);
  let reader;
  try {
  const res = await fetch(`${API}/workspaces/${wsId}/chat`, {
    signal: controller.signal,
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("arevei_token")}` },
    body: JSON.stringify({ message, history }),
  });
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
  reader = res.body.getReader();
  const decoder = new TextDecoder();
  let text = "";
    while (true) {
      const { value, done } = await reader.read();
      text += decoder.decode(value, { stream: !done });
      if (text.includes("[error:")) throw new Error(text.slice(text.indexOf("[error:")));
      onText(text);
      if (done) break;
    }
    if (!text.trim()) throw new Error("empty response");
    return text;
  } catch (error) {
    if (controller.signal.aborted) throw new Error("AI request timed out after 60 seconds");
    throw error;
  } finally {
    clearTimeout(timer);
    if (reader) {
      reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }
}

export function useAiStatus(ws) {
  const [model, setModel] = useState(null);
  const [state, setState] = useState("loading");
  const [detail, setDetail] = useState("");
  const [checkedAt, setCheckedAt] = useState(null);
  const version = useRef(ws.id);
  version.current = ws.id;
  const active = useRef(false);
  const requestVersion = useRef(0);
  const load = useCallback(async () => {
    const [workspace, catalog] = await Promise.all([api.get(`/workspaces/${ws.id}`, { timeout: 10000 }), api.get("/models", { timeout: 10000 })]);
    return catalog.data.models.find((m) => m.id === workspace.data.model_id) || { id: workspace.data.model_id, label: workspace.data.model_id, configured: false };
  }, [ws.id]);
  useEffect(() => {
    if (active.current) return;
    const request = requestVersion.current;
    let cancelled = false;
    if (!active.current) { setState("loading"); setCheckedAt(null); setDetail(""); }
    load().then((m) => {
      if (!cancelled && request === requestVersion.current && !active.current) { setModel(m); setState(m.configured ? "untested" : "missing"); }
    }).catch(() => {
      if (!cancelled && request === requestVersion.current && !active.current) { setState("failed"); setDetail("Cannot load AI configuration. Refresh the page."); }
    });
    return () => { cancelled = true; };
  }, [load, ws.model_id]);

  const run = async (message, history, onText) => {
    const current = version.current;
    requestVersion.current++;
    active.current = true;
    setState("checking"); setDetail("");
    try {
      const selected = await load();
      if (current === version.current) setModel(selected);
      const text = await streamManager(ws.id, message, history, onText);
      if (current === version.current) { setState("working"); setCheckedAt(new Date()); }
      return text;
    } catch (error) {
      if (current === version.current) { setState("failed"); setDetail(aiErrorMessage(error)); setCheckedAt(new Date()); }
      throw error;
    } finally {
      active.current = false;
    }
  };
  return { model, state, detail, checkedAt, run };
}

export function AiStatus({ status, busy = false }) {
  const { model, state, detail, checkedAt } = status;
  const checking = busy || state === "checking" || state === "loading";
  const failed = state === "failed" || state === "missing";
  const Icon = checking ? Loader2 : state === "working" ? CheckCircle2 : failed ? AlertCircle : Radio;
  const color = state === "working" ? "text-emerald-600" : failed ? "text-amber-600" : "text-muted-foreground";
  const label = { loading: "Loading configuration", checking: "Connecting…", working: "Last request succeeded", failed: "Request failed", missing: "Provider key needed", untested: "Configured · not tested" }[state];
  const test = async () => {
    try { await status.run("Reply with exactly AI connection working.", []); } catch { /* Rendered in status panel. */ }
  };
  return (
    <div className="mx-4 my-3 rounded-lg border border-border bg-background p-3 space-y-2" data-testid="ai-status">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Workspace AI</div>
          <div className="text-sm font-semibold break-words">{model?.label || "Loading model…"}</div>
          <div className="text-xs text-muted-foreground">{model ? providerName(model.provider) : "Reading saved selection"}</div>
        </div>
        <button type="button" onClick={test} disabled={busy || checking} title="Send a short AI request to check this workspace's connection" className="shrink-0 rounded-md border px-2 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50">Test AI</button>
      </div>
      <div role="status" aria-live="polite" className={`flex items-center gap-1.5 text-xs ${color}`}>
        <Icon className={`h-3.5 w-3.5 shrink-0 ${checking ? "animate-spin" : ""}`} /> {busy ? "Waiting for AI response (up to 60 seconds)" : label}
      </div>
      {detail && <p className="text-xs text-amber-600" role="alert">{detail}</p>}
      {checkedAt && <p className="text-[10px] text-muted-foreground">Checked at {checkedAt.toLocaleTimeString()}</p>}
    </div>
  );
}
