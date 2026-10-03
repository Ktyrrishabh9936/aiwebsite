const KEY = "arevei_timezone";
export function systemTimezone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}
export function timezonePreference() {
  try { return JSON.parse(localStorage.getItem(KEY)) || { mode: "automatic", zone: systemTimezone() }; }
  catch { return { mode: "automatic", zone: systemTimezone() }; }
}
export function getAppTimezone() {
  const preference = timezonePreference();
  if (preference.mode !== "manual") return systemTimezone();
  try { new Intl.DateTimeFormat("en", { timeZone: preference.zone }); return preference.zone; }
  catch { return systemTimezone(); }
}
export function saveTimezonePreference(mode, zone) {
  new Intl.DateTimeFormat("en", { timeZone: zone });
  localStorage.setItem(KEY, JSON.stringify({ mode, zone }));
  window.dispatchEvent(new Event("arevei:timezone-changed"));
}
export const formatDateTime = (value, options = {}) => new Date(value).toLocaleString(undefined, { ...options, timeZone: getAppTimezone() });
export const formatDate = (value, options = {}) => {
  const calendarDay = typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
  return new Date(calendarDay ? `${value}T12:00:00Z` : value).toLocaleDateString(undefined, { ...options, timeZone: calendarDay ? "UTC" : getAppTimezone() });
};
export const formatTime = (value, options = {}) => new Date(value).toLocaleTimeString(undefined, { ...options, timeZone: getAppTimezone() });
export function zonedInput(value = new Date(), zone = getAppTimezone()) {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(value));
  const p = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}
export const appDate = (value = new Date()) => zonedInput(value).slice(0, 10);
export function inputToUtc(value, zone = getAppTimezone()) {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) throw new Error("Choose a valid date and time");
  const desired = Date.parse(`${value}:00Z`);
  let instant = desired;
  for (let i = 0; i < 4; i++) {
    const actual = Date.parse(`${zonedInput(instant, zone)}:00Z`);
    const difference = desired - actual;
    if (!difference) return new Date(instant).toISOString();
    instant += difference;
  }
  throw new Error("This time does not exist in the selected timezone. Choose another time.");
}
export function dayBounds(day) {
  const next = new Date(`${day}T12:00:00Z`); next.setUTCDate(next.getUTCDate() + 1);
  return { start: inputToUtc(`${day}T00:00`), end: inputToUtc(`${next.toISOString().slice(0, 10)}T00:00`) };
}
