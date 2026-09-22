import { useEffect, useState } from "react";
import api, { formatError } from "../lib/api";

const fields = {
  plivo: [["auth_id", "Auth ID"], ["from_number", "Calling phone number"], ["trigger_url", "Plivo agent flow URL"], ["flow_id", "Flow ID (optional)"], ["staff_number", "Staff bridge number (optional)"]],
  sarvam: [["organization_id", "Sarvam organization ID"], ["workspace_id", "Sarvam workspace ID"], ["app_id", "Agent / App ID"], ["app_version", "Committed app version"], ["connection_id", "Telephony connection ID"], ["agent_phone_number", "Agent phone number"]],
};
const secrets = { plivo: [["auth_token", "Auth token"], ["callback_token", "Callback token (32+ characters, optional with signatures)"], ["bearer_token", "Flow bearer token (only for bearer authentication)"]], sarvam: [["api_key", "Voice Agents API key"]] };
const input = "w-full border rounded px-3 py-2 bg-background text-sm";

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
  const base = `/workspaces/${workspaceId}/voice-providers`;
  const selected = providers.find((p) => p.provider === provider);

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

  const run = async (test = false) => {
    setBusy(true); setMessage("");
    try {
      await api.put(`${base}/${provider}`, { ...draft, credentials, revision: selected?.revision });
      setCredentials({});
      const result = test ? (await api.post(`${base}/${provider}/test`, {})).data : null;
      const { data } = await api.get(base); setProviders(data);
      setProvider(data.find((item) => item.is_default)?.provider || provider);
      setMessage(result ? result.status.replaceAll("_", " ") : `${provider === "sarvam" ? "Sarvam" : "Plivo"} saved as this workspace's default voice provider.`);
    } catch (error) {
      const detail = error.response?.data?.detail;
      setMessage(typeof detail === "string" ? detail : "Could not save or verify provider configuration");
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
          <button type="button" className="border rounded px-3 py-2 text-sm mt-3" onClick={generateGuide}>Generate setup guide</button>
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
    <p className="text-sm">Status: {(selected?.status || "missing_configuration").replaceAll("_", " ")}{selected?.is_default && " · Workspace default"}{selected?.last_verified_at && ` · Checked ${new Date(selected.last_verified_at).toLocaleString()}`}</p>
    {message && <p role="status" className="text-sm">{message}</p>}
    <div className="space-y-2"><h3 className="font-semibold text-sm">Webhooks</h3><p className="text-xs text-muted-foreground">{selected?.last_callback_at ? `Last verified callback: ${new Date(selected.last_callback_at).toLocaleString()}` : "No verified callback received yet"}</p>
      {selected?.webhooks?.message && <p className="text-sm">{selected.webhooks.message}</p>}
      {selected?.webhooks?.endpoints?.map((endpoint) => <div key={endpoint.event} className="text-xs border rounded p-2 space-y-1"><p>{endpoint.method} · {endpoint.event}</p><code className="break-all">{endpoint.url}</code><button type="button" className="block underline" onClick={() => copy(endpoint.url, "Webhook URL copied")}>Copy</button></div>)}
      <p className="text-xs text-muted-foreground">{provider === "plivo" ? "Use Plivo signatures, or send your saved callback token in the X-Arevei-Webhook-Token header for qualification results." : "Callback URLs and authentication metadata are attached automatically to each outbound call."}</p>
    </div>
  </section>;
}
