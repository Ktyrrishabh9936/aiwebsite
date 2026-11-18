import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CheckCircle2, Loader2, Sparkles } from "lucide-react";
import api, { formatError } from "../lib/api";

const OPEN = ["awaiting_approval", "scheduled", "suggested"];

/** Opened from the daily plan email: review the plan, untick anything to leave out, approve once. No sign-in. */
export default function PlanApproval() {
  const token = useSearchParams()[0].get("t") || "";
  const [plan, setPlan] = useState(null);
  const [error, setError] = useState("");
  const [skip, setSkip] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);

  useEffect(() => {
    api.get(`/ai-ops/plan/${token}`).then(({ data }) => setPlan(data)).catch((err) => setError(formatError(err.response?.data?.detail)));
  }, [token]);

  const groups = useMemo(() => {
    const byAgent = new Map();
    (plan?.actions || []).filter((item) => OPEN.includes(item.status)).forEach((item) => {
      const name = item.agent_name || "For you and your team";
      byAgent.set(name, [...(byAgent.get(name) || []), item]);
    });
    return [...byAgent.entries()];
  }, [plan]);

  const approve = async () => {
    setBusy(true); setError("");
    try { const { data } = await api.post(`/ai-ops/plan/${token}/approve`, { skip: [...skip] }); setDone(data); }
    catch (err) { setError(formatError(err.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const toggle = (id) => setSkip((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  const time = (value) => (value ? new Date(value).toLocaleTimeString(undefined, { timeZone: plan.timezone, hour: "numeric", minute: "2-digit" }) : "");

  const shell = "mx-auto min-h-screen max-w-3xl space-y-5 px-4 py-8 sm:py-12";
  if (error && !plan) return <main className={shell}><div role="alert" className="rounded-2xl border bg-card p-6 text-center"><p className="font-semibold">This plan cannot be opened</p><p className="mt-1 text-sm text-muted-foreground">{error}</p></div></main>;
  if (!plan) return <main className="grid min-h-screen place-items-center text-muted-foreground"><Loader2 className="h-5 w-5 animate-spin" /></main>;

  const waiting = plan.approval === "pending" && !plan.replaced && !done;
  const count = (plan.actions || []).filter((item) => item.status === "awaiting_approval" && !skip.has(item.id)).length;

  return (
    <main className={shell}>
      <header>
        <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.18em] text-primary"><Sparkles className="h-3.5 w-3.5" />Daily AI plan · {plan.business} · {plan.day}</p>
        <h1 className="mt-2 font-display text-2xl font-black tracking-tight sm:text-3xl">{plan.headline || "Today's plan"}</h1>
        {plan.summary && <p className="mt-2 text-sm leading-6 text-muted-foreground">{plan.summary}</p>}
      </header>

      {done && <div role="status" className="flex items-start gap-3 rounded-2xl border border-emerald-500/40 bg-emerald-500/5 p-5"><CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" /><div><p className="font-semibold">Plan approved</p><p className="text-sm text-muted-foreground">{done.approved} action{done.approved === 1 ? "" : "s"} will run at the planned times{done.removed ? `, ${done.removed} removed` : ""}. You can close this page.</p></div></div>}
      {!done && plan.replaced && <div role="status" className="rounded-2xl border bg-card p-5 text-sm">A newer plan has replaced this one. <a href={plan.app_url} className="font-semibold text-primary hover:underline">Open the latest plan</a></div>}
      {!done && !plan.replaced && plan.approval === "approved" && <div role="status" className="rounded-2xl border bg-card p-5 text-sm">This plan has already been approved and is running.</div>}

      {groups.length === 0 ? <p className="rounded-2xl border bg-card p-5 text-sm text-muted-foreground">There are no open actions in this plan.</p> : groups.map(([name, items]) => (
        <section key={name} className="rounded-2xl border bg-card p-5">
          <h2 className="font-display text-lg font-bold">{name} <span className="text-sm font-normal text-muted-foreground">· {items.length}</span></h2>
          <ul className="mt-3 divide-y">
            {items.map((item) => (
              <li key={item.id} className="py-3">
                <label className={`flex items-start gap-3 ${waiting && item.status === "awaiting_approval" ? "cursor-pointer" : ""}`}>
                  {waiting && item.status === "awaiting_approval" && <input type="checkbox" checked={!skip.has(item.id)} onChange={() => toggle(item.id)} aria-label={`Include ${item.purpose_label || item.kind} for ${item.lead_name}`} className="mt-1 h-4 w-4" />}
                  <span className={`min-w-0 flex-1 ${skip.has(item.id) ? "opacity-50 line-through" : ""}`}>
                    <span className="block text-sm font-semibold">{item.purpose_label || item.kind} · {item.lead_name} <span className="font-normal text-muted-foreground">{item.stage_label}{item.kind !== "task" && time(item.scheduled_for) ? ` · ${time(item.scheduled_for)}` : ""}</span></span>
                    <span className="mt-0.5 block text-sm text-muted-foreground">{item.reason}</span>
                    {item.subject && <span className="mt-0.5 block text-xs text-muted-foreground">Email subject: {item.subject}</span>}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </section>
      ))}

      {error && plan && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {waiting && (
        <div className="sticky bottom-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border bg-card p-4 shadow-lg">
          <p className="text-sm text-muted-foreground">Untick anything you want left out. Nothing runs until you approve.</p>
          <div className="flex flex-wrap gap-2">
            <a href={plan.app_url} className="inline-flex h-11 items-center rounded-xl border px-4 text-sm font-medium hover:bg-accent">Edit in the app</a>
            <button type="button" onClick={approve} disabled={busy} className="inline-flex h-11 items-center gap-2 rounded-xl bg-primary px-5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}Approve {count} action{count === 1 ? "" : "s"}
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
