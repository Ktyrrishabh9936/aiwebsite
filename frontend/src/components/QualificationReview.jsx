import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Circle, XCircle, ClipboardCheck, ChevronDown } from "lucide-react";
import api, { formatError } from "../lib/api";

const labels = { not_reviewed: "Not Reviewed", correct: "Correct", incorrect: "Incorrect" };
const reviewIcons = { not_reviewed: Circle, correct: CheckCircle2, incorrect: XCircle };
const fieldLabels = { requirement: "Requirement", product_fit: "Product fit", budget: "Budget", eligibility: "Eligibility", purchase_timeline: "Timeline", buying_intent: "Buying intent", decision_maker_status: "Decision maker", location: "Location", dnd_requested: "Do not call", not_interested: "Not interested" };
const humanize = (value) => String(value).toLowerCase().replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const missing = (value) => value == null || (typeof value === "string" && /^(\s*|n\/?a|not available|null|unknown)$/i.test(value.trim()));

function formatFact(value, key) {
  if (missing(value)) return "Not provided";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.map((item) => formatFact(item)).filter((item) => item !== "Not provided").join(" · ") || "Not provided";
  if (typeof value === "object") {
    if (key === "budget") {
      const amount = (number) => {
        if (missing(number)) return null;
        const numeric = Number(number);
        if (!Number.isFinite(numeric)) return String(number);
        try { return new Intl.NumberFormat("en-IN", value.currency ? { style: "currency", currency: value.currency, maximumFractionDigits: 0 } : { maximumFractionDigits: 0 }).format(numeric); }
        catch { return `${numeric.toLocaleString("en-IN")} ${value.currency || ""}`.trim(); }
      };
      const exact = amount(value.value), low = amount(value.min), high = amount(value.max);
      return exact ?? (low && high ? `${low} – ${high}` : low ? `From ${low}` : high ? `Up to ${high}` : "Not provided");
    }
    return Object.entries(value).map(([name, item]) => [name, formatFact(item, name)]).filter(([, item]) => item !== "Not provided").map(([name, item]) => `${humanize(name)}: ${item}`).join(" · ") || "Not provided";
  }
  return String(value).includes("_") ? humanize(value) : String(value);
}

function FactGrid({ entries, status, fields, busy, onToggle }) {
  return <dl className="grid grid-cols-1 min-[380px]:grid-cols-2 gap-x-5 gap-y-4">
    {entries.map(([key, value]) => {
      const formatted = formatFact(value, key);
      const label = fieldLabels[key] || humanize(key);
      return <div key={key} className={`min-w-0 ${fields.includes(key) && status === "incorrect" ? "border-l-2 border-rose-500 pl-2" : ""}`}>
        <dt className="text-[11px] font-medium text-muted-foreground mb-1">{label}</dt>
        <dd className={`text-sm leading-relaxed break-words ${formatted === "Not provided" ? "text-muted-foreground/70" : "font-medium"}`}>{formatted}</dd>
        {status === "incorrect" && <label className="mt-1.5 inline-flex items-center gap-2 text-xs text-muted-foreground cursor-pointer"><input type="checkbox" className="accent-primary rounded" checked={fields.includes(key)} disabled={busy} onChange={() => onToggle(key)} />{label} is incorrect</label>}
      </div>;
    })}
  </dl>;
}

