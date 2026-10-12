import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowRight, Bot, Check, Clock, FastForward, Loader2, Pencil, RotateCcw, SendHorizontal, SkipForward, Sparkles, Wand2 } from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../../lib/api";

const CHOICE_LABELS = {
  business_stage: { starting: "Just getting started", existing: "Already selling" },
  offer_confidence: { unknown: "Not sure yet", testing: "Still testing", validated: "Proven — customers buy regularly" },
};

function minutesLeft(seconds) {
  if (!seconds) return "Almost done";
  const m = Math.max(1, Math.round(seconds / 60));
  return `about ${m} min left`;
}

function displayValue(key, value, currency) {
  if (value === undefined || value === null || value === "") return "";
  if (CHOICE_LABELS[key]) return CHOICE_LABELS[key][value] || String(value);
  if (typeof value === "number") return new Intl.NumberFormat("en-IN", { style: "currency", currency: currency || "INR", maximumFractionDigits: 0 }).format(value);
  return String(value);
}

function Bubble({ role, children, reduce }) {
  const mine = role === "user";
  return (
    <motion.div initial={reduce ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18 }} className={`flex items-end gap-2 ${mine ? "justify-end" : "justify-start"}`}>
      {!mine && <span className="mb-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground"><Bot className="h-4 w-4" /></span>}
      <div className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-6 ${mine ? "rounded-br-md bg-primary text-primary-foreground" : "rounded-bl-md border bg-card"}`}>{children}</div>
    </motion.div>
  );
}

function Typing() {
  return (
    <div className="flex items-end gap-2" role="status" aria-label="AI Manager is typing">
      <span className="grid h-7 w-7 place-items-center rounded-full bg-primary text-primary-foreground"><Bot className="h-4 w-4" /></span>
      <div className="flex gap-1 rounded-2xl rounded-bl-md border bg-card px-4 py-3">
        {[0, 1, 2].map((i) => <span key={i} className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60" style={{ animationDelay: `${i * 120}ms` }} />)}
      </div>
    </div>
  );
}

export function InterviewProgress({ state }) {
  const pct = state ? Math.round((state.index / Math.max(state.total, 1)) * 100) : 0;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs">
        <span className="font-semibold">{state?.done ? "All questions answered" : `Question ${Math.min((state?.index || 0) + 1, state?.total || 1)} of ${state?.total || "…"}`}</span>
        <span className="inline-flex items-center gap-1 text-muted-foreground"><Clock className="h-3.5 w-3.5" />{state?.done ? "Review & build" : minutesLeft(state?.eta_seconds)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Setup progress">
        <motion.div className="h-full rounded-full bg-primary" initial={false} animate={{ width: `${pct}%` }} transition={{ duration: 0.4 }} />
      </div>
      <div className="hidden flex-wrap gap-1.5 sm:flex">
        {(state?.questions || []).map((q, i) => {
          const answered = state.answers?.[q.key] !== undefined;
          const skipped = state.skipped?.includes(q.key);
          return <span key={q.key} className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${i === state.index ? "bg-primary text-primary-foreground" : answered ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" : skipped ? "bg-muted text-muted-foreground line-through" : "bg-muted/60 text-muted-foreground"}`}>{q.label}</span>;
        })}
      </div>
    </div>
  );
}

