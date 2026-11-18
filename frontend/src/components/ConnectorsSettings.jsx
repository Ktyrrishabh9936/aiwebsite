import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Loader2, MessageSquare, PhoneCall } from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";

// Mail servers of the common providers, so most people only type their email and password.
const MAIL_SERVERS = {
  "gmail.com": "smtp.gmail.com", "googlemail.com": "smtp.gmail.com", "outlook.com": "smtp-mail.outlook.com", "hotmail.com": "smtp-mail.outlook.com",
  "live.com": "smtp-mail.outlook.com", "yahoo.com": "smtp.mail.yahoo.com", "yahoo.in": "smtp.mail.yahoo.com", "zoho.com": "smtp.zoho.com",
  "zoho.in": "smtp.zoho.in", "icloud.com": "smtp.mail.me.com", "rediffmail.com": "smtp.rediffmail.com",
};
const serverFor = (email) => { const domain = (email.split("@")[1] || "").trim().toLowerCase(); return domain ? MAIL_SERVERS[domain] || `smtp.${domain}` : ""; };

/* Small brand-coloured marks so each connector is recognisable at a glance. */
function Mark({ kind }) {
  const box = "grid h-11 w-11 shrink-0 place-items-center rounded-xl";
  if (kind === "email") return <span className={`${box} bg-red-500/10`} aria-hidden="true"><svg viewBox="0 0 24 24" className="h-6 w-6"><rect x="2" y="5" width="20" height="14" rx="2.5" fill="#fff" stroke="#EA4335" strokeWidth="1.6" /><path d="M3.5 7.5 12 13.5l8.5-6" fill="none" stroke="#EA4335" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg></span>;
  if (kind === "google-calendar") return <span className={`${box} bg-blue-500/10`} aria-hidden="true"><svg viewBox="0 0 24 24" className="h-6 w-6"><rect x="3" y="4" width="18" height="17" rx="3" fill="#fff" stroke="#4285F4" strokeWidth="1.6" /><rect x="3" y="4" width="18" height="5" rx="2" fill="#4285F4" /><text x="12" y="18" textAnchor="middle" fontSize="8" fontWeight="700" fill="#4285F4" fontFamily="Arial, sans-serif">31</text></svg></span>;
  if (kind === "calendly") return <span className={`${box} bg-sky-500/10`} aria-hidden="true"><svg viewBox="0 0 24 24" className="h-6 w-6"><circle cx="12" cy="12" r="9" fill="#fff" stroke="#006BFF" strokeWidth="1.8" /><path d="M15.5 9.2a4.2 4.2 0 1 0 0 5.6" fill="none" stroke="#006BFF" strokeWidth="2" strokeLinecap="round" /></svg></span>;
  const Icon = kind === "voice" ? PhoneCall : MessageSquare;
  return <span className={`${box} bg-primary/10 text-primary`} aria-hidden="true"><Icon className="h-5 w-5" /></span>;
}

function Row({ mark, name, status, connected, children, action }) {
  return (
    <li className="rounded-2xl border bg-background p-4 transition hover:border-primary/30">
      <div className="flex flex-wrap items-center gap-3">
        <Mark kind={mark} />
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-2 font-semibold">{name}{connected && <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-600 dark:text-emerald-400"><CheckCircle2 className="h-3 w-3" />Connected</span>}</p>
          <p className="truncate text-sm text-muted-foreground">{status}</p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">{action}</div>
      </div>
      {children}
    </li>
  );
}

const primary = "inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60";
const plain = "inline-flex h-10 items-center justify-center gap-2 rounded-xl border px-4 text-sm font-medium hover:bg-accent disabled:opacity-60";
const input = "mt-1 h-11 w-full rounded-xl border bg-card px-3.5 text-sm font-normal";

