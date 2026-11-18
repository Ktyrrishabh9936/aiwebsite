import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { AlertTriangle, Bot, CalendarClock, CalendarDays, Check, CheckCircle2, Clock, Loader2, Mail, MessageSquareReply, Pencil, PhoneCall, Play, Plus, Search, Settings, ShieldCheck, Sparkles, UserRound, X } from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../../lib/api";
import { inputToUtc, zonedInput } from "../../lib/timezone";
import DailyAiSettings from "../../components/DailyAiSettings";

const KIND = {
  call: { label: "AI call", icon: PhoneCall },
  email: { label: "Email", icon: Mail },
  task: { label: "For you", icon: UserRound },
  lead_request: { label: "Lead request", icon: MessageSquareReply },
};
const STATUS = {
  scheduled: ["Planned", "bg-blue-500/10 text-blue-600 dark:text-blue-400"],
  running: ["Working", "bg-blue-500/10 text-blue-600 dark:text-blue-400"],
  in_progress: ["On the call", "bg-blue-500/10 text-blue-600 dark:text-blue-400"],
  done: ["Done", "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"],
  failed: ["Failed", "bg-red-500/10 text-red-600 dark:text-red-400"],
  skipped: ["Skipped", "bg-muted text-muted-foreground"],
  cancelled: ["Removed", "bg-muted text-muted-foreground"],
  superseded: ["Replaced", "bg-muted text-muted-foreground"],
  awaiting_approval: ["Waiting for approval", "bg-amber-500/10 text-amber-600 dark:text-amber-400"],
  awaiting_admin: ["Needs your answer", "bg-amber-500/10 text-amber-600 dark:text-amber-400"],
  suggested: ["Suggested", "bg-violet-500/10 text-violet-600 dark:text-violet-400"],
};
const EDITABLE = ["awaiting_approval", "scheduled"];
const small = "inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-semibold hover:bg-accent disabled:opacity-60";
const primary = "inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary px-2.5 text-xs font-semibold text-primary-foreground disabled:opacity-60";
const control = "mt-1 h-10 w-full rounded-lg border bg-card px-3 text-sm font-normal";

