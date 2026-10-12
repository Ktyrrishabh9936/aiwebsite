import { useCallback, useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, ChevronDown, MessageSquare, PhoneCall } from "lucide-react";
import api from "../../lib/api";
import VoiceProviders from "../VoiceProviders";
import TwilioSmsSettings from "../TwilioSmsSettings";

function ChannelCard({ icon: Icon, title, description, benefit, connected, open, onToggle, children }) {
  return (
    <section className={`overflow-hidden rounded-2xl border bg-card transition ${open ? "ring-2 ring-primary/20" : ""}`}>
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-start gap-4 p-5 text-left hover:bg-accent/40">
        <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${connected ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" : "bg-primary/10 text-primary"}`}><Icon className="h-5 w-5" /></span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">{title}</span>
            {connected
              ? <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-600 dark:text-emerald-400"><CheckCircle2 className="h-3 w-3" />Connected</span>
              : <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">Optional</span>}
          </span>
          <span className="mt-1 block text-sm text-muted-foreground">{description}</span>
          <span className="mt-2 block text-xs font-medium text-primary">{benefit}</span>
        </span>
        <ChevronDown className={`mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && <div className="border-t bg-background/60 p-4 sm:p-5">{children}</div>}
    </section>
  );
}

/** Optional voice agent and SMS configuration during onboarding. */
export default function ChannelsStep({ wsId, onContinue, onSkip }) {
  const [open, setOpen] = useState("");
  const [voice, setVoice] = useState(false);
  const [sms, setSms] = useState(false);

  const refresh = useCallback(() => {
    api.get(`/workspaces/${wsId}/voice-providers`).then(({ data }) => setVoice((data || []).some((p) => p.enabled))).catch(() => {});
    api.get(`/workspaces/${wsId}/crm/sms/config`).then(({ data }) => setSms(Boolean(data?.enabled))).catch(() => {});
  }, [wsId]);
  useEffect(() => { refresh(); }, [refresh]);
  const toggle = (key) => { setOpen((o) => (o === key ? "" : key)); refresh(); };

  return (
    <div className="space-y-4">
      <ChannelCard icon={PhoneCall} title="Voice agent" connected={voice} open={open === "voice"} onToggle={() => toggle("voice")}
        description="Connect Plivo or Sarvam so your AI calls and qualifies every new lead."
        benefit="Leads contacted within minutes convert up to several times better.">
        <VoiceProviders workspaceId={wsId} />
      </ChannelCard>
      <ChannelCard icon={MessageSquare} title="SMS" connected={sms} open={open === "sms"} onToggle={() => toggle("sms")}
        description="Connect Twilio to text leads straight from their CRM record."
        benefit="Reach the leads who don't pick up the phone.">
        <TwilioSmsSettings wsId={wsId} />
      </ChannelCard>
      <div className="flex flex-col-reverse items-stretch gap-3 pt-2 sm:flex-row sm:items-center sm:justify-between">
        <button type="button" onClick={onSkip} className="h-11 rounded-xl px-4 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-foreground">Skip to dashboard</button>
        <button type="button" onClick={onContinue} className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-primary px-6 text-sm font-semibold text-primary-foreground hover:bg-primary/90">
          {voice || sms ? "Continue" : "I'll do this later"}<ArrowRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
