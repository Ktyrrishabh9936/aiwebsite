import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Bot, CalendarDays, Check, FileText, HeartHandshake, Loader2, Mail, PhoneCall, PhoneForwarded, Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";
import VoiceAgentSetup from "./VoiceAgentSetup";

const ROLE_ICON = { first_call: PhoneCall, follow_up: PhoneForwarded, proposal: FileText, customer_care: HeartHandshake, custom: Bot };
const ABILITIES = [["call", "Phone calls", PhoneCall], ["email", "Emails", Mail], ["meeting", "Meetings", CalendarDays]];
const STATUS = {
  ready: ["Active", "bg-emerald-500", "text-emerald-600 dark:text-emerald-400"],
  limited: ["Partly connected", "bg-amber-500", "text-amber-600 dark:text-amber-400"],
  blocked: ["Not connected", "bg-red-500", "text-red-600 dark:text-red-400"],
  off: ["Off", "bg-muted-foreground/50", "text-muted-foreground"],
};
const BLANK = { name: "", description: "", stages: [], actions: ["email"], instructions: "", enabled: true };
const formOf = (agent) => ({ name: agent.name, description: agent.description, stages: agent.stages.map((stage) => stage.key), actions: agent.actions, instructions: agent.instructions, enabled: agent.enabled });
const same = (a, b) => JSON.stringify(Array.isArray(a) ? [...a].sort() : a) === JSON.stringify(Array.isArray(b) ? [...b].sort() : b);

function Dot({ status }) {
  const tone = (STATUS[status] || STATUS.off)[1];
  return (
    <span className="relative inline-flex h-2.5 w-2.5 shrink-0" aria-hidden="true">
      {status === "ready" && <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${tone}`} />}
      <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${tone}`} />
    </span>
  );
}

function Heading({ children }) {
  return <h4 className="mb-2 w-fit border-b border-dashed border-muted-foreground/50 pb-0.5 text-sm font-semibold text-muted-foreground">{children}</h4>;
}

