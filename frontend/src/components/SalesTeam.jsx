import { useCallback, useEffect, useRef, useState } from "react";
import api, { formatError } from "../lib/api";
import { toast } from "sonner";
import WorkspaceMembers from "./WorkspaceMembers";

export function useSalesPeople(wsId) {
  const [people, setPeople] = useState([]);
  useEffect(() => {
    let active = true;
    const refresh = () => api.get(`/workspaces/${wsId}/crm/sales-team`).then(({ data }) => { if (active) setPeople(data.items || []); }).catch(() => {});
    refresh();
    window.addEventListener("crm:sales-team-updated", refresh);
    return () => { active = false; window.removeEventListener("crm:sales-team-updated", refresh); };
  }, [wsId]);
  return people;
}

export function SalesAssignment({ wsId, lead, onUpdated }) {
  const people = useSalesPeople(wsId);
  const [draft, setDraft] = useState(lead.sales_assignment || {});
  const [saving, setSaving] = useState(false);
  const locked = lead.customer_status === "customer" || lead.status === "won";
  useEffect(() => setDraft(lead.sales_assignment || {}), [lead.sales_assignment]);
  const save = async () => {
    setSaving(true);
    try { const { data } = await api.put(`/workspaces/${wsId}/crm/sales-team/leads/${lead.id}`, draft); onUpdated(data); toast.success("Sales assignment saved"); }
    catch (error) { toast.error(formatError(error.response?.data?.detail)); }
    finally { setSaving(false); }
  };
  return <section className="rounded-lg border bg-muted/20 p-4 space-y-3">
    <h4 className="text-sm font-semibold">Sales ownership & lead source</h4>
    <div className="grid sm:grid-cols-2 gap-3">
      {[["sales_agent_id", "Sales agent", "sales_agent"], ["channel_partner_id", "Channel partner", "channel_partner"], ["introduced_by_id", "Lead brought by", null]].map(([key, label, role]) => <label key={key} className="text-sm">{label}<select disabled={locked} value={draft[key] || ""} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} className="mt-1 h-10 w-full rounded-lg border bg-background px-2"><option value="">None</option>{people.filter((person) => (!role || person.role === role) && (person.active || person.id === draft[key])).map((person) => <option key={person.id} value={person.id}>{person.name}{!person.active ? " (inactive)" : ""}</option>)}</select></label>)}
      <label className="text-sm">Acquisition channel<select disabled={locked} value={draft.acquisition_channel || "direct"} onChange={(event) => setDraft({ ...draft, acquisition_channel: event.target.value })} className="mt-1 h-10 w-full rounded-lg border bg-background px-2"><option value="direct">Direct enquiry</option><option value="marketing">Marketing</option><option value="referral">Referral</option></select></label>
    </div>
    <div className="flex justify-between gap-3 items-center"><p className="text-xs text-muted-foreground">{locked ? "Sales credit is locked after conversion." : "Assignment and introduction credit are tracked separately for the linked property."}</p>{!locked && <button onClick={save} disabled={saving} className="shrink-0 px-3 py-2 rounded-lg border text-sm font-semibold disabled:opacity-50">{saving ? "Saving…" : "Save assignment"}</button>}</div>
  </section>;
}