export default function QualificationReview({ lead, wsId }) {
  const [state, setState] = useState(null);
  const [status, setStatus] = useState("not_reviewed");
  const [note, setNote] = useState("");
  const [fields, setFields] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [reload, setReload] = useState(0);
  const generation = useRef(0);
  const url = `/workspaces/${wsId}/crm/leads/${lead.id}/qualification-review`;
  const q = lead.qualification_call || {};
  const sourceKey = JSON.stringify([q.call_uuid, q.session_id, q.engine_result, q.structured_qualification, q.qualification_status, lead.qualification_data]);
  const hasResult = Boolean(q.engine_result || q.structured_qualification || lead.qualification_data);
  const accept = (data) => {
    setState(data); setStatus(data.review.status); setNote(data.review.note || ""); setFields(data.review.incorrect_fields || []);
  };
  useEffect(() => {
    let live = true;
    generation.current += 1;
    setState(null); setError(""); setSaved(false); setBusy(false);
    if (hasResult) api.get(url).then(({ data }) => { if (live) accept(data); }).catch((e) => { if (live) setError(formatError(e.response?.data?.detail || e.message)); });
    return () => { live = false; generation.current += 1; };
  }, [url, sourceKey, hasResult, reload]);
  if (!hasResult) return null;
  const source = state?.source || {};
  const facts = source.engine_result?.qualification_data || source.structured_qualification || source.qualification_data || {};
  const priority = ["requirement", "budget", "location", "purchase_timeline", "buying_intent", "decision_maker_status"];
  const entries = Object.entries(facts).sort(([a], [b]) => (priority.includes(a) ? priority.indexOf(a) : 99) - (priority.includes(b) ? priority.indexOf(b) : 99));
  const factProps = { status, fields, busy, onToggle: (key) => { setFields((old) => old.includes(key) ? old.filter((field) => field !== key) : [...old, key]); setSaved(false); } };
  const save = async () => {
    const version = generation.current;
    setBusy(true); setError(""); setSaved(false);
    try {
      const { data } = await api.put(url, { status, note, incorrect_fields: status === "incorrect" ? fields : [], source_version: state.source_version });
      if (version === generation.current) { accept(data); setSaved(true); }
    } catch (e) { if (version === generation.current) setError(formatError(e.response?.data?.detail || e.message)); }
    finally { if (version === generation.current) setBusy(false); }
  };
  return <section className="rounded-xl border border-border bg-background/40 overflow-hidden" aria-label="AI Qualification Review">
    <div className="px-4 pt-4 pb-3 flex items-start gap-3">
      <div className="p-2 rounded-lg bg-primary/10 text-primary shrink-0"><ClipboardCheck size={17} /></div>
      <div className="min-w-0"><h4 className="font-semibold text-sm">AI Qualification Review</h4><p className="text-xs text-muted-foreground mt-1">Check the AI’s findings and leave your verdict.</p></div>
    </div>
    <div className="px-4 pb-4 space-y-4">
    {error && <div role="alert" className="text-sm text-destructive">{error} <button type="button" onClick={() => setReload((v) => v + 1)} className="underline">Reload review</button></div>}
    {!state && !error && <p role="status" className="text-sm">Loading review…</p>}
    {state?.has_qualification && <>
      {state.stale && <p className="text-sm text-amber-600">The AI result changed. The previous review is preserved in history; this result is Not Reviewed.</p>}
      <div className="flex items-center justify-between gap-3 rounded-lg bg-secondary/50 px-3 py-2"><span className="text-xs text-muted-foreground">AI assessment</span><span className="text-xs font-semibold rounded-md border bg-background px-2.5 py-1">{humanize(source.engine_result?.lead_status || source.qualification_status || "Available")}</span></div>
      <fieldset disabled={busy}><legend className="text-xs font-medium mb-2">Is this assessment correct? <span className="font-normal text-muted-foreground">Optional</span></legend><div className="grid grid-cols-3 gap-2">{Object.entries(labels).map(([value, label]) => {
        const Icon = reviewIcons[value];
        const selectedStyle = value === "correct" ? "peer-checked:border-emerald-500/70 peer-checked:bg-emerald-500/10 peer-checked:text-emerald-600 dark:peer-checked:text-emerald-400" : value === "incorrect" ? "peer-checked:border-rose-500/70 peer-checked:bg-rose-500/10 peer-checked:text-rose-600 dark:peer-checked:text-rose-400" : "peer-checked:border-primary/60 peer-checked:bg-primary/10 peer-checked:text-primary";
        return <label key={value} className="cursor-pointer min-w-0"><input className="sr-only peer" type="radio" name={`qualification-review-${lead.id}`} value={value} checked={status === value} onChange={() => { setStatus(value); setSaved(false); }} /><span className={`flex flex-col min-[440px]:flex-row items-center justify-center gap-1.5 min-h-12 px-1.5 py-2 rounded-lg border text-xs font-medium text-muted-foreground transition-colors hover:bg-accent peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-disabled:opacity-50 ${selectedStyle}`}><Icon size={15} className="shrink-0" />{label}</span></label>;
      })}</div></fieldset>
      <div className="border-t pt-4 space-y-4">
        <div className="flex justify-between gap-2"><h5 className="text-xs font-semibold">AI findings</h5>{status === "incorrect" && <span className="text-[11px] text-muted-foreground">Select incorrect fields below</span>}</div>
        <FactGrid entries={entries.slice(0, 6)} {...factProps} />
        {entries.length > 6 && <details className="group border-t pt-3"><summary className="flex items-center justify-between cursor-pointer list-none text-xs font-medium text-muted-foreground [&::-webkit-details-marker]:hidden">More findings ({entries.length - 6})<ChevronDown size={14} className="group-open:rotate-180 transition-transform" /></summary><div className="mt-4 max-h-64 overflow-y-auto pr-1"><FactGrid entries={entries.slice(6)} {...factProps} /></div></details>}
        {entries.length === 0 && <p className="text-xs text-muted-foreground">No structured findings were recorded.</p>}
      </div>
      <label className="block text-xs font-medium border-t pt-4">Salesperson note <span className="font-normal text-muted-foreground">(optional)</span><textarea value={note} maxLength={4000} disabled={busy} placeholder={status === "incorrect" ? "What needs correcting?" : "Add context from your conversation…"} onChange={(e) => { setNote(e.target.value); setSaved(false); }} className="block w-full rounded-lg border bg-background px-3 py-2.5 mt-2 text-sm font-normal resize-y focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50" rows={2} /></label>
      <div className="flex items-center justify-between gap-3"><span role="status" className="text-xs text-muted-foreground">{saved ? "Review saved" : "Your review helps measure AI accuracy."}</span><button type="button" disabled={busy} onClick={save} className="shrink-0 rounded-lg bg-primary text-primary-foreground px-4 py-2.5 text-xs font-semibold hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50">{busy ? "Saving…" : "Save Review"}</button></div>
      {state.review.reviewed_at && <p className="text-[11px] text-muted-foreground border-t pt-3 leading-relaxed">Reviewed by: {state.review.reviewed_by_name || state.review.reviewed_by} · Reviewed on: {new Date(state.review.reviewed_at).toLocaleString()} · Status: {labels[state.review.status]}</p>}
    </>}
    </div>
  </section>;
}
