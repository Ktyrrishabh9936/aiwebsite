import { useState } from "react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";
import { useSalesPeople } from "./SalesTeam";

export default function ShareLead({ wsId, lead, onUpdated }) {
  const people = useSalesPeople(wsId);
  const [agentId, setAgentId] = useState("");
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const share = lead.lead_share;
  const shareLead = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/workspaces/${wsId}/crm/sales-team/leads/${lead.id}/share`, { sales_agent_id: agentId });
      setLink(`${window.location.origin}${data.share_path}`);
      onUpdated(data.lead);
      toast.success("Lead assigned. The agent can view it after signing in.");
    } catch (error) { toast.error(formatError(error.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const revoke = async () => {
    setBusy(true);
    try { const { data } = await api.delete(`/workspaces/${wsId}/crm/sales-team/leads/${lead.id}/share`); setLink(""); setAgentId(""); onUpdated(data); toast.success("Sharing revoked and sales agent unassigned"); }
    catch (error) { toast.error(formatError(error.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(link); toast.success("Lead link copied"); }
    catch { toast.error("Select and copy the link below"); }
  };
  return <section className="rounded-lg border bg-primary/5 p-4 space-y-3">
    <h4 className="text-sm font-semibold">Share lead</h4>
    <p className="text-xs text-muted-foreground">Invite the agent to this workspace first. Only the assigned agent can open the lead after signing in. Reassignment removes the previous agent's access.</p>
    {share && <p className="text-sm">Shared with <strong>{share.agent_name}</strong></p>}
    {!share && lead.sales_assignment?.sales_agent_name && <p className="text-sm text-muted-foreground">Assigned to {lead.sales_assignment.sales_agent_name}</p>}
    <div className="flex flex-wrap gap-2"><select aria-label="Agent to share lead with" value={agentId} disabled={busy} onChange={(event) => setAgentId(event.target.value)} className="min-w-0 flex-1 h-10 rounded-lg border bg-background px-2 text-sm"><option value="">Choose an available sales agent</option>{people.filter((person) => person.active && person.role === "sales_agent").map((person) => <option key={person.id} value={person.id}>{person.name}</option>)}</select><button type="button" onClick={shareLead} disabled={busy || !agentId} className="rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50">{busy ? "Saving…" : share ? "Reassign & share" : "Share with agent"}</button>{(share || lead.sales_assignment?.sales_agent_id) && <button type="button" disabled={busy} onClick={revoke} className="rounded-lg border px-3 py-2 text-sm font-medium text-destructive disabled:opacity-50">Revoke / unassign</button>}</div>
    {people.filter((person) => person.active && person.role === "sales_agent").length === 0 && <p className="text-xs text-muted-foreground">Add or activate a sales agent in the Sales team tab first.</p>}
    {link && <div className="space-y-2"><label className="block text-xs text-muted-foreground">Lead link<input aria-label="Lead link" readOnly value={link} onFocus={(event) => event.target.select()} className="mt-1 h-10 w-full rounded-lg border bg-background px-3 text-sm" /></label><button type="button" onClick={copy} className="rounded-lg border px-3 py-2 text-sm font-semibold">Copy link</button><p className="text-xs text-muted-foreground">The previous agent loses access when you revoke or reassign this lead.</p></div>}
  </section>;
}
