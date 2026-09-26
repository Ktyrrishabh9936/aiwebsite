import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import api from "../lib/api";
import QualificationReview from "./QualificationReview";
import { qualificationError } from "../pages/sections/Qualification";

export default function LeadQualificationPanel({ lead, readOnly = false, apiBase }) {
  const { wsId } = useParams();
  const [profiles, setProfiles] = useState([]);
  const [selected, setSelected] = useState(lead.qualification_profile_id || "");
  const [history, setHistory] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadingProfiles, setLoadingProfiles] = useState(true);
  const base = apiBase || `/workspaces/${wsId}/crm/qualification`;
  const result = lead.qualification_call?.engine_result;
  useEffect(() => { setSelected(lead.qualification_profile_id || ""); }, [lead.id, lead.qualification_profile_id]);
  useEffect(() => {
    if (readOnly) { setLoadingProfiles(false); return undefined; }
    let live = true;
    setProfiles([]); setLoadingProfiles(true); setError("");
    api.get(`${base}/profiles`).then(({ data }) => { if (live) setProfiles(data.profiles); }).catch((e) => { if (live) setError(qualificationError(e)); }).finally(() => { if (live) setLoadingProfiles(false); });
    return () => { live = false; };
  }, [base, lead.id, readOnly]);
  useEffect(() => {
    let live = true;
    api.get(`${base}/leads/${lead.id}/history`).then(({ data }) => { if (live) setHistory(data); }).catch((e) => { if (live) setError(qualificationError(e)); });
    return () => { live = false; };
  }, [base, lead.id, lead.updated_at]);
  const assign = async (id) => {
    setBusy(true); setError("");
    try { await api.put(`${base}/leads/${lead.id}/profile`, { profile_id: id || null }); setSelected(id); }
    catch (e) { setError(qualificationError(e)); } finally { setBusy(false); }
  };
  return <section className="rounded-xl border bg-card p-4 space-y-3">
    <div className="flex justify-between items-center gap-2"><h3 className="font-semibold">Qualification engine</h3>{!readOnly && <Link to={`/app/w/${wsId}/qualification`} className="text-xs text-primary">Configure profiles</Link>}</div>
    {!readOnly && <label className="block text-xs text-muted-foreground">Profile for the next call<select aria-label="Lead qualification profile" disabled={busy || loadingProfiles} value={selected} onChange={(e) => assign(e.target.value)} className="block w-full mt-1 rounded-md border bg-background p-2 text-sm"><option value="">Use campaign / workspace default</option>{profiles.map((p) => <option key={p.id} value={p.id}>{p.product_name}</option>)}</select></label>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {lead.qualification_processing?.status === "processing" && <p role="status" className="text-sm text-primary">Processing the latest call facts…</p>}
    {lead.qualification_processing?.status === "failed" && <p role="alert" className="text-sm text-destructive">The last call event could not be processed. The saved result below may be from an earlier event; a webhook retry is needed.</p>}
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">{Object.entries({ "Lead status": result?.lead_status || lead.lead_status || "NEW", "Call outcome": result?.call_outcome || lead.call_outcome || "No result", "Score": result?.qualification_score ?? "Not scored", "Temperature": result?.lead_temperature || "Not assigned", "Extraction confidence": result ? `${result.confidence_score}%` : "Not assessed", "Attempts": lead.call_attempt_count || 0 }).map(([label, value]) => <div key={label}><div className="text-xs text-muted-foreground">{label}</div><div className="font-medium mt-1">{String(value).replaceAll("_", " ")}</div></div>)}</div>
    {result ? <><p className="text-sm">{result.disqualification_reason || result.qualification_reason}</p><p className="text-sm">Next action: <strong>{result.next_action.replaceAll("_", " ")}</strong>{result.retry_eligible ? " · Retry eligible" : ""}</p>{lead.qualification_call?.scheduled_for && <p className="text-xs">Scheduled: {new Date(lead.qualification_call.scheduled_for).toLocaleString([], { dateStyle: "medium", timeStyle: "short", hour12: true })}</p>}{result.missing_information?.length > 0 && <p className="text-sm text-amber-600">Missing: {result.missing_information.join(", ")}</p>}<details className="text-sm"><summary className="cursor-pointer">Collected facts and score breakdown</summary><pre className="overflow-auto text-xs bg-secondary p-3 mt-2 rounded">{JSON.stringify({ facts: result.qualification_data, score_breakdown: result.score_breakdown }, null, 2)}</pre></details></> : <p className="text-xs text-muted-foreground">No engine result yet. The next completed call will appear here.</p>}
    {lead.do_not_call && <p className="text-sm text-destructive font-semibold">Do not call: future calls are blocked.</p>}
    <details className="text-sm"><summary className="cursor-pointer">Call decision history ({history.length})</summary><div className="mt-2 space-y-2">{history.map((call) => <div key={call.id} className="border rounded-md p-3 text-xs space-y-1"><p>{new Date(call.created_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short", hour12: true })} · {call.result?.call_outcome || "Processing"}</p><p>{call.result?.lead_status} · Score: {call.result?.qualification_score ?? "Not scored"}</p><p>{call.result?.disqualification_reason || call.result?.qualification_reason}</p><p className="text-muted-foreground">Profile: {call.profile_snapshot?.product_name || "Pending"}</p></div>)}</div></details>
    {!readOnly && <QualificationReview lead={lead} wsId={wsId} />}
  </section>;
}
