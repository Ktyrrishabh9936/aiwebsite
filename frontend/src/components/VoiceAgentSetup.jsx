import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PhoneCall, Sparkles } from "lucide-react";
import api, { formatError } from "../lib/api";
import DedicatedAgentSetup from "./DedicatedAgentSetup";
import InboundCallsSetup from "./InboundCallsSetup";
import VoiceAgentDetails from "./VoiceAgentDetails";

const input = "w-full border rounded px-3 py-2 bg-background text-sm";
const errorMessage = (error, fallback) => {
  const detail = error?.response?.data?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail) && detail.message) return detail.message;
  return detail != null ? formatError(detail) : fallback;
};
const formatDate = (iso) => { try { return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }); } catch { return ""; } };

/** True when the workspace's selected voice agent can place calls right now. */
export const canCall = (state) => Boolean(state?.active_type && state.calling_enabled
  && (state.active_type !== "master" || state.trial?.status === "active"));

/** Loads the workspace voice agent; shared by the setup card, the banner and the CRM. */
export function useVoiceAgent(workspaceId) {
  const [state, setState] = useState({ loading: true });
  const reload = () => api.get(`/workspaces/${workspaceId}/voice-agent`)
    .then(({ data }) => setState({ loading: false, ...data }))
    .catch(() => setState({ loading: false, error: true }));
  useEffect(() => { if (workspaceId) reload(); }, [workspaceId]); // eslint-disable-line react-hooks/exhaustive-deps
  return [state, reload, setState];
}

/** Recommends setting up the AI voice agent until the workspace has one, and flags an ended trial. */
export function VoiceAgentBanner({ workspaceId }) {
  const [state] = useVoiceAgent(workspaceId);
  const ended = state.active_type === "master" && state.trial?.status === "expired";
  const key = `voice-agent-banner-dismissed:${workspaceId}:${ended ? "ended" : "setup"}`;
  const [dismissed, setDismissed] = useState(() => { try { return localStorage.getItem(key) === "1"; } catch { return false; } });
  if (state.loading || state.error || dismissed || (state.active_type && !ended)) return null;
  const dismiss = () => { try { localStorage.setItem(key, "1"); } catch { /* storage unavailable */ } setDismissed(true); };
  const trialOpen = state.trial?.status === "available";
  return (
    <div role="note" className="flex flex-col gap-3 rounded-xl border border-primary/30 bg-primary/5 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary"><PhoneCall className="h-4 w-4" /></span>
        <div>
          <p className="text-sm font-semibold">{ended ? "Your free voice agent trial has ended" : "Set up your AI voice agent"}</p>
          <p className="text-sm text-muted-foreground">{ended ? "Your settings and call history are kept. Connect your own agent to keep calling new leads."
            : `It calls every new lead within minutes, qualifies them and updates the CRM.${trialOpen ? ` Try it free for ${state.trial.days} days.` : ""}`}</p>
        </div>
      </div>
      <div className="flex shrink-0 gap-2">
        <button type="button" onClick={dismiss} className="rounded-lg px-3 py-2 text-sm text-muted-foreground hover:bg-accent">Later</button>
        <Link to={`/app/w/${workspaceId}/settings#voice`} className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90">{ended ? "Connect agent" : "Set up agent"}</Link>
      </div>
    </div>
  );
}

