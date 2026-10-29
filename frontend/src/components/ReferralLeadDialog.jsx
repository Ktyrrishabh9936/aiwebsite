import { useEffect, useState } from "react";
import { Plus, XCircle } from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";

const BLANK = { full_name: "", phone: "", email: "", property_id: "", acquisition_channel: "referral" };
const inputClass = "mt-1 h-10 w-full rounded-lg border bg-background px-3 text-sm";

// Shared members add the leads they introduce; the owner's CRM records their introduction credit.
export default function ReferralLeadDialog({ apiBase, onClose, onCreated }) {
  const [draft, setDraft] = useState(BLANK);
  const [properties, setProperties] = useState([]);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    let live = true;
    api.get(`${apiBase}/properties`).then(({ data }) => { if (live) setProperties(data.items || []); }).catch(() => {});
    return () => { live = false; };
  }, [apiBase]);
  const set = (key, value) => setDraft({ ...draft, [key]: value });
  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      const { data } = await api.post(`${apiBase}/leads`, draft);
      toast.success("Lead added with your introduction credit. No automatic AI call was triggered.");
      onCreated(data);
    } catch (error) { toast.error(formatError(error.response?.data?.detail)); }
    finally { setSaving(false); }
  };
  return (
    <div className="fixed inset-0 z-[60] bg-background/80 backdrop-blur-sm p-4 grid place-items-center">
      <form onSubmit={submit} className="w-full max-w-2xl rounded-xl border bg-card shadow-xl">
        <div className="flex items-start justify-between gap-4 p-5 border-b">
          <div>
            <h3 className="font-bold text-lg">Add referral / marketing lead</h3>
            <p className="text-xs text-muted-foreground mt-1">The lead is credited to you and shared with you in this workspace.</p>
          </div>
          <button type="button" onClick={onClose} className="p-1 rounded-lg hover:bg-accent text-muted-foreground" title="Close"><XCircle className="w-5 h-5" /></button>
        </div>
        <div className="p-5 grid sm:grid-cols-2 gap-3">
          <label className="text-sm">Name<input required value={draft.full_name} onChange={(e) => set("full_name", e.target.value)} className={inputClass} /></label>
          <label className="text-sm">Phone<input required type="tel" value={draft.phone} onChange={(e) => set("phone", e.target.value)} className={inputClass} /></label>
          <label className="text-sm">Email (optional)<input type="email" value={draft.email} onChange={(e) => set("email", e.target.value)} className={inputClass} /></label>
          <label className="text-sm">Property<select value={draft.property_id} onChange={(e) => set("property_id", e.target.value)} className={inputClass}><option value="">Not yet selected</option>{properties.map((property) => <option key={property.id} value={property.id}>{property.name}</option>)}</select></label>
          <label className="text-sm">Source<select value={draft.acquisition_channel} onChange={(e) => set("acquisition_channel", e.target.value)} className={inputClass}><option value="referral">Referral</option><option value="marketing">Marketing</option></select></label>
        </div>
        <div className="p-5 border-t flex flex-wrap items-center justify-end gap-2">
          <button type="button" onClick={onClose} className="px-3 h-9 rounded-lg border bg-background hover:bg-accent text-sm font-semibold">Cancel</button>
          <button disabled={saving} className="inline-flex items-center gap-2 px-3 h-9 rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50"><Plus className="w-4 h-4" /> Add lead</button>
        </div>
      </form>
    </div>
  );
}