/** The AI team in one simple view: pick an agent on the left, read and edit it on the right. */
export default function AgentControlPanel({ wsId, compact = false, initial = null }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(initial); // an agent id, "voice" or "new"
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState("");

  const load = useCallback(() => api.get(`/workspaces/${wsId}/ai-agents`)
    .then(({ data: next }) => { setData(next); setError(""); })
    .catch((err) => setError(formatError(err.response?.data?.detail))), [wsId]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (initial) setSelected(initial); }, [initial]);

  const creating = selected === "new";
  const onVoice = selected === "voice";
  const agent = useMemo(() => (creating || onVoice ? null : data?.agents.find((item) => item.id === selected) || data?.agents[0] || null), [data, selected, creating, onVoice]);
  // The form always starts from the saved agent, so switching agents never carries edits across.
  useEffect(() => { if (creating) setDraft(BLANK); else if (agent) setDraft(formOf(agent)); }, [agent?.id, agent?.updated_at, creating]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error && !data) return <p role="alert" className="text-sm text-destructive">{error}</p>;
  if (!data) return <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Loading your AI team…</div>;

  const voice = data.channels.voice;
  const saved = agent ? formOf(agent) : BLANK;
  const dirty = draft && (creating || Object.keys(draft).some((key) => !same(draft[key], saved[key])));
  const set = (key, value) => setDraft((current) => ({ ...current, [key]: value }));
  const toggle = (key, value) => set(key, draft[key].includes(value) ? draft[key].filter((item) => item !== value) : [...draft[key], value]);

  const send = async (key, request, message) => {
    setSaving(key);
    try { const { data: next } = await request(); setData(next); toast.success(message); return next; }
    catch (err) { toast.error(formatError(err.response?.data?.detail)); return null; }
    finally { setSaving(""); }
  };
  const save = async (event) => {
    event.preventDefault();
    if (creating) {
      const next = await send("save", () => api.post(`/workspaces/${wsId}/ai-agents`, draft), "Agent created");
      if (next) setSelected(next.agents[next.agents.length - 1].id);
      return;
    }
    // Send only what changed, so an agent that follows its role's default stages keeps doing so.
    const changes = Object.fromEntries(Object.entries(draft).filter(([key, value]) => !same(value, saved[key])));
    await send("save", () => api.patch(`/workspaces/${wsId}/ai-agents/${agent.id}`, changes), "Saved");
  };
  const remove = async () => {
    if (!window.confirm(`Delete ${agent.name}?`)) return;
    if (await send("delete", () => api.delete(`/workspaces/${wsId}/ai-agents/${agent.id}`), "Agent deleted")) setSelected(null);
  };

  const item = (active) => `flex shrink-0 items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition ${compact ? "border" : "w-full"} ${active ? "bg-primary/10 font-semibold text-primary ring-1 ring-inset ring-primary/20" : "text-foreground hover:bg-accent"}`;
  const Icon = ROLE_ICON[agent?.role] || Bot;
  const unavailable = (key) => agent?.capabilities.find((entry) => entry.action === key && !entry.available);

  return (
    <div className={`grid items-start gap-5 ${compact ? "" : "md:grid-cols-[240px_minmax(0,1fr)]"}`}>
      <nav aria-label="AI agents" className={compact ? "flex gap-2 overflow-x-auto pb-1" : "space-y-1"}>
        <button type="button" onClick={() => setSelected("voice")} aria-pressed={onVoice} className={item(onVoice)}>
          <PhoneCall className="h-4 w-4 shrink-0" /><span className="min-w-0 flex-1 truncate">Voice agent</span><Dot status={voice.connected ? "ready" : "blocked"} />
        </button>
        {!compact && <p className="px-3 pb-1 pt-3 text-[11px] font-bold uppercase tracking-[0.14em] text-muted-foreground">Agents</p>}
        {data.agents.map((entry) => {
          const EntryIcon = ROLE_ICON[entry.role] || Bot;
          const active = !creating && !onVoice && agent?.id === entry.id;
          return (
            <button key={entry.id} type="button" onClick={() => setSelected(entry.id)} aria-pressed={active} className={item(active)}>
              <EntryIcon className="h-4 w-4 shrink-0" /><span className="min-w-0 flex-1 truncate">{entry.name}</span><Dot status={entry.status} />
            </button>
          );
        })}
        <button type="button" onClick={() => setSelected("new")} aria-pressed={creating} className={`${item(creating)} text-muted-foreground`}><Plus className="h-4 w-4 shrink-0" /><span className="truncate">New agent</span></button>
      </nav>

      {onVoice ? (
        <div className="animate-fade-up space-y-3">
          <p className="text-sm text-muted-foreground">This is the voice that makes every call. The agents on the left decide who it calls and why.</p>
          <VoiceAgentSetup workspaceId={wsId} onSaved={load} />
        </div>
      ) : !draft ? null : (
        <form key={creating ? "new" : agent.id} onSubmit={save} className="animate-fade-up space-y-6 rounded-2xl border bg-card p-5 sm:p-7" aria-label={creating ? "New agent" : `${agent.name} details`}>
          <div className="flex flex-wrap items-center gap-3">
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary"><Icon className="h-5 w-5" /></span>
            <input value={draft.name} onChange={(event) => set("name", event.target.value)} required maxLength={60} placeholder="Agent name" aria-label="Agent name" className="min-w-0 flex-1 bg-transparent font-display text-2xl font-bold tracking-tight focus:outline-none" />
            {!creating && <span className={`inline-flex items-center gap-2 text-xs font-semibold ${STATUS[agent.status]?.[2]}`}><Dot status={agent.status} />{STATUS[agent.status]?.[0]}</span>}
            <label className="inline-flex cursor-pointer items-center gap-2 text-sm font-medium"><input type="checkbox" role="switch" checked={draft.enabled} onChange={(event) => set("enabled", event.target.checked)} aria-label="Agent is on" className="h-4 w-4" />On</label>
          </div>

          <div>
            <Heading>Role</Heading>
            {creating || !agent.builtin
              ? <textarea value={draft.description} onChange={(event) => set("description", event.target.value)} rows={2} maxLength={400} placeholder="What is this agent responsible for?" aria-label="Role" className="w-full rounded-xl border bg-background px-3.5 py-2.5 text-sm" />
              : <p className="text-[15px] leading-7">{agent.description}</p>}
          </div>

          <div>
            <Heading>Works on leads in</Heading>
            <div className="flex flex-wrap gap-2">
              {data.stages.map((stage) => {
                const on = draft.stages.includes(stage.key);
                return <button key={stage.key} type="button" aria-pressed={on} onClick={() => toggle("stages", stage.key)} className={`inline-flex h-10 items-center gap-1.5 rounded-xl border px-3.5 text-sm font-medium transition ${on ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent"}`}>{on && <Check className="h-3.5 w-3.5" />}{stage.label}</button>;
              })}
            </div>
          </div>

          <div>
            <Heading>Can do</Heading>
            <div className="flex flex-wrap gap-2">
              {ABILITIES.map(([key, label, AbilityIcon]) => {
                const on = draft.actions.includes(key);
                return <button key={key} type="button" aria-pressed={on} onClick={() => toggle("actions", key)} className={`inline-flex h-10 items-center gap-2 rounded-xl border px-3.5 text-sm font-medium transition ${on ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent"}`}><AbilityIcon className="h-4 w-4" />{label}</button>;
              })}
            </div>
            {!creating && ABILITIES.filter(([key]) => draft.actions.includes(key) && unavailable(key)).map(([key, label]) => (
              <p key={key} className="mt-2 flex items-start gap-2 text-sm text-amber-600 dark:text-amber-400"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /><span>{label} cannot run yet: {unavailable(key).note} {key === "call" && <button type="button" onClick={() => setSelected("voice")} className="font-semibold underline">Set up the voice agent</button>}</span></p>
            ))}
          </div>

          <div>
            <Heading>Instructions</Heading>
            <textarea value={draft.instructions} onChange={(event) => set("instructions", event.target.value)} rows={5} maxLength={2000} aria-label="Instructions"
              placeholder="Tell this agent how to work in your own words. For example: always offer a site visit this week. Never discuss discounts." className="w-full rounded-xl border bg-background px-3.5 py-3 text-[15px] leading-7" />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button disabled={!dirty || saving === "save" || !draft.name.trim() || !draft.actions.length || (creating && !draft.stages.length)} className="inline-flex h-11 items-center gap-2 rounded-xl bg-primary px-6 text-sm font-semibold text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50">
              {saving === "save" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}{creating ? "Create agent" : "Save"}
            </button>
            {!creating && !agent.builtin && <button type="button" onClick={remove} disabled={saving === "delete"} className="inline-flex h-11 items-center gap-2 rounded-xl border px-4 text-sm font-medium text-destructive hover:bg-destructive/5"><Trash2 className="h-4 w-4" />Delete</button>}
          </div>
        </form>
      )}

      {data.unassigned_stages.length > 0 && !onVoice && (
        <p className={`flex items-start gap-2 rounded-xl border border-amber-500/40 bg-amber-500/5 p-3 text-sm text-amber-700 dark:text-amber-400 ${compact ? "" : "md:col-start-2"}`}><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />No agent works on {data.unassigned_stages.map((stage) => stage.label).join(", ")} leads, so those come to you as tasks.</p>
      )}
    </div>
  );
}
