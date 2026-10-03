import { appDate, formatDate, getAppTimezone, inputToUtc, zonedInput, dayBounds, saveTimezonePreference } from "./timezone";
afterEach(() => localStorage.removeItem("arevei_timezone"));

test("manual timezone controls dates and converts scheduled wall time to UTC", () => {
  saveTimezonePreference("manual", "Asia/Kolkata");
  expect(getAppTimezone()).toBe("Asia/Kolkata");
  expect(appDate("2026-10-03T20:00:00Z")).toBe("2026-10-04");
  expect(zonedInput("2026-10-03T10:00:00Z")).toBe("2026-10-03T15:30");
  expect(inputToUtc("2026-10-03T15:30")).toBe("2026-10-03T10:00:00.000Z");
});

test("day ranges follow daylight saving and nonexistent times are rejected", () => {
  saveTimezonePreference("manual", "America/New_York");
  const bounds = dayBounds("2026-03-08");
  expect(new Date(bounds.end) - new Date(bounds.start)).toBe(23 * 3600000);
  expect(() => inputToUtc("2026-03-08T02:30")).toThrow("does not exist");
  expect(inputToUtc("2026-07-01T09:00")).toBe("2026-07-01T13:00:00.000Z");
  expect(inputToUtc("2026-01-01T09:00")).toBe("2026-01-01T14:00:00.000Z");
});

test("automatic mode uses the system timezone and invalid manual values are rejected", () => {
  saveTimezonePreference("automatic", "UTC");
  expect(getAppTimezone()).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
  expect(() => saveTimezonePreference("manual", "invalid/timezone")).toThrow();
});

test("calendar dates remain on their stated day in every timezone", () => {
  saveTimezonePreference("manual", "Pacific/Kiritimati");
  expect(formatDate("2026-10-03", { day: "numeric" })).toBe("3");
  saveTimezonePreference("manual", "America/Los_Angeles");
  expect(formatDate("2026-10-03", { day: "numeric" })).toBe("3");
});
