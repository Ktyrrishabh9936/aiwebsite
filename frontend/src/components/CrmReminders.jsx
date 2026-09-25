import { useCallback, useEffect, useState } from "react";
import api, { formatError } from "../lib/api";

export function localDate(value = new Date()) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}
const localTime = (value) => { const date = new Date(value); return `${localDate(date)}T${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`; };
const blank = () => ({ title: "", note: "", due_at: localTime(Date.now() + 3600000) });
const inputClass = "w-full rounded-lg border bg-background p-2 text-sm";
const dateLabel = (value) => new Date(value).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
const timeLabel = (value) => new Date(value).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", timeZoneName: "short" });
const calendarDays = (month) => {
  const start = new Date(month.getFullYear(), month.getMonth(), 1);
  start.setDate(start.getDate() - start.getDay());
  return Array.from({ length: 42 }, (_, index) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + index));
};

export default function CrmReminders({ wsId, leadId, onOpenLead }) {
  const [day, setDay] = useState(localDate);
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  const [view, setView] = useState("day");
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
  const [notificationPermission, setNotificationPermission] = useState(() => typeof Notification === "undefined" ? "unsupported" : Notification.permission);
  const base = `/workspaces/${wsId}/crm`;
  const today = localDate();
  const chooseDay = (value) => { setDay(value); setMonth(new Date(`${value}T00:00:00`)); setView("day"); setPage(0); };
  const enableNotifications = async () => {
    if (typeof Notification === "undefined") return;
    try {
      const permission = await Notification.requestPermission();
      setNotificationPermission(permission);
      if (permission === "granted") window.dispatchEvent(new Event("arevei:reminder-notifications-enabled"));
    } catch { setError("Browser notifications could not be enabled."); }
  };
  useEffect(() => {
    const syncPermission = () => setNotificationPermission(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
    window.addEventListener("focus", syncPermission);
    return () => window.removeEventListener("focus", syncPermission);
  }, []);
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
    if (editing) { if (await update(editing, payload)) { chooseDay(localDate(new Date(payload.due_at))); setEditing(null); setDraft(blank()); } return; }
    setBusy(true); setError("");
    try { await api.post(`${base}/leads/${leadId}/reminders`, payload); chooseDay(localDate(new Date(payload.due_at))); setDraft(blank()); setRevision((v) => v + 1); }
    catch (e) { setError(formatError(e.response?.data?.detail || e.message)); }
    finally { setBusy(false); }
  };
  return <section className="space-y-4" aria-label="Lead reminders">
    <div><h3 className="font-semibold">{leadId ? "Lead reminders" : "Contact planner"}</h3><p className="text-xs text-muted-foreground mt-1">Plan who to contact and what to discuss or share. Due times use your local timezone. No automatic calls or messages are sent.</p></div>
    <div className="rounded-xl border bg-card p-4" aria-label="Reminder calendar">
      <div className="flex items-center justify-between gap-2 mb-3"><div><h4 className="font-semibold">{month.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</h4><p className="text-xs text-muted-foreground">Selected: {dateLabel(`${day}T12:00:00`)}</p></div><div className="flex gap-2"><button type="button" aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))} className="rounded-lg border px-3 py-1.5 text-sm">‹</button><button type="button" onClick={() => chooseDay(localDate())} className="rounded-lg border px-3 py-1.5 text-sm">Today</button><button type="button" aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))} className="rounded-lg border px-3 py-1.5 text-sm">›</button></div></div>
      <div className="grid grid-cols-7 gap-1 text-center text-xs text-muted-foreground mb-1">{["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((name) => <span key={name}>{name}</span>)}</div>
      <div className="grid grid-cols-7 gap-1">{calendarDays(month).map((date) => { const key = localDate(date); const selected = key === day; const isToday = key === today; return <button key={key} type="button" aria-label={dateLabel(date)} aria-current={isToday ? "date" : undefined} aria-pressed={selected} onClick={() => chooseDay(key)} className={`h-9 rounded-lg text-sm transition ${selected ? "bg-primary text-primary-foreground font-semibold" : isToday ? "border-2 border-primary text-primary font-semibold" : date.getMonth() === month.getMonth() ? "hover:bg-accent" : "text-muted-foreground/50 hover:bg-accent"}`}>{date.getDate()}</button>; })}</div>
    </div>
    <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-card p-3 text-sm">
      <span className="font-medium">Browser reminders</span>
      {notificationPermission === "granted" ? <span className="text-emerald-600 dark:text-emerald-400">Enabled</span> : notificationPermission === "denied" ? <span className="text-muted-foreground">Blocked in browser settings</span> : notificationPermission === "unsupported" ? <span className="text-muted-foreground">Unavailable in this browser</span> : <button type="button" onClick={enableNotifications} className="rounded-lg border px-3 py-1.5 font-medium hover:bg-accent">Enable notifications</button>}
      <span className="text-xs text-muted-foreground">Alerts appear at the due time while this workspace is open.</span>
    </div>
    {(leadId || editing) && <form onSubmit={save} className="rounded-xl border bg-card p-4 space-y-3">
      <h4 className="text-sm font-medium">{editing ? "Edit reminder" : "Set a reminder"}</h4>
      <label className="block text-xs">What needs to happen?<input required maxLength={200} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} placeholder="Call about the site visit" className={`${inputClass} mt-1`} /></label>
      <label className="block text-xs">Reminder date and time (your timezone)<input required type="datetime-local" value={draft.due_at} onChange={(e) => setDraft({ ...draft, due_at: e.target.value })} className={`${inputClass} mt-1`} /></label>
      <label className="block text-xs">What to discuss or share<textarea maxLength={4000} rows={2} value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} placeholder="Share the brochure and confirm their budget…" className={`${inputClass} mt-1`} /></label>
      <div className="flex gap-2"><button disabled={busy} className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm disabled:opacity-50">{busy ? "Saving…" : editing ? "Save changes" : "Add reminder"}</button>{editing && <button type="button" onClick={() => { setEditing(null); setDraft(blank()); }} className="text-sm px-3">Cancel edit</button>}</div>
    </form>}
    <div className="flex flex-wrap items-center gap-2">
      <select aria-label="Reminder view" value={view} onChange={(e) => { setView(e.target.value); setPage(0); }} className="rounded-lg border bg-background p-2 text-sm"><option value="day">By date</option><option value="overdue">Overdue</option><option value="all">All dates</option></select>
      {view === "day" && <input aria-label="Reminder date" type="date" value={day} onChange={(e) => { if (e.target.value) chooseDay(e.target.value); }} className="rounded-lg border bg-background p-2 text-sm" />}
      <select aria-label="Reminder status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }} className="rounded-lg border bg-background p-2 text-sm"><option value="pending">Pending</option><option value="done">Completed</option><option value="cancelled">Cancelled</option><option value="all">All statuses</option></select>
      <button onClick={() => setRevision((v) => v + 1)} className="text-xs border rounded-lg p-2">Refresh</button>
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {loading ? <p role="status" className="text-sm text-muted-foreground">Loading reminders…</p> : !error && <>
      {!items.length && <p className="border border-dashed rounded-xl p-6 text-sm text-muted-foreground">No reminders match this view.{!leadId && " Open a lead’s Reminders tab to add one."}</p>}
      {items.map((item) => <article key={item.id} className="rounded-xl border bg-card p-4 space-y-2">
        <div className="flex flex-wrap justify-between gap-2"><strong className="text-sm">{item.title}</strong><div className="text-right"><p className={`text-sm font-semibold ${item.status === "pending" && new Date(item.scheduled_time) < new Date() ? "text-amber-600 dark:text-amber-400" : "text-foreground"}`}>Due {timeLabel(item.scheduled_time)}</p><p className="text-xs text-muted-foreground">{dateLabel(item.scheduled_time)} | {item.status === "done" ? "Completed" : item.status}</p></div></div>
        <div className="text-sm"><button disabled={!item.lead_available || !onOpenLead} onClick={() => onOpenLead(item.lead_id)} className="text-primary underline disabled:no-underline disabled:text-muted-foreground">{item.lead_name}</button>{item.lead_phone && <span className="ml-2 text-muted-foreground">{item.lead_phone}</span>}{!item.lead_available && <span className="text-xs text-muted-foreground ml-2">Lead unavailable or trashed</span>}</div>
        {item.objective && <p className="text-sm whitespace-pre-wrap break-words">{item.objective}</p>}
        <div className="flex flex-wrap gap-2 text-xs">{item.status === "pending" ? <><button disabled={busy} onClick={() => update(item.id, { status: "done" })} className="border rounded-lg px-3 py-2">Mark done</button><button disabled={busy} onClick={() => { setEditing(item.id); setDraft({ title: item.title, note: item.objective || "", due_at: localTime(item.scheduled_time) }); }} className="border rounded-lg px-3 py-2">Edit / reschedule</button><button disabled={busy} onClick={() => update(item.id, { status: "cancelled" })} className="px-2 text-muted-foreground">Cancel reminder</button></> : <button disabled={busy} onClick={() => update(item.id, { status: "pending" })} className="border rounded-lg px-3 py-2">Reopen</button>}</div>
      </article>)}
      <div className="flex items-center justify-between text-xs text-muted-foreground"><span>{total} reminders</span><div className="flex gap-3"><button disabled={!page} onClick={() => setPage((v) => v - 1)}>Previous</button><button disabled={(page + 1) * 50 >= total} onClick={() => setPage((v) => v + 1)}>Next</button></div></div>
    </>}
  </section>;
}
