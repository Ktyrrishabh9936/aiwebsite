import { useEffect, useState } from "react";
import { CalendarClock, ChevronDown, ClipboardCheck, Loader2, Mail, PhoneCall, Save } from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";
import { getAppTimezone, systemTimezone } from "../lib/timezone";

const MODES = [
  { value: "auto", label: "Do it automatically", hint: "The AI acts at the planned time." },
  { value: "approval", label: "Ask me first", hint: "Nothing goes out until you approve it." },
  { value: "off", label: "Don't do this", hint: "You get it as a suggestion instead." },
];
// With plan approval on, a channel is simply in the plan or not; the one approval covers it.
const PLAN_MODES = [
  { value: "auto", label: "Include in the plan", hint: "Runs once you approve the day's plan." },
  { value: "off", label: "Don't do this", hint: "You get it as a suggestion instead." },
];
const APPROVAL = [
  { value: "review", label: "I approve the plan first", hint: "The plan is emailed to you. Nothing runs until you approve it, with one click for the whole plan." },
  { value: "auto", label: "Run the plan automatically", hint: "The AI starts on the plan straight away. You still get the email." },
];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DEFAULTS = {
  enabled: true, run_time: "09:00", timezone: "", plan_approval: "review", calls: "auto", lead_emails: "auto", max_calls_per_day: 20, max_emails_per_day: 30,
  report_email: "", meeting_mode: "auto", meeting_duration_minutes: 30, meeting_hours: { start: "10:00", end: "18:00" }, meeting_days: [0, 1, 2, 3, 4, 5],
};
const FIELDS = Object.keys(DEFAULTS);

function zoneList(current) {
  const supported = Intl.supportedValuesOf?.("timeZone") || ["Asia/Kolkata", "Asia/Dubai", "Europe/London", "America/New_York"];
  return [...new Set(["UTC", systemTimezone(), current, ...supported].filter(Boolean))].sort();
}

