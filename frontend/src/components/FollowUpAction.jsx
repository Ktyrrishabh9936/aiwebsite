import { useEffect, useState } from "react";
import { CalendarPlus, Sparkles } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "./ui/dialog";
import api, { formatError } from "../lib/api";

const nextHour = () => {
  const date = new Date(Date.now() + 60 * 60 * 1000);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}T${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
};

function FollowUpDateTime({ value }) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return <time dateTime={date.toISOString()} className="mt-1 inline-flex flex-wrap items-baseline gap-x-1.5 text-foreground/80">
    <span className="font-medium">{date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}</span>
    <span className="text-muted-foreground">{date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", hour12: true })}</span>
  </time>;
}

export function useFollowUpSnapshots(wsId, leadIds) {
  const ids = leadIds.filter(Boolean).join(",");
  const [snapshots, setSnapshots] = useState({});
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const refresh = () => setRevision((value) => value + 1);
    window.addEventListener("arevei:follow-up-changed", refresh);
    return () => window.removeEventListener("arevei:follow-up-changed", refresh);
  }, []);
  useEffect(() => {
    if (!ids) { setSnapshots({}); return undefined; }
    let live = true;
    api.get(`/workspaces/${wsId}/crm/follow-ups/snapshots`, { params: { lead_ids: ids } })
      .then(({ data }) => { if (live) setSnapshots(data); })
      .catch(() => { if (live) setSnapshots({}); });
    return () => { live = false; };
  }, [wsId, ids, revision]);
  return snapshots;
}

export function FollowUpSnapshot({ snapshot, compact = false }) {
  if (!snapshot) return <span className={compact ? "text-xs text-muted-foreground" : "text-sm text-foreground/80"}>Follow-up status unavailable</span>;
  const next = snapshot.next_action;
  return <div className={`${compact ? "space-y-2 text-xs" : "grid gap-4 text-sm sm:grid-cols-2"}`}>
    <div className="min-w-0"><p className="text-xs font-medium text-muted-foreground">Last response</p><p className="mt-0.5 text-foreground/90 break-words">{snapshot.last_response}</p><FollowUpDateTime value={snapshot.last_response_at} /></div>
    {next ? <div className="min-w-0"><p className="text-xs font-medium text-muted-foreground">Next action</p><p className="mt-0.5 font-medium text-foreground break-words">{next.title}</p><FollowUpDateTime value={next.due_at} /></div>
      : <p className={snapshot.follow_up_pending ? "text-amber-700 dark:text-amber-400 font-semibold" : "text-muted-foreground"}>{snapshot.follow_up_pending ? "Follow-up pending · No next action set" : "No follow-up needed"}{snapshot.suggested_action && <span className="block font-normal text-muted-foreground">Suggested: {snapshot.suggested_action}</span>}</p>}
  </div>;
}

export default function FollowUpAction({ wsId, lead, snapshot, compact = false }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const [dueAt, setDueAt] = useState(nextHour);
  const [outcome, setOutcome] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const base = `/workspaces/${wsId}/crm`;
  const changed = () => window.dispatchEvent(new Event("arevei:follow-up-changed"));
  const suggest = async () => {
    setBusy(true); setError("");
    try {
      const { data } = await api.post(`${base}/leads/${lead.id}/follow-up/suggest`);
      setTitle(data.title || ""); setNote(data.note || ""); setReason(`${data.source === "ai" ? "AI suggestion" : "Suggested next step"}: ${data.reason || "Review before saving."}`);
    } catch (e) { setError(formatError(e.response?.data?.detail || e.message)); }
    finally { setBusy(false); }
  };
  const save = async (event) => {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await api.post(`${base}/leads/${lead.id}/reminders`, { title: title.trim(), note: note.trim(), due_at: new Date(dueAt).toISOString() });
      changed(); setOpen(false); setTitle(""); setNote(""); setReason(""); setDueAt(nextHour());
    } catch (e) { setError(formatError(e.response?.data?.detail || e.message)); }
    finally { setBusy(false); }
  };
  const complete = async (event) => {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await api.patch(`${base}/reminders/${snapshot.next_action.id}`, { status: "done", outcome: outcome.trim() });
      changed(); setOutcome("");
    } catch (e) { setError(formatError(e.response?.data?.detail || e.message)); }
    finally { setBusy(false); }
  };
  const leadName = lead.field_values?.full_name || lead.full_name || lead.field_values?.phone || lead.phone || "this lead";
  return <Dialog open={open} onOpenChange={setOpen}>
    <DialogTrigger asChild><button type="button" onClick={(event) => event.stopPropagation()} className={`inline-flex items-center justify-center gap-1.5 rounded-lg border bg-background hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring font-medium ${compact ? "min-h-9 px-2 text-xs" : "min-h-10 px-3 text-sm"}`} aria-label={`Follow up with ${leadName}`}><CalendarPlus size={16} /> Follow up</button></DialogTrigger>
    <DialogContent className="max-w-lg max-h-[90dvh] overflow-y-auto" onClick={(event) => event.stopPropagation()}>
      <DialogHeader><DialogTitle>Follow up with {leadName}</DialogTitle></DialogHeader>
      <div className="rounded-lg bg-muted p-3 text-sm space-y-1"><p><strong>Stage:</strong> {snapshot?.stage?.replaceAll("_", " ") || lead.status || "New"}</p><p><strong>Last response:</strong> {snapshot?.last_response || "No response recorded yet"}</p><p><strong>Next action:</strong> {snapshot?.next_action?.title || "None scheduled"}</p></div>
      {snapshot?.next_action && <form onSubmit={complete} className="rounded-lg border p-3 space-y-2"><p className="text-sm font-semibold">Record the outcome</p><label className="block text-xs">What did the lead say or what happened?<textarea required maxLength={1000} rows={2} value={outcome} onChange={(event) => setOutcome(event.target.value)} className="mt-1 w-full rounded-lg border bg-background p-2 text-sm" placeholder="Spoke with the lead; they asked for a site visit on Friday" /></label><button type="submit" disabled={busy || !outcome.trim()} className="rounded-lg border px-3 py-2 text-xs font-semibold disabled:opacity-50">Complete follow-up</button></form>}
      <form onSubmit={save} className="space-y-3"><div className="flex items-center justify-between gap-2"><h3 className="text-sm font-semibold">Plan the next action</h3><button type="button" onClick={suggest} disabled={busy} className="inline-flex items-center gap-1 rounded-lg border px-3 py-2 text-xs font-medium disabled:opacity-50"><Sparkles size={14} /> Suggest with AI</button></div>
        {reason && <p className="text-xs text-muted-foreground">{reason}</p>}
        <label className="block text-xs">Action<input required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} className="mt-1 w-full rounded-lg border bg-background p-2 text-sm" placeholder="Call to confirm the site visit" /></label>
        <label className="block text-xs">When<input required type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} className="mt-1 w-full rounded-lg border bg-background p-2 text-sm" /></label>
        <label className="block text-xs">Context (optional)<textarea maxLength={4000} rows={2} value={note} onChange={(event) => setNote(event.target.value)} className="mt-1 w-full rounded-lg border bg-background p-2 text-sm" placeholder="What to discuss or share" /></label>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <button type="submit" disabled={busy || !title.trim() || !dueAt} className="min-h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50">{busy ? "Working…" : "Save follow-up"}</button>
      </form>
      <p className="text-xs text-muted-foreground">Suggestions create drafts only. No call or message is sent automatically.</p>
    </DialogContent>
  </Dialog>;
}
