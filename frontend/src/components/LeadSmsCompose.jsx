import { useEffect, useState } from "react";
import { MessageSquare, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";
import { whatsappPhone } from "./LeadWhatsAppCompose";

function draftFor(name) {
  const first = String(name || "").trim().split(/\s+/)[0];
  return `Hi${first ? ` ${first}` : ""}, following up on your enquiry. Let me know if you would like more details.`;
}

export default function LeadSmsCompose({ open, onOpenChange, wsId, lead, apiBase, onSent }) {
  const [config, setConfig] = useState(null);
  const [history, setHistory] = useState([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [refreshing, setRefreshing] = useState("");
  const base = apiBase || `/workspaces/${wsId}/crm/sms`;
  const phone = (lead?.field_values || {}).phone || lead?.phone;
  const recipient = whatsappPhone(phone);
  const validPhone = /^\+[1-9]\d{7,14}$/.test(recipient);
  const leadName = lead?.full_name || lead?.field_values?.full_name;

  useEffect(() => {
    if (!open || !lead?.id) return;
    let active = true;
    setConfig(null);
    setHistory([]);
    setText(draftFor(leadName));
    Promise.all([api.get(`${base}/config`), api.get(`${base}/leads/${lead.id}`)])
      .then(([settings, messages]) => { if (active) { setConfig(settings.data); setHistory(messages.data); } })
      .catch((error) => { if (active) toast.error(formatError(error.response?.data?.detail)); });
    return () => { active = false; };
  }, [open, base, lead?.id, leadName]);

  const send = async () => {
    setSending(true);
    try {
      const { data } = await api.post(`${base}/leads/${lead.id}`, { text: text.trim() });
      setHistory((current) => [data, ...current]);
      if (onSent) await onSent();
      setText("");
      toast.success("SMS submitted to Twilio. Check delivery status below.");
    } catch (error) {
      toast.error(formatError(error.response?.data?.detail));
    } finally {
      setSending(false);
    }
  };

  const refresh = async (message) => {
    setRefreshing(message.id);
    try {
      const { data } = await api.post(`${base}/leads/${lead.id}/${message.id}/refresh`, {});
      setHistory((current) => current.map((item) => item.id === data.id ? data : item));
    } catch (error) {
      toast.error(formatError(error.response?.data?.detail));
    } finally {
      setRefreshing("");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[90dvh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><MessageSquare className="h-5 w-5 text-primary" /> Send SMS</DialogTitle>
          <DialogDescription>Send from your Twilio account to this lead’s saved number.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <p className="rounded-lg border bg-muted/40 px-3 py-2 text-sm">To <strong>{recipient || "No phone number"}</strong></p>
          {!validPhone && <p className="text-sm text-amber-500">Save a valid phone number with country code on this lead before sending.</p>}
          {config && (!config.configured || !config.enabled) && <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm">Configure and enable Twilio SMS in CRM Settings first.</p>}
          <label className="block space-y-1.5 text-sm font-medium">Message
            <textarea aria-label="SMS message" value={text} onChange={(event) => setText(event.target.value)} rows={5} maxLength={1600} className="w-full resize-y rounded-lg border bg-background p-3 text-sm leading-relaxed" />
          </label>
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-muted-foreground">{text.length}/1600 characters · SMS may use multiple billable segments</span>
            <button type="button" onClick={send} disabled={sending || !config?.enabled || !config?.configured || !validPhone || !text.trim()} className="h-10 shrink-0 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50">{sending ? "Sending…" : "Send SMS"}</button>
          </div>
          <div className="space-y-2 border-t pt-4">
            <h4 className="text-sm font-semibold">Recent SMS</h4>
            {history.length === 0 && <p className="text-sm text-muted-foreground">No SMS sent from this CRM yet.</p>}
            {history.map((message) => <div key={message.id} className="rounded-lg border bg-muted/20 p-3 text-sm">
              <div className="flex items-center justify-between gap-2"><span className="font-semibold capitalize">{message.status || "Unknown"}{message.error_code ? ` · Error ${message.error_code}` : ""}</span><button type="button" onClick={() => refresh(message)} disabled={refreshing === message.id} className="inline-flex items-center gap-1 text-xs text-primary disabled:opacity-50"><RefreshCw className={`h-3.5 w-3.5 ${refreshing === message.id ? "animate-spin" : ""}`} /> Refresh</button></div>
              <p className="mt-1 whitespace-pre-wrap break-words">{message.body}</p>
              <p className="mt-2 text-xs text-muted-foreground">{message.to} · {new Date(message.created_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</p>
            </div>)}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
