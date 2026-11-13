import { lazy, Suspense, useEffect, useRef, useState } from "react";
import api, { formatError } from "../lib/api";

const VoiceProviders = lazy(() => import("./VoiceProviders"));
const input = "w-full border rounded px-3 py-2 bg-background text-sm";
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
  return (
    <div className="space-y-3" aria-label="Your own agent">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">Sarvam account: {account.status === "loading" ? "checking…" : account.status === "connected" ? `connected${account.connected_by ? ` (${account.connected_by})` : ""}` : account.status === "expired" ? "sign-in expired" : account.status === "unavailable" ? "status unavailable" : "not connected"}</p>
        <button type="button" disabled={busy || account.status === "loading"} onClick={account.status === "unavailable" ? loadAccount : connect} className="border rounded-lg px-3 py-1.5 text-sm disabled:opacity-50">
          {account.status === "unavailable" ? "Retry" : connected ? "Reconnect" : "Connect Sarvam account"}
        </button>
      </div>
      {account.status === "expired" && <p className="text-xs text-muted-foreground">Sarvam sign-ins last about a day. Your existing agent keeps calling; reconnect only to create a new agent.</p>}
      {connected && <>
        <div className="grid sm:grid-cols-2 gap-3">
          <label className="text-sm">Agent name in Sarvam<input className={input} maxLength={50} value={form.agent_name} placeholder={agentNameFor(profile?.business_name)} onChange={(e) => setForm({ ...form, agent_name: e.target.value })} /></label>
          <label className="text-sm">Language<select className={input} value={form.initial_language} onChange={(e) => setForm({ ...form, initial_language: e.target.value, voice_id: "" })}>{LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}</select></label>
          <label className="text-sm">Telephony connection<select className={input} value={form.connection_id} onChange={(e) => { const item = connections.find((c) => c.connection_id === e.target.value); setForm({ ...form, connection_id: e.target.value, agent_phone_number: item?.phone_numbers?.[0] || "" }); }}>
            {!connections.length && <option value="">No telephony connection in Sarvam yet</option>}
            {connections.map((c) => <option key={c.connection_id} value={c.connection_id}>{c.name}{c.provider ? ` · ${c.provider}` : ""}</option>)}
          </select></label>
          <label className="text-sm">Calling number<select className={input} value={form.agent_phone_number} onChange={(e) => setForm({ ...form, agent_phone_number: e.target.value })}>
            {!numbers.length && <option value="">No onboarded number</option>}
            {numbers.map((n) => <option key={n} value={n}>{n}</option>)}
          </select></label>
          <label className="text-sm">Voice (optional)<select className={input} value={form.voice_id} onChange={(e) => setForm({ ...form, voice_id: e.target.value })}>
            <option value="">Default voice</option>
            {voices.map((v) => <option key={v.voice_id} value={v.voice_id}>{v.name}{v.gender ? ` · ${v.gender}` : ""}</option>)}
          </select></label>
          {(!keySaved || unsaved) && <label className="text-sm">Sarvam Voice Agents API key<input type="password" autoComplete="new-password" className={input} value={form.api_key} placeholder="Used to place calls" onChange={(e) => setForm({ ...form, api_key: e.target.value })} /></label>}
        </div>
        <p className="text-xs text-muted-foreground">The agent is created with the business details and behaviour above, then connected and verified automatically.</p>
        <button type="button" disabled={busy || !form.connection_id || !form.agent_phone_number || (!keySaved && !form.api_key.trim())} onClick={create} className="rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm font-semibold disabled:opacity-50">
          {busy ? "Working…" : configured ? "Create a new dedicated agent" : "Create my agent"}
        </button>
      </>}
      {unsaved && <button type="button" disabled={busy} onClick={finishConnecting} className="border rounded-lg px-3 py-2 text-sm">Finish connecting</button>}
      {message && <p role="status" className="text-sm">{message}</p>}
      <details className="rounded-lg border p-3" onToggle={(e) => { const open = e.currentTarget.open; setManual(open); if (!open) onConnected?.(); }}>
        <summary className="cursor-pointer text-sm">Advanced: set up an existing agent manually</summary>
        {manual && <div className="mt-3"><Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}><VoiceProviders workspaceId={workspaceId} /></Suspense></div>}
      </details>
    </div>
  );
}
