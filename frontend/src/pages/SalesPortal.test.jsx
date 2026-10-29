import React, { act } from "react";
import { createRoot } from "react-dom/client";
import SalesPortal from "./SalesPortal";
import api from "../lib/api";
import { saveTimezonePreference } from "../lib/timezone";

jest.mock("react-router-dom", () => ({ useLocation: () => ({ search: "" }), useNavigate: () => jest.fn(), useParams: () => ({ wsId: "ws" }), Link: ({ to, children, ...props }) => <a href={to} {...props}>{children}</a> }), { virtual: true });
jest.mock("../context/AuthContext", () => ({ useAuth: () => ({ user: { name: "Asha", email: "asha@example.com" }, logout: jest.fn() }) }));
jest.mock("../lib/api", () => ({ __esModule: true, API: "/api", formatError: (v) => v, default: { get: jest.fn(), post: jest.fn(), patch: jest.fn() } }));
jest.mock("../components/LeadQualificationPanel", () => () => null);
jest.mock("../components/ThemeToggle", () => ({ ThemeToggle: () => null }));
jest.mock("../components/AgentWorkspace", () => ({ AgentWorkspace: ({ ws }) => <div>Agent workspace for {ws.organization}</div> }));
let root, container;
const lead = { id: "lead", full_name: "Diya", phone: "+14155550123", status: "new", created_at: "2026-10-03T10:00:00Z", assigned_salesperson: "Asha", field_values: { full_name: "Diya", phone: "+14155550123", email: "" } };
const settings = { states: [{ key: "new", label: "New", color: "blue" }, { key: "contacted", label: "Contacted", color: "amber" }, { key: "won", label: "Won", color: "emerald" }], fields: [{ key: "phone", label: "Phone", type: "phone", editable: false }, { key: "full_name", label: "Name", type: "text", editable: true }], tag_library: [] };
const workspace = { id: "ws", name: "Royal Estates", organization: "Royal Estates Pvt Ltd", access_role: "sales_agent", member_name: "Asha", shared_by: { name: "Rishabh", email: "owner@example.com" } };
const workspaces = [{ id: "own", name: "My agency", access_role: "owner" }, { id: "ws", name: "Royal Estates", access_role: "sales_agent" }];

beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  api.get.mockImplementation(async (url) => ({ data:
    url.endsWith("/sales-portal/settings") ? settings
    : url.includes("/sales-portal/leads?") ? { items: [lead], total: 1, page: 1, limit: 10 }
    : url.endsWith("/leads/lead") ? { lead, reminders: [] }
    : url.endsWith("/performance") ? { currency: "INR", item: { assigned_leads: 1, sales: 0, sales_minor: 0, introduced_leads: 0 } }
    : url.endsWith("/follow-ups/snapshots") ? { lead: { last_response: "Shared brochure", next_action: null, follow_up_pending: true } }
    : url.endsWith("/reminders") ? { items: [{ id: "reminder", title: "Call back", scheduled_time: "2026-10-03T10:00:00Z", status: "pending", lead_name: "Diya", lead_available: true }], total: 1 }
    : { items: [] } }));
  api.post.mockResolvedValue({ data: { lead: { ...lead, status: "won", customer_status: "customer", conversion_type: "single_payment" } } });
  api.patch.mockResolvedValue({ data: { lead: { ...lead, status: "contacted" }, reminders: [] } });
});
afterEach(() => { act(() => root.unmount()); container.remove(); localStorage.removeItem("arevei_timezone"); jest.clearAllMocks(); });

const button = (text) => [...container.querySelectorAll("button")].find((item) => item.textContent.trim() === text);

async function openLead() {
  await act(async () => root.render(<SalesPortal workspace={workspace} workspaces={workspaces} />));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 450)); });
  await act(async () => container.querySelector('[aria-label="Open details for Diya"]').click());
}

test("the shared page names who shared it, whose leads they are and the member's role", async () => {
  await openLead();
  const details = container.querySelector('[aria-label="Shared workspace details"]').textContent;
  expect(details).toContain("Shared by Rishabh (owner@example.com)");
  expect(details).toContain("Organization: Royal Estates Pvt Ltd");
  expect(details).toContain("You: Asha · Sales agent");
  expect(container.textContent).toContain("Shared workspace");
  expect(api.get).toHaveBeenCalledWith("/workspaces/ws/sales-portal/settings", expect.anything());
  expect(api.get).not.toHaveBeenCalledWith(expect.stringContaining("/crm/"), expect.anything());
});

test("members get every lead tab of the owner CRM without owner administration", async () => {
  await openLead();
  const tabs = [...container.querySelectorAll('[aria-label="Lead sections"] button')].map((item) => item.textContent);
  expect(tabs).toEqual(["AI Insights", "Details", "Qualification", "Follow-up", "Payments", "Receipts", "Invoice", "Notes"]);
  expect(container.querySelector('[aria-label="CRM sections"]')).toBeNull();
  expect(container.querySelector('[title="Move lead to trash"]')).toBeNull();
  expect(container.textContent).not.toContain("Test lead");
});

test("members change the stage, including booking the deal, through the member API", async () => {
  await openLead();
  const select = container.querySelector('[aria-label="Lead state"]');
  expect([...select.options].find((option) => option.value === "won").disabled).toBe(false);
  expect(container.querySelector('input[aria-label="Phone"]')).toBeNull();
  await act(async () => { select.value = "contacted"; select.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(api.patch).toHaveBeenCalledWith("/workspaces/ws/sales-portal/leads/lead", { status: "contacted" });
});

test("members convert their lead and record payments on the member API", async () => {
  await openLead();
  await act(async () => button("Convert Lead").click());
  expect(api.post).toHaveBeenCalledWith("/workspaces/ws/sales-portal/leads/lead/convert", expect.objectContaining({ conversion_type: "single_payment" }));
  await act(async () => button("Payments").click());
  expect(container.textContent).toContain("Single Payment Transaction");
});

test("sales follow-ups use the shared planner on the member API", async () => {
  saveTimezonePreference("manual", "Asia/Kolkata");
  await openLead();
  await act(async () => button("Follow-up").click());
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  expect(api.get).toHaveBeenCalledWith("/workspaces/ws/sales-portal/reminders", { params: expect.objectContaining({ lead_id: "lead" }) });
  expect(container.textContent).toContain("Call back");
  expect(container.textContent).not.toContain("Follow-up notifications");
  const title = container.querySelector('input[placeholder="Call about the site visit"]');
  const due = container.querySelector('input[type="datetime-local"]');
  for (const [input, value] of [[title, "Discuss pricing"], [due, "2026-10-03T15:30"]]) {
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  }
  await act(async () => title.form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(api.post).toHaveBeenCalledWith("/workspaces/ws/sales-portal/leads/lead/reminders", { title: "Discuss pricing", note: "", due_at: "2026-10-03T10:00:00.000Z" });
});

test("agent mode opens the AI manager for the shared workspace", async () => {
  await openLead();
  await act(async () => button("Agent Mode").click());
  expect(container.textContent).toContain("Agent workspace for Royal Estates Pvt Ltd");
  expect(container.querySelector("#workspace-content").hidden).toBe(true);
});
