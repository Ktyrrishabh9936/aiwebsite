import React, { act } from "react";
import { createRoot } from "react-dom/client";
import DailyAiSettings from "./DailyAiSettings";
import api from "../lib/api";

jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock("../lib/timezone", () => ({ getAppTimezone: () => "Asia/Kolkata", systemTimezone: () => "Asia/Kolkata" }));
jest.mock("../lib/api", () => ({ __esModule: true, default: { get: jest.fn(), put: jest.fn() }, formatError: (detail) => String(detail || "error") }));

let container, root;
beforeEach(() => { global.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

const change = async (element, value) => act(async () => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
});

test("a new workspace picks a run time during onboarding and it is saved switched on", async () => {
  api.get.mockResolvedValue({ data: { configured: false, enabled: false, run_time: "09:00", timezone: "UTC", calls: "auto", lead_emails: "auto" } });
  api.put.mockResolvedValue({ data: { enabled: true, next_run_at: "2026-11-18T02:00:00+00:00" } });
  const onSaved = jest.fn();
  await act(async () => root.render(<DailyAiSettings wsId="ws" onboarding submitLabel="Save and continue" onSaved={onSaved} />));
  expect(container.querySelector('[role="switch"]')).toBeNull(); // onboarding always switches it on
  expect(container.querySelector('[aria-label="Timezone"]').value).toBe("Asia/Kolkata"); // the viewer's zone, not the server default
  await change(container.querySelector('[aria-label="Daily run time"]'), "07:30");
  await act(async () => container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(api.put).toHaveBeenCalledWith("/workspaces/ws/ai-ops/settings", expect.objectContaining({ enabled: true, run_time: "07:30", timezone: "Asia/Kolkata", plan_approval: "review", calls: "auto", lead_emails: "auto" }));
  expect(container.querySelectorAll('input[name="AI calls to leads"]')).toHaveLength(2); // one plan approval covers each channel
  expect(onSaved).toHaveBeenCalledTimes(1);
});

test("settings keep the saved choices and can require approval", async () => {
  api.get.mockResolvedValue({ data: { configured: true, enabled: true, run_time: "08:00", timezone: "Europe/London", plan_approval: "auto", calls: "auto", lead_emails: "approval", next_run_at: "2026-11-18T08:00:00+00:00" } });
  api.put.mockResolvedValue({ data: { enabled: true } });
  await act(async () => root.render(<DailyAiSettings wsId="ws" />));
  expect(container.querySelector('[role="switch"]').checked).toBe(true);
  expect(container.querySelector('[aria-label="Timezone"]').value).toBe("Europe/London");
  expect(container.textContent).toContain("Next run");
  const askFirst = [...container.querySelectorAll('input[name="AI calls to leads"]')][1];
  await act(async () => askFirst.click());
  await act(async () => container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(api.put).toHaveBeenCalledWith("/workspaces/ws/ai-ops/settings", expect.objectContaining({ plan_approval: "auto", calls: "approval", lead_emails: "approval", timezone: "Europe/London" }));
});
