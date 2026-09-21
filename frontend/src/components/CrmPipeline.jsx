import { useEffect, useState } from "react";
import api, { formatError } from "../lib/api";

function Column({ stage, wsId, search, states, onSelect, onChanged, revision }) {
  const [items, setItems] = useState([]), [total, setTotal] = useState(0), [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => { setPage(0); }, [search, revision]);
  useEffect(() => {
    let live = true; setLoading(true); setError("");
    api.get(`/workspaces/${wsId}/crm/pipeline`, { params: { status: stage.key, search, offset: page * 30, limit: 30 } }).then(({ data }) => { if (live) { setItems(data.items); setTotal(data.total); } }).catch((e) => { if (live) setError(formatError(e.response?.data?.detail || e.message)); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [wsId, stage.key, search, page, revision]);
  const move = async (lead, status) => {
    setBusy(true); setError("");
    try { const { data } = await api.patch(`/workspaces/${wsId}/crm/pipeline/leads/${lead.id}`, { status }); onChanged(data); }
    catch (e) { setError(formatError(e.response?.data?.detail || e.message)); }
    finally { setBusy(false); }
  };
  return <section className="w-64 shrink-0 rounded-xl border bg-secondary/20 flex flex-col max-h-[70dvh]" aria-label={`${stage.label} pipeline`}>
    <header className="p-3 flex justify-between border-b text-sm font-semibold"><span>{stage.label}</span><span className="rounded-full bg-background border px-2 text-xs py-0.5">{total}</span></header>
    <div className="p-3 space-y-3 overflow-y-auto min-h-28">
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
      {loading ? <p className="text-xs text-muted-foreground">Loading leads…</p> : <>{!items.length && <p className="text-xs text-muted-foreground py-5 text-center">No leads in this stage</p>}{items.map((lead) => { const values = lead.field_values || {}; return <article key={lead.id} className="rounded-lg border bg-card shadow-sm p-3 space-y-3">
        <button onClick={() => onSelect(lead.id)} className="block w-full text-left rounded focus-visible:ring-2 focus-visible:ring-ring"><p className="text-sm font-semibold break-words">{values.full_name || lead.full_name || values.phone || lead.phone || "Unnamed lead"}</p><p className="text-xs text-muted-foreground mt-1">{values.phone || lead.phone || "No phone"}</p><p className="text-[11px] text-muted-foreground mt-2">{lead.lead_status?.replaceAll("_", " ") || "New lead"}</p></button>
        <select aria-label={`Move ${values.full_name || lead.full_name || "lead"} to stage`} disabled={busy} value={lead.status} onChange={(e) => move(lead, e.target.value)} className="w-full border rounded-md bg-background p-1.5 text-xs">{states.map((state) => <option key={state.key} value={state.key}>{state.label}</option>)}</select>
      </article>; })}</>}
    </div>
    {total > 30 && <footer className="p-3 flex justify-between text-xs border-t"><button disabled={!page || loading} onClick={() => setPage((v) => v - 1)}>Previous</button><span>{page + 1} / {Math.ceil(total / 30)}</span><button disabled={(page + 1) * 30 >= total || loading} onClick={() => setPage((v) => v + 1)}>Next</button></footer>}
  </section>;
}

export default function CrmPipeline({ wsId, states, search, onSelect, onChanged, statusFilter, revision }) {
  return <div><p className="text-xs text-muted-foreground mb-3">Open a card to view the lead. Use its stage menu to move it through your pipeline.</p><div className="flex gap-4 overflow-x-auto pb-4" aria-label="CRM Kanban board">{states.filter((stage) => statusFilter === "all" || stage.key === statusFilter).map((stage) => <Column key={stage.key} {...{ stage, wsId, search, states, onSelect, onChanged, revision }} />)}</div></div>;
}
