import React, { act } from "react";
import { createRoot } from "react-dom/client";
import SalesPortal from "./SalesPortal";
import api from "../lib/api";
import { saveTimezonePreference, formatDateTime } from "../lib/timezone";

jest.mock("react-router-dom", () => ({ useLocation: () => ({ search: "" }), useNavigate: () => jest.fn() }), { virtual: true });
jest.mock("../context/AuthContext", () => ({ useAuth: () => ({ logout: jest.fn() }) }));
jest.mock("../lib/api", () => ({ __esModule: true, formatError: (v) => v, default: { get: jest.fn(), post: jest.fn() } }));
jest.mock("../components/LeadQualificationPanel", () => () => null);
let root, container;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  const lead = { id: "lead", full_name: "Diya", phone: "+14155550123", created_at: "2026-10-03T10:00:00Z" };
  api.get.mockImplementation(async (url) => ({ data: url.endsWith("/leads/lead") ? { lead, reminders: [{ id: "reminder", title: "Call back", scheduled_time: "2026-10-03T10:00:00Z", status: "pending" }] } : url.endsWith("/leads") ? { items: [lead], total: 1 } : url.endsWith("/performance") ? { item: { assigned_leads: 1, sales: 0, sales_minor: 0, introduced_leads: 0 } } : { items: [] } }));
  api.post.mockResolvedValue({ data: {} });
});
afterEach(() => { act(() => root.unmount()); container.remove(); localStorage.removeItem("arevei_timezone"); jest.clearAllMocks(); });

test("sales follow-ups display and schedule in the application timezone", async () => {
  saveTimezonePreference("manual", "Asia/Kolkata");
  await act(async () => root.render(<SalesPortal workspace={{ id: "ws", name: "Workspace" }} workspaces={[]} />));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 300)); });
  await act(async () => [...container.querySelectorAll("button")].find((button) => button.textContent.includes("Diya")).click());
  await act(async () => [...container.querySelectorAll("button")].find((button) => button.textContent === "Follow-up").click());
  expect(container.textContent).toContain(formatDateTime("2026-10-03T10:00:00Z", { dateStyle: "medium", timeStyle: "short", hour12: true }));
  for (const [label, value] of [["Follow-up title", "Discuss pricing"], ["Follow-up due date", "2026-10-03T15:30"]]) {
    const input = container.querySelector(`[aria-label="${label}"]`);
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  }
  await act(async () => container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(api.post).toHaveBeenCalledWith("/workspaces/ws/sales-portal/leads/lead/reminders", { title: "Discuss pricing", note: "", due_at: "2026-10-03T10:00:00.000Z" });
});
