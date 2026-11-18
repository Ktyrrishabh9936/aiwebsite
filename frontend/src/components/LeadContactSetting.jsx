import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";

export const CONTACT_OPTIONS = [
  { value: "normal", label: "Normal", help: "The AI may call and email this lead when the daily plan says so." },
  { value: "do_not_call", label: "Do not call", help: "The AI never calls this lead again. Emails are still allowed." },
  { value: "no_contact", label: "Completed · no contact", help: "Everything is finished with this lead. The AI never calls, emails or raises work for them. Only you contact them." },
];

/** The setting a lead is on. A call can set do-not-call by itself (the lead asked), so that counts too. */
export const contactPreference = (lead) => lead?.contact_preference && lead.contact_preference !== "normal" ? lead.contact_preference
  : lead?.do_not_call ? "do_not_call" : "normal";

export function ContactBadge({ lead }) {
  const value = contactPreference(lead);
  if (value === "normal") return null;
  return <span className={`inline-block text-[11px] uppercase px-1.5 py-0.5 rounded border ${value === "no_contact" ? "border-slate-400/50 text-slate-600 dark:text-slate-300" : "border-destructive/40 text-destructive"}`}>{value === "no_contact" ? "Completed · no contact" : "Do not call"}</span>;
}

/**
 * Who the AI may contact. Kept apart from the pipeline stage: a lead can be Won, Lost or anything else
 * and separately be "do not call" or "completed, no contact".
 */
export default function LeadContactSetting({ wsId, lead, onUpdated, disabled }) {
  const saved = contactPreference(lead);
  const [value, setValue] = useState(saved);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setValue(saved); setReason(""); }, [lead.id, saved]);

  const save = async () => {
    setBusy(true);
    try {
      const { data } = await api.patch(`/workspaces/${wsId}/crm/leads/${lead.id}/contact-preference`, { preference: value, reason: reason.trim() });
      onUpdated?.(data);
      setReason("");
      toast.success(value === "normal" ? "The AI may contact this lead again." : value === "do_not_call" ? "Saved. The AI will never call this lead." : "Saved. The AI will not contact this lead.");
    } catch (error) {
      toast.error(formatError(error.response?.data?.detail || error.message));
    } finally { setBusy(false); }
  };

  const option = CONTACT_OPTIONS.find((item) => item.value === value);
  return (
    <div className="rounded-lg border bg-background p-3 space-y-2" aria-label="AI contact setting">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-semibold">AI contact</span>
        <ContactBadge lead={lead} />
      </div>
      <select aria-label="AI contact setting" value={value} disabled={disabled || busy} onChange={(e) => setValue(e.target.value)}
        className="w-full sm:max-w-sm h-10 px-3 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary">
        {CONTACT_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select>
      <p className="text-xs text-muted-foreground">{option?.help} This is separate from the stage, so Won and Lost stay as they are.</p>
      {value !== saved && <div className="flex flex-wrap gap-2">
        {value !== "normal" && <input value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} placeholder="Reason (optional), saved as a note"
          aria-label="Reason" className="h-9 min-w-0 flex-1 px-3 rounded-lg border bg-background text-sm" />}
        <button type="button" disabled={busy} onClick={save} className="h-9 rounded-lg bg-primary px-3 text-sm font-semibold text-primary-foreground disabled:opacity-50">{busy ? "Saving…" : "Save"}</button>
        <button type="button" disabled={busy} onClick={() => setValue(saved)} className="h-9 rounded-lg border px-3 text-sm">Cancel</button>
      </div>}
    </div>
  );
}
