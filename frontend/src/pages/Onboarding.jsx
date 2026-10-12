import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  ArrowLeft, ArrowRight, Bot, Briefcase, Building2, Check, CheckCircle2, Clock, Globe, Headphones, Home, Loader2,
  Megaphone, MessageCircle, Mic, Rocket, Search, Share2, Sparkles, Store, UserRound, Users, Wand2,
} from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";
import { useAuth } from "../context/AuthContext";
import SetupHelpCard, { AREVEI_CONTACT } from "../components/onboarding/SetupHelpCard";
import InterviewChat from "../components/onboarding/InterviewChat";
import ChannelsStep from "../components/onboarding/ChannelsStep";
import SetupChecklist from "../components/onboarding/SetupChecklist";

const ROLES = [
  { value: "founder", label: "Founder / Owner", icon: Rocket },
  { value: "marketer", label: "Marketer", icon: Megaphone },
  { value: "real_estate_broker", label: "Real Estate Broker", icon: Home },
  { value: "sales_leader", label: "Sales Leader", icon: Users },
  { value: "agency", label: "Agency", icon: Briefcase },
  { value: "other", label: "Other", icon: UserRound },
];
const SOURCES = [
  { value: "social_media", label: "Social media", icon: Share2 },
  { value: "chatgpt_ai", label: "ChatGPT / AI tools", icon: Sparkles },
  { value: "whatsapp", label: "WhatsApp", icon: MessageCircle },
  { value: "google_search", label: "Google search", icon: Search },
  { value: "referral", label: "Friend / referral", icon: Users },
  { value: "event", label: "Event / office visit", icon: Store },
  { value: "other", label: "Other", icon: Globe },
];
const SUBSTEPS = [
  { key: "interview", label: "Business & strategy" },
  { key: "channels", label: "Voice & SMS" },
  { key: "done", label: "Ready" },
];
const ORDER = ["about", "setup", "interview", "channels", "done"];
const MOBILE_INDEX = { about: 0, setup: 1, interview: 1, channels: 2, done: 3 };

