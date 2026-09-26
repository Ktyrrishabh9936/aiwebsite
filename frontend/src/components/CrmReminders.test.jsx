import React, { act } from "react";
import { createRoot } from "react-dom/client";
import CrmReminders from "./CrmReminders";
import api from "../lib/api";

jest.mock("../lib/api", () => ({ __esModule: true, formatError: (v) => v, default: { get: jest.fn(), post: jest.fn(), patch: jest.fn() } }));
let container, root;
beforeEach(() => { global.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); api.get.mockResolvedValue({ data: { items: [], total: 0 } }); api.post.mockResolvedValue({ data: {} }); api.patch.mockResolvedValue({ data: {} }); });
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });
async function change(element, value) { await act(async () => { Object.getOwnPropertyDescriptor(element.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, "value").set.call(element, value); element.dispatchEvent(new Event("input", { bubbles: true })); }); }

test("creates a lead reminder with UTC time and sharing instructions", async () => {
  await act(async () => root.render(<CrmReminders wsId="ws" leadId="lead" />));
  await change(container.querySelector('input:not([type])'), "Share brochure");
  await change(container.querySelector('input[type="datetime-local"]'), "2026-09-21T10:00");
  await change(container.querySelector("textarea"), "Discuss pricing");
  await act(async () => container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(api.post).toHaveBeenCalledWith("/workspaces/ws/crm/leads/lead/reminders", { title: "Share brochure", note: "Discuss pricing", due_at: new Date("2026-09-21T10:00").toISOString() });
});

test("daily planner filters dates, opens the lead and marks a reminder done", async () => {
  api.get.mockResolvedValue({ data: { items: [{ id: "task", lead_id: "lead", title: "Call", objective: "Share prices", scheduled_time: "2026-09-21T10:00:00Z", status: "pending", lead_name: "Diya", lead_phone: "+14155550123", lead_available: true }], total: 1 } });
  const open = jest.fn();
  await act(async () => root.render(<CrmReminders wsId="ws" onOpenLead={open} />));
  expect(api.get).toHaveBeenCalledWith("/workspaces/ws/crm/reminders", { params: expect.objectContaining({ start: expect.any(String), end: expect.any(String), status: "pending" }) });
  expect(container.querySelector('[aria-current="date"]')?.getAttribute("aria-pressed")).toBe("true");
  expect(container.textContent).toContain("Due ");
  expect(container.textContent).toContain("Share prices");
  await act(async () => [...container.querySelectorAll("button")].find((b) => b.textContent === "Diya").click());
  expect(open).toHaveBeenCalledWith("lead");
  await change(container.querySelector('input[placeholder="Record the lead’s response before completing"]'), "Asked for a call tomorrow");
  await act(async () => [...container.querySelectorAll("button")].find((b) => b.textContent === "Complete follow-up").click());
  expect(api.patch).toHaveBeenCalledWith("/workspaces/ws/crm/reminders/task", { status: "done", outcome: "Asked for a call tomorrow" });
});