function ReviewCard({ state, currency, onBuild, building, missing, onRestart }) {
  const [values, setValues] = useState(() => ({ ...state.answers }));
  const [timezone, setTimezone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [hour, setHour] = useState(8);
  const set = (key, value) => setValues((v) => ({ ...v, [key]: value }));
  const fieldClass = (key) => `mt-1 w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 ${missing.includes(key) ? "border-destructive ring-1 ring-destructive/30" : ""}`;
  return (
    <motion.section initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="rounded-2xl border bg-card p-5 sm:p-6" aria-labelledby="review-heading">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id="review-heading" className="flex items-center gap-2 text-lg font-bold"><Pencil className="h-4 w-4 text-primary" />Review your answers</h3>
          <p className="mt-1 text-sm text-muted-foreground">Edit anything, then let your AI Manager build your sales strategy.</p>
        </div>
        <button type="button" onClick={onRestart} className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"><RotateCcw className="h-3.5 w-3.5" />Start over</button>
      </div>
      {missing.length > 0 && <p role="alert" className="mt-4 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">Please fill the highlighted answers — they're needed to build a useful strategy.</p>}
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        {state.questions.map((q) => {
          const value = values[q.key];
          const label = <span className="text-xs font-semibold">{q.label}{q.required && <span className="text-destructive"> *</span>}</span>;
          if (CHOICE_LABELS[q.key]) {
            return <label key={q.key} className="block">{label}<select value={value || ""} onChange={(e) => set(q.key, e.target.value)} className={fieldClass(q.key)}><option value="">Choose…</option>{Object.entries(CHOICE_LABELS[q.key]).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>;
          }
          if (["monthly_revenue_target", "monthly_sales_budget"].includes(q.key)) {
            return <label key={q.key} className="block">{label}<div className="relative"><input type="number" min="0" inputMode="numeric" value={value ?? ""} onChange={(e) => set(q.key, e.target.value === "" ? "" : Number(e.target.value))} className={fieldClass(q.key)} placeholder="0" />{typeof value === "number" && value > 0 && <span className="pointer-events-none absolute right-3 top-1/2 mt-0.5 -translate-y-1/2 text-xs text-muted-foreground">{displayValue(q.key, value, currency)}</span>}</div></label>;
          }
          const long = ["organisation", "offerings", "ideal_customer", "customer_feedback", "constraints"].includes(q.key);
          return <label key={q.key} className={`block ${long ? "sm:col-span-2" : ""}`}>{label}{long
            ? <textarea rows={2} value={Array.isArray(value) ? value.join(", ") : value || ""} onChange={(e) => set(q.key, e.target.value)} className={fieldClass(q.key)} />
            : <input value={Array.isArray(value) ? value.join(", ") : value || ""} onChange={(e) => set(q.key, e.target.value)} className={fieldClass(q.key)} />}</label>;
        })}
        <label className="block"><span className="text-xs font-semibold">Timezone</span><input value={timezone} onChange={(e) => setTimezone(e.target.value)} className={fieldClass("timezone")} /></label>
        <label className="block"><span className="text-xs font-semibold">Morning briefing time</span><select value={hour} onChange={(e) => setHour(Number(e.target.value))} className={fieldClass("morning_hour")}>{Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}</select></label>
      </div>
      <button type="button" disabled={building} onClick={() => onBuild({ answers: values, timezone, morning_hour: hour })} className="mt-6 inline-flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-primary px-5 text-sm font-semibold text-primary-foreground shadow-sm transition hover:bg-primary/90 disabled:opacity-60">
        {building ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}{building ? "Saving your answers…" : "Build my sales strategy"}
      </button>
    </motion.section>
  );
}

/** AI-guided business & sales-strategy interview. Calls onFinished({strategy_status}) after saving. */
export default function InterviewChat({ wsId, currency = "INR", onFinished, onSkip, skipLabel = "Skip setup" }) {
  const reduce = useReducedMotion();
  const [state, setState] = useState(null);
  const [message, setMessage] = useState("");
  const [picked, setPicked] = useState([]);
  const [sending, setSending] = useState(false);
  const [building, setBuilding] = useState(false);
  const [missing, setMissing] = useState([]);
  const [error, setError] = useState("");
  const scroller = useRef(null);
  const input = useRef(null);
  const current = state?.current;

  useEffect(() => {
    let live = true;
    api.get(`/workspaces/${wsId}/onboarding/interview`).then(({ data }) => { if (live) setState(data); })
      .catch((e) => { if (live) setError(formatError(e.response?.data?.detail) || "Could not start the setup chat"); });
    return () => { live = false; };
  }, [wsId]);

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: reduce ? "auto" : "smooth" });
  }, [state?.transcript?.length, sending, reduce]);

  const currentKey = current?.key;
  useEffect(() => { setPicked([]); setMessage(""); if (currentKey && input.current) input.current.focus({ preventScroll: true }); }, [currentKey]);

  const send = async (payload) => {
    if (sending) return;
    setSending(true); setError("");
    const optimistic = payload.message ? payload.message : payload.skip_all ? "Skip the rest" : payload.skip ? "Skip" : "";
    if (optimistic) setState((s) => ({ ...s, transcript: [...(s?.transcript || []), { role: "user", text: optimistic, pending: true }] }));
    try {
      const { data } = await api.post(`/workspaces/${wsId}/onboarding/interview/answer`, payload);
      setState(data); setMessage(""); setPicked([]);
    } catch (e) {
      setState((s) => ({ ...s, transcript: (s?.transcript || []).filter((m) => !m.pending) }));
      setError(formatError(e.response?.data?.detail) || "That didn't go through. Try again.");
    } finally { setSending(false); }
  };

  const submit = (event) => {
    event?.preventDefault();
    const text = current?.type === "multi" && picked.length ? [...picked, message.trim()].filter(Boolean).join(", ") : message.trim();
    if (text) send({ message: text });
  };

  const build = async (body) => {
    setBuilding(true); setMissing([]);
    try {
      const { data } = await api.post(`/workspaces/${wsId}/onboarding/interview/complete`, body);
      toast.success("Answers saved. Building your strategy…");
      onFinished?.(data);
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (detail?.missing) { setMissing(detail.missing); toast.error(`Please add: ${detail.labels.join(", ")}`); }
      else toast.error(formatError(detail) || "Could not save your answers");
    } finally { setBuilding(false); }
  };

  const restart = async () => {
    if (!window.confirm("Clear your answers and start the setup chat again?")) return;
    const { data } = await api.post(`/workspaces/${wsId}/onboarding/interview/restart`);
    setState(data); setMissing([]);
  };

  const transcript = useMemo(() => state?.transcript || [], [state]);

  if (error && !state) return <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-sm">{error}</div>;
  if (!state) return <div className="grid h-80 place-items-center text-sm text-muted-foreground"><Loader2 className="h-5 w-5 animate-spin" /></div>;

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border bg-card shadow-sm">
        <div className="border-b p-4 sm:p-5"><InterviewProgress state={state} /></div>
        <div ref={scroller} className="h-[min(52vh,460px)] space-y-3 overflow-y-auto bg-muted/20 p-4 sm:p-5" aria-live="polite">
          {transcript.map((m, i) => <Bubble key={`${i}-${m.at || ""}`} role={m.role} reduce={reduce}>{m.text}</Bubble>)}
          {sending && <Typing />}
        </div>
        {!state.done && current && (
          <form onSubmit={submit} className="space-y-3 border-t p-4 sm:p-5">
            {current.suggestion && (
              <button type="button" disabled={sending} onClick={() => send({ message: current.suggestion })} className="group flex w-full items-start gap-2 rounded-xl border border-dashed border-primary/40 bg-primary/5 px-3 py-2 text-left text-xs hover:bg-primary/10">
                <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                <span><span className="font-semibold text-primary">From your website: </span><span className="line-clamp-2 text-muted-foreground group-hover:text-foreground">{current.suggestion}</span></span>
              </button>
            )}
            {current.chips?.length > 0 && (
              <div className="flex flex-wrap gap-2" role="group" aria-label="Quick answers">
                {current.chips.map((chip) => {
                  const on = picked.includes(chip);
                  return (
                    <button key={chip} type="button" disabled={sending} aria-pressed={current.type === "multi" ? on : undefined}
                      onClick={() => current.type === "multi" ? setPicked((p) => on ? p.filter((c) => c !== chip) : [...p, chip]) : send({ message: chip })}
                      className={`inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm transition ${on ? "border-primary bg-primary text-primary-foreground" : "bg-background hover:border-primary/50 hover:bg-primary/5"}`}>
                      {on && <Check className="h-3.5 w-3.5" />}{chip}
                    </button>
                  );
                })}
              </div>
            )}
            {(current.type !== "choice" || current.allow_text) && (
              <div className="flex items-end gap-2">
                {current.type === "text"
                  ? <textarea ref={input} rows={2} value={message} onChange={(e) => setMessage(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }} placeholder={current.placeholder || "Type your answer…"} aria-label={current.text} className="min-h-[48px] flex-1 resize-none rounded-xl border bg-background px-3.5 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
                  : <input ref={input} value={message} onChange={(e) => setMessage(e.target.value)} placeholder={current.type === "multi" ? "Add another source (optional)" : current.placeholder || "Type your answer…"} aria-label={current.text} className="h-12 flex-1 rounded-xl border bg-background px-3.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />}
                <button type="submit" disabled={sending || (!message.trim() && !(current.type === "multi" && picked.length))} aria-label="Send answer" className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-primary text-primary-foreground transition hover:bg-primary/90 disabled:opacity-40">
                  {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : current.type === "multi" ? <ArrowRight className="h-4 w-4" /> : <SendHorizontal className="h-4 w-4" />}
                </button>
              </div>
            )}
            {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <span className="text-muted-foreground">Tip: ask me anything, like “what can Arevei do?”</span>
              <div className="flex gap-1">
                <button type="button" disabled={sending} onClick={() => send({ skip: true })} className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 font-medium text-muted-foreground hover:bg-accent hover:text-foreground"><SkipForward className="h-3.5 w-3.5" />Skip question</button>
                <button type="button" disabled={sending} onClick={() => send({ skip_all: true })} className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 font-medium text-muted-foreground hover:bg-accent hover:text-foreground"><FastForward className="h-3.5 w-3.5" />Skip the rest</button>
              </div>
            </div>
          </form>
        )}
      </div>
      <AnimatePresence>{state.done && <ReviewCard key="review" state={state} currency={currency} onBuild={build} building={building} missing={missing} onRestart={restart} />}</AnimatePresence>
      {onSkip && <div className="text-center"><button type="button" onClick={onSkip} className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">{skipLabel}</button></div>}
    </div>
  );
}
