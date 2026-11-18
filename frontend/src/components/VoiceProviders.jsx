import { formatDateTime } from "../lib/timezone";
import { useEffect, useRef, useState } from "react";
import api, { formatError } from "../lib/api";
import SarvamPasteSignIn from "./SarvamPasteSignIn";

const fields = {
  plivo: [["auth_id", "Auth ID"], ["from_number", "Calling phone number"], ["trigger_url", "Plivo agent flow URL"], ["flow_id", "Flow ID (optional)"], ["staff_number", "Staff bridge number (optional)"]],
  sarvam: [["organization_id", "Sarvam organization ID"], ["workspace_id", "Sarvam workspace ID"], ["app_id", "Agent / App ID"], ["app_version", "Committed app version"], ["connection_id", "Telephony connection ID"], ["agent_phone_number", "Agent phone number"]],
};
const secrets = { plivo: [["auth_token", "Auth token"], ["callback_token", "Callback token (32+ characters, optional with signatures)"], ["bearer_token", "Flow bearer token (only for bearer authentication)"]], sarvam: [["api_key", "Voice Agents API key"]] };
const input = "w-full border rounded px-3 py-2 bg-background text-sm";
const LANGUAGES = ["English", "Hindi", "Bengali", "Gujarati", "Kannada", "Konkani", "Malayalam", "Tamil", "Telugu", "Punjabi", "Odia", "Marathi", "Assamese"];
const newCreationKey = () => (typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`);
const agentNameFor = (business) => `${(business || "AREVEI").replace(/[^\w\- ()]/g, " ").replace(/\s+/g, " ").trim().slice(0, 34) || "AREVEI"} Lead Qualifier`;
const errorDetail = (error) => { const detail = error?.response?.data?.detail; return detail && typeof detail === "object" && !Array.isArray(detail) ? detail : null; };
const errorMessage = (error, fallback) => errorDetail(error)?.message || (error?.response?.data?.detail != null ? formatError(error.response.data.detail)
  : !error?.response ? (error?.message && !error?.request ? error.message : fallback) : `The backend returned HTTP ${error.response.status}.`);
const ACCOUNT_LABELS = { connected: "connected", expired: "signed out (Sarvam ends sign-ins after 24 hours; calls keep working)", disconnected: "not connected", unavailable: "status unavailable" };

export default function VoiceProviders({ workspaceId }) {
  const [providers, setProviders] = useState([]);
  const [provider, setProvider] = useState("plivo");
  const [draft, setDraft] = useState({ config: {}, enabled: false });
  const [credentials, setCredentials] = useState({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [guideMessage, setGuideMessage] = useState("");
  const [guideForm, setGuideForm] = useState({ business_name: "", offer: "", objective: "", instructions: "" });
  const [guide, setGuide] = useState(null);
  const [account, setAccount] = useState({ status: "disconnected" });
  const [connections, setConnections] = useState([]);
  const [voices, setVoices] = useState([]);
  const [createForm, setCreateForm] = useState({ agent_name: "", connection_id: "", agent_phone_number: "", initial_language: "English", voice_id: "", api_key: "" });
  const [creationKey, setCreationKey] = useState(newCreationKey);
  const [creation, setCreation] = useState(null);
  const [createMessage, setCreateMessage] = useState("");
  const connectListener = useRef(null);
  const [pasting, setPasting] = useState(false);
  const base = `/workspaces/${workspaceId}/voice-providers`;
  const selected = providers.find((p) => p.provider === provider);
  const sarvamAccountConnected = account.status === "connected";

  const loadAccount = async () => {
    try {
      const { data } = await api.get(`${base}/sarvam/account`);
      const status = data?.status === "connected" || data?.status === "expired" ? data.status : "disconnected";
      setAccount({ ...(data || {}), status });
      if (status !== "connected") { setConnections([]); return; }
      const { data: list } = await api.get(`${base}/sarvam/account/connections`);
      const items = Array.isArray(list?.connections) ? list.connections : [];
      setConnections(items);
      setCreateForm((form) => {
        const connection = items.find((item) => item.connection_id === form.connection_id) || items[0];
        if (!connection) return form;
        const phone = connection.phone_numbers?.includes(form.agent_phone_number) ? form.agent_phone_number : connection.phone_numbers?.[0] || "";
        return { ...form, connection_id: connection.connection_id, agent_phone_number: phone };
      });
    } catch (error) {
      setAccount({ status: "unavailable", error: errorMessage(error, "The backend could not be reached.") });
      setConnections([]);
    }
  };
  useEffect(() => {
    if (provider !== "sarvam") return;
    setCreation(null); setCreateMessage("");
    loadAccount();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, base]);
  useEffect(() => {
    if (!sarvamAccountConnected) { setVoices([]); return undefined; }
    let active = true;
    api.get(`${base}/sarvam/account/voices`, { params: { language: createForm.initial_language } })
      .then(({ data }) => { if (active) setVoices(Array.isArray(data?.voices) ? data.voices : []); })
      .catch(() => { if (active) setVoices([]); });
    return () => { active = false; };
  }, [sarvamAccountConnected, createForm.initial_language, base]);
  useEffect(() => () => { if (connectListener.current) window.removeEventListener("message", connectListener.current); }, []);

  useEffect(() => {
    let active = true;
    setProviders([]); setCredentials({}); setMessage("");
    api.get(base).then(({ data }) => {
      if (!active) return;
      setProviders(data);
      setProvider(data.find((item) => item.is_default)?.provider || "plivo");
    }).catch(() => { if (active) setMessage("Could not load voice providers"); });
    return () => { active = false; };
  }, [base]);
  useEffect(() => {
    const config = { ...(selected?.config || {}) };
    if (provider === "sarvam" && selected?.status === "missing_configuration") config.payload_mode = "lead_context_v1";
    setDraft({ config, enabled: selected?.enabled || false }); setCredentials({}); setGuide(null); setGuideMessage("");
  }, [selected, provider]);

  const run = async (test = false, recover = false) => {
    setBusy(true); setMessage("");
    let stage = "save";
    try {
      const recoveryRequested = recover || (provider === "sarvam" && !!credentials.api_key?.trim());
      const payload = { ...draft, credentials, revision: selected?.revision, ...(recoveryRequested ? { recover_credentials: true } : {}) };
      let saved;
      try {
        ({ data: saved } = await api.put(`${base}/${provider}`, payload));
      } catch (error) {
        const detail = error.response?.data?.detail;
        const unsupportedRecovery = error.response?.status === 422 && Array.isArray(detail) && detail.length === 1
          && detail[0].type === "extra_forbidden"
          && JSON.stringify(detail[0].loc) === JSON.stringify(["body", "recover_credentials"]);
        if (!recoveryRequested || !unsupportedRecovery) throw error;
        if (recover) throw new Error("This backend does not support credential recovery. Deploy the updated backend, then reconnect.");
        const { recover_credentials, ...compatiblePayload } = payload;
        ({ data: saved } = await api.put(`${base}/${provider}`, compatiblePayload));
      }
      setProviders((items) => items.map((item) => item.provider === provider
        ? { ...item, ...saved } : { ...item, is_default: false }));
      setCredentials({});
      stage = "test";
      const result = test ? (await api.post(`${base}/${provider}/test`, {})).data : null;
      if (result) setProviders((items) => items.map((item) => item.provider === provider ? { ...item, ...result } : item));
      stage = "refresh";
      const { data } = await api.get(base); setProviders(data);
      setProvider(data.find((item) => item.is_default)?.provider || provider);
      setMessage(result ? result.status.replaceAll("_", " ") : `${provider === "sarvam" ? "Sarvam" : "Plivo"} saved as this workspace's default voice provider.`);
    } catch (error) {
      const detail = error.response?.data?.detail;
      const prefix = stage === "save" ? "Could not save provider configuration"
        : stage === "test" ? "Configuration saved, but connection verification failed"
        : "Configuration saved, but provider details could not be refreshed";
      const reason = detail != null ? formatError(detail)
        : !error.response ? (error.message && !error.request ? error.message : "The backend could not be reached. Check the connection and the backend's CORS settings.")
        : `The backend returned HTTP ${error.response.status}.`;
      setMessage(`${prefix}: ${reason}`);
    } finally { setBusy(false); }
  };

  const generateGuide = async () => {
    setBusy(true); setMessage(""); setGuideMessage("Creating your setup guide…");
    try {
      const { data } = await api.post(`${base}/sarvam/setup-guide`, guideForm);
      setGuide(data);
      setGuideMessage("Setup guide ready. Create and commit the agent in Sarvam, then connect it below.");
    } catch (error) {
      const detail = error.response?.data?.detail;
      const errorMessage = detail ? formatError(detail) : error.response?.status === 404
        ? "The setup-guide API is not available on the running backend. Restart or deploy the updated backend and try again."
        : "Could not create the setup guide. Check the backend connection and try again.";
      setGuideMessage(errorMessage);
    } finally { setBusy(false); }
  };

  const copy = async (value, success) => {
    try { await navigator.clipboard.writeText(value); setMessage(success); }
    catch { setMessage("Copy unavailable. Select and copy the text manually."); }
  };

  const connectAccount = async () => {
    setBusy(true); setCreateMessage("");
    try {
      const { data } = await api.post(`${base}/sarvam/account/connect`, {});
      const popup = window.open(data.authorization_url, "Sarvam Connect", "width=560,height=720");
      if (!popup) { setCreateMessage("Allow pop-ups for this site, then connect again."); return; }
      if (data.mode === "paste") { setPasting(true); setCreateMessage(""); return; }
      setPasting(false);
      setCreateMessage("Finish signing in to Sarvam in the window that opened.");
      if (connectListener.current) window.removeEventListener("message", connectListener.current);
      const listener = (event) => {
        if (event.data?.type !== "SARVAM_CONNECTED" && event.data?.type !== "SARVAM_CONNECT_FAILED") return;
        window.removeEventListener("message", listener); connectListener.current = null;
        if (event.data.type === "SARVAM_CONNECTED") { setCreateMessage("Sarvam account connected."); loadAccount(); }
        else setCreateMessage("Sarvam sign-in did not complete. Try connecting again.");
      };
      connectListener.current = listener;
      window.addEventListener("message", listener);
    } catch (error) {
      setCreateMessage(`Could not start Sarvam sign-in: ${errorMessage(error, "The backend could not be reached.")}`);
    } finally { setBusy(false); }
  };

  const disconnectAccount = async () => {
    setBusy(true); setCreateMessage("");
    try { await api.delete(`${base}/sarvam/account`); setAccount({ status: "disconnected" }); setConnections([]); setCreateMessage("Sarvam account disconnected. Existing agents keep working."); }
    catch (error) { setCreateMessage(`Could not disconnect: ${errorMessage(error, "The backend could not be reached.")}`); }
    finally { setBusy(false); }
  };

  const applyCreation = async (data, verb) => {
    setCreation(data.creation);
    if (data.provider) setProviders((items) => items.map((item) => item.provider === "sarvam" ? { ...item, ...data.provider } : { ...item, is_default: false }));
    setCreateForm((form) => ({ ...form, api_key: "" }));
    setCreationKey(newCreationKey());
    try { const { data: list } = await api.get(base); if (Array.isArray(list)) setProviders(list); } catch { /* provider details refresh is best effort */ }
    const verification = data.provider?.status === "connected" ? "Connection verified; calls can start now."
      : `Connection check: ${(data.provider?.status || "unverified").replaceAll("_", " ")}. Check the Voice Agents API key, then use Save & Test Connection.`;
    setCreateMessage(`Agent "${data.creation?.agent_name}" ${verb} in Sarvam (version ${data.creation?.app_version}) and connected to this workspace. ${verification}`);
  };

  const createAgent = async () => {
    setBusy(true); setCreateMessage("Creating the agent in Sarvam…"); setCreation(null);
    try {
      const languages = [...new Set([createForm.initial_language, "English", "Hindi"])];
      const payload = { creation_key: creationKey, agent_name: createForm.agent_name.trim() || agentNameFor(guideForm.business_name),
        business_name: guideForm.business_name, offer: guideForm.offer, objective: guideForm.objective, instructions: guideForm.instructions,
        connection_id: createForm.connection_id, agent_phone_number: createForm.agent_phone_number,
        initial_language: createForm.initial_language, supported_languages: languages, revision: selected?.revision };
      if (createForm.voice_id) payload.voice_id = createForm.voice_id;
      if (createForm.api_key.trim()) payload.api_key = createForm.api_key.trim();
      const { data } = await api.post(`${base}/sarvam/agents`, payload);
      await applyCreation(data, data.idempotent ? "already existed" : "created");
    } catch (error) {
      const code = errorDetail(error)?.code;
      if (code === "created_unsaved") setCreation({ status: "created_unsaved" });
      if (code === "account_reconnect_required" || code === "account_not_connected") setAccount((current) => ({ ...current, status: "expired" }));
      setCreateMessage(`Could not create the agent: ${errorMessage(error, "The backend could not be reached.")}`);
    } finally { setBusy(false); }
  };

  const finishConnecting = async () => {
    setBusy(true); setCreateMessage("Connecting the created agent…");
    try {
      const body = { revision: selected?.revision };
      if (createForm.api_key.trim()) body.api_key = createForm.api_key.trim();
      const { data } = await api.post(`${base}/sarvam/agents/${creationKey}/connect`, body);
      await applyCreation(data, "exists");
    } catch (error) {
      setCreateMessage(`Could not connect the created agent: ${errorMessage(error, "The backend could not be reached.")}`);
    } finally { setBusy(false); }
  };

  const regenerateCallbackSecurity = async () => {
    setBusy(true); setMessage("");
    try {
      await api.post(`${base}/sarvam/callback-secret/regenerate`, { revision: selected?.revision });
      const { data } = await api.get(base); setProviders(data);
      setMessage("Callback security regenerated. Existing calls remain valid.");
    } catch (error) {
      const detail = error.response?.data?.detail;
      setMessage(typeof detail === "string" ? detail : "Could not regenerate callback security");
    } finally { setBusy(false); }
  };

  const sarvamMode = draft.config.payload_mode || "legacy";
  return <section className="rounded-xl border p-5 space-y-4 bg-card" aria-label="Voice providers">
    <h2 className="font-bold text-lg">Voice Providers</h2>
    <p className="text-sm text-muted-foreground">Configure automated lead qualification calls for this workspace.</p>
    <fieldset disabled={busy} className="space-y-4">
      <label className="block text-sm">Provider<select className={input} value={provider} onChange={(e) => { setProvider(e.target.value); setMessage(""); }}><option value="plivo">Plivo</option><option value="sarvam">Sarvam</option></select></label>
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />Enabled</label>

      {provider === "sarvam" && <>
        <label className="block text-sm">Agent input mode
          <select aria-label="Agent input mode" className={input} value={sarvamMode} onChange={(e) => setDraft({ ...draft, config: { ...draft.config, payload_mode: e.target.value } })}>
            <option value="lead_context_v1">Lead context (recommended)</option>
            <option value="legacy">Existing agent (legacy variables)</option>
          </select>
        </label>
        <p className="text-xs text-muted-foreground">{sarvamMode === "lead_context_v1" ? "AREVEI sends lead_name, lead_phone, and a dynamic lead_context to every call." : "Keeps the original variables expected by your current working agent."}</p>
        <details className="border rounded-lg p-3 space-y-3">
          <summary className="font-medium text-sm cursor-pointer">Set up a new Sarvam agent</summary>
          <p className="text-xs text-muted-foreground mt-3">Add the business details once. AREVEI will create the prompt and exact variable checklist.</p>
          <div className="grid sm:grid-cols-2 gap-3 mt-3">
            <label className="text-sm">Business name<input className={input} value={guideForm.business_name} onChange={(e) => setGuideForm({ ...guideForm, business_name: e.target.value })} placeholder="Uses workspace name if blank" /></label>
            <label className="text-sm">Product or service<input className={input} value={guideForm.offer} onChange={(e) => setGuideForm({ ...guideForm, offer: e.target.value })} placeholder="Uses qualification profile if blank" /></label>
            <label className="text-sm sm:col-span-2">Call objective<input className={input} value={guideForm.objective} onChange={(e) => setGuideForm({ ...guideForm, objective: e.target.value })} placeholder="Qualify the lead and agree on the next step" /></label>
            <label className="text-sm sm:col-span-2">Additional instructions<textarea className={input} rows="3" value={guideForm.instructions} onChange={(e) => setGuideForm({ ...guideForm, instructions: e.target.value })} placeholder="Optional policies, tone, language, or handoff rules" /></label>
          </div>
          <div className="border rounded p-3 space-y-3 mt-3" aria-label="Sarvam account">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium">Sarvam account: {ACCOUNT_LABELS[account.status] || account.status}{account.connected_by ? ` (${account.connected_by})` : ""}</p>
              {sarvamAccountConnected
                ? <button type="button" className="underline text-xs" onClick={disconnectAccount}>Disconnect</button>
                : <button type="button" className="border rounded px-3 py-2 text-sm" onClick={connectAccount}>Connect Sarvam account</button>}
            </div>
            {pasting && !sarvamAccountConnected && <SarvamPasteSignIn workspaceId={workspaceId} onCancel={() => setPasting(false)}
              onConnected={async () => { setPasting(false); setCreateMessage("Sarvam account connected."); await loadAccount(); }} />}
            {sarvamAccountConnected ? <>
              <p className="text-xs text-muted-foreground">AREVEI creates the agent with your business details above, configures the lead-context inputs and qualification outputs, commits a version and connects it here.</p>
              <div className="grid sm:grid-cols-2 gap-3">
                <label className="text-sm">Agent name<input className={input} maxLength="50" value={createForm.agent_name} placeholder={agentNameFor(guideForm.business_name)} onChange={(e) => setCreateForm({ ...createForm, agent_name: e.target.value })} /></label>
                <label className="text-sm">Language<select aria-label="Agent language" className={input} value={createForm.initial_language} onChange={(e) => setCreateForm({ ...createForm, initial_language: e.target.value, voice_id: "" })}>{LANGUAGES.map((name) => <option key={name} value={name}>{name}</option>)}</select></label>
                <label className="text-sm">Telephony connection<select aria-label="Telephony connection" className={input} value={createForm.connection_id} onChange={(e) => { const item = connections.find((c) => c.connection_id === e.target.value); setCreateForm({ ...createForm, connection_id: e.target.value, agent_phone_number: item?.phone_numbers?.[0] || "" }); }}>
                  {connections.length === 0 && <option value="">No telephony connection in Sarvam yet</option>}
                  {connections.map((item) => <option key={item.connection_id} value={item.connection_id}>{item.name}{item.provider ? ` · ${item.provider}` : ""}</option>)}
                </select></label>
                <label className="text-sm">Agent phone number<select aria-label="Agent phone number" className={input} value={createForm.agent_phone_number} onChange={(e) => setCreateForm({ ...createForm, agent_phone_number: e.target.value })}>
                  {(connections.find((c) => c.connection_id === createForm.connection_id)?.phone_numbers || []).map((phone) => <option key={phone} value={phone}>{phone}</option>)}
                  {!(connections.find((c) => c.connection_id === createForm.connection_id)?.phone_numbers || []).length && <option value="">No onboarded number</option>}
                </select></label>
                <label className="text-sm">Voice (optional)<select aria-label="Agent voice" className={input} value={createForm.voice_id} onChange={(e) => setCreateForm({ ...createForm, voice_id: e.target.value })}>
                  <option value="">Sarvam default voice</option>
                  {voices.map((voice) => <option key={voice.voice_id} value={voice.voice_id}>{voice.name}{voice.gender ? ` · ${voice.gender}` : ""}</option>)}
                </select></label>
                {!selected?.configured_secrets?.includes("api_key") && <label className="text-sm">Voice Agents API key<input type="password" autoComplete="new-password" className={input} value={createForm.api_key} placeholder="Required for placing calls" onChange={(e) => setCreateForm({ ...createForm, api_key: e.target.value })} /></label>}
              </div>
              <button type="button" className="rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm disabled:opacity-50" disabled={busy || !createForm.connection_id || !createForm.agent_phone_number} onClick={createAgent}>Create agent in Sarvam</button>
            </> : <p className="text-xs text-muted-foreground">{account.error || "Connect the Sarvam account that owns your voice agents. AREVEI then creates and connects the agent for you; the manual guide below remains available."}</p>}
            {createMessage && <p role="status" className="text-sm">{createMessage}</p>}
            {creation?.status === "created_unsaved" && <button type="button" className="border rounded px-3 py-2 text-sm" onClick={finishConnecting}>Finish connecting</button>}
          </div>
          <p className="text-xs text-muted-foreground mt-3">Manual alternative: generate a prompt for Sarvam's AI agent builder.</p>
          <button type="button" className="border rounded px-3 py-2 text-sm mt-1" onClick={generateGuide}>Generate setup guide</button>
          {guideMessage && <p role="status" className="text-sm mt-2">{guideMessage}</p>}
          {guide && <div className="space-y-3 mt-4" aria-label="Sarvam setup guide">
            <div><p className="text-sm font-medium">Inputs Sarvam AI will configure</p><div className="flex flex-wrap gap-2 mt-1">{guide.variables.map((item) => <code key={item.name} className="border rounded px-2 py-1 text-xs">{item.name}</code>)}</div><p className="text-xs text-muted-foreground mt-1">Your existing qualification output variables will remain unchanged.</p></div>
            <div><div className="flex items-center justify-between"><p className="text-sm font-medium">Sarvam AI setup prompt</p><button type="button" className="underline text-xs" onClick={() => copy(guide.prompt, "Sarvam setup prompt copied")}>Copy setup prompt</button></div><textarea readOnly aria-label="Generated Sarvam agent prompt" className={`${input} mt-1 font-mono`} rows="12" value={guide.prompt} /></div>
            <ol className="list-decimal pl-5 text-xs space-y-1">{guide.steps.map((step) => <li key={step}>{step}</li>)}</ol>
            {guide.output_prompt && <details className="border rounded p-3">
              <summary className="font-medium text-sm cursor-pointer">Creating a fresh agent? Add qualification outputs</summary>
              <p className="text-xs text-muted-foreground mt-2">Paste this separately into Sarvam's AI builder after the main setup prompt. Existing working agents do not need it.</p>
              <div className="flex items-center justify-between mt-3"><p className="text-sm font-medium">Output-variable setup prompt</p><button type="button" className="underline text-xs" onClick={() => copy(guide.output_prompt, "Output-variable setup prompt copied")}>Copy output prompt</button></div>
              <textarea readOnly aria-label="Generated Sarvam output variable prompt" className={`${input} mt-1 font-mono`} rows="12" value={guide.output_prompt} />
              <p className="text-sm font-medium mt-3">Outputs Sarvam AI will configure</p>
              <div className="grid sm:grid-cols-2 gap-1 mt-1">{guide.output_variables?.map((item) => <code key={item.name} className="border rounded px-2 py-1 text-xs">{item.name} · {item.type}</code>)}</div>
              <ol className="list-decimal pl-5 text-xs space-y-1 mt-3">{guide.fresh_agent_steps?.map((step) => <li key={step}>{step}</li>)}</ol>
            </details>}
          </div>}
        </details>
      </>}

      <details open className="border rounded-lg p-3">
        <summary className="font-medium text-sm cursor-pointer">{provider === "sarvam" ? "Connect committed agent" : "Provider connection"}</summary>
        <div className="grid sm:grid-cols-2 gap-3 mt-3">{fields[provider].map(([key, label]) => <label key={key} className="text-sm">{label}<input className={input} value={draft.config[key] ?? ""} onChange={(e) => setDraft({ ...draft, config: { ...draft.config, [key]: e.target.value } })} /></label>)}
          {provider === "plivo" && <label className="text-sm">Flow authentication<select className={input} value={draft.config.auth_type || "basic"} onChange={(e) => setDraft({ ...draft, config: { ...draft.config, auth_type: e.target.value } })}><option value="basic">Account credentials</option><option value="bearer">Bearer token</option></select></label>}
          {secrets[provider].filter(([key]) => key !== "bearer_token" || draft.config.auth_type === "bearer").map(([key, label]) => <label key={key} className="text-sm">{label}<input type="password" autoComplete="new-password" className={input} value={credentials[key] || ""} placeholder={selected?.configured_secrets?.includes(key) ? "Saved •••••••• — enter to replace" : "Not configured"} onChange={(e) => setCredentials({ ...credentials, [key]: e.target.value })} /></label>)}
          {provider === "sarvam" && <div className="text-sm border rounded p-3 space-y-2" aria-label="Callback Security"><p className="font-medium">Callback Security</p><p>✓ Automatically configured</p><button type="button" className="underline disabled:opacity-50" disabled={!selected?.callback_security_configured} onClick={regenerateCallbackSecurity}>Regenerate Secret</button></div>}
        </div>
      </details>
      <div className="flex gap-3"><button type="button" className="border rounded px-3 py-2 text-sm" onClick={() => run()}>Save</button><button type="button" className="border rounded px-3 py-2 text-sm" onClick={() => run(true)}>Save & Test Connection</button></div>
    </fieldset>
    <p className="text-sm">Status: {(selected?.status || "missing_configuration").replaceAll("_", " ")}{selected?.is_default && " · Workspace default"}{selected?.last_verified_at && ` · Checked ${formatDateTime(selected.last_verified_at)}`}</p>
    {message && <p role="status" className="text-sm">{message}</p>}
    {provider === "sarvam" && message.includes("cannot be decrypted") && <div className="border rounded-lg p-4 space-y-3"><p className="text-sm">The saved API key is unreadable. Enter your Sarvam Voice Agents API key above, then reconnect. Agent settings are preserved. Callback security will be regenerated; update the callback URL in Sarvam using the refreshed webhook details below.</p><button type="button" disabled={busy || !credentials.api_key?.trim()} className="rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm disabled:opacity-50" onClick={() => run(true, true)}>Reconnect Sarvam</button></div>}
    <div className="space-y-2"><h3 className="font-semibold text-sm">Webhooks</h3><p className="text-xs text-muted-foreground">{selected?.last_callback_at ? `Last verified callback: ${formatDateTime(selected.last_callback_at)}` : "No verified callback received yet"}</p>
      {selected?.webhooks?.message && <p className="text-sm">{selected.webhooks.message}</p>}
      {selected?.webhooks?.endpoints?.map((endpoint) => <div key={endpoint.event} className="text-xs border rounded p-2 space-y-1"><p>{endpoint.method} · {endpoint.event}</p><code className="break-all">{endpoint.url}</code><button type="button" className="block underline" onClick={() => copy(endpoint.url, "Webhook URL copied")}>Copy</button></div>)}
      <p className="text-xs text-muted-foreground">{provider === "plivo" ? "Use Plivo signatures, or send your saved callback token in the X-Arevei-Webhook-Token header for qualification results." : "Callback URLs and authentication metadata are attached automatically to each outbound call."}</p>
    </div>
  </section>;
}