export default function SalesTeam({ wsId }) {
  const [, setPeople] = useState([]);
  const [report, setReport] = useState(null);
  const [propertyId, setPropertyId] = useState("");
  const [draft, setDraft] = useState({ name: "", role: "sales_agent", phone: "", email: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [updatingId, setUpdatingId] = useState("");
  const togglePending = useRef(false);
  const load = useCallback(async () => {
    try { const [team, performance] = await Promise.all([api.get(`/workspaces/${wsId}/crm/sales-team`), api.get(`/workspaces/${wsId}/crm/sales-team/performance/summary`, { params: { property_id: propertyId } })]); setPeople(team.data.items); setReport(performance.data); setError(""); }
    catch (err) { setError(formatError(err.response?.data?.detail)); }
  }, [wsId, propertyId]);
  useEffect(() => { load(); }, [load]);
  const add = async (event) => { event.preventDefault(); setSaving(true); try { await api.post(`/workspaces/${wsId}/crm/sales-team`, draft); setDraft({ name: "", role: "sales_agent", phone: "", email: "" }); await load(); window.dispatchEvent(new Event("crm:sales-team-updated")); } catch (err) { toast.error(formatError(err.response?.data?.detail)); } finally { setSaving(false); } };
  const toggle = async (person) => {
    if (!person || togglePending.current) return;
    togglePending.current = true;
    setUpdatingId(person.id);
    const active = !person.active;
    try {
      await api.patch(`/workspaces/${wsId}/crm/sales-team/${person.id}`, { active });
      setPeople((current) => current.map((item) => item.id === person.id ? { ...item, active } : item));
      setReport((current) => current ? { ...current, items: current.items.map((item) => item.id === person.id ? { ...item, active } : item) } : current);
      window.dispatchEvent(new Event("crm:sales-team-updated"));
      toast.success(active ? "Sales person reactivated" : "Sales person deactivated");
    } catch (err) { toast.error(formatError(err.response?.data?.detail)); }
    finally { togglePending.current = false; setUpdatingId(""); }
  };
  const money = (minor) => new Intl.NumberFormat(undefined, { style: "currency", currency: report?.currency || "INR", maximumFractionDigits: 0 }).format(minor / 100);
  return <div className="space-y-5">
    <WorkspaceMembers wsId={wsId} />
    <section className="rounded-xl border bg-card p-5 space-y-4"><h3 className="font-semibold">Sales agents & channel partners</h3><p className="text-sm text-muted-foreground">Manage sales contacts, assignments, and referral credit.</p><form onSubmit={add} className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3"><input aria-label="Sales person name" required placeholder="Name" value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} className="h-10 px-3 rounded-lg border bg-background text-sm" /><select aria-label="Sales person role" value={draft.role} onChange={(event) => setDraft({ ...draft, role: event.target.value })} className="h-10 px-2 rounded-lg border bg-background text-sm"><option value="sales_agent">Sales agent</option><option value="channel_partner">Channel partner</option></select>{["phone", "email"].map((key) => <input key={key} aria-label={`Sales person ${key}`} placeholder={key === "phone" ? "Phone (optional)" : "Email (optional)"} type={key === "email" ? "email" : "tel"} value={draft[key]} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} className="h-10 px-3 rounded-lg border bg-background text-sm" />)}<button disabled={saving} className="h-10 rounded-lg bg-primary text-primary-foreground text-sm font-semibold">{saving ? "Adding…" : "Add person"}</button></form></section>
    <section className="rounded-xl border bg-card p-5 space-y-4"><div className="flex flex-wrap justify-between gap-3"><h3 className="font-semibold">Sales & lead contribution</h3><select aria-label="Performance property" value={propertyId} onChange={(event) => setPropertyId(event.target.value)} className="h-10 px-3 rounded-lg border bg-background text-sm"><option value="">All properties</option>{report?.properties.map((property) => <option key={property.id} value={property.id}>{property.name}</option>)}</select></div><p className="text-xs text-muted-foreground">Sales value is booked deal value, not collected payments. A deal assigned to both roles appears under each person; do not add their totals together. Trashed leads are excluded.</p>{error && <p className="text-sm text-destructive">{error}</p>}{!report && !error && <p className="text-sm text-muted-foreground">Loading performance…</p>}<div className="overflow-x-auto"><table className="w-full text-sm text-left"><thead className="text-muted-foreground"><tr>{["Name / role", "Assigned", "Sales", "Sales value", "Brought leads", "Marketing", "Referrals", "Brought → sales", "Status"].map((label) => <th key={label} className="p-3 whitespace-nowrap font-medium">{label}</th>)}</tr></thead><tbody>{report?.items.map((row) => <tr key={row.id} className="border-t"><td className="p-3 font-medium">{row.name}<span className="block text-xs text-muted-foreground">{row.role === "sales_agent" ? "Sales agent" : "Channel partner"}</span></td>{[row.assigned_leads, row.sales, money(row.sales_minor), row.introduced_leads, row.marketing_leads, row.referral_leads, row.introduced_sales].map((value, index) => <td key={index} className="p-3 whitespace-nowrap">{value}</td>)}<td className="p-3"><span className={`block mb-2 text-xs font-semibold ${row.active ? "text-emerald-500" : "text-muted-foreground"}`}>{row.active ? "Active" : "Inactive"}</span><button type="button" disabled={Boolean(updatingId)} onClick={() => toggle(row)} className="text-xs underline underline-offset-4 disabled:opacity-50">{updatingId === row.id ? "Saving..." : row.active ? "Deactivate" : "Reactivate"}</button></td></tr>)}</tbody></table>{report?.items.length === 0 && <p className="p-4 text-sm text-muted-foreground">Add your first sales agent or channel partner above.</p>}</div></section>
  </div>;
}
