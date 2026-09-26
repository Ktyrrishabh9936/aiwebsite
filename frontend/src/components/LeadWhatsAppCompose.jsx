import { useEffect, useState } from "react";
import { ExternalLink, MessageCircle } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";

export function whatsappPhone(phone) {
  const raw = String(phone || "").trim();
  const digits = raw.replace(/\D/g, "");
  if (raw.startsWith("+") && /^\+[1-9]\d{7,14}$/.test(`+${digits}`)) return `+${digits}`;
  if (digits.length === 10) return `+91${digits}`;
  return raw;
}

export function whatsappLink(phone, message) {
  const recipient = whatsappPhone(phone);
  const text = String(message || "").trim();
  if (!/^\+[1-9]\d{7,14}$/.test(recipient) || !text) return "";
  return `https://wa.me/${recipient.slice(1)}?text=${encodeURIComponent(text)}`;
}

function suggestedMessage(name) {
  const firstName = String(name || "").trim().split(/\s+/)[0];
  return `Hi${firstName ? ` ${firstName}` : ""}, following up on your enquiry. Let me know if you would like more details.`;
}

export default function LeadWhatsAppCompose({ open, onOpenChange, phone, leadName, onMarkSent }) {
  const [recipient, setRecipient] = useState("");
  const [message, setMessage] = useState("");
  const [opened, setOpened] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setRecipient(whatsappPhone(phone));
    setMessage(suggestedMessage(leadName));
    setOpened(false);
  }, [open, phone, leadName]);

  const link = whatsappLink(recipient, message);
  const markSent = async () => {
    setSaving(true);
    try {
      const saved = await onMarkSent({
        source: "manual_whatsapp",
        direction: "outbound",
        body: `To ${whatsappPhone(recipient)}\n${message.trim()}`,
      });
      if (saved) onOpenChange(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><MessageCircle className="h-5 w-5 text-emerald-500" /> WhatsApp message</DialogTitle>
          <DialogDescription>Review or edit the message before opening WhatsApp.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <label className="block space-y-1.5 text-sm font-medium">Recipient number
            <input aria-label="WhatsApp recipient number" value={recipient} onChange={(event) => { setRecipient(event.target.value); setOpened(false); }} placeholder="+919876543210" className="h-10 w-full rounded-lg border bg-background px-3 text-sm" />
          </label>
          <p className="text-xs text-muted-foreground">A 10-digit lead number starts with +91 by default. Check the country code before opening WhatsApp.</p>
          <label className="block space-y-1.5 text-sm font-medium">Message
            <textarea aria-label="WhatsApp message" value={message} onChange={(event) => { setMessage(event.target.value); setOpened(false); }} rows={5} className="w-full resize-y rounded-lg border bg-background p-3 text-sm leading-relaxed" />
          </label>
          {!link && <p className="text-xs text-amber-500">Enter a message and a phone number with country code.</p>}
          <a href={link || undefined} target="_blank" rel="noopener noreferrer" onClick={() => { if (link) setOpened(true); }} aria-disabled={!link} className={`flex h-10 items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 text-sm font-semibold text-white ${link ? "hover:bg-emerald-700" : "pointer-events-none opacity-50"}`}><ExternalLink className="h-4 w-4" /> Open WhatsApp</a>
          <div className="flex items-center justify-between gap-3 border-t pt-3">
            <p className="text-xs text-muted-foreground">Opening WhatsApp does not send the message. Record it only after sending.</p>
            <button type="button" onClick={markSent} disabled={!opened || saving} className="shrink-0 rounded-lg border px-3 py-2 text-xs font-semibold disabled:opacity-40">{saving ? "Saving..." : "Mark sent"}</button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
