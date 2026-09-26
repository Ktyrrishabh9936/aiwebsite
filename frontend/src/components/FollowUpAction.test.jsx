import React, { act } from "react";
import { createRoot } from "react-dom/client";
import FollowUpAction, { FollowUpSnapshot } from "./FollowUpAction";
import api from "../lib/api";

jest.mock("./ui/dialog", () => ({
  Dialog: ({ children }) => <div>{children}</div>,
  DialogContent: ({ children }) => <div>{children}</div>,
  DialogHeader: ({ children }) => <div>{children}</div>,
  DialogTitle: ({ children }) => <h2>{children}</h2>,
  DialogTrigger: ({ children }) => children,
}));
jest.mock("../lib/api", () => ({ __esModule: true, formatError: (value) => value, default: { post: jest.fn(), patch: jest.fn() } }));

let container, root;
beforeEach(() => { global.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });
const button = (label) => [...container.querySelectorAll("button")].find((item) => item.textContent.includes(label));
const change = async (element, value) => act(async () => {
  Object.getOwnPropertyDescriptor(element.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, "value").set.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
});

test("AI suggestion remains editable before a human saves a follow-up", async () => {
  api.post.mockResolvedValueOnce({ data: { source: "ai", title: "Call lead", note: "Discuss site visit", reason: "No next action" } }).mockResolvedValueOnce({ data: {} });
  await act(async () => root.render(<FollowUpAction wsId="ws" lead={{ id: "lead", status: "new", full_name: "Diya" }} />));
  await act(async () => button("Suggest with AI").click());
  expect(api.post).toHaveBeenCalledWith("/workspaces/ws/crm/leads/lead/follow-up/suggest");
  await change(container.querySelector('input[maxlength="200"]'), "Send brochure");
  await act(async () => button("Save follow-up").click());
  expect(api.post).toHaveBeenCalledWith("/workspaces/ws/crm/leads/lead/reminders", expect.objectContaining({ title: "Send brochure", note: "Discuss site visit" }));
});

test("completing a follow-up records the lead response", async () => {
  api.patch.mockResolvedValue({ data: {} });
  const snapshot = { stage: "contacted", last_response: "Asked for more details", next_action: { id: "task", title: "Call again" } };
  await act(async () => root.render(<FollowUpAction wsId="ws" lead={{ id: "lead", full_name: "Diya" }} snapshot={snapshot} />));
  await change(container.querySelector('textarea[maxlength="1000"]'), "Visit confirmed for Friday");
  await act(async () => button("Complete follow-up").click());
  expect(api.patch).toHaveBeenCalledWith("/workspaces/ws/crm/reminders/task", { status: "done", outcome: "Visit confirmed for Friday" });
});

test("follow-up dates show the date prominently and use a 12-hour time", async () => {
  const lastResponseAt = "2026-09-25T15:23:00.000Z";
  const dueAt = "2026-09-26T09:30:00.000Z";
  await act(async () => root.render(<FollowUpSnapshot snapshot={{ last_response: "Asked for details", last_response_at: lastResponseAt, next_action: { title: "Share demo", due_at: dueAt } }} />));
  const times = [...container.querySelectorAll("time")];
  expect(times).toHaveLength(2);
  for (const [time, value] of times.map((time, index) => [time, [lastResponseAt, dueAt][index]])) {
    const date = new Date(value);
    expect(time.querySelector(".font-medium").textContent).toBe(date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }));
    expect(time.textContent).toContain(date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", hour12: true }));
  }
});