function StatusChip({ state }) {
  const { active_type: type, calling_enabled: on, trial } = state;
  const [text, tone] = !type ? ["Not set up", "bg-muted text-muted-foreground"]
    : type === "master" && trial?.status === "expired" ? ["Trial ended", "bg-destructive/10 text-destructive"]
    : !on ? ["Paused", "bg-amber-500/10 text-amber-700 dark:text-amber-400"]
    : type === "master" ? [`Free trial · ${trial.days_left} day${trial.days_left === 1 ? "" : "s"} left`, "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"]
    : ["Your own agent · active", "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"];
  return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${tone}`}>{text}</span>;
}

/** The workspace's AI voice agent: a 14-day free trial agent or the workspace's own dedicated agent. */
export default function VoiceAgentSetup({ workspaceId, onSaved }) {
  const [state, reload, setState] = useVoiceAgent(workspaceId);
  const [form, setForm] = useState(null);
  const [choice, setChoice] = useState("");
  const [showOwn, setShowOwn] = useState(false);
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (state.loading || state.error) return;
    const p = state.profile || {};
    setForm({ agent_name: p.agent_name || state.defaults?.agent_name || "", business_name: p.business_name || state.defaults?.business_name || "",
      business_details: p.business_details || "", behaviour: p.behaviour || "" });
  }, [state.loading, state.error, state.profile, state.defaults]);

  if (state.loading || (!state.error && !form)) return <section className="border rounded-md bg-card p-6 text-sm text-muted-foreground">Loading voice agent…</section>;
  if (state.error) {
    return (
      <section className="border rounded-md bg-card p-6 space-y-2">
        <h2 className="font-display text-xl font-bold">AI Voice Agent</h2>
        <p className="text-sm text-muted-foreground">Could not load your voice agent.</p>
        <button type="button" onClick={() => { setState({ loading: true }); reload(); }} className="border rounded-lg px-3 py-1.5 text-sm">Retry</button>
      </section>
    );
  }

  const { active_type: type, trial, dedicated } = state;
  const trialActive = trial?.status === "active";
  const valid = form.agent_name.trim() && form.business_name.trim();
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const act = async (name, request, success) => {
    setBusy(name); setMessage("");
    try {
      const { data } = await request();
      if (data && "active_type" in data) setState({ loading: false, ...data }); else await reload();
      setMessage(success); setConfirm(null); setChoice(""); onSaved?.();
      return true;
    } catch (error) {
      setMessage(errorMessage(error, "Something went wrong. Try again."));
      return false;
    } finally { setBusy(""); }
  };
  const base = `/workspaces/${workspaceId}/voice-agent`;
  const saveProfile = () => act("save", () => api.put(base, form), "Saved. The next call uses these settings.");
  const startTrial = () => act("trial", () => api.post(`${base}/trial`, form), `Your free trial has started. New leads will be called automatically for ${trial.days} days.`);
  const setCalling = (enabled) => act("calling", () => api.post(`${base}/calling`, { enabled }), enabled ? "Calling resumed." : "Calling paused.");
  const switchTo = (agentType) => act("switch", () => api.post(`${base}/switch`, { agent_type: agentType }),
    agentType === "master" ? "The free-trial agent now handles new calls." : "Your own agent now handles new calls.");
  const ownConnected = async () => {
    // Keep the details used to create the agent as the workspace profile.
    if (form.agent_name.trim() && form.business_name.trim()) await api.put(`/workspaces/${workspaceId}/voice-agent`, form).catch(() => {});
    await reload(); setShowOwn(false); onSaved?.();
  };
  const generate = async () => {
    setBusy("generate"); setMessage("");
    try {
      const { data } = await api.post(`${base}/generate`, { business_name: form.business_name, notes: form.business_details });
      setForm((f) => ({ ...f, business_details: data.business_details || f.business_details, behaviour: f.behaviour.trim() ? f.behaviour : (data.behaviour || "") }));
      setMessage(data.business_details ? "Draft ready. Review and edit it before saving." : "Add your business profile in Brain first, or write the details here.");
    } catch (error) {
      setMessage(errorMessage(error, "Could not generate details. Try again."));
    } finally { setBusy(""); }
  };

  const profileFields = (
    <>
      <div className="grid sm:grid-cols-2 gap-3">
        <label className="text-sm">Agent name<input className={input} maxLength={50} value={form.agent_name} onChange={set("agent_name")} placeholder="e.g. Priya" /><span className="text-xs text-muted-foreground">The name your agent introduces itself with.</span></label>
        <label className="text-sm">Business name<input className={input} maxLength={120} value={form.business_name} onChange={set("business_name")} /></label>
      </div>
      <label className="block text-sm">
        <span className="flex items-center justify-between gap-2">Business details
          <button type="button" onClick={generate} disabled={!!busy} className="inline-flex items-center gap-1 text-xs text-primary disabled:opacity-50"><Sparkles className="h-3.5 w-3.5" />{busy === "generate" ? "Generating…" : "Generate with AI"}</button>
        </span>
        <textarea className={`${input} mt-1`} rows={5} maxLength={3000} value={form.business_details} onChange={set("business_details")} placeholder="What you sell, who you serve, locations, key facts callers ask about." />
      </label>
      <label className="block text-sm">Agent behaviour
        <textarea className={`${input} mt-1`} rows={5} maxLength={3000} value={form.behaviour} onChange={set("behaviour")} placeholder="Tone, the questions to ask, what counts as a qualified lead, and the next step to agree on (e.g. book a site visit)." />
      </label>
    </>
  );
  const confirmBox = confirm && (
    <div role="alertdialog" aria-label="Confirm change" className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 space-y-2">
      <p className="text-sm">{confirm.text}</p>
      <div className="flex gap-2">
        <button type="button" disabled={!!busy} onClick={confirm.run} className="rounded-lg bg-primary text-primary-foreground px-3 py-1.5 text-sm font-semibold disabled:opacity-50">{busy ? "Working…" : confirm.label}</button>
        <button type="button" disabled={!!busy} onClick={() => setConfirm(null)} className="rounded-lg border px-3 py-1.5 text-sm">Cancel</button>
      </div>
    </div>
  );
  const askSwitch = (agentType) => setConfirm({
    label: "Switch", run: () => switchTo(agentType),
    text: agentType === "master" ? "New calls will be placed by the free-trial agent instead of your own agent. Your own agent stays connected and you can switch back any time."
      : "New calls will be placed by your own agent instead of the free-trial agent. Your trial settings are kept. Calls already in progress are not affected.",
  });
  const askTrialFromOwn = () => setConfirm({
    label: "Start trial", run: startTrial,
    text: `This starts your one-time ${trial.days}-day free trial and makes the trial agent handle new calls. Your own agent stays connected and you can switch back any time.`,
  });

  return (
    <section className="rounded-2xl border bg-card p-4 sm:p-6 space-y-5" aria-label="AI voice agent">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="font-display text-xl font-bold">AI Voice Agent</h2>
          <p className="text-sm text-muted-foreground mt-1">Your agent calls new leads, qualifies them and updates the CRM.</p>
        </div>
        <StatusChip state={state} />
      </div>

      {!type && <>
        <div className="grid gap-3 sm:grid-cols-2">
          <button type="button" aria-pressed={choice === "trial"} disabled={trial?.status !== "available"} onClick={() => { setChoice("trial"); setMessage(""); }}
            className={`rounded-xl border p-4 text-left transition disabled:opacity-60 ${choice === "trial" ? "ring-2 ring-primary/40 border-primary" : "hover:bg-accent/40"}`}>
            <span className="block font-semibold">Start {trial?.days || 14}-day free trial</span>
            <span className="mt-1 block text-sm text-muted-foreground">{trial?.status === "expired" ? `Your free trial ended on ${formatDate(trial.expires_at)}.`
              : trial?.status === "unavailable" ? "The free trial isn't available right now."
              : "Ready-to-use agent. No accounts or keys needed. Just tell it about your business."}</span>
          </button>
          <button type="button" aria-pressed={choice === "dedicated"} onClick={() => { setChoice("dedicated"); setMessage(""); }}
            className={`rounded-xl border p-4 text-left transition ${choice === "dedicated" ? "ring-2 ring-primary/40 border-primary" : "hover:bg-accent/40"}`}>
            <span className="block font-semibold">Connect your own agent</span>
            <span className="mt-1 block text-sm text-muted-foreground">Use your own Sarvam account, telephony connection and number for a dedicated agent.</span>
          </button>
        </div>
        {choice && profileFields}
        {choice === "trial" && <>
          <p className="text-xs text-muted-foreground">The trial runs for {trial.days} days from today{trial.calling_number ? ` and calls come from ${trial.calling_number}` : ""}. Editing your agent later never restarts it.</p>
          <button type="button" disabled={!!busy || !valid} onClick={startTrial} className="rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm font-semibold disabled:opacity-50">{busy === "trial" ? "Starting…" : `Start ${trial.days}-day free trial`}</button>
        </>}
        {choice === "dedicated" && <>
          <DedicatedAgentSetup workspaceId={workspaceId} profile={form} configured={dedicated?.configured} onConnected={ownConnected} />
        </>}
      </>}

      {type === "master" && <>
        {trial.status === "expired"
          ? <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">Your free trial ended on {formatDate(trial.expires_at)}. Trial calls have stopped; your settings and call history are kept. Connect your own agent to keep calling.</div>
          : <p className="text-sm text-muted-foreground">Free trial ends on {formatDate(trial.expires_at)}.{trial.calling_number ? ` Calls come from ${trial.calling_number}.` : ""}</p>}
        {profileFields}
        <p className="text-xs text-muted-foreground">Changes apply from the next call.</p>
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={!!busy || !valid} onClick={saveProfile} className="rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm font-semibold disabled:opacity-50">{busy === "save" ? "Saving…" : "Save changes"}</button>
          {trialActive && (state.calling_enabled
            ? <button type="button" disabled={!!busy} onClick={() => setCalling(false)} className="rounded-lg border px-4 py-2 text-sm disabled:opacity-50">Pause calling</button>
            : <button type="button" disabled={!!busy} onClick={() => setCalling(true)} className="rounded-lg border px-4 py-2 text-sm disabled:opacity-50">Resume calling</button>)}
        </div>
        <div className="border-t pt-4 space-y-3">
          <p className="text-sm font-semibold">Your own agent</p>
          {dedicated?.configured
            ? <><p className="text-sm text-muted-foreground">{dedicated.agent_name ? `"${dedicated.agent_name}"` : "Your dedicated agent"} is connected{dedicated.calling_number ? ` (${dedicated.calling_number})` : ""} but not handling calls.</p>
              {!confirm && <button type="button" disabled={!!busy} onClick={() => askSwitch("dedicated")} className="rounded-lg border px-3 py-1.5 text-sm">Switch to your own agent</button>}</>
            : <button type="button" onClick={() => setShowOwn((v) => !v)} aria-expanded={showOwn} className="rounded-lg border px-3 py-1.5 text-sm">{showOwn ? "Hide" : "Connect your own agent"}</button>}
          {showOwn && !dedicated?.configured && <DedicatedAgentSetup workspaceId={workspaceId} profile={form} configured={false} onConnected={ownConnected} />}
        </div>
      </>}

      {type === "dedicated" && <>
        <div className="flex flex-wrap items-center gap-3 rounded-2xl border bg-background p-4">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary"><PhoneCall className="h-5 w-5" /></span>
          <div className="min-w-0 flex-1 text-sm">
            <p className="text-base font-semibold">{dedicated?.agent_name || "Your dedicated agent"}</p>
            <p className="text-muted-foreground">{dedicated?.calling_number ? `Calls from ${dedicated.calling_number} · ` : ""}Connection: {(dedicated?.status || "unverified").replaceAll("_", " ")}{dedicated?.last_verified_at ? ` · checked ${formatDate(dedicated.last_verified_at)}` : ""}</p>
          </div>
        </div>
        <VoiceAgentDetails workspaceId={workspaceId} refreshKey={`${dedicated?.agent_name}:${state.profile?.business_details}:${state.profile?.behaviour}`} />
        <div className="flex flex-wrap gap-2">
          {state.calling_enabled
            ? <button type="button" disabled={!!busy} onClick={() => setCalling(false)} className="rounded-lg border px-4 py-2 text-sm disabled:opacity-50">Pause calling</button>
            : <button type="button" disabled={!!busy} onClick={() => setCalling(true)} className="rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm font-semibold disabled:opacity-50">Resume calling</button>}
          {!confirm && trialActive && <button type="button" disabled={!!busy} onClick={() => askSwitch("master")} className="rounded-lg border px-4 py-2 text-sm">Switch to free-trial agent</button>}
          {!confirm && trial?.status === "available" && <button type="button" disabled={!!busy || !valid} onClick={askTrialFromOwn} className="rounded-lg border px-4 py-2 text-sm">Try the {trial.days}-day free trial</button>}
        </div>
        <InboundCallsSetup workspaceId={workspaceId} />
        <details className="rounded-xl border" open={showOwn} onToggle={(e) => setShowOwn(e.currentTarget.open)}>
          <summary className="cursor-pointer px-4 py-3 text-sm font-medium">Edit business details, or create a new agent</summary>
          {showOwn && <div className="space-y-3 border-t p-4">
            {profileFields}
            <p className="text-xs text-muted-foreground">These details are used when you create a new dedicated agent and by the free-trial agent. Your current agent's own instructions are managed in your Sarvam account.</p>
            <button type="button" disabled={!!busy || !valid} onClick={saveProfile} className="rounded-lg border px-3 py-1.5 text-sm disabled:opacity-50">{busy === "save" ? "Saving…" : "Save details"}</button>
            <DedicatedAgentSetup workspaceId={workspaceId} profile={form} configured onConnected={ownConnected} />
          </div>}
        </details>
      </>}

      {confirmBox}
      {message && <p role="status" className="text-sm">{message}</p>}
    </section>
  );
}