/** Connectors as a simple list: one row per service, one button to connect it. Email already works without setup. */
export default function ConnectorsSettings({ wsId, onOpenVoice }) {
  const [status, setStatus] = useState(null);
  const [voice, setVoice] = useState(null);
  const [open, setOpen] = useState(""); // which row's form is showing
  const [busy, setBusy] = useState("");
  const [mail, setMail] = useState({ email: "", password: "", host: "" });
  const [link, setLink] = useState("");

  const load = useCallback(() => api.get(`/workspaces/${wsId}/connectors`).then(({ data }) => { setStatus(data); setLink(data.calendly?.url || ""); })
    .catch((error) => toast.error(formatError(error.response?.data?.detail))), [wsId]);
  useEffect(() => { load(); api.get(`/workspaces/${wsId}/voice-agent`).then(({ data }) => setVoice(data)).catch(() => setVoice({})); }, [load, wsId]);
  useEffect(() => {
    // The Google sign-in window tells us when it finishes.
    const onMessage = (event) => {
      if (event.data?.type === "CONNECTOR_CONNECTED") { toast.success("Google connected"); setOpen(""); load(); }
      if (event.data?.type === "CONNECTOR_FAILED") toast.error("Google was not connected. Please try again.");
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [load]);

  const run = async (key, work, success) => {
    setBusy(key);
    try { const result = await work(); if (result?.data?.email) setStatus(result.data); if (success) toast.success(typeof success === "function" ? success(result) : success); return result || true; }
    catch (error) { toast.error(formatError(error.response?.data?.detail)); return null; }
    finally { setBusy(""); }
  };
  const google = (services) => run("google", async () => {
    const { data } = await api.post(`/workspaces/${wsId}/connectors/google/start`, { services });
    window.open(data.url, "arevei-google", "width=520,height=680");
  });
  const connectMail = async (event) => {
    event.preventDefault();
    const address = mail.email.trim();
    const result = await run("mail", () => api.put(`/workspaces/${wsId}/connectors/email/smtp`, { host: (mail.host || serverFor(address)).trim(), port: 587, username: address, password: mail.password, from_email: address, from_name: "" }), "Your email is connected");
    if (result) { setOpen(""); setMail({ email: "", password: "", host: "" }); }
  };
  const connectCalendly = async (event) => {
    event.preventDefault();
    if (await run("calendly", () => api.put(`/workspaces/${wsId}/connectors/calendly`, { url: link }), "Calendly connected")) setOpen("");
  };

  if (!status) return <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Loading connectors…</div>;
  const { email, google: account, calendly, calendar } = status;
  const ownEmail = email.mode !== "platform";
  const services = account.services || [];
  const spinner = (key) => busy === key && <Loader2 className="h-4 w-4 animate-spin" />;
  const knownServer = Boolean(MAIL_SERVERS[(mail.email.split("@")[1] || "").trim().toLowerCase()]);
  const voiceReady = Boolean(voice?.active_type && voice.calling_enabled && (voice.active_type !== "master" || voice.trial?.status === "active"));

  return (
    <ul className="space-y-3" aria-label="Connectors">
      <Row mark="email" name="Email" connected={ownEmail || email.platform_ready}
        status={ownEmail ? `Sending from ${email.sending_from}` : email.platform_ready ? `Working now from ${email.sending_from}. Nothing to set up.` : "Not available yet. Connect your own email."}
        action={ownEmail
          ? <button type="button" disabled={busy === "mail-off"} onClick={() => run("mail-off", () => (email.mode === "smtp" ? api.delete(`/workspaces/${wsId}/connectors/email/smtp`) : api.patch(`/workspaces/${wsId}/connectors/google`, { send_email: false })), "Back to the built-in email")} className={plain}>{spinner("mail-off")}Disconnect</button>
          : <button type="button" onClick={() => setOpen(open === "email" ? "" : "email")} aria-expanded={open === "email"} className={plain}>Use my own email</button>}>
        {email.smtp?.last_error && <p role="alert" className="mt-3 text-xs text-amber-600">The last email from your account failed, so the built-in email was used. Reconnect with the correct password.</p>}
        {open === "email" && !ownEmail && (
          <div className="mt-4 animate-fade-up space-y-4 border-t pt-4">
            <button type="button" disabled={busy === "google"} onClick={() => (services.includes("gmail") ? run("gmail-on", () => api.patch(`/workspaces/${wsId}/connectors/google`, { send_email: true }), "Sending from your Gmail") : google([...new Set([...services, "gmail"])]))} className={`${primary} w-full sm:w-auto`}>{spinner("google")}Continue with Gmail</button>
            <form onSubmit={connectMail} className="space-y-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Or another email account</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-sm font-medium">Email address<input required type="email" value={mail.email} onChange={(e) => setMail({ ...mail, email: e.target.value })} placeholder="sales@yourcompany.com" autoComplete="off" className={input} /></label>
                <label className="text-sm font-medium">Password<input required type="password" value={mail.password} onChange={(e) => setMail({ ...mail, password: e.target.value })} autoComplete="new-password" className={input} /></label>
                {mail.email.includes("@") && !knownServer && <label className="text-sm font-medium sm:col-span-2">Mail server<input value={mail.host || serverFor(mail.email)} onChange={(e) => setMail({ ...mail, host: e.target.value })} className={input} /><span className="mt-1 block text-xs font-normal text-muted-foreground">We guessed this from your address. Change it only if your email provider gave you a different one.</span></label>}
              </div>
              <p className="text-xs text-muted-foreground">Some providers need an “app password” instead of your normal one. The password is stored encrypted.</p>
              <button disabled={busy === "mail"} className={primary}>{spinner("mail")}Connect</button>
            </form>
          </div>
        )}
        <button type="button" disabled={busy === "test"} onClick={() => run("test", () => api.post(`/workspaces/${wsId}/connectors/email/test`), (r) => `Test sent to ${r.data.sent_to}`)} className="mt-3 text-xs font-semibold text-primary hover:underline disabled:opacity-60">{busy === "test" ? "Sending…" : "Send me a test email"}</button>
      </Row>

      <Row mark="google-calendar" name="Google Calendar" connected={calendar.google}
        status={calendar.google ? `${account.account_email}. Meetings are booked when you are free.` : account.status === "reconnect_required" ? "Access expired. Connect again." : "Book meetings only when you are free."}
        action={calendar.google
          ? <button type="button" disabled={busy === "google-off"} onClick={() => run("google-off", () => api.delete(`/workspaces/${wsId}/connectors/google`), "Google disconnected")} className={plain}>{spinner("google-off")}Disconnect</button>
          : <button type="button" disabled={busy === "google"} onClick={() => google([...new Set([...services, "calendar"])])} className={primary}>{spinner("google")}Connect</button>} />

      <Row mark="calendly" name="Calendly" connected={calendly.connected}
        status={calendly.connected ? `${calendly.url.replace("https://", "")}. Leads who ask for a meeting get this link.` : "Leads who ask for a meeting get your booking link."}
        action={calendly.connected
          ? <><button type="button" onClick={() => setOpen(open === "calendly" ? "" : "calendly")} className={plain}>Change</button><button type="button" disabled={busy === "calendly-off"} onClick={() => run("calendly-off", () => api.delete(`/workspaces/${wsId}/connectors/calendly`), "Calendly disconnected")} className={plain}>{spinner("calendly-off")}Disconnect</button></>
          : <button type="button" onClick={() => setOpen(open === "calendly" ? "" : "calendly")} aria-expanded={open === "calendly"} className={primary}>Connect</button>}>
        {open === "calendly" && (
          <form onSubmit={connectCalendly} className="mt-4 flex animate-fade-up flex-wrap items-end gap-3 border-t pt-4">
            <label className="min-w-0 flex-1 text-sm font-medium">Your Calendly link<input required value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://calendly.com/your-name/30min" aria-label="Your Calendly link" className={input} /></label>
            <button disabled={busy === "calendly"} className={primary}>{spinner("calendly")}Save</button>
          </form>
        )}
      </Row>

      <Row mark="voice" name="Voice agent" connected={voiceReady}
        status={!voice ? "Checking…" : voiceReady ? `${voice.profile?.agent_name || voice.dedicated?.agent_name || "Your agent"} is making calls${voice.active_type === "master" ? ` · free trial, ${voice.trial.days_left} days left` : ""}` : voice.active_type ? "Calling is paused or the trial has ended." : "Calls every new lead and follows up by phone."}
        action={onOpenVoice ? <button type="button" onClick={onOpenVoice} className={voiceReady ? plain : primary}>{voiceReady ? "Open" : "Set up"}</button>
          : <Link to={`/app/w/${wsId}/ai?agent=voice`} className={voiceReady ? plain : primary}>{voiceReady ? "Open" : "Set up"}</Link>} />

      <Row mark="sms" name="SMS" status="Text leads from the CRM with your Twilio number." action={<Link to={`/app/w/${wsId}/settings#sms`} className={plain}>Open</Link>} />
    </ul>
  );
}
