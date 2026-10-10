import { useEffect, useState } from "react";
import { Link, useNavigate, useOutletContext } from "react-router-dom";
import api from "../../lib/api";

export default function Customers() {
  const { ws } = useOutletContext();
  const nav = useNavigate();
  const [data, setData] = useState(null), [error, setError] = useState(""), [page, setPage] = useState(1);
  const [search, setSearch] = useState(""), [selected, setSelected] = useState(null);
  const [request, setRequest] = useState(""), [kind, setKind] = useState("upsell"), [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController(); setData(null); setSelected(null); setError("");
    api.get(`/workspaces/${ws.id}/crm/customers`, { params: { page, search }, signal: controller.signal }).then(({data: result}) => { if (!controller.signal.aborted) setData(result); }).catch(() => { if (!controller.signal.aborted) setError("Could not load customers. Try again."); });
    return () => controller.abort();
  }, [ws.id, page, search]);
  const removeCustomer = async customer => {
    if (!window.confirm(`Delete ${customer.name} from the customer list? CRM deals and payment history will be preserved.`)) return;
    setBusy(true); setError("");
    try { await api.delete(`/workspaces/${ws.id}/crm/customers/${customer.id}`); setData(current => ({...current, total: current.total-1, items: current.items.filter(item=>item.id!==customer.id)})); setSelected(null); }
    catch { setError("Could not delete customer. Try again."); }
    finally { setBusy(false); }
  };
  const repeat = async e => {
    e.preventDefault(); setBusy(true); setError("");
    try { const { data: lead } = await api.post(`/workspaces/${ws.id}/crm/customers/${selected.id}/opportunities`, { request, kind }); nav(`/app/w/${ws.id}/crm?lead=${lead.id}`); }
    catch (err) { setError(typeof err.response?.data?.detail === "string" ? err.response.data.detail : "Could not create this opportunity."); }
    finally { setBusy(false); }
  };
  const money = value => `${ws.currency || "INR"} ${Number(value).toLocaleString()}`;
  return <div className="p-6 sm:p-10 max-w-7xl mx-auto space-y-6"><div><h1 className="text-3xl font-bold">Customers & lifecycle</h1><p className="text-muted-foreground mt-2">Customer relationships, collected lifetime value and repeat opportunities.</p><p className="text-sm text-muted-foreground mt-1">Won deals awaiting payment are shown separately from fully paid customers. LTV includes collected receipts, including archived linked deals.</p></div>
    <input aria-label="Search customers" placeholder="Search name, phone or email" value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} className="rounded-lg border bg-background p-3 w-full max-w-md"/>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {!data && !error && <p>Loading customers...</p>}
    {data && <><p className="text-sm text-muted-foreground">{data.total} customer relationships</p><div className="overflow-x-auto rounded-xl border"><table className="w-full text-sm"><thead className="bg-muted/40"><tr>{["Customer", "Lifecycle", "Collected LTV", "Outstanding", "Open deals", ""].map((label,i)=><th key={i} className="p-4 text-left">{label}</th>)}</tr></thead><tbody>{data.items.map(customer => <tr key={customer.id} className="border-t"><td className="p-4"><button className="font-semibold text-primary" onClick={() => { setSelected(customer); setRequest(""); }}>{customer.name}</button><p className="text-muted-foreground mt-1">{customer.email || customer.phone}</p></td><td className="p-4">{customer.lifecycle === "customer" ? "Customer · fully paid" : "Won · payment pending"}{customer.archived && " · archived"}</td><td className="p-4">{money(customer.ltv)}{customer.capped && " (partial)"}</td><td className="p-4">{money(customer.outstanding)}</td><td className="p-4">{customer.open_opportunities}</td><td className="p-4"><button className="rounded-lg border px-3 py-2" onClick={() => { setSelected(customer); setRequest(""); }}>View lifecycle</button><button disabled={busy || customer.archived} className="ml-2 rounded-lg bg-primary text-primary-foreground px-3 py-2" onClick={()=>{setSelected(customer);setKind("upsell");setRequest("");setTimeout(()=>document.querySelector('[aria-label="Requested product or service"]')?.focus(),0);}}>Add upsell lead</button><button disabled={busy} className="ml-2 px-3 py-2 text-destructive" onClick={()=>removeCustomer(customer)}>Delete customer</button></td></tr>)}</tbody></table>{!data.items.length && <p className="p-6 text-muted-foreground">No customers yet. Won and converted leads will appear here.</p>}</div><div className="flex gap-4 items-center"><button disabled={page===1} onClick={()=>setPage(page-1)} className="border rounded-lg px-3 py-2 disabled:opacity-40">Previous</button><span>Page {page}</span><button disabled={page*data.limit>=data.total} onClick={()=>setPage(page+1)} className="border rounded-lg px-3 py-2 disabled:opacity-40">Next</button></div></>}
    {selected && <section className="rounded-xl border bg-card p-6 space-y-5"><div className="flex justify-between"><h2 className="text-xl font-bold">{selected.name} · lifecycle</h2><button onClick={()=>setSelected(null)}>Close</button></div><p>Collected LTV: <strong>{money(selected.ltv)}</strong></p><div className="space-y-3">{selected.deals.map(deal=><article key={deal.id} className="rounded-lg border p-4"><Link className="font-semibold text-primary" to={`/app/w/${ws.id}/crm?lead=${deal.id}`}>{deal.request}</Link><p className="mt-2 text-sm text-muted-foreground">{deal.kind} · {deal.status} · Collected {money(deal.paid)} · Due {money(deal.due)}{deal.archived && " · archived"}</p></article>)}</div>{!selected.archived && <form onSubmit={repeat} className="space-y-3 border-t pt-5"><h3 className="font-semibold">New product or service request</h3><select aria-label="Opportunity type" className="rounded-lg border bg-background p-3" value={kind} onChange={e=>setKind(e.target.value)}><option value="upsell">Upsell</option><option value="cross_sell">Cross-sell</option><option value="repeat_purchase">Repeat purchase</option></select><textarea aria-label="Requested product or service" required maxLength={2000} value={request} onChange={e=>setRequest(e.target.value)} placeholder="Describe what the customer has requested" className="block w-full rounded-lg border bg-background p-3"/><p className="text-sm text-muted-foreground">Creates a linked CRM opportunity. Original payments stay with the original deal. No automatic qualification call is scheduled.</p><button disabled={busy || !request.trim()} className="rounded-lg bg-primary text-primary-foreground px-4 py-3 disabled:opacity-50">{busy ? "Creating..." : "Create repeat opportunity"}</button></form>}</section>}
  </div>;
}
