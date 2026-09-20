import { useEffect, useState } from "react";
import api from "../lib/api";

const fields = {
  plivo: [["auth_id", "Auth ID"], ["from_number", "Calling phone number"], ["trigger_url", "Plivo agent flow URL"], ["flow_id", "Flow ID (optional)"], ["staff_number", "Staff bridge number (optional)"]],
  sarvam: [["organization_id", "Sarvam organization ID"], ["workspace_id", "Sarvam workspace ID"], ["app_id", "Agent / App ID"], ["app_version", "Published app version"], ["connection_id", "Telephony connection ID"], ["agent_phone_number", "Agent phone number"]],
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
  const base = `/workspaces/${workspaceId}/voice-providers`;
  const selected = providers.find((p) => p.provider === provider);
  useEffect(() => {
    let active = true;
    setProviders([]); setCredentials({}); setMessage("");
    api.get(base).then(({ data }) => { if (active) setProviders(data); }).catch(() => { if (active) setMessage("Could not load voice providers"); });
    return () => { active = false; };
  }, [base]);
  useEffect(() => { setDraft({ config: selected?.config || {}, enabled: selected?.enabled || false }); setCredentials({}); }, [selected, provider]);
  const run = async (test = false) => {
    setBusy(true); setMessage("");
    try {
      // Test the exact saved form; blank secrets preserve existing values.
      await api.put(`${base}/${provider}`, { ...draft, credentials, revision: selected?.revision });
      setCredentials({});
      const result = test ? (await api.post(`${base}/${provider}/test`, {})).data : null;
      const { data } = await api.get(base); setProviders(data);
      setMessage(result ? result.status.replaceAll("_", " ") : "Configuration saved. Test the connection before placing calls.");
    } catch (error) {
      const detail = error.response?.data?.detail;
      setMessage(typeof detail === "string" ? detail : "Could not save or verify provider configuration");
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
  return <section className="rounded-xl border p-5 space-y-4 bg-card" aria-label="Voice providers">
    <h2 className="font-bold text-lg">Voice Providers</h2>
    <p className="text-sm text-muted-foreground">Configure automated lead qualification calls for this workspace. Choose the provider in each qualification profile.</p>
    <fieldset disabled={busy} className="space-y-4">
      <label className="block text-sm">Provider<select className={input} value={provider} onChange={(e) => { setProvider(e.target.value); setMessage(""); }}><option value="plivo">Plivo</option><option value="sarvam">Sarvam</option></select></label>
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />Enabled</label>
      <div className="grid sm:grid-cols-2 gap-3">{fields[provider].map(([key, label]) => <label key={key} className="text-sm">{label}<input className={input} value={draft.config[key] ?? ""} onChange={(e) => setDraft({ ...draft, config: { ...draft.config, [key]: e.target.value } })} /></label>)}
        {provider === "plivo" && <label className="text-sm">Flow authentication<select className={input} value={draft.config.auth_type || "basic"} onChange={(e) => setDraft({ ...draft, config: { ...draft.config, auth_type: e.target.value } })}><option value="basic">Account credentials</option><option value="bearer">Bearer token</option></select></label>}
        {secrets[provider].filter(([key]) => key !== "bearer_token" || draft.config.auth_type === "bearer").map(([key, label]) => <label key={key} className="text-sm">{label}<input type="password" autoComplete="new-password" className={input} value={credentials[key] || ""} placeholder={selected?.configured_secrets?.includes(key) ? "Saved •••••••• — enter to replace" : "Not configured"} onChange={(e) => setCredentials({ ...credentials, [key]: e.target.value })} /></label>)}
        {provider === "sarvam" && <div className="text-sm border rounded p-3 space-y-2" aria-label="Callback Security"><p className="font-medium">Callback Security</p><p>✓ Automatically configured</p><button type="button" className="underline disabled:opacity-50" disabled={!selected?.callback_security_configured} onClick={regenerateCallbackSecurity}>Regenerate Secret</button></div>}
      </div>
      <div className="flex gap-3"><button type="button" className="border rounded px-3 py-2 text-sm" onClick={() => run()}>Save</button><button type="button" className="border rounded px-3 py-2 text-sm" onClick={() => run(true)}>Save & Test Connection</button></div>
    </fieldset>
    <p className="text-sm">Status: {(selected?.status || "missing_configuration").replaceAll("_", " ")}{selected?.last_verified_at && ` · Checked ${new Date(selected.last_verified_at).toLocaleString()}`}</p>
    {message && <p role="status" className="text-sm">{message}</p>}
    <div className="space-y-2"><h3 className="font-semibold text-sm">Webhooks</h3><p className="text-xs text-muted-foreground">{selected?.last_callback_at ? `Last verified callback: ${new Date(selected.last_callback_at).toLocaleString()}` : "No verified callback received yet"}</p>
      {selected?.webhooks?.message && <p className="text-sm">{selected.webhooks.message}</p>}
      {selected?.webhooks?.endpoints?.map((endpoint) => <div key={endpoint.event} className="text-xs border rounded p-2 space-y-1"><p>{endpoint.method} · {endpoint.event}</p><code className="break-all">{endpoint.url}</code><button type="button" className="block underline" onClick={async () => { try { await navigator.clipboard.writeText(endpoint.url); setMessage("Webhook URL copied"); } catch { setMessage("Copy unavailable. Select and copy the URL above."); } }}>Copy</button></div>)}
      <p className="text-xs text-muted-foreground">{provider === "plivo" ? "Use Plivo signatures, or send your saved callback token in the X-Arevei-Webhook-Token header for qualification results." : "Callback URLs and authentication metadata are attached automatically to each outbound call."}</p>
    </div>
  </section>;
}
