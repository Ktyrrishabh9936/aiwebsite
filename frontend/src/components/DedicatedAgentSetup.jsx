import { lazy, Suspense, useEffect, useRef, useState } from "react";
import api, { formatError } from "../lib/api";
import SarvamPasteSignIn from "./SarvamPasteSignIn";

const VoiceProviders = lazy(() => import("./VoiceProviders"));
const LANGUAGES = ["English", "Hindi", "Bengali", "Gujarati", "Kannada", "Konkani", "Malayalam", "Tamil", "Telugu", "Punjabi", "Odia", "Marathi", "Assamese"];
const newKey = () => (typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`);
const detail = (error) => { const d = error?.response?.data?.detail; return d && typeof d === "object" && !Array.isArray(d) ? d : null; };
const errorMessage = (error, fallback) => detail(error)?.message || (error?.response?.data?.detail != null ? formatError(error.response.data.detail) : fallback);
const agentNameFor = (business) => `${(business || "My").replace(/[^\w\- ()]/g, " ").replace(/\s+/g, " ").trim().slice(0, 34) || "My"} Lead Qualifier`;

/**
 * Connect the workspace's own Sarvam account and create a dedicated agent in it, using the existing
 * agent builder endpoints. The previous manual configuration stays available as a fallback.
 */
export default function DedicatedAgentSetup({ workspaceId, profile, configured, onConnected }) {
  const base = `/workspaces/${workspaceId}/voice-providers`;
  const [account, setAccount] = useState({ status: "loading" });
  const [connections, setConnections] = useState([]);
  const [voices, setVoices] = useState([]);
  const [keySaved, setKeySaved] = useState(false);
  const [form, setForm] = useState({ agent_name: "", connection_id: "", agent_phone_number: "", initial_language: "English", voice_id: "", api_key: "" });
  const [creationKey, setCreationKey] = useState(newKey);
  const [unsaved, setUnsaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [manual, setManual] = useState(false);
  const [pasting, setPasting] = useState(false);
  const [more, setMore] = useState(false);
  const listener = useRef(null);
  const connected = account.status === "connected";

  const loadAccount = async () => {
    try {
      const [{ data }, providers] = await Promise.all([api.get(`${base}/sarvam/account`), api.get(base).catch(() => ({ data: [] }))]);
      const sarvam = (providers.data || []).find?.((p) => p.provider === "sarvam");
      setKeySaved(Boolean(sarvam?.configured_secrets?.includes("api_key")));
      const status = data?.status === "connected" || data?.status === "expired" ? data.status : "disconnected";
      setAccount({ ...(data || {}), status });
      // AREVEI's own Sarvam workspace (or not yet known to be another one): the server key is used
      if (data?.platform_key || data?.platform_key_possible) setKeySaved(true);
      if (status !== "connected") { setConnections([]); return; }
      const { data: list } = await api.get(`${base}/sarvam/account/connections`);
      const items = Array.isArray(list?.connections) ? list.connections : [];
      setConnections(items);
      setForm((f) => {
        const item = items.find((c) => c.connection_id === f.connection_id) || items.find((c) => c.phone_numbers?.length) || items[0];
        if (!item) return f;
        return { ...f, connection_id: item.connection_id, agent_phone_number: item.phone_numbers?.includes(f.agent_phone_number) ? f.agent_phone_number : item.phone_numbers?.[0] || "" };
      });
    } catch (error) {
      setAccount({ status: "unavailable", error: errorMessage(error, "Could not reach the server. Try again.") });
    }
  };
  useEffect(() => { loadAccount(); }, [base]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { if (listener.current) window.removeEventListener("message", listener.current); }, []);
  useEffect(() => {
    if (!connected) { setVoices([]); return undefined; }
    let active = true;
    api.get(`${base}/sarvam/account/voices`, { params: { language: form.initial_language } })
      .then(({ data }) => { if (active) setVoices(Array.isArray(data?.voices) ? data.voices : []); })
      .catch(() => { if (active) setVoices([]); });
    return () => { active = false; };
  }, [connected, form.initial_language, base]);

  const connect = async () => {
    setBusy(true); setMessage("");
    try {
      const { data } = await api.post(`${base}/sarvam/account/connect`, {});
      const popup = window.open(data.authorization_url, "Sarvam Connect", "width=560,height=720");
      if (!popup) { setMessage("Allow pop-ups for this site, then connect again."); return; }
      if (data.mode === "paste") { setPasting(true); setMessage(""); return; }
      setPasting(false);
      setMessage("Finish signing in to Sarvam in the window that opened.");
      if (listener.current) window.removeEventListener("message", listener.current);
      const handle = (event) => {
        if (event.data?.type !== "SARVAM_CONNECTED" && event.data?.type !== "SARVAM_CONNECT_FAILED") return;
        window.removeEventListener("message", handle); listener.current = null;
        if (event.data.type === "SARVAM_CONNECTED") { setMessage("Sarvam account connected."); loadAccount(); }
        else setMessage("Sarvam sign-in did not complete. Try connecting again.");
      };
      listener.current = handle;
      window.addEventListener("message", handle);
    } catch (error) {
      setMessage(`Could not start Sarvam sign-in: ${errorMessage(error, "Could not reach the server.")}`);
    } finally { setBusy(false); }
  };

  const finished = async (data) => {
    setCreationKey(newKey()); setUnsaved(false); setForm((f) => ({ ...f, api_key: "" }));
    const verified = data.provider?.status === "connected";
    setMessage(`Agent "${data.creation?.agent_name}" is ${data.idempotent ? "already" : "now"} connected. ${verified ? "Connection verified." : `Connection check: ${(data.provider?.status || "unverified").replaceAll("_", " ")}. Check the API key.`}`);
    await onConnected?.();
  };

  const create = async () => {
    setBusy(true); setMessage("Creating your agent in Sarvam… this can take a minute."); setUnsaved(false);
    try {
      const payload = { creation_key: creationKey, agent_name: form.agent_name.trim() || agentNameFor(profile?.business_name),
        business_name: profile?.business_name || "", offer: profile?.business_details || "", objective: "", instructions: profile?.behaviour || "",
        connection_id: form.connection_id, agent_phone_number: form.agent_phone_number,
        initial_language: form.initial_language, supported_languages: [...new Set([form.initial_language, "English", "Hindi"])] };
      if (form.voice_id) payload.voice_id = form.voice_id;
      if (form.api_key.trim()) payload.api_key = form.api_key.trim();
      const { data } = await api.post(`${base}/sarvam/agents`, payload);
      await finished(data);
    } catch (error) {
      const code = detail(error)?.code;
      if (code === "created_unsaved") setUnsaved(true);
      if (code === "account_reconnect_required" || code === "account_not_connected") setAccount((a) => ({ ...a, status: "expired" }));
      setMessage(`Could not create the agent: ${errorMessage(error, "Could not reach the server.")}`);
    } finally { setBusy(false); }
  };

  const finishConnecting = async () => {
    setBusy(true); setMessage("Connecting the created agent…");
    try {
      const body = form.api_key.trim() ? { api_key: form.api_key.trim() } : {};
      const { data } = await api.post(`${base}/sarvam/agents/${creationKey}/connect`, body);
      await finished(data);
    } catch (error) {
      setMessage(`Could not connect the created agent: ${errorMessage(error, "Could not reach the server.")}`);
    } finally { setBusy(false); }
  };

  const numbers = connections.find((c) => c.connection_id === form.connection_id)?.phone_numbers || [];
  const connection = connections.find((c) => c.connection_id === form.connection_id);
  const needsKey = !keySaved || unsaved;
  // What was filled in automatically stays out of the way, unless something is missing and needs the user.
  const needsAttention = connected && (needsKey || !form.connection_id || !form.agent_phone_number);
  const accountText = account.status === "loading" ? "Checking…" : connected ? `Connected${account.connected_by ? ` as ${account.connected_by}` : ""}`
    : account.status === "expired" ? "Sign-in expired" : account.status === "unavailable" ? "Status unavailable" : "Not connected";
  const field = "mt-1 h-11 w-full rounded-xl border bg-background px-3.5 text-sm";
  return (
    <div className="space-y-4" aria-label="Your own agent">
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border bg-background p-4">
        <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl text-sm font-bold ${connected ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" : "bg-primary/10 text-primary"}`} aria-hidden="true">S</span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">Sarvam account</p>
          <p className="truncate text-sm text-muted-foreground">{accountText}</p>
        </div>
        <button type="button" disabled={busy || account.status === "loading"} onClick={account.status === "unavailable" ? loadAccount : connect}
          className={`inline-flex h-10 items-center rounded-xl px-4 text-sm font-semibold disabled:opacity-50 ${connected ? "border font-medium hover:bg-accent" : "bg-primary text-primary-foreground hover:bg-primary/90"}`}>
          {account.status === "unavailable" ? "Retry" : connected ? "Reconnect" : "Connect Sarvam account"}
        </button>
      </div>
      {pasting && <SarvamPasteSignIn workspaceId={workspaceId} onCancel={() => setPasting(false)}
        onConnected={async () => { setPasting(false); setMessage("Sarvam account connected."); await loadAccount(); }} />}
      {account.status === "expired" && <p className="text-xs text-muted-foreground">Sarvam sign-ins last about a day. Your existing agent keeps calling; reconnect only to create a new agent.</p>}

      {connected && (
        <div className="space-y-4 rounded-2xl border bg-background p-4 sm:p-5">
          <div>
            <p className="font-semibold">{configured ? "Create a new agent" : "Create your agent"}</p>
            <p className="text-sm text-muted-foreground">It is created with your business details and behaviour, then connected and checked automatically.</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm font-medium">Agent name in Sarvam<input className={field} maxLength={50} value={form.agent_name} placeholder={agentNameFor(profile?.business_name)} onChange={(e) => setForm({ ...form, agent_name: e.target.value })} /></label>
            <label className="text-sm font-medium">Language<select className={field} value={form.initial_language} onChange={(e) => setForm({ ...form, initial_language: e.target.value, voice_id: "" })}>{LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}</select></label>
          </div>
          {form.agent_phone_number && <p className="text-sm text-muted-foreground">Calls will come from <span className="font-semibold text-foreground">{form.agent_phone_number}</span>{connection?.name ? ` (${connection.name})` : ""}.</p>}
          <details className="rounded-xl border" open={more || needsAttention} onToggle={(e) => setMore(e.currentTarget.open)}>
            <summary className="cursor-pointer px-4 py-3 text-sm font-medium">More options{needsAttention && <span className="ml-2 text-xs font-semibold text-amber-600 dark:text-amber-400">needs your input</span>}</summary>
            <div className="grid gap-3 border-t p-4 sm:grid-cols-2">
              <label className="text-sm font-medium">Telephony connection<select className={field} value={form.connection_id} onChange={(e) => { const item = connections.find((c) => c.connection_id === e.target.value); setForm({ ...form, connection_id: e.target.value, agent_phone_number: item?.phone_numbers?.[0] || "" }); }}>
                {!connections.length && <option value="">No telephony connection in Sarvam yet</option>}
                {connections.map((c) => <option key={c.connection_id} value={c.connection_id}>{c.name}{c.provider ? ` · ${c.provider}` : ""}</option>)}
              </select></label>
              <label className="text-sm font-medium">Calling number<select className={field} value={form.agent_phone_number} onChange={(e) => setForm({ ...form, agent_phone_number: e.target.value })}>
                {!numbers.length && <option value="">No onboarded number</option>}
                {numbers.map((n) => <option key={n} value={n}>{n}</option>)}
              </select></label>
              <label className="text-sm font-medium">Voice (optional)<select className={field} value={form.voice_id} onChange={(e) => setForm({ ...form, voice_id: e.target.value })}>
                <option value="">Default voice</option>
                {voices.map((v) => <option key={v.voice_id} value={v.voice_id}>{v.name}{v.gender ? ` · ${v.gender}` : ""}</option>)}
              </select></label>
              {needsKey && <label className="text-sm font-medium">Sarvam Voice Agents API key<input type="password" autoComplete="new-password" className={field} value={form.api_key} placeholder="Used to place calls" onChange={(e) => setForm({ ...form, api_key: e.target.value })} /></label>}
            </div>
          </details>
          <button type="button" disabled={busy || !form.connection_id || !form.agent_phone_number || (!keySaved && !form.api_key.trim())} onClick={create} className="inline-flex h-11 items-center rounded-xl bg-primary px-5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
            {busy ? "Working…" : configured ? "Create a new dedicated agent" : "Create my agent"}
          </button>
        </div>
      )}
      {unsaved && <button type="button" disabled={busy} onClick={finishConnecting} className="inline-flex h-10 items-center rounded-xl border px-4 text-sm font-medium">Finish connecting</button>}
      {message && <p role="status" className="text-sm">{message}</p>}
      <details className="rounded-xl border" onToggle={(e) => { const open = e.currentTarget.open; setManual(open); if (!open) onConnected?.(); }}>
        <summary className="cursor-pointer px-4 py-3 text-sm text-muted-foreground">Advanced: set up an existing agent manually</summary>
        {manual && <div className="border-t p-4"><Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}><VoiceProviders workspaceId={workspaceId} /></Suspense></div>}
      </details>
    </div>
  );
}