function ModeChoice({ icon: Icon, title, value, onChange, modes = MODES }) {
  // When the plan is approved as a whole, "in the plan" stands for any channel setting other than off.
  const chosen = (mode) => (modes === PLAN_MODES && mode === "auto" ? value !== "off" : value === mode);
  return (
    <fieldset className="rounded-xl border bg-background p-4">
      <legend className="sr-only">{title}</legend>
      <p className="flex items-center gap-2 text-sm font-semibold"><Icon className="h-4 w-4 text-primary" />{title}</p>
      <div className="mt-3 grid gap-2">
        {modes.map((mode) => (
          <label key={mode.value} className={`flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2 text-sm transition ${chosen(mode.value) ? "border-primary bg-primary/5" : "hover:bg-accent/40"}`}>
            <input type="radio" name={title} className="mt-1" checked={chosen(mode.value)} onChange={() => onChange(mode.value)} />
            <span><span className="font-medium">{mode.label}</span><span className="block text-xs text-muted-foreground">{mode.hint}</span></span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** The daily AI run: when it runs and how much it may do on its own. Used in onboarding and Settings. */
export default function DailyAiSettings({ wsId, onboarding = false, onSaved, submitLabel }) {
  const [form, setForm] = useState(null);
  const [meta, setMeta] = useState({});
  const [saving, setSaving] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    api.get(`/workspaces/${wsId}/ai-ops/settings`).then(({ data }) => {
      if (!live) return;
      const values = Object.fromEntries(FIELDS.map((key) => [key, data[key] ?? DEFAULTS[key]]));
      // A workspace that has never chosen a time starts from the viewer's own timezone, switched on.
      if (!data.configured) Object.assign(values, { timezone: getAppTimezone(), enabled: true });
      setForm(values);
      setMeta(data);
    }).catch((err) => { if (live) { setForm({ ...DEFAULTS, timezone: getAppTimezone() }); setError(formatError(err.response?.data?.detail)); } });
    return () => { live = false; };
  }, [wsId]);

  if (!form) return <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Loading…</div>;
  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const toggleDay = (day) => set("meeting_days", form.meeting_days.includes(day) ? form.meeting_days.filter((d) => d !== day) : [...form.meeting_days, day].sort());

  const save = async (event) => {
    event.preventDefault();
    setSaving(true); setError("");
    try {
      const { data } = await api.put(`/workspaces/${wsId}/ai-ops/settings`, {
        ...form, max_calls_per_day: Number(form.max_calls_per_day), max_emails_per_day: Number(form.max_emails_per_day),
        meeting_duration_minutes: Number(form.meeting_duration_minutes),
      });
      setMeta(data);
      if (!onboarding) toast.success(form.enabled ? "Daily AI run saved" : "Daily AI run switched off");
      onSaved?.(data);
    } catch (err) {
      setError(formatError(err.response?.data?.detail));
    } finally { setSaving(false); }
  };

  const input = "mt-1 h-11 w-full rounded-xl border bg-background px-3.5 text-sm font-normal";
  return (
    <form onSubmit={save} className="space-y-5">
      {!onboarding && (
        <label className="flex items-center justify-between gap-4 rounded-xl border bg-background p-4">
          <span><span className="text-sm font-semibold">Run the AI every day</span><span className="block text-xs text-muted-foreground">Switch off to stop the daily plan and all automatic calls and emails.</span></span>
          <input type="checkbox" role="switch" aria-label="Run the AI every day" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} className="h-5 w-5" />
        </label>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-sm font-semibold">Run every day at
          <input type="time" required value={form.run_time} onChange={(e) => set("run_time", e.target.value)} className={input} aria-label="Daily run time" />
        </label>
        <label className="text-sm font-semibold">Timezone
          <select value={form.timezone} onChange={(e) => set("timezone", e.target.value)} className={input} aria-label="Timezone">
            {zoneList(form.timezone).map((zone) => <option key={zone} value={zone}>{zone.replaceAll("_", " ")}</option>)}
          </select>
        </label>
      </div>
      <p className="-mt-2 text-xs text-muted-foreground">At this time your AI reads the CRM, decides which leads need attention, gives each to the right agent and emails you the plan.</p>
      <ModeChoice icon={ClipboardCheck} title="Approving the daily plan" value={form.plan_approval} onChange={(value) => set("plan_approval", value)} modes={APPROVAL} />
      <div className="grid gap-4 lg:grid-cols-2">
        <ModeChoice icon={PhoneCall} title="AI calls to leads" value={form.calls} onChange={(value) => set("calls", value)} modes={form.plan_approval === "review" ? PLAN_MODES : MODES} />
        <ModeChoice icon={Mail} title="Emails to leads and customers" value={form.lead_emails} onChange={(value) => set("lead_emails", value)} modes={form.plan_approval === "review" ? PLAN_MODES : MODES} />
      </div>
      <button type="button" onClick={() => setAdvanced((open) => !open)} aria-expanded={advanced} className="inline-flex items-center gap-1 text-sm font-medium text-primary">
        Limits, report email and meetings<ChevronDown className={`h-4 w-4 transition-transform ${advanced ? "rotate-180" : ""}`} />
      </button>
      {advanced && (
        <div className="grid gap-4 rounded-xl border bg-background p-4 sm:grid-cols-2">
          <label className="text-sm font-semibold">Most AI calls per day
            <input type="number" min="0" max="200" value={form.max_calls_per_day} onChange={(e) => set("max_calls_per_day", e.target.value)} className={input} />
          </label>
          <label className="text-sm font-semibold">Most emails per day
            <input type="number" min="0" max="500" value={form.max_emails_per_day} onChange={(e) => set("max_emails_per_day", e.target.value)} className={input} />
          </label>
          <label className="text-sm font-semibold sm:col-span-2">Send the daily plan to
            <input type="email" value={form.report_email} onChange={(e) => set("report_email", e.target.value)} placeholder={meta.report_email_default || "you@company.com"} className={input} />
            <span className="mt-1 block text-xs font-normal text-muted-foreground">Leave blank to use {meta.report_email_default || "the workspace owner's email"}. Replies from leads also come here.</span>
          </label>
          <label className="text-sm font-semibold sm:col-span-2">When a lead asks for a meeting
            <select value={form.meeting_mode} onChange={(e) => set("meeting_mode", e.target.value)} className={input}>
              <option value="auto">Book a free time, tell the lead and me (I can change it)</option>
              <option value="admin_first">Propose a time to me first; tell the lead after I confirm</option>
            </select>
          </label>
          <label className="text-sm font-semibold">Meeting length (minutes)
            <input type="number" min="10" max="240" step="5" value={form.meeting_duration_minutes} onChange={(e) => set("meeting_duration_minutes", e.target.value)} className={input} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="text-sm font-semibold">Meetings from
              <input type="time" value={form.meeting_hours.start} onChange={(e) => set("meeting_hours", { ...form.meeting_hours, start: e.target.value })} className={input} />
            </label>
            <label className="text-sm font-semibold">until
              <input type="time" value={form.meeting_hours.end} onChange={(e) => set("meeting_hours", { ...form.meeting_hours, end: e.target.value })} className={input} />
            </label>
          </div>
          <fieldset className="sm:col-span-2">
            <legend className="text-sm font-semibold">Meeting days</legend>
            <div className="mt-2 flex flex-wrap gap-2">
              {DAYS.map((label, day) => (
                <button key={label} type="button" aria-pressed={form.meeting_days.includes(day)} onClick={() => toggleDay(day)}
                  className={`h-9 rounded-lg border px-3 text-sm font-medium ${form.meeting_days.includes(day) ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent"}`}>{label}</button>
              ))}
            </div>
          </fieldset>
        </div>
      )}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <div className="flex flex-wrap items-center gap-3">
        <button disabled={saving || !form.meeting_days.length} className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-primary px-6 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : onboarding ? <CalendarClock className="h-4 w-4" /> : <Save className="h-4 w-4" />}{submitLabel || "Save"}
        </button>
        {!onboarding && meta.next_run_at && <span className="text-xs text-muted-foreground">Next run: {new Date(meta.next_run_at).toLocaleString(undefined, { timeZone: form.timezone, dateStyle: "medium", timeStyle: "short" })} ({form.timezone})</span>}
      </div>
    </form>
  );
}
