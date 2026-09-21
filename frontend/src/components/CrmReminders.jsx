import { useCallback, useEffect, useState } from "react";
import api, { formatError } from "../lib/api";

export function localDate(value = new Date()) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}
const localTime = (value) => { const date = new Date(value); return `${localDate(date)}T${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`; };
const blank = () => ({ title: "", note: "", due_at: localTime(Date.now() + 3600000) });
const inputClass = "w-full rounded-lg border bg-background p-2 text-sm";

export default function CrmReminders({ wsId, leadId, onOpenLead }) {
  const [day, setDay] = useState(localDate);
  const [view, setView] = useState(leadId ? "all" : "day");
  const [status, setStatus] = useState("pending");
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [draft, setDraft] = useState(blank);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const base = `/workspaces/${wsId}/crm`;
  useEffect(() => {
    let live = true;
    const params = { status, offset: page * 50, limit: 50 };
    if (leadId) params.lead_id = leadId;
    if (view === "overdue") params.overdue = true;
    if (view === "day") {
      if (!day) { setError("Choose a date"); setLoading(false); return; }
      const start = new Date(`${day}T00:00:00`), end = new Date(start); end.setDate(end.getDate() + 1);
      params.start = start.toISOString(); params.end = end.toISOString();
    }
    setLoading(true); setError("");
    api.get(`${base}/reminders`, { params }).then(({ data }) => { if (live) { setItems(data.items); setTotal(data.total); } }).catch((e) => { if (live) setError(formatError(e.response?.data?.detail || e.message)); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [base, leadId, day, view, status, page, revision]);
  const update = useCallback(async (id, payload) => {
    setBusy(true); setError("");
    try { await api.patch(`${base}/reminders/${id}`, payload); setRevision((v) => v + 1); return true; }
    catch (e) { setError(formatError(e.response?.data?.detail || e.message)); return false; }
    finally { setBusy(false); }
  }, [base]);
  const save = async (event) => {
    event.preventDefault();
    const payload = { ...draft, due_at: new Date(draft.due_at).toISOString() };
    if (editing) { if (await update(editing, payload)) { setEditing(null); setDraft(blank()); } return; }
    setBusy(true); setError("");
    try { await api.post(`${base}/leads/${leadId}/reminders`, payload); setDraft(blank()); setRevision((v) => v + 1); setPage(0); }
    catch (e) { setError(formatError(e.response?.data?.detail || e.message)); }
    finally { setBusy(false); }
  };
  return <section className="space-y-4" aria-label="Lead reminders">
    <div><h3 className="font-semibold">{leadId ? "Lead reminders" : "Contact planner"}</h3><p className="text-xs text-muted-foreground mt-1">Plan who to contact and what to discuss or share. Times use your local timezone. Reminders appear here; no automatic calls or messages are sent.</p></div>
    {(leadId || editing) && <form onSubmit={save} className="rounded-xl border bg-card p-4 space-y-3">
      <h4 className="text-sm font-medium">{editing ? "Edit reminder" : "Set a reminder"}</h4>
      <label className="block text-xs">What needs to happen?<input required maxLength={200} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} placeholder="Call about the site visit" className={`${inputClass} mt-1`} /></label>
      <label className="block text-xs">Date and time<input required type="datetime-local" value={draft.due_at} onChange={(e) => setDraft({ ...draft, due_at: e.target.value })} className={`${inputClass} mt-1`} /></label>
      <label className="block text-xs">What to discuss or share<textarea maxLength={4000} rows={2} value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} placeholder="Share the brochure and confirm their budget…" className={`${inputClass} mt-1`} /></label>
      <div className="flex gap-2"><button disabled={busy} className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm disabled:opacity-50">{busy ? "Saving…" : editing ? "Save changes" : "Add reminder"}</button>{editing && <button type="button" onClick={() => { setEditing(null); setDraft(blank()); }} className="text-sm px-3">Cancel edit</button>}</div>
    </form>}
    <div className="flex flex-wrap items-center gap-2">
      <select aria-label="Reminder view" value={view} onChange={(e) => { setView(e.target.value); setPage(0); }} className="rounded-lg border bg-background p-2 text-sm"><option value="day">By date</option><option value="overdue">Overdue</option><option value="all">All dates</option></select>
      {view === "day" && <><input aria-label="Reminder date" type="date" value={day} onChange={(e) => { setDay(e.target.value); setPage(0); }} className="rounded-lg border bg-background p-2 text-sm" /><button onClick={() => { setDay(localDate()); setPage(0); }} className="text-xs border rounded-lg p-2">Today</button></>}
      <select aria-label="Reminder status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }} className="rounded-lg border bg-background p-2 text-sm"><option value="pending">Pending</option><option value="done">Completed</option><option value="cancelled">Cancelled</option><option value="all">All statuses</option></select>
      <button onClick={() => setRevision((v) => v + 1)} className="text-xs border rounded-lg p-2">Refresh</button>
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {loading ? <p role="status" className="text-sm text-muted-foreground">Loading reminders…</p> : !error && <>
      {!items.length && <p className="border border-dashed rounded-xl p-6 text-sm text-muted-foreground">No reminders match this view.{!leadId && " Open a lead’s Reminders tab to add one."}</p>}
      {items.map((item) => <article key={item.id} className="rounded-xl border bg-card p-4 space-y-2">
        <div className="flex flex-wrap justify-between gap-2"><strong className="text-sm">{item.title}</strong><span className={`text-xs ${item.status === "pending" && new Date(item.scheduled_time) < new Date() ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"}`}>{new Date(item.scheduled_time).toLocaleString()} · {item.status === "done" ? "Completed" : item.status}</span></div>
        <div className="text-sm"><button disabled={!item.lead_available || !onOpenLead} onClick={() => onOpenLead(item.lead_id)} className="text-primary underline disabled:no-underline disabled:text-muted-foreground">{item.lead_name}</button>{item.lead_phone && <span className="ml-2 text-muted-foreground">{item.lead_phone}</span>}{!item.lead_available && <span className="text-xs text-muted-foreground ml-2">Lead unavailable or trashed</span>}</div>
        {item.objective && <p className="text-sm whitespace-pre-wrap break-words">{item.objective}</p>}
        <div className="flex flex-wrap gap-2 text-xs">{item.status === "pending" ? <><button disabled={busy} onClick={() => update(item.id, { status: "done" })} className="border rounded-lg px-3 py-2">Mark done</button><button disabled={busy} onClick={() => { setEditing(item.id); setDraft({ title: item.title, note: item.objective || "", due_at: localTime(item.scheduled_time) }); }} className="border rounded-lg px-3 py-2">Edit / reschedule</button><button disabled={busy} onClick={() => update(item.id, { status: "cancelled" })} className="px-2 text-muted-foreground">Cancel reminder</button></> : <button disabled={busy} onClick={() => update(item.id, { status: "pending" })} className="border rounded-lg px-3 py-2">Reopen</button>}</div>
      </article>)}
      <div className="flex items-center justify-between text-xs text-muted-foreground"><span>{total} reminders</span><div className="flex gap-3"><button disabled={!page} onClick={() => setPage((v) => v - 1)}>Previous</button><button disabled={(page + 1) * 50 >= total} onClick={() => setPage((v) => v + 1)}>Next</button></div></div>
    </>}
  </section>;
}
