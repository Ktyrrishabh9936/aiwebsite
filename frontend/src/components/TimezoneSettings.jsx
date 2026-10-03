import { useState } from "react";
import { getAppTimezone, saveTimezonePreference, systemTimezone, timezonePreference } from "../lib/timezone";

export default function TimezoneSettings() {
  const preference = timezonePreference();
  const [mode, setMode] = useState(preference.mode);
  const [zone, setZone] = useState(preference.zone || systemTimezone());
  const [message, setMessage] = useState("");
  const zones = [...new Set(["UTC", systemTimezone(), zone, ...(Intl.supportedValuesOf?.("timeZone") || ["Asia/Kolkata", "America/New_York", "Europe/London"])])].sort();
  return <section className="rounded-xl border bg-card p-5 space-y-4" aria-label="Application timezone">
    <div><h3 className="font-semibold">Application timezone</h3><p className="text-sm text-muted-foreground mt-1">Use one timezone for dates, follow-ups, reminders and AI scheduling throughout the app. This preference is saved on this device.</p></div>
    <label className="block text-sm">Timezone mode<select aria-label="Timezone mode" value={mode} onChange={(event) => setMode(event.target.value)} className="block w-full h-10 border rounded-lg bg-background px-3 mt-1"><option value="automatic">Automatic — use system timezone</option><option value="manual">Manual — choose a timezone</option></select></label>
    {mode === "manual" && <label className="block text-sm">Timezone<select aria-label="Application timezone selection" value={zone} onChange={(event) => setZone(event.target.value)} className="block w-full h-10 border rounded-lg bg-background px-3 mt-1">{zones.map((item) => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}</select></label>}
    <p className="text-xs text-muted-foreground">Current: {getAppTimezone()} · System: {systemTimezone()}</p>
    <button type="button" onClick={() => { try { saveTimezonePreference(mode, mode === "automatic" ? systemTimezone() : zone); setMessage("Timezone applied"); } catch { setMessage("Could not save timezone. Please try again."); } }} className="rounded-lg bg-primary text-primary-foreground px-3 py-2 text-sm font-semibold">Apply timezone</button>
    {message && <p role="status" className="text-sm">{message}</p>}
  </section>;
}
