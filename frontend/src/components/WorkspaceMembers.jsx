import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";
import { useSalesPeople } from "./SalesTeam";

export default function WorkspaceMembers({ wsId }) {
  const people = useSalesPeople(wsId);
  const [data, setData] = useState({ items: [], invitations: [] });
  const [personId, setPersonId] = useState("");
  const [email, setEmail] = useState("");
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => { try { const response = await api.get(`/workspaces/${wsId}/members`); setData({ items: [], invitations: [], ...response.data }); setError(""); } catch (err) { setError(formatError(err.response?.data?.detail)); } }, [wsId]);
  useEffect(() => { load(); }, [load]);
  const invite = async (event) => {
    event.preventDefault(); setBusy(true);
    try { const response = await api.post(`/workspaces/${wsId}/members/invite`, { sales_person_id: personId, email }); setLink(`${window.location.origin}${response.data.invite_path}`); await load(); toast.success("Invitation created. Copy the link and share it with the invited person."); }
    catch (err) { toast.error(formatError(err.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const toggle = async (member) => { setBusy(true); try { await api.patch(`/workspaces/${wsId}/members/${encodeURIComponent(member.id)}`, { active: !member.active }); await load(); toast.success(member.active ? "Workspace access revoked" : "Workspace access restored"); } catch (err) { toast.error(formatError(err.response?.data?.detail)); } finally { setBusy(false); } };
  const revoke = async (invitation) => { setBusy(true); try { await api.delete(`/workspaces/${wsId}/members/invitations/${encodeURIComponent(invitation.id)}`); setLink(""); await load(); } catch (err) { toast.error(formatError(err.response?.data?.detail)); } finally { setBusy(false); } };
  return <section className="rounded-xl border bg-card p-5 space-y-4">
    <h3 className="font-semibold">Workspace login & access</h3><p className="text-sm text-muted-foreground">Invite an existing sales agent or channel partner. Their login grants access only to their permitted leads and personal performance. Invitations expire in seven days.</p>
    <form onSubmit={invite} className="flex flex-wrap gap-3"><select aria-label="Person to invite" value={personId} required onChange={(event) => { setPersonId(event.target.value); setEmail(people.find((person) => person.id === event.target.value)?.email || ""); }} className="min-w-0 flex-1 h-10 rounded-lg border bg-background px-2 text-sm"><option value="">Choose active sales person</option>{people.filter((person) => person.active).map((person) => <option key={person.id} value={person.id} label={`${person.name} (${person.role === "sales_agent" ? "Sales agent" : "Channel partner"})`} />)}</select><input aria-label="Invitation email" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="Their login email" className="h-10 flex-1 min-w-0 rounded-lg border bg-background px-3 text-sm" /><button disabled={busy || !personId} className="h-10 rounded-lg bg-primary text-primary-foreground px-4 text-sm font-semibold disabled:opacity-50">Create invitation</button></form>
    {link && <label className="block text-sm">Invitation link<input readOnly value={link} onFocus={(event) => event.target.select()} className="mt-1 h-10 w-full rounded-lg border bg-background px-3 text-sm" /><button type="button" onClick={async () => { try { await navigator.clipboard.writeText(link); toast.success("Invitation copied"); } catch { toast.error("Select and copy the invitation link"); } }} className="mt-2 rounded-lg border px-3 py-2 text-sm">Copy invitation</button></label>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <div className="space-y-2">{data.items.map((member) => <div key={member.id} className="flex items-center justify-between gap-3 rounded-lg border p-3 text-sm"><div><strong>{member.name}</strong><p className="text-xs text-muted-foreground">{member.email} · {member.role.replaceAll("_", " ")} · {member.active ? "Access active" : "Access revoked"}</p></div><button type="button" disabled={busy} onClick={() => toggle(member)} className="rounded-lg border px-3 py-2 text-xs font-semibold disabled:opacity-50">{member.active ? "Revoke access" : "Restore access"}</button></div>)}{data.invitations.map((invitation) => <div key={invitation.id} className="flex items-center justify-between gap-3 rounded-lg border p-3 text-sm"><span>{invitation.email} <span className="text-muted-foreground">· Invitation pending</span></span><button disabled={busy} type="button" onClick={() => revoke(invitation)} className="text-xs underline">Revoke invitation</button></div>)}</div>
  </section>;
}
