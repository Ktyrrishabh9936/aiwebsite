import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Brain, RefreshCw } from "lucide-react";
import api from "../lib/api";

export default function SalesBriefing({ wsId, expanded = false }) {
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async (signal) => {
    try { const { data } = await api.get(`/workspaces/${wsId}/sales/briefing`, { signal }); if (!Array.isArray(data?.priorities)) throw new Error("Invalid sales briefing"); if (!signal?.aborted) { setReport(data); setError(""); } }
    catch { if (!signal?.aborted) setError("Sales insights could not refresh. Try again."); }
  }, [wsId]);
  useEffect(() => {
    const controller = new AbortController(); setReport(null); load(controller.signal);
    const timer = setInterval(() => { if (!document.hidden) load(controller.signal); }, 60000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [load]);
  const review = async () => {
    setBusy(true);
    try { const { data } = await api.post(`/workspaces/${wsId}/sales/review`); setReport(data); setError(""); }
    catch { setError("Review could not be completed. Complete sales setup and try again."); }
    finally { setBusy(false); }
  };
  return <section className="rounded-xl border bg-card p-5 space-y-4" aria-label="AI Manager sales briefing">
    <div className="flex flex-wrap justify-between items-center gap-3"><div><h2 className="font-bold flex items-center gap-2"><Brain size={18} className="text-primary"/>AI Manager Insights</h2><p className="text-sm text-muted-foreground mt-1">Live sales priorities based on recorded CRM activity.</p></div><button type="button" aria-label="Refresh sales insights" onClick={() => load()} className="p-2 rounded-lg border"><RefreshCw size={15}/></button></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {!report && !error && <p className="text-sm text-muted-foreground">Reviewing your pipeline...</p>}
    {report && <>
      {!report.profile_ready && <p className="text-sm">Give your manager the business context first. <Link className="text-primary underline" to={`/app/w/${wsId}/sales-strategy`}>Complete sales setup</Link></p>}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">{[["Active opportunities",report.active_opportunities],["Overdue tasks",report.overdue_tasks],["Stale leads",report.stale_leads],["Known pipeline value",report.known_pipeline_value === null ? "Not configured" : `${report.currency} ${Number(report.known_pipeline_value).toLocaleString()}`]].map(([label,value]) => <div key={label} className="rounded-lg bg-muted/40 p-3"><p className="text-sm text-muted-foreground">{label}</p><p className="font-bold mt-1 break-words">{value}</p></div>)}</div>
      <p className="text-sm text-muted-foreground">As of {new Date(report.generated_at).toLocaleString()} · {report.unpriced_opportunities} opportunities have no recorded deal value. {report.capped && "Snapshot is capped; counts and value describe analysed records only."}</p>
      <div className="space-y-3 max-h-80 overflow-y-auto pr-2">{report.priorities.slice(0, expanded ? 30 : 3).map(lead => <article key={lead.lead_id} className="border-t pt-3"><div className="flex flex-wrap justify-between gap-2"><Link className="text-sm font-semibold text-primary" to={`/app/w/${wsId}/crm?lead=${lead.lead_id}`}>{lead.name}</Link><span className="text-sm text-muted-foreground">{lead.stage} · {lead.owner}</span></div><p className="text-sm mt-1">{lead.next_action}</p><p className="text-sm text-muted-foreground mt-1">{lead.signals.map(s => s.reason).join(" ")}</p></article>)}</div>
      {!report.priorities.length && <p className="text-sm text-muted-foreground">No lead risks detected in the recorded data. Review open commitments and customer feedback before increasing spend.</p>}
      {expanded && <><h3 className="text-sm font-semibold">Questions before scaling</h3>{report.questions.map(q => <p key={q} className="text-sm text-muted-foreground">{q}</p>)}<h3 className="text-sm font-semibold">Overdue work</h3>{report.pending_work.map(task => <p key={task.id} className="text-sm"><Link className="text-primary" to={task.lead_id ? `/app/w/${wsId}/crm?lead=${task.lead_id}` : `/app/w/${wsId}/tasks`}>{task.title}</Link> · {task.due_at ? new Date(task.due_at).toLocaleString() : "No due date"}</p>)}</>}
      <div className="flex flex-wrap gap-3"><Link className="text-sm text-primary font-semibold" to={`/app/w/${wsId}/sales-strategy`}>Sales strategy & setup</Link>{expanded && <button type="button" disabled={busy || !report.profile_ready} onClick={review} className="text-sm font-semibold rounded-lg bg-primary text-primary-foreground px-3 py-2 disabled:opacity-50">{busy ? "Reviewing..." : "Review & create missing sales tasks"}</button>}</div>
    </>}
  </section>;
}
