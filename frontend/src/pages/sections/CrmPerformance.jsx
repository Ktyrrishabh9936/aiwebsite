import { appDate } from "../../lib/timezone";
import { useEffect, useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import api, { formatError } from "../../lib/api";

export function recentPeriod() {
  const end = new Date();
  const start = new Date(end); start.setUTCDate(start.getUTCDate() - 29);
  return { start: appDate(start), end: appDate(end), profile_id: "", status: "" };
}

const percent = (value) => value == null ? "—" : `${value}%`;
function Metrics({ title, items }) {
  return <section className="space-y-3"><h3 className="font-semibold">{title}</h3><div className="grid grid-cols-2 lg:grid-cols-4 gap-3">{items.map(([label, value]) => <div className="border rounded-lg bg-card p-4" key={label}><p className="text-xs text-muted-foreground">{label}</p><p className="text-xl font-bold mt-2">{value ?? "—"}</p></div>)}</div></section>;
}

function BarChart({ title, description, items }) {
  const maximum = Math.max(1, ...items.map(([, value]) => Number(value) || 0));
  return <section className="rounded-xl border bg-card p-5 sm:p-6 space-y-5">
    <div><h3 className="font-semibold">{title}</h3><p className="text-xs text-muted-foreground mt-1 leading-relaxed">{description}</p></div>
    <div className="space-y-4" role="img" aria-label={`${title}: ${items.map(([label, value]) => `${label} ${value ?? "unknown"}`).join(", ")}`}>
      {items.map(([label, value, color = "bg-primary"]) => <div key={label} title={`${label}: ${value ?? "Unknown"}`}>
        <div className="flex justify-between gap-3 text-sm mb-2"><span className="text-muted-foreground">{label}</span><span className="font-semibold tabular-nums">{value ?? "—"}</span></div>
        <div className="h-3 rounded-full bg-muted overflow-hidden"><div className={`h-full rounded-full ${color}`} style={{ width: `${Math.max(0, Number(value) || 0) / maximum * 100}%` }} /></div>
      </div>)}
    </div>
    {items.every(([, value]) => !value) && <p className="text-xs text-muted-foreground">No data to chart for this selection.</p>}
  </section>;
}

function ReviewChart({ reviews }) {
  const reviewed = Number(reviews.reviewed) || 0;
  const circumference = 2 * Math.PI * 42;
  const correctArc = reviewed ? (Number(reviews.correct) || 0) / reviewed * circumference : 0;
  return <section className="rounded-xl border bg-card p-5 sm:p-6 space-y-5">
    <div><h3 className="font-semibold">AI qualification quality</h3><p className="text-xs text-muted-foreground mt-1">Human-reviewed qualifications only</p></div>
    <div className="flex flex-col sm:flex-row items-center gap-6">
      <div className="relative w-44 h-44 shrink-0">
        <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90" role="img" aria-label={`Review accuracy chart: ${reviews.correct ?? 0} correct, ${reviews.incorrect ?? 0} incorrect, ${reviewed} reviewed`}>
          <circle cx="50" cy="50" r="42" fill="none" strokeWidth="9" className={reviewed ? "stroke-rose-500" : "stroke-muted"} />
          {reviewed > 0 && <circle cx="50" cy="50" r="42" fill="none" strokeWidth="9" className="stroke-emerald-500" strokeDasharray={`${correctArc} ${circumference}`}><title>{reviews.correct} correct out of {reviewed} reviewed</title></circle>}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center text-center pointer-events-none"><span className="text-3xl font-bold tabular-nums">{percent(reviews.accuracy)}</span><span className="text-xs text-muted-foreground mt-1">AI qualification<br />accuracy</span></div>
      </div>
      <dl className="w-full space-y-3 text-sm">
        {[["Correct", reviews.correct, "bg-emerald-500"], ["Incorrect", reviews.incorrect, "bg-rose-500"], ["Not Reviewed", reviews.not_reviewed, "bg-muted-foreground"]].map(([label, value, color]) => <div key={label} className="flex justify-between gap-4"><dt className="flex items-center gap-2 text-muted-foreground"><span className={`w-2.5 h-2.5 rounded-full ${color}`} />{label}</dt><dd className="font-semibold tabular-nums">{value ?? "—"}</dd></div>)}
        <div className="flex justify-between border-t pt-3"><dt>Reviewed</dt><dd className="font-semibold tabular-nums">{reviewed}</dd></div>
      </dl>
    </div>
    {reviews.accuracy == null && <p className="text-sm text-muted-foreground">Not enough reviewed data</p>}
    <p className="text-xs text-muted-foreground leading-relaxed">Accuracy = Correct ÷ (Correct + Incorrect). Not Reviewed results are excluded from the chart and accuracy. Review the AI qualification directly in a lead record. Changed AI results need a fresh review.</p>
  </section>;
}

export default function CrmPerformance({ wsId, states = [] }) {
  const [view, setView] = useState("calling");
  const [filters, setFilters] = useState(recentPeriod);
  const [profiles, setProfiles] = useState([]);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [profileError, setProfileError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const reload = (event) => { if (event.detail?.wsId === wsId) setRefresh((value) => value + 1); };
    window.addEventListener("arevei:lead-metrics-changed", reload);
    return () => window.removeEventListener("arevei:lead-metrics-changed", reload);
  }, [wsId]);
  useEffect(() => {
    let live = true;
    setProfiles([]); setProfileError("");
    api.get(`/workspaces/${wsId}/crm/qualification/profiles`).then(({ data }) => { if (live) setProfiles(data.profiles || []); }).catch(() => { if (live) setProfileError("Qualification profiles could not be loaded."); });
    return () => { live = false; };
  }, [wsId]);
  useEffect(() => {
    let live = true;
    setLoading(true); setData(null); setError("");
    if (!filters.start || !filters.end || filters.start > filters.end) {
      setError("Choose a valid start and end date."); setLoading(false);
      return () => { live = false; };
    }
    const params = Object.fromEntries(Object.entries(filters).filter(([, value]) => value));
    api.get(`/workspaces/${wsId}/crm/performance`, { params }).then(({ data }) => { if (live) setData(data); }).catch((e) => { if (live) setError(formatError(e.response?.data?.detail || e.message)); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [wsId, filters, refresh]);
  const change = (key, value) => setFilters((old) => ({ ...old, [key]: value }));
  const f = data?.funnel || {}, c = data?.calling || {}, q = data?.qualification || {}, r = data?.reviews || {}, sales = data?.sales || {};
  const stageLabel = (key) => states.find((state) => state.key === key)?.label || key.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  return <div className="space-y-6" aria-label="CRM Performance">
    <div><h2 className="text-xl font-bold">CRM Performance</h2><p className="text-sm text-muted-foreground mt-1">Leads created in the selected application timezone date range, with their current qualification and human review. Calls shown were attempted in this range for those leads. Test and trashed leads are excluded.</p></div>
    <div className="flex flex-wrap items-end gap-3 rounded-lg border bg-card p-4">
      {["start", "end"].map((key) => <label key={key} className="text-xs">{key === "start" ? "Start date" : "End date"}<input type="date" value={filters[key]} onChange={(e) => change(key, e.target.value)} className="block border rounded-md bg-background p-2 mt-1 text-sm" /></label>)}
      <label className="text-xs">Qualification profile<select value={filters.profile_id} onChange={(e) => change("profile_id", e.target.value)} className="block border rounded-md bg-background p-2 mt-1 text-sm"><option value="">All profiles</option>{profiles.map((p) => <option key={p.id} value={p.id}>{p.product_name}</option>)}</select></label>
      <label className="text-xs">Lead status<select value={filters.status} onChange={(e) => change("status", e.target.value)} className="block border rounded-md bg-background p-2 mt-1 text-sm"><option value="">All statuses</option>{states.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</select></label>
      <button onClick={() => setRefresh((v) => v + 1)} disabled={loading} className="border rounded-md px-3 py-2 text-sm disabled:opacity-50">Refresh</button>
    </div>
    {profileError && <p role="alert" className="text-sm text-destructive">{profileError}</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {loading && <p role="status">Loading performance…</p>}
    <div role="tablist" aria-label="Performance reports" className="flex flex-wrap gap-2 border-b pb-3">
      {[["calling", "Calling & qualification"], ["sales", "Leads & sales"]].map(([key, label]) =>
        <button key={key} type="button" role="tab" aria-selected={view === key} onClick={() => setView(key)} className={`rounded-md px-4 py-2 text-sm font-medium ${view === key ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground"}`}>{label}</button>)}
    </div>
    {data && <>
      {f.total_leads === 0 && <p className="rounded-lg border border-dashed p-6 text-muted-foreground">No leads match these filters. Change the date range or filters to see performance.</p>}
      {view === "calling" ? <>
      <Metrics title="Performance at a glance" items={[["Total leads", f.total_leads], ["Connection rate", percent(c.connection_rate)], ["Qualification completion", percent(q.completion_rate)], ["Average call duration", c.average_duration_seconds == null ? "—" : `${c.average_duration_seconds}s`]]} />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <BarChart title="Lead reach" description="Lead counts. Eligibility reflects current phone, DND and junk restrictions; calling windows, retry limits and provider readiness still apply." items={[["Total leads", f.total_leads], ["Leads eligible for calling", f.eligible_leads, "bg-sky-500"], ["Leads attempted", f.leads_attempted, "bg-indigo-500"]]} />
        <BarChart title="Calling funnel & outcomes" description="Call counts. Retries count as separate attempts; completed conversations are included in connected calls." items={[["Calls attempted", c.calls_attempted], ["Connected calls", c.connected, "bg-sky-500"], ["Completed conversations", c.completed_conversations, "bg-emerald-500"], ["No answer", c.no_answer, "bg-amber-500"], ["Busy", c.busy, "bg-violet-500"], ["Failed calls", c.failed, "bg-rose-500"]]} />
        <BarChart title="Qualification performance" description="Latest AI results. Follow-up can overlap qualified or disqualified outcomes, so these bars are not a breakdown of a single total." items={[["Qualified leads", q.qualified, "bg-emerald-500"], ["Disqualified leads", q.disqualified, "bg-rose-500"], ["Follow-up required", q.follow_up_required, "bg-amber-500"]]} />
        <ReviewChart reviews={r} />
      </div>
      <details className="rounded-lg border p-4 text-xs text-muted-foreground leading-relaxed"><summary className="cursor-pointer font-medium text-foreground">How these metrics are calculated</summary><div className="mt-3 space-y-2"><p>Connection rate = connected calls ÷ calls attempted. Average duration uses completed conversations with a recorded duration.</p><p>Qualification completion = qualified or disqualified results ÷ all saved AI results. With a profile filter, calls use their recorded profile and qualifications use the latest result’s profile.</p><p>Each bar chart uses its own count scale. Unknown rates and durations appear as —.</p></div></details>
      </> : <>
        <Metrics title="Lead and sales overview" items={[["Total leads", sales.total_leads], ["Junk", `${sales.junk ?? 0} · ${percent(sales.junk_rate)}`], ["Not qualified", `${sales.not_qualified ?? 0} · ${percent(sales.not_qualified_rate)}`], ["Converted", `${sales.converted ?? 0} · ${percent(sales.conversion_rate)}`], ["Demo / meeting", sales.demo_meeting], ["Proposal", sales.proposal], ["Payment issues", sales.payment_issues]]} />
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
          <section className="rounded-xl border bg-card p-5 sm:p-6 space-y-4">
            <div><h3 className="font-semibold">Lead trend</h3><p className="text-xs text-muted-foreground mt-1">Created leads by UTC day. Converted shows how many from each day are customers now.</p></div>
            {(sales.trend || []).length ? <div className="h-64" role="img" aria-label="Daily leads created and currently converted">
              <ResponsiveContainer width="100%" height="100%"><AreaChart data={sales.trend} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="date" tickFormatter={(value) => value.slice(5)} minTickGap={25} fontSize={11} /><YAxis allowDecimals={false} fontSize={11} /><Tooltip />
                <Area type="monotone" dataKey="leads" name="Total leads" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.18} />
                <Area type="monotone" dataKey="converted" name="Converted" stroke="#10b981" fill="#10b981" fillOpacity={0.25} />
              </AreaChart></ResponsiveContainer>
            </div> : <p className="text-sm text-muted-foreground">No leads to chart for this selection.</p>}
          </section>
          <BarChart title="Sales stages" description="Current lead stage counts. These are separate from AI qualification results." items={[["Demo / meeting", sales.demo_meeting, "bg-sky-500"], ["Proposal", sales.proposal, "bg-violet-500"], ["Payment issues", sales.payment_issues, "bg-amber-500"], ["Converted", sales.converted, "bg-emerald-500"]]} />
        </div>
        <section className="rounded-xl border bg-card p-5 sm:p-6 space-y-3"><h3 className="font-semibold">Current CRM stages</h3><p className="text-xs text-muted-foreground">Every lead appears in one current stage.</p><div className="flex flex-wrap gap-2">{(sales.stages || []).map(({ key, count }) => <span key={key} className="rounded-full border bg-muted/40 px-3 py-1.5 text-sm">{stageLabel(key)} <strong className="ml-1 tabular-nums">{count}</strong></span>)}</div></section>
        <p className="text-xs text-muted-foreground leading-relaxed">Percentages use total leads in this selection. Junk and not qualified are separate, based on the latest saved qualification. Converted means Won, customer, or a recorded conversion. Demo, proposal and payment issues count leads in matching CRM stages; add those stages in CRM Settings if your pipeline uses them. Trashed leads are excluded.</p>
      </>}
    </>}
  </div>;
}