function Choice({ option, selected, onSelect }) {
  const Icon = option.icon;
  return (
    <button type="button" onClick={() => onSelect(option.value)} aria-pressed={selected}
      className={`group flex items-center gap-3 rounded-xl border px-3.5 py-3 text-left text-sm transition ${selected ? "border-primary bg-primary/5 ring-2 ring-primary/20" : "bg-card hover:border-primary/40 hover:bg-accent/40"}`}>
      <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg transition ${selected ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground group-hover:text-foreground"}`}><Icon className="h-4 w-4" /></span>
      <span className="flex-1 font-medium">{option.label}</span>
      {selected && <Check className="h-4 w-4 text-primary" />}
    </button>
  );
}

function Stepper({ step }) {
  const at = ORDER.indexOf(step);
  const main = [
    { label: "Create account", done: true },
    { label: "About you", done: at > 0, active: at === 0 },
    { label: "AI Manager setup", done: false, active: at >= 1 },
  ];
  return (
    <ol className="space-y-1" aria-label="Onboarding progress">
      {main.map((item, i) => (
        <li key={item.label}>
          <div className={`flex items-center gap-3 rounded-lg px-2 py-2 text-sm ${item.active ? "font-semibold" : item.done ? "text-muted-foreground" : "text-muted-foreground/70"}`}>
            <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-bold ${item.done ? "bg-emerald-500 text-white" : item.active ? "bg-primary text-primary-foreground" : "border bg-background"}`}>{item.done ? <Check className="h-3.5 w-3.5" /> : i + 1}</span>
            {item.label}
          </div>
          {i === 2 && at >= 2 && (
            <ol className="ml-[22px] mt-1 space-y-1 border-l pl-5">
              {SUBSTEPS.map((s) => {
                const sat = ORDER.indexOf(s.key);
                return <li key={s.key} className={`flex items-center gap-2 py-1 text-xs ${sat === at ? "font-semibold text-foreground" : sat < at ? "text-muted-foreground" : "text-muted-foreground/60"}`}>{sat < at ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> : <span className={`h-2 w-2 rounded-full ${sat === at ? "bg-primary" : "bg-muted-foreground/30"}`} />}{s.label}</li>;
              })}
            </ol>
          )}
        </li>
      ))}
    </ol>
  );
}

function StepHeader({ eyebrow, title, description }) {
  return (
    <div className="mb-6">
      <p className="text-xs font-bold uppercase tracking-[0.18em] text-primary">{eyebrow}</p>
      <h1 className="mt-2 text-2xl font-bold tracking-tight sm:text-3xl">{title}</h1>
      {description && <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">{description}</p>}
    </div>
  );
}

function AboutStep({ initial, onDone }) {
  const [role, setRole] = useState(initial.role || "");
  const [roleOther, setRoleOther] = useState(initial.role_other || "");
  const [heard, setHeard] = useState(initial.heard_from || "");
  const [heardOther, setHeardOther] = useState(initial.heard_from_other || "");
  const [website, setWebsite] = useState("");
  const [noSite, setNoSite] = useState(false);
  const [businessName, setBusinessName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const needsWorkspace = !initial.workspace_id;
  const ready = role && heard && (role !== "other" || roleOther.trim()) && (!needsWorkspace || (noSite ? businessName.trim() : website.trim()));

  const submit = async (event) => {
    event.preventDefault();
    if (!ready) return;
    setBusy(true); setError("");
    try {
      await api.put("/onboarding/profile", { role, role_other: roleOther, heard_from: heard, heard_from_other: heardOther });
      let workspaceId = initial.workspace_id;
      if (!workspaceId) {
        let url = website.trim();
        if (url && !/^https?:\/\//i.test(url)) url = `https://${url}`;
        const modules = role === "real_estate_broker" ? { real_estate: true, agency: false } : role === "agency" ? { real_estate: false, agency: true } : undefined;
        const { data } = await api.post("/workspaces", noSite ? { name: businessName.trim(), modules } : { website_url: url, modules });
        workspaceId = data.id;
        localStorage.setItem("arevei_onboarded", "1");
      }
      const { data } = await api.put("/onboarding/step", { step: "setup", workspace_id: workspaceId });
      onDone(data, workspaceId);
    } catch (err) {
      setError(formatError(err.response?.data?.detail) || "Something went wrong. Please try again.");
    } finally { setBusy(false); }
  };

  return (
    <form onSubmit={submit} className="space-y-8">
      <StepHeader eyebrow="Step 2 of 3 · About you" title="Tell us a little about yourself" description="This helps your AI Manager tailor its questions, suggestions and setup to you." />
      <fieldset>
        <legend className="mb-3 text-sm font-semibold">What best describes you?</legend>
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">{ROLES.map((o) => <Choice key={o.value} option={o} selected={role === o.value} onSelect={setRole} />)}</div>
        {role === "other" && <input autoFocus value={roleOther} onChange={(e) => setRoleOther(e.target.value)} placeholder="Your role" aria-label="Your role" className="mt-3 h-11 w-full rounded-xl border bg-background px-3.5 text-sm sm:max-w-sm" />}
      </fieldset>
      <fieldset>
        <legend className="mb-3 text-sm font-semibold">How did you hear about Arevei?</legend>
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">{SOURCES.map((o) => <Choice key={o.value} option={o} selected={heard === o.value} onSelect={setHeard} />)}</div>
        {["other", "event"].includes(heard) && <input value={heardOther} onChange={(e) => setHeardOther(e.target.value)} placeholder={heard === "event" ? "Which event or location?" : "Tell us where"} aria-label="Where did you hear about us" className="mt-3 h-11 w-full rounded-xl border bg-background px-3.5 text-sm sm:max-w-sm" />}
      </fieldset>
      {needsWorkspace && (
        <fieldset className="rounded-2xl border bg-card p-5">
          <legend className="sr-only">Your business</legend>
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">{noSite ? <Building2 className="h-5 w-5" /> : <Globe className="h-5 w-5" />}</span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold">{noSite ? "What's your business called?" : "Your business website"}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{noSite ? "We'll build your AI's knowledge from your answers instead." : "Your AI learns your business from it in the background while you continue."}</p>
              {noSite
                ? <input autoFocus value={businessName} onChange={(e) => setBusinessName(e.target.value)} placeholder="e.g. Skyline Realty" aria-label="Business name" className="mt-3 h-11 w-full rounded-xl border bg-background px-3.5 text-sm" />
                : <input value={website} onChange={(e) => setWebsite(e.target.value)} type="text" inputMode="url" autoComplete="url" placeholder="yourcompany.com" aria-label="Website" className="mt-3 h-11 w-full rounded-xl border bg-background px-3.5 text-sm" />}
              <button type="button" onClick={() => setNoSite((v) => !v)} className="mt-2 text-xs font-medium text-primary hover:underline">{noSite ? "I have a website" : "I don't have a website yet"}</button>
            </div>
          </div>
        </fieldset>
      )}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <button disabled={!ready || busy} className="inline-flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-primary px-6 text-sm font-semibold text-primary-foreground shadow-sm transition hover:bg-primary/90 disabled:opacity-50 sm:w-auto">
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}{busy ? "Setting up your workspace…" : "Continue"}{!busy && <ArrowRight className="h-4 w-4" />}
      </button>
    </form>
  );
}

function SetupChoiceStep({ wsId, onAi, onSkip, onAssisted }) {
  const [assist, setAssist] = useState(false);
  const [form, setForm] = useState({ phone: "", preferred_time: "", note: "" });
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const requestHelp = async (event) => {
    event.preventDefault(); setBusy(true);
    try { await api.post("/onboarding/assist", { ...form, workspace_id: wsId }); setSent(true); }
    catch (err) { toast.error(formatError(err.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const cards = [
    { key: "ai", icon: Wand2, title: "Set up with AI", badge: "Recommended", time: "About 8 minutes", body: "Chat with your AI Manager about your business and goals. It builds your sales strategy, then you connect voice and SMS.", action: onAi, primary: true },
    { key: "assist", icon: Headphones, title: "Contact Arevei for setup", time: "We reach out within 1 business day", body: "Our team configures your AI Manager, voice agent and lead sources for you.", action: () => setAssist(true) },
    { key: "skip", icon: ArrowRight, title: "Skip to dashboard", time: "Finish anytime", body: "Explore first. A setup checklist on your dashboard helps you finish later.", action: onSkip },
  ];
  if (sent) {
    return (
      <div className="mx-auto max-w-lg py-6 text-center">
        <span className="mx-auto grid h-16 w-16 place-items-center rounded-full bg-emerald-500/10 text-emerald-500"><CheckCircle2 className="h-8 w-8" /></span>
        <h1 className="mt-5 text-2xl font-bold">Request sent — we'll be in touch</h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">The Arevei team will contact you shortly to set everything up. You can also reach us anytime at <span className="font-semibold text-foreground">{AREVEI_CONTACT.name}</span> · <a className="font-semibold text-primary" href={`mailto:${AREVEI_CONTACT.email}`}>{AREVEI_CONTACT.email}</a>.</p>
        <div className="mt-6 flex flex-col justify-center gap-2 sm:flex-row">
          <button type="button" onClick={onAssisted} className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-primary px-6 text-sm font-semibold text-primary-foreground">Go to dashboard<ArrowRight className="h-4 w-4" /></button>
          <button type="button" onClick={onAi} className="h-11 rounded-xl border px-5 text-sm font-medium hover:bg-accent">Start with AI meanwhile</button>
        </div>
      </div>
    );
  }
  return (
    <div>
      <StepHeader eyebrow="Step 3 of 3 · AI Manager setup" title="How would you like to set up your AI Manager?" description="Your AI Manager needs to understand your business and sales goals to run your pipeline. Pick what works for you." />
      <div className="grid gap-3 lg:grid-cols-3">
        {cards.map((c) => (
          <button key={c.key} type="button" onClick={c.action} className={`group relative flex flex-col rounded-2xl border p-5 text-left transition hover:-translate-y-0.5 hover:shadow-md ${c.primary ? "border-primary/50 bg-gradient-to-br from-primary/10 via-card to-card ring-1 ring-primary/20" : "bg-card hover:border-primary/30"} ${assist && c.key === "assist" ? "ring-2 ring-primary/30" : ""}`}>
            {c.badge && <span className="absolute right-4 top-4 rounded-full bg-primary px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-primary-foreground">{c.badge}</span>}
            <span className={`grid h-11 w-11 place-items-center rounded-xl ${c.primary ? "bg-primary text-primary-foreground" : "bg-muted text-foreground"}`}><c.icon className="h-5 w-5" /></span>
            <span className="mt-4 text-base font-semibold">{c.title}</span>
            <span className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-primary"><Clock className="h-3 w-3" />{c.time}</span>
            <span className="mt-3 flex-1 text-sm leading-6 text-muted-foreground">{c.body}</span>
            <span className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-primary">{c.key === "ai" ? "Start setup" : c.key === "assist" ? "Request help" : "Go to dashboard"}<ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" /></span>
          </button>
        ))}
      </div>
      <AnimatePresence>
        {assist && (
          <motion.form initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} onSubmit={requestHelp} className="mt-4 overflow-hidden rounded-2xl border bg-card">
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <div className="sm:col-span-2"><p className="font-semibold">Let our team set it up for you</p><p className="text-sm text-muted-foreground">Share how to reach you. Or contact <span className="font-semibold text-foreground">{AREVEI_CONTACT.name}</span> at <a className="font-semibold text-primary" href={`mailto:${AREVEI_CONTACT.email}`}>{AREVEI_CONTACT.email}</a>.</p></div>
              <label className="text-xs font-semibold">Phone / WhatsApp<input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="+91 98765 43210" className="mt-1 h-11 w-full rounded-xl border bg-background px-3.5 text-sm font-normal" /></label>
              <label className="text-xs font-semibold">Best time to call<input value={form.preferred_time} onChange={(e) => setForm({ ...form, preferred_time: e.target.value })} placeholder="Weekdays after 4pm" className="mt-1 h-11 w-full rounded-xl border bg-background px-3.5 text-sm font-normal" /></label>
              <label className="text-xs font-semibold sm:col-span-2">Anything we should know? (optional)<textarea rows={2} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="e.g. We run Meta ads for 3 projects and want every lead called" className="mt-1 w-full rounded-xl border bg-background px-3.5 py-2.5 text-sm font-normal" /></label>
            </div>
            <div className="flex justify-end gap-2 border-t bg-muted/30 px-5 py-3">
              <button type="button" onClick={() => setAssist(false)} className="h-10 rounded-lg px-4 text-sm hover:bg-accent">Cancel</button>
              <button disabled={busy} className="inline-flex h-10 items-center gap-2 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground disabled:opacity-60">{busy && <Loader2 className="h-4 w-4 animate-spin" />}Request setup help</button>
            </div>
          </motion.form>
        )}
      </AnimatePresence>
    </div>
  );
}

function DoneStep({ wsId, onFinish }) {
  const [ws, setWs] = useState(null);
  useEffect(() => {
    let live = true;
    const load = () => api.get(`/workspaces/${wsId}`).then(({ data }) => { if (live) setWs(data); }).catch(() => {});
    load();
    const timer = setInterval(load, 5000);
    return () => { live = false; clearInterval(timer); };
  }, [wsId]);
  const status = ws?.strategy_status || (ws?.sales_strategy ? "ready" : null);
  const strategyLine = {
    ready: { icon: CheckCircle2, cls: "text-emerald-500", text: "Your sales strategy is ready." },
    building: { icon: Loader2, cls: "animate-spin text-primary", text: "Your AI Manager is writing your sales strategy…" },
    waiting_for_brain: { icon: Loader2, cls: "animate-spin text-primary", text: "Learning your website first, then writing your strategy…" },
    error: { icon: Bot, cls: "text-amber-500", text: "Strategy couldn't be built automatically — retry anytime from Brain → Sales strategy." },
  }[status];
  return (
    <div>
      <div className="relative overflow-hidden rounded-3xl border bg-gradient-to-br from-primary/15 via-card to-card p-6 sm:p-8">
        <span className="grid h-14 w-14 place-items-center rounded-2xl bg-primary text-primary-foreground shadow-lg shadow-primary/30"><Rocket className="h-7 w-7" /></span>
        <h1 className="mt-5 text-2xl font-bold tracking-tight sm:text-3xl">Your AI Manager is ready to work</h1>
        <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">Ask it anything from the chat bubble on every page — try “What should I focus on today?” or “What can you do?”.</p>
        {strategyLine && <p className="mt-4 inline-flex items-center gap-2 rounded-full bg-background/80 px-3 py-1.5 text-sm font-medium"><strategyLine.icon className={`h-4 w-4 ${strategyLine.cls}`} />{strategyLine.text}</p>}
      </div>
      <div className="mt-5"><SetupChecklist wsId={wsId} dismissible={false} title="Your setup checklist" /></div>
      <div className="mt-6 flex flex-col gap-2 sm:flex-row">
        <button type="button" onClick={() => onFinish("")} className="inline-flex h-12 items-center justify-center gap-2 rounded-xl bg-primary px-6 text-sm font-semibold text-primary-foreground shadow-sm hover:bg-primary/90">Go to dashboard<ArrowRight className="h-4 w-4" /></button>
        <button type="button" onClick={() => onFinish("/workflows/landing-forms")} className="inline-flex h-12 items-center justify-center gap-2 rounded-xl border px-5 text-sm font-medium hover:bg-accent">Connect your landing page form</button>
      </div>
    </div>
  );
}

export default function Onboarding() {
  const nav = useNavigate();
  const reduce = useReducedMotion();
  const { user, updateOnboarding } = useAuth();
  const [state, setState] = useState(null);
  const [wsId, setWsId] = useState("");
  const [ws, setWs] = useState(null);
  const savedStep = state?.step && ORDER.includes(state.step) ? state.step : "about";
  // Every step after "About you" needs the workspace created there.
  const step = wsId ? savedStep : "about";

  useEffect(() => {
    api.get("/onboarding").then(({ data }) => {
      // Completed users reaching /welcome are creating another workspace: start fresh.
      if (data.completed) { setState({ step: "about", role: data.role, heard_from: data.heard_from, role_other: data.role_other, heard_from_other: data.heard_from_other, fresh: true }); return; }
      setState(data);
      if (data.workspace_id) setWsId(data.workspace_id);
    }).catch(() => setState({ step: "about" }));
  }, []);

  useEffect(() => {
    if (!wsId) return;
    api.get(`/workspaces/${wsId}`).then(({ data }) => setWs(data)).catch(() => { setWsId(""); setState((s) => ({ ...s, step: "about", workspace_id: undefined })); });
  }, [wsId]);

  const go = useCallback(async (next) => {
    setState((s) => ({ ...s, step: next }));
    window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
    try { const { data } = await api.put("/onboarding/step", { step: next, workspace_id: wsId || undefined }); updateOnboarding(data); } catch { /* step is also kept locally */ }
  }, [wsId, updateOnboarding, reduce]);

  const finish = useCallback(async (skipped, path = "") => {
    try { const { data } = await api.post("/onboarding/complete", { skipped }); updateOnboarding(data); } catch { /* dashboard still opens */ }
    localStorage.setItem("arevei_onboarded", "1");
    nav(wsId ? `/app/w/${wsId}${path}` : "/app", { replace: true });
  }, [nav, wsId, updateOnboarding]);

  if (!state) return <div className="grid min-h-screen place-items-center text-muted-foreground"><Loader2 className="h-5 w-5 animate-spin" /></div>;
  const firstName = (user?.name || "").split(" ")[0];

  return (
    <div className="app-shell min-h-screen bg-background lg:grid lg:grid-cols-[300px_1fr]">
      <aside className="hidden border-r bg-card lg:flex lg:flex-col lg:p-6">
        <Logo />
        <div className="mt-10">
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">Getting started</p>
          <p className="mt-1 text-lg font-bold">Welcome{firstName ? `, ${firstName}` : ""} 👋</p>
          <div className="mt-6"><Stepper step={step} /></div>
        </div>
        <div className="mt-auto space-y-4">
          {ws && <div className="rounded-xl border bg-background p-3 text-xs"><p className="font-semibold">{ws.name}</p><p className="mt-1 flex items-center gap-1.5 text-muted-foreground">{ws.brain_status === "ready" ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> : ws.brain_status === "building" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Mic className="h-3.5 w-3.5" />}{ws.brain_status === "ready" ? "Business Brain trained" : ws.brain_status === "building" ? "Learning your website…" : "Brain builds from your answers"}</p></div>}
          <SetupHelpCard />
        </div>
      </aside>
      <div className="flex min-h-screen flex-col">
        <header className="flex h-16 items-center justify-between border-b bg-card/80 px-4 backdrop-blur sm:px-6 lg:justify-end">
          <span className="lg:hidden"><Logo /></span>
          <div className="flex items-center gap-2">
            {["interview", "channels"].includes(step) && <button type="button" onClick={() => go(step === "channels" ? "interview" : "setup")} className="hidden h-9 items-center gap-1.5 rounded-lg px-3 text-sm text-muted-foreground hover:bg-accent sm:inline-flex"><ArrowLeft className="h-4 w-4" />Back</button>}
            {step !== "about" && step !== "done" && <button type="button" onClick={() => finish(true)} className="h-9 rounded-lg px-3 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-foreground">Skip to dashboard</button>}
            <ThemeToggle />
          </div>
        </header>
        <div className="border-b px-4 py-3 lg:hidden">
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
            {["About you", "AI setup", "Voice & SMS", "Ready"].map((label, i) => (
              <span key={label} className={`flex-1 rounded-full py-1 text-center ${MOBILE_INDEX[step] === i ? "bg-primary text-primary-foreground" : MOBILE_INDEX[step] > i ? "bg-primary/15 text-primary" : "bg-muted"}`}>{label}</span>
            ))}
          </div>
        </div>
        <main className="flex-1 px-4 py-8 sm:px-8 lg:px-12 lg:py-12">
          <div className="mx-auto w-full max-w-4xl">
            <AnimatePresence mode="wait">
              <motion.div key={step} initial={reduce ? false : { opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={reduce ? undefined : { opacity: 0, y: -8 }} transition={{ duration: 0.2 }}>
                {step === "about" && <AboutStep initial={{ ...state, workspace_id: state.fresh ? undefined : wsId || state.workspace_id }} onDone={(data, id) => { setWsId(id); setState({ ...data, step: "setup" }); updateOnboarding(data); }} />}
                {step === "setup" && <SetupChoiceStep wsId={wsId} onAi={() => go("interview")} onSkip={() => finish(true)} onAssisted={() => finish(true)} />}
                {step === "interview" && wsId && (
                  <div>
                    <StepHeader eyebrow="AI Manager setup · Business & strategy" title="Let's build your sales strategy" description="Answer in your own words or tap a suggestion. Skip anything you're unsure about — you can edit it all later." />
                    <InterviewChat wsId={wsId} currency={ws?.currency} onFinished={() => go("channels")} onSkip={() => go("channels")} skipLabel="Skip this and set up voice & SMS" />
                  </div>
                )}
                {step === "channels" && wsId && (
                  <div>
                    <StepHeader eyebrow="AI Manager setup · Voice & SMS" title="Connect your voice agent and SMS" description="Optional, but this is where the magic happens: your AI calls every new lead within minutes. You can always do this later in Settings." />
                    <ChannelsStep wsId={wsId} onContinue={() => go("done")} onSkip={() => finish(true)} />
                  </div>
                )}
                {step === "done" && wsId && <DoneStep wsId={wsId} onFinish={(path) => finish(false, path)} />}
              </motion.div>
            </AnimatePresence>
            <SetupHelpCard compact className="mt-10 lg:hidden" />
          </div>
        </main>
      </div>
    </div>
  );
}