function Pill({ status }) {
  const [label, tone] = STATUS[status] || [status, "bg-muted text-muted-foreground"];
  return <span className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ${tone}`}>{label}</span>;
}

function Card({ title, icon: Icon, count, children, id, aside }) {
  return (
    <section id={id} className="rounded-2xl border bg-card p-5 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 font-display text-lg font-bold"><Icon className="h-5 w-5 text-primary" />{title}{count != null && <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-semibold text-muted-foreground">{count}</span>}</h2>
        {aside}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** Which agents may do this kind of action for this planned item. */
function agentsFor(agents, item, kind) {
  return agents.filter((agent) => agent.enabled && agent.actions.includes(kind)
    && (agent.stages.length ? agent.stages.includes(item.stage) : agent.categories.includes(item.category)));
}

export default function DailyPlan() {
  const { wsId } = useParams();
  const [params] = useSearchParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [drafts, setDrafts] = useState({});
  const [editing, setEditing] = useState(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => api.get(`/workspaces/${wsId}/ai-ops/today`)
    .then(({ data: next }) => { setData(next); setError(""); })
    .catch((err) => setError(formatError(err.response?.data?.detail))), [wsId]);

  const working = ["strategy", "ready"].includes(data?.run?.status);
  // Check often while a plan is being written, otherwise twice a minute for action results.
  useEffect(() => { load(); const timer = setInterval(load, working ? 5000 : 30000); return () => clearInterval(timer); }, [load, working]);
  useEffect(() => {
    // Email links point at one meeting or request: bring it into view once loaded.
    const target = params.get("meeting") || params.get("request");
    if (data && target) document.getElementById(`item-${target}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [data, params]);

  const zone = data?.settings?.timezone || "UTC";
  const at = useCallback((value, options) => (value ? new Date(value).toLocaleString(undefined, { timeZone: zone, ...options }) : ""), [zone]);
  const act = async (key, request, success) => {
    setBusy(key);
    try { const result = await request(); if (success) toast.success(typeof success === "function" ? success(result) : success); await load(); return result; }
    catch (err) { toast.error(formatError(err.response?.data?.detail)); return null; }
    finally { setBusy(""); }
  };
  const draft = (id, patch) => setDrafts((current) => ({ ...current, [id]: { ...current[id], ...patch } }));
  const action = (id, verb, body) => act(`${verb}-${id}`, () => api.post(`/workspaces/${wsId}/ai-ops/actions/${id}/${verb}`, body), null);

  const groups = useMemo(() => {
    const actions = (data?.actions || []).filter((a) => a.status !== "superseded");
    const plan = actions.filter((a) => ["call", "email"].includes(a.kind));
    const byAgent = new Map();
    plan.forEach((item) => { const name = item.agent_name || "AI Manager"; byAgent.set(name, [...(byAgent.get(name) || []), item]); });
    return {
      requests: actions.filter((a) => a.status === "awaiting_admin"),
      suggestions: actions.filter((a) => a.status === "suggested"),
      plan, byAgent: [...byAgent.entries()],
      waiting: plan.filter((a) => a.status === "awaiting_approval"),
      meetings: (data?.meetings || []).filter((m) => m.status !== "cancelled"),
    };
  }, [data]);

  if (error && !data) return <div className="p-6 sm:p-10"><p role="alert" className="text-sm text-destructive">{error}</p></div>;
  if (!data) return <div className="grid min-h-[40vh] place-items-center text-muted-foreground"><Loader2 className="h-5 w-5 animate-spin" /></div>;
  const { settings, run } = data;
  const agents = data.agents || [];
  const leadLink = (id) => `/app/w/${wsId}/crm?lead=${id}`;
  const preparing = run && ["strategy", "ready"].includes(run.status);
  const approval = run?.approval?.status;
  const pending = approval === "pending" && groups.waiting.length > 0;
  const openMeetings = groups.meetings.filter((m) => !["confirmed", "link_sent"].includes(m.status));
  const settledMeetings = groups.meetings.filter((m) => ["confirmed", "link_sent"].includes(m.status));

  if (!settings.enabled) {
    return (
      <div className="mx-auto max-w-3xl space-y-6 p-6 sm:p-10">
        <div><h1 className="font-display text-3xl font-black tracking-tight">Daily AI Plan</h1>
          <p className="mt-1 text-muted-foreground">Choose a time. Every day your AI reads the CRM, decides which leads need attention, gives each to the right agent and emails you the plan to approve.</p></div>
        <section className="rounded-2xl border bg-card p-5 sm:p-6"><DailyAiSettings wsId={wsId} submitLabel="Switch on the daily AI run" onSaved={load} /></section>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6 sm:p-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-black tracking-tight">Daily AI Plan</h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
            <Clock className="h-4 w-4" />Runs every day at {settings.run_time} ({zone.replaceAll("_", " ")})
            {settings.next_run_at && <span>· next {at(settings.next_run_at, { weekday: "short", hour: "numeric", minute: "2-digit" })}</span>}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to={`/app/w/${wsId}/ai`} className="inline-flex h-10 items-center gap-2 rounded-xl border px-4 text-sm font-medium hover:bg-accent"><Bot className="h-4 w-4" />Agents</Link>
          <Link to={`/app/w/${wsId}/ai?tab=daily`} className="inline-flex h-10 items-center gap-2 rounded-xl border px-4 text-sm font-medium hover:bg-accent"><Settings className="h-4 w-4" />Settings</Link>
          <button type="button" disabled={busy === "run" || preparing} onClick={() => act("run", () => api.post(`/workspaces/${wsId}/ai-ops/run`), "Reading your CRM. The plan appears here in a minute or two.")}
            className="inline-flex h-10 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60">
            {busy === "run" || preparing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}{preparing ? "Preparing plan…" : "Run now"}
          </button>
        </div>
      </div>

      {!run && <section className="rounded-2xl border border-dashed bg-card p-8 text-center"><CalendarClock className="mx-auto h-8 w-8 text-primary" /><p className="mt-3 font-semibold">No plan yet</p><p className="mt-1 text-sm text-muted-foreground">Your first plan arrives at the next run time. Choose “Run now” to see one straight away.</p></section>}

      {run && (
        <section className="rounded-2xl border bg-gradient-to-br from-primary/10 via-card to-card p-5 sm:p-6">
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-primary">Strategy · {run.day}{run.trigger === "manual" ? " · run by you" : ""}</p>
          {run.strategy ? (
            <>
              <h2 className="mt-2 font-display text-2xl font-bold tracking-tight">{run.strategy.headline}</h2>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">{run.strategy.summary}</p>
              {run.strategy.focus?.length > 0 && <ul className="mt-4 grid gap-2 sm:grid-cols-2">{run.strategy.focus.map((item) => <li key={item} className="flex items-start gap-2 rounded-xl border bg-background/70 p-3 text-sm"><Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />{item}</li>)}</ul>}
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                {run.strategy.pipeline_strategy && <div><p className="text-xs font-semibold uppercase text-muted-foreground">Sales pipeline</p><p className="mt-1 text-sm leading-6">{run.strategy.pipeline_strategy}</p></div>}
                {run.strategy.customer_strategy && <div><p className="text-xs font-semibold uppercase text-muted-foreground">Customers</p><p className="mt-1 text-sm leading-6">{run.strategy.customer_strategy}</p></div>}
              </div>
              {run.strategy.risks?.length > 0 && <ul className="mt-4 space-y-1">{run.strategy.risks.map((risk) => <li key={risk} className="flex items-start gap-2 text-sm text-amber-700 dark:text-amber-400"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{risk}</li>)}</ul>}
            </>
          ) : <p className="mt-3 flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Reading your CRM and writing today's strategy…</p>}
          <div className="mt-5 flex flex-wrap gap-2">
            {Object.entries(run.stats?.stage_counts || {}).map(([stage, count]) => <span key={stage} className="rounded-full border bg-background px-3 py-1 text-xs font-medium">{stage} <span className="font-bold">{count}</span></span>)}
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            {run.stats?.resting > 0 && `${run.stats.resting} leads are left alone today (no current requirement, or already followed up enough). `}
            {run.strategy_source === "rules" && "The AI model was unavailable, so this plan was built from CRM rules. "}
            {run.deferred > 0 && `${run.deferred} more leads were left for tomorrow because of today's limits or calling hours. `}
            {run.report?.sent ? `Emailed to ${run.report.to}.` : run.status === "completed" && run.report?.error ? `The email could not be sent: ${run.report.error}` : ""}
            {run.status === "failed" && " This run failed. Choose “Run now” to try again."}
          </p>
        </section>
      )}

      {pending && (
        <section role="status" className="sticky top-2 z-10 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-amber-500/50 bg-card p-4 shadow-lg sm:p-5">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-400"><ShieldCheck className="h-5 w-5" /></span>
            <div><p className="font-semibold">Today's plan is waiting for your approval</p>
              <p className="text-sm text-muted-foreground">{groups.waiting.length} action{groups.waiting.length === 1 ? "" : "s"} across {groups.byAgent.length} agent{groups.byAgent.length === 1 ? "" : "s"}. Change or remove anything below, then approve once. Nothing runs before that.</p></div>
          </div>
          <button type="button" disabled={busy === "approve-plan"} onClick={() => act("approve-plan", () => api.post(`/workspaces/${wsId}/ai-ops/plan/approve`, { skip: [] }), (r) => `Plan approved. ${r.data.approved} action${r.data.approved === 1 ? "" : "s"} will run at the planned times.`)}
            className="inline-flex h-11 items-center gap-2 rounded-xl bg-primary px-5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60">
            {busy === "approve-plan" ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}Approve the plan
          </button>
        </section>
      )}

      {(groups.requests.length > 0 || openMeetings.length > 0) && (
        <Card title="Needs you" icon={AlertTriangle} count={groups.requests.length + openMeetings.length}>
          <ul className="space-y-3">
            {groups.requests.map((item) => (
              <li key={item.id} id={`item-${item.id}`} className="rounded-xl border bg-background p-4">
                <div className="flex flex-wrap items-center justify-between gap-2"><Link to={leadLink(item.lead_id)} className="font-semibold hover:underline">{item.lead_name}</Link><Pill status={item.status} /></div>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">{(item.payload?.requests || []).map((text) => <li key={text}>{text}</li>)}</ul>
                <textarea rows={3} value={drafts[item.id]?.message || ""} onChange={(e) => draft(item.id, { message: e.target.value })} placeholder="Write your answer. It is emailed to the lead." aria-label={`Reply to ${item.lead_name}`} className="mt-3 w-full rounded-lg border bg-card px-3 py-2 text-sm" />
                <div className="mt-2 flex flex-wrap gap-2">
                  <button type="button" disabled={busy === `reply-${item.id}` || (drafts[item.id]?.message || "").trim().length < 2} onClick={() => action(item.id, "reply", { message: drafts[item.id].message })} className={primary}>{busy === `reply-${item.id}` ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Mail className="h-3.5 w-3.5" />}Email the lead</button>
                  <button type="button" onClick={() => action(item.id, "done", { note: "Handled outside the app." })} className={small}>I handled it myself</button>
                </div>
              </li>
            ))}
            {openMeetings.map((meeting) => <MeetingRow key={meeting.id} meeting={meeting} wsId={wsId} zone={zone} at={at} act={act} busy={busy} leadLink={leadLink} />)}
          </ul>
        </Card>
      )}

      {run && (
        <Card title="Today's plan" icon={Sparkles} count={groups.plan.filter((a) => a.status !== "cancelled").length}
          aside={!preparing && <button type="button" onClick={() => setAdding((open) => !open)} className={small}><Plus className="h-3.5 w-3.5" />Add a lead</button>}>
          {approval === "approved" && <p className="mb-4 flex items-center gap-2 rounded-lg bg-emerald-500/10 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-400"><CheckCircle2 className="h-4 w-4 shrink-0" />Approved{run.approval.by ? ` by ${run.approval.by}` : ""} · {at(run.approval.at, { hour: "numeric", minute: "2-digit" })}. The agents are working through it.</p>}
          {adding && <AddLead wsId={wsId} agents={agents} act={act} onDone={() => setAdding(false)} />}
          {groups.plan.length === 0 ? <p className="text-sm text-muted-foreground">{preparing ? "Actions appear here once the strategy is written." : "No calls or emails in this plan."}</p> : (
            <div className="space-y-5">
              {groups.byAgent.map(([name, items]) => (
                <div key={name}>
                  <h3 className="flex items-center gap-2 text-sm font-bold"><span className="grid h-7 w-7 place-items-center rounded-lg bg-primary/10 text-primary"><Bot className="h-4 w-4" /></span>{name}<span className="text-xs font-normal text-muted-foreground">{items.filter((a) => a.status !== "cancelled").length} action{items.filter((a) => a.status !== "cancelled").length === 1 ? "" : "s"}</span></h3>
                  <ul className="mt-2 divide-y rounded-xl border bg-background">
                    {items.map((item) => {
                      const Icon = KIND[item.kind]?.icon || Sparkles;
                      const open = EDITABLE.includes(item.status);
                      return (
                        <li key={item.id} className={`p-3 sm:p-4 ${item.status === "cancelled" ? "opacity-60" : ""}`}>
                          <div className="flex flex-wrap items-start gap-x-4 gap-y-1">
                            <span className="w-16 shrink-0 pt-0.5 text-xs font-semibold tabular-nums text-muted-foreground">{at(item.scheduled_for, { hour: "numeric", minute: "2-digit" })}</span>
                            <span className="min-w-0 flex-1">
                              <span className="flex flex-wrap items-center gap-2 text-sm font-semibold"><Icon className="h-4 w-4 text-primary" />{item.purpose_label || KIND[item.kind]?.label} · <Link to={leadLink(item.lead_id)} className="hover:underline">{item.lead_name}</Link><span className="text-xs font-normal text-muted-foreground">{item.stage_label}</span></span>
                              <span className="mt-0.5 block text-sm text-muted-foreground">{item.result || item.reason}</span>
                              {item.kind === "email" && open && editing !== item.id && <span className="mt-1 block truncate text-xs text-muted-foreground">Email: {item.payload?.subject}</span>}
                            </span>
                            <span className="flex items-center gap-1.5">
                              <Pill status={item.status} />
                              {open && item.status === "awaiting_approval" && !pending && <button type="button" disabled={busy === `approve-${item.id}`} onClick={() => action(item.id, "approve")} className={primary}><Check className="h-3.5 w-3.5" />Approve</button>}
                              {open && <button type="button" onClick={() => setEditing(editing === item.id ? null : item.id)} aria-label={`Change action for ${item.lead_name}`} aria-expanded={editing === item.id} className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"><Pencil className="h-4 w-4" /></button>}
                              {open && <button type="button" onClick={() => action(item.id, "cancel")} aria-label={`Remove action for ${item.lead_name}`} className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-destructive"><X className="h-4 w-4" /></button>}
                            </span>
                          </div>
                          {open && editing === item.id && <ActionEditor key={item.updated_at} item={item} agents={agents} wsId={wsId} zone={zone} act={act} onClose={() => setEditing(null)} />}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {groups.suggestions.length > 0 && (
        <Card title="For you and your team" icon={UserRound} count={groups.suggestions.length}>
          <ul className="divide-y">
            {groups.suggestions.map((item) => (
              <li key={item.id} className="py-3">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="min-w-0 flex-1"><Link to={leadLink(item.lead_id)} className="text-sm font-semibold hover:underline">{item.lead_name}</Link><span className="ml-2 text-xs text-muted-foreground">{item.stage_label}</span><span className="mt-0.5 block text-sm text-muted-foreground">{item.reason}</span></span>
                  {(item.allowed || []).some((kind) => kind !== "task") && <button type="button" onClick={() => setEditing(editing === item.id ? null : item.id)} className={small}><Bot className="h-3.5 w-3.5" />Give to an agent</button>}
                  <button type="button" disabled={busy === `done-${item.id}`} onClick={() => action(item.id, "done", { note: "" })} className={small}><CheckCircle2 className="h-3.5 w-3.5" />Done</button>
                  <button type="button" onClick={() => action(item.id, "cancel")} className={small}>Dismiss</button>
                </div>
                {editing === item.id && <ActionEditor key={item.updated_at} item={item} agents={agents} wsId={wsId} zone={zone} act={act} onClose={() => setEditing(null)} />}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Meetings" icon={CalendarDays} count={settledMeetings.length}>
        {!data.connectors?.calendar?.connected && <p className="mb-3 rounded-lg border border-dashed p-3 text-sm text-muted-foreground">No calendar connected, so your availability is not checked. <Link to={`/app/w/${wsId}/ai?tab=connections`} className="font-semibold text-primary hover:underline">Connect a calendar</Link></p>}
        {settledMeetings.length === 0
          ? <p className="text-sm text-muted-foreground">When a lead asks for a meeting on a call, it is arranged and shown here.</p>
          : <ul className="space-y-3">{settledMeetings.map((meeting) => <MeetingRow key={meeting.id} meeting={meeting} wsId={wsId} zone={zone} at={at} act={act} busy={busy} leadLink={leadLink} />)}</ul>}
      </Card>
    </div>
  );
}

/** Change how, by whom and when a planned action is done, and what its email says. */
function ActionEditor({ item, agents, wsId, zone, act, onClose }) {
  const kinds = (item.allowed?.length ? item.allowed : [item.kind]).filter((kind) => kind === "task" || agentsFor(agents, item, kind).length > 0 || kind === item.kind);
  const [kind, setKind] = useState(item.kind);
  const [agentId, setAgentId] = useState(item.agent_id || "");
  const [when, setWhen] = useState(item.scheduled_for ? zonedInput(item.scheduled_for, zone) : "");
  const [subject, setSubject] = useState(item.payload?.subject || "");
  const [body, setBody] = useState(item.payload?.body || "");
  const choices = kind === "task" ? [] : agentsFor(agents, item, kind);

  const save = async () => {
    const changes = {};
    if (kind !== item.kind) changes.kind = kind;
    const chosen = kind === "task" ? "" : (choices.some((agent) => agent.id === agentId) ? agentId : choices[0]?.id || "");
    if (chosen && chosen !== (item.agent_id || "")) changes.agent_id = chosen;
    if (kind !== "task" && when && when !== (item.scheduled_for ? zonedInput(item.scheduled_for, zone) : "")) {
      try { changes.scheduled_for = inputToUtc(when, zone); } catch (err) { toast.error(err.message); return; }
    }
    if (kind === "email" && item.kind === "email") {
      if (subject.trim() && subject !== item.payload?.subject) changes.subject = subject;
      if (body.trim() && body !== item.payload?.body) changes.body = body;
    }
    if (!Object.keys(changes).length) { onClose(); return; }
    if (await act(`edit-${item.id}`, () => api.patch(`/workspaces/${wsId}/ai-ops/actions/${item.id}`, changes), "Plan updated")) onClose();
  };

  return (
    <div className="mt-3 animate-fade-up space-y-3 rounded-xl border bg-card p-3 sm:p-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-xs font-semibold">Action
          <select value={kind} onChange={(e) => setKind(e.target.value)} className={control} aria-label="Action type">
            {kinds.map((value) => <option key={value} value={value}>{value === "task" ? "Leave it to me (no AI action)" : KIND[value].label}</option>)}
          </select>
        </label>
        {kind !== "task" && (
          <label className="text-xs font-semibold">Agent
            <select value={choices.some((agent) => agent.id === agentId) ? agentId : choices[0]?.id || ""} onChange={(e) => setAgentId(e.target.value)} className={control} aria-label="Agent">
              {choices.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
            </select>
          </label>
        )}
        {kind !== "task" && (
          <label className="text-xs font-semibold">Time ({zone.replaceAll("_", " ")})
            <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} className={control} aria-label="Planned time" />
          </label>
        )}
      </div>
      {kind === "email" && item.kind === "email" && (
        <div className="space-y-2">
          <input value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={150} aria-label="Email subject" className="h-10 w-full rounded-lg border bg-background px-3 text-sm" />
          <textarea rows={7} value={body} onChange={(e) => setBody(e.target.value)} maxLength={3000} aria-label="Email message" className="w-full rounded-lg border bg-background px-3 py-2 text-sm" />
        </div>
      )}
      {kind === "email" && item.kind !== "email" && <p className="text-xs text-muted-foreground">A standard email is prepared. Open the action again to edit its wording.</p>}
      <div className="flex gap-2"><button type="button" onClick={save} className={primary}><Check className="h-3.5 w-3.5" />Save changes</button><button type="button" onClick={onClose} className={small}>Cancel</button></div>
    </div>
  );
}

/** Put a lead the AI did not pick into today's plan. */
function AddLead({ wsId, agents, act, onDone }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [lead, setLead] = useState(null);
  const [kind, setKind] = useState("call");
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (query.trim().length < 2) { setResults([]); return undefined; }
    let live = true;
    const timer = setTimeout(() => api.get(`/workspaces/${wsId}/crm/leads`, { params: { search: query.trim(), page: 1, limit: 6 } })
      .then(({ data }) => { if (live) setResults(data.items || []); }).catch(() => { if (live) setResults([]); }), 300);
    return () => { live = false; clearTimeout(timer); };
  }, [query, wsId]);

  const name = (item) => item.field_values?.full_name || item.field_values?.email || item.field_values?.phone || "Unnamed lead";
  const add = async () => {
    const saved = await act("add-lead", () => api.post(`/workspaces/${wsId}/ai-ops/plan/actions`, { lead_id: lead.id, kind, reason }), `${name(lead)} added to the plan`);
    if (saved) onDone();
  };

  return (
    <div className="mb-5 animate-fade-up space-y-3 rounded-xl border border-dashed bg-background p-4">
      {!lead ? (
        <>
          <label className="relative block"><Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
            <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find a lead by name, phone or email" aria-label="Find a lead" className="h-10 w-full rounded-lg border bg-card pl-9 pr-3 text-sm" /></label>
          {results.length > 0 && <ul className="divide-y rounded-lg border bg-card">{results.map((item) => <li key={item.id}><button type="button" onClick={() => setLead(item)} className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-accent"><span className="font-medium">{name(item)}</span><span className="text-xs text-muted-foreground">{item.status_label || item.status}</span></button></li>)}</ul>}
          {query.trim().length >= 2 && results.length === 0 && <p className="text-xs text-muted-foreground">No leads match.</p>}
        </>
      ) : (
        <>
          <p className="flex items-center justify-between gap-3 text-sm font-semibold">{name(lead)}<button type="button" onClick={() => setLead(null)} className="text-xs font-medium text-primary hover:underline">Choose another</button></p>
          <div className="grid gap-3 sm:grid-cols-[180px_1fr]">
            <label className="text-xs font-semibold">Action
              <select value={kind} onChange={(e) => setKind(e.target.value)} className={control}>
                <option value="call">AI call</option><option value="email">Email</option><option value="task">Reminder for me</option>
              </select>
            </label>
            <label className="text-xs font-semibold">Why (optional)
              <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} placeholder="For example: met at the expo, wants a call back" className={control} />
            </label>
          </div>
          {kind !== "task" && agents.every((agent) => !agent.enabled || !agent.actions.includes(kind)) && <p className="text-xs text-amber-600">No active agent can do this. Switch one on in AI Control first.</p>}
          <div className="flex gap-2"><button type="button" onClick={add} className={primary}><Plus className="h-3.5 w-3.5" />Add to the plan</button><button type="button" onClick={onDone} className={small}>Cancel</button></div>
        </>
      )}
    </div>
  );
}

function MeetingRow({ meeting, wsId, zone, at, act, busy, leadLink }) {
  const [changing, setChanging] = useState(false);
  const [when, setWhen] = useState(meeting.start ? zonedInput(meeting.start, zone) : "");
  const [note, setNote] = useState("");
  const confirmed = meeting.status === "confirmed";
  const save = async (useNewTime) => {
    let start;
    try { start = useNewTime ? inputToUtc(when, zone) : undefined; } catch (err) { toast.error(err.message); return; }
    const result = await act(`meeting-${meeting.id}`, () => api.post(`/workspaces/${wsId}/ai-ops/meetings/${meeting.id}/confirm`, { start, note }),
      (r) => (r.data.conflict ? "Saved, but this time overlaps something else in your calendar" : r.data.lead_notified ? "Saved. The lead has been emailed." : "Saved. The lead has no email, so tell them by phone."));
    if (result) setChanging(false);
  };
  return (
    <li id={`item-${meeting.id}`} className="rounded-xl border bg-background p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold"><Link to={leadLink(meeting.lead_id)} className="hover:underline">{meeting.lead_name}</Link>{meeting.topic && <span className="ml-2 text-xs font-normal text-muted-foreground">{meeting.topic}</span>}</p>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${confirmed ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" : "bg-amber-500/10 text-amber-600 dark:text-amber-400"}`}>{confirmed ? "Confirmed" : meeting.status === "link_sent" ? "Booking link sent" : meeting.status === "needs_time" ? "Needs a time" : "Proposed"}</span>
      </div>
      <p className="mt-1 text-sm">{meeting.start ? `${at(meeting.start, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })} · ${meeting.duration_minutes} min` : meeting.status === "link_sent" ? "Waiting for the lead to pick a time" : "No time chosen yet"}</p>
      {meeting.requested_text && <p className="mt-1 text-xs text-muted-foreground">The lead said: “{meeting.requested_text}”</p>}
      {meeting.slot_note && <p className="mt-1 text-xs text-muted-foreground">{meeting.slot_note}</p>}
      {meeting.calendar_error && <p role="alert" className="mt-1 text-xs text-amber-600">{meeting.calendar_error}</p>}
      {confirmed && <p className="mt-1 text-xs text-muted-foreground">{meeting.lead_notified ? "The lead has been emailed this time." : "The lead has not been emailed (no email address). Confirm by phone."}{meeting.calendar_link && <> · <a href={meeting.calendar_link} target="_blank" rel="noreferrer" className="font-semibold text-primary hover:underline">Open in calendar</a></>}</p>}
      {changing && (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <label className="text-xs font-semibold">New time ({zone.replaceAll("_", " ")})<input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} className={control} /></label>
          <label className="text-xs font-semibold">Note for the lead (optional)<input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} className={control} /></label>
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {changing
          ? <><button type="button" disabled={!when || busy === `meeting-${meeting.id}`} onClick={() => save(true)} className={primary}>{busy === `meeting-${meeting.id}` && <Loader2 className="h-3.5 w-3.5 animate-spin" />}Save and email the lead</button><button type="button" onClick={() => setChanging(false)} className={small}>Back</button></>
          : <>
            {!confirmed && meeting.start && <button type="button" disabled={busy === `meeting-${meeting.id}`} onClick={() => save(false)} className={primary}><Check className="h-3.5 w-3.5" />Confirm this time</button>}
            <button type="button" onClick={() => setChanging(true)} className={small}><CalendarClock className="h-3.5 w-3.5" />{meeting.start ? "Choose a different time" : meeting.status === "link_sent" ? "Set the time myself" : "Choose a time"}</button>
            <button type="button" onClick={() => act(`cancel-${meeting.id}`, () => api.post(`/workspaces/${wsId}/ai-ops/meetings/${meeting.id}/cancel`, { notify_lead: true }), "Meeting cancelled")} className={small}><X className="h-3.5 w-3.5" />Cancel meeting</button>
          </>}
      </div>
    </li>
  );
}
