import { useEffect, useState } from "react";
import { MessageSquare } from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";

const EMPTY = { enabled: false, account_sid: "", auth_token: "", from_number: "", messaging_service_sid: "", token_present: false };

export default function TwilioSmsSettings({ wsId }) {
  const [settings, setSettings] = useState(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    api.get(`/workspaces/${wsId}/crm/sms/config`).then(({ data }) => {
      if (active) setSettings({ ...EMPTY, ...data, auth_token: "" });
    }).catch((error) => {
      if (active) toast.error(formatError(error.response?.data?.detail));
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [wsId]);

  const set = (field, value) => setSettings((current) => ({ ...current, [field]: value }));
  const save = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      const { data } = await api.put(`/workspaces/${wsId}/crm/sms/config`, {
        enabled: settings.enabled,
        account_sid: settings.account_sid.trim(),
        auth_token: settings.auth_token.trim(),
        from_number: settings.from_number.trim(),
        messaging_service_sid: settings.messaging_service_sid.trim(),
      });
      setSettings({ ...EMPTY, ...data, auth_token: "" });
      toast.success("Twilio SMS settings saved");
    } catch (error) {
      toast.error(formatError(error.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="rounded-xl border bg-card p-5 space-y-4 xl:col-span-2">
      <div>
        <h3 className="font-bold flex items-center gap-2"><MessageSquare className="w-4 h-4 text-primary" /> Twilio SMS</h3>
        <p className="mt-1 text-sm text-muted-foreground">Send SMS to a lead from their saved phone number. Twilio charges for sent messages.</p>
      </div>
      {loading ? <p className="text-sm text-muted-foreground">Loading SMS settings…</p> : (
        <form onSubmit={save} className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-sm font-medium">Account SID
              <input value={settings.account_sid} onChange={(event) => set("account_sid", event.target.value)} placeholder="AC…" autoComplete="off" className="h-10 w-full rounded-lg border bg-background px-3 text-sm" required />
            </label>
            <label className="space-y-1 text-sm font-medium">Auth Token
              <input value={settings.auth_token} onChange={(event) => set("auth_token", event.target.value)} placeholder={settings.token_present ? "Saved — leave blank to keep" : "Enter Auth Token"} type="password" autoComplete="new-password" className="h-10 w-full rounded-lg border bg-background px-3 text-sm" required={!settings.token_present} />
            </label>
            <label className="space-y-1 text-sm font-medium">Twilio sender number or ID
              <input value={settings.from_number} onChange={(event) => set("from_number", event.target.value)} placeholder="+15551234567 or BRAND" className="h-10 w-full rounded-lg border bg-background px-3 text-sm" />
            </label>
            <label className="space-y-1 text-sm font-medium">Messaging Service SID (optional)
              <input value={settings.messaging_service_sid} onChange={(event) => set("messaging_service_sid", event.target.value)} placeholder="MG…" className="h-10 w-full rounded-lg border bg-background px-3 text-sm" />
            </label>
          </div>
          <p className="text-xs text-muted-foreground">Enter a sender number, alphanumeric sender ID, or Messaging Service SID. If both are set, the Messaging Service is used. For Indian numbers, confirm Twilio sender and template requirements before sending.</p>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <label className="flex items-center gap-2 text-sm font-medium"><input type="checkbox" checked={settings.enabled} onChange={(event) => set("enabled", event.target.checked)} /> Enable SMS sending</label>
            <button type="submit" disabled={saving || (!settings.from_number && !settings.messaging_service_sid)} className="h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50">{saving ? "Saving…" : "Save Twilio settings"}</button>
          </div>
        </form>
      )}
    </section>
  );
}
