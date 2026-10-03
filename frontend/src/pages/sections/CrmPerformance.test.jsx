import React, { act } from "react";
import { createRoot } from "react-dom/client";
import CrmPerformance from "./CrmPerformance";
import CrmInbox from "./CrmInbox";
import api from "../../lib/api";

jest.mock("react-router-dom", () => ({ useParams: () => ({ wsId: "workspace" }), useLocation: () => ({ search: "" }), Link: ({ children, to, ...props }) => <a href={to} {...props}>{children}</a> }), { virtual: true });
jest.mock("../../lib/api", () => ({ __esModule: true, API: "/api", formatError: (v) => v, default: { get: jest.fn(), patch: jest.fn() } }));
jest.mock("../../components/LeadQualificationPanel", () => () => null);
let container, root, response;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  response = { funnel: { total_leads: 102, eligible_leads: 100, leads_attempted: 90 }, calling: { calls_attempted: 95, connected: 85, no_answer: 5, busy: 3, failed: 2, completed_conversations: 80, connection_rate: 89.5, average_duration_seconds: 62 }, qualification: { qualified: 65, disqualified: 15, follow_up_required: 5, completion_rate: 80 }, reviews: { reviewed: 100, correct: 85, incorrect: 15, not_reviewed: 2, accuracy: 85 } };
  api.get.mockImplementation(async (url) => ({ data: url.endsWith("/profiles") ? { profiles: [{ id: "profile", product_name: "Homes" }] } : url.endsWith("/performance") ? response : url.includes("/crm/bootstrap?") ? { settings: { fields: [], states: [], templates: [], organization: {} }, agents: { agents: [], selected_agent_config_id: "" }, leads: { items: [], total: 0, page: 1, limit: 10 } } : url.includes("/leads?") ? { items: [], total: 0 } : { fields: [], states: [], agents: [], templates: [] } }));
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test("renders metrics and reviewed-only accuracy without recalculating using unreviewed leads", async () => {
  await act(async () => root.render(<CrmPerformance wsId="workspace" />));
  expect(container.textContent).toContain("CRM Performance");
  expect(container.textContent).toContain("85%"); expect(container.textContent).toContain("62s");
  expect(container.textContent).toContain("Not Reviewed results are excluded");
  expect(container.textContent).not.toContain("83.3%");
  expect(api.get).toHaveBeenCalledWith("/workspaces/workspace/crm/performance", expect.objectContaining({ params: expect.objectContaining({ start: expect.any(String), end: expect.any(String) }) }));
});

test("empty and no-review states do not invent zero accuracy", async () => {
  response.funnel.total_leads = 0;
  response.reviews = { accuracy: null, reviewed: 0, correct: 0, incorrect: 0, not_reviewed: 0 };
  await act(async () => root.render(<CrmPerformance wsId="workspace" />));
  expect(container.textContent).toContain("No leads match these filters");
  expect(container.textContent).toContain("Not enough reviewed data");
});

test("Leads & sales tab shows cohort rates and recorded sales stages", async () => {
  response.sales = {
    total_leads: 102, junk: 12, junk_rate: 11.8, not_qualified: 20, not_qualified_rate: 19.6,
    converted: 8, conversion_rate: 7.8, demo_meeting: 6, proposal: 4, payment_issues: 2,
    trend: [{ date: "2026-09-20", leads: 102, converted: 8 }], stages: [{ key: "proposal", count: 4 }],
  };
  await act(async () => root.render(<CrmPerformance wsId="workspace" states={[{ key: "proposal", label: "Proposal sent" }]} />));
  await act(async () => container.querySelector('[role="tab"][aria-selected="false"]').click());
  expect(container.textContent).toContain("Lead and sales overview");
  expect(container.textContent).toContain("12 · 11.8%");
  expect(container.textContent).toContain("20 · 19.6%");
  expect(container.textContent).toContain("8 · 7.8%");
  expect(container.textContent).toContain("Payment issues");
  expect(container.textContent).toContain("Proposal sent");
});

test("profile and status filters are sent to the scoped API", async () => {
  await act(async () => root.render(<CrmPerformance wsId="workspace" states={[{ key: "won", label: "Won" }]} />));
  const selects = container.querySelectorAll("select");
  await act(async () => { selects[0].value = "profile"; selects[0].dispatchEvent(new Event("change", { bubbles: true })); });
  await act(async () => { selects[1].value = "won"; selects[1].dispatchEvent(new Event("change", { bubbles: true })); });
  expect(api.get).toHaveBeenLastCalledWith("/workspaces/workspace/crm/performance", { params: expect.objectContaining({ profile_id: "profile", status: "won" }) });
});

test("failed metrics show an error rather than misleading zero counts", async () => {
  api.get.mockRejectedValue(new Error("Network unavailable"));
  await act(async () => root.render(<CrmPerformance wsId="workspace" />));
  expect(container.textContent).toContain("Network unavailable");
  expect(container.textContent).not.toContain("No leads match these filters");
});

test("Performance tab is inside CRM and Records and Settings remain accessible", async () => {
  await act(async () => root.render(<CrmInbox />));
  const button = (text) => [...container.querySelectorAll("button")].find((b) => b.textContent.trim() === text);
  expect(button("Records")).toBeTruthy(); expect(button("Settings")).toBeTruthy();
  expect(api.get.mock.calls.some(([url]) => url.endsWith("/performance"))).toBe(false);
  await act(async () => button("Performance").click());
  expect(container.querySelector('[aria-label="CRM Performance"]')).toBeTruthy();
  await act(async () => button("Records").click());
  expect(container.textContent).toContain("New Lead");
  expect(container.querySelector('[aria-label="CRM Performance"]')).toBeNull();
});

test("clicking a lead fetches detail by ID rather than stringifying the lead object", async () => {
  const summary = { id: "lead-123", status: "new", field_values: { full_name: "Webhook Lead" }, created_at: "2026-09-25T00:00:00Z" };
  api.get.mockImplementation(async (url) => ({ data:
    url.includes("/crm/bootstrap?")
      ? { settings: { fields: [{ key: "full_name", label: "Name", active: true }], states: [{ key: "new", label: "New", color: "blue" }], templates: [], organization: {} }, agents: { agents: [], selected_agent_config_id: "" }, leads: { items: [summary], total: 1, page: 1, limit: 10 } }
      : url.endsWith("/crm/leads/lead-123") ? { ...summary, lead_notes: [] } : {}
  }));
  await act(async () => root.render(<CrmInbox />));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 80)); });
  const row = [...container.querySelectorAll("tbody tr")].find((item) => item.textContent.includes("Webhook Lead"));
  await act(async () => row.click());
  expect(api.get).toHaveBeenCalledWith("/workspaces/workspace/crm/leads/lead-123");
  expect(api.get.mock.calls.some(([url]) => url.includes("[object"))).toBe(false);
});

test("a Sheet sync event refreshes only the paginated lead list", async () => {
  await act(async () => root.render(<CrmInbox />));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 80)); });
  api.get.mockClear();
  await act(async () => window.dispatchEvent(new Event("arevei:sheet-synced")));
  expect(api.get).toHaveBeenCalledWith(
    "/workspaces/workspace/crm/leads?page=1&limit=10",
    expect.objectContaining({ signal: undefined }),
  );
  expect(api.get.mock.calls.some(([url]) => url.includes("/crm/bootstrap"))).toBe(false);
});

test("selecting Test lead immediately saves and unmarks without Save CRM", async () => {
  const summary = { id: "test-lead", status: "new", field_values: { full_name: "Test customer" }, created_at: "2026-09-25T00:00:00Z" };
  api.get.mockImplementation(async (url) => ({ data: url.includes("/crm/bootstrap?")
    ? { settings: { fields: [{ key: "full_name", label: "Name", active: true }], states: [{ key: "new", label: "New", color: "blue" }], templates: [], organization: {} }, agents: { agents: [] }, leads: { items: [summary], total: 1, page: 1, limit: 10 } }
    : url.endsWith("/crm/leads/test-lead") ? summary : {} }));
  api.patch.mockImplementation(async (url, body) => ({ data: { ...summary, ...body } }));
  await act(async () => root.render(<CrmInbox />));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 80)); });
  await act(async () => container.querySelector("tbody tr").click());
  const checkbox = () => [...container.querySelectorAll('input[type="checkbox"]')].find((input) => input.closest("label")?.textContent.includes("Test lead"));
  expect(checkbox().checked).toBe(false);
  for (const expected of [true, false]) {
    await act(async () => checkbox().click());
    expect(api.patch).toHaveBeenLastCalledWith("/workspaces/workspace/crm/leads/test-lead/test-lead", { is_test_lead: expected });
    expect(checkbox().checked).toBe(expected);
    expect(container.querySelector("tbody").textContent.includes("Test lead")).toBe(expected);
  }
});

test("performance reloads after test lead changes in the current workspace", async () => {
  await act(async () => root.render(<CrmPerformance wsId="workspace" />));
  api.get.mockClear();
  await act(async () => window.dispatchEvent(new CustomEvent("arevei:lead-metrics-changed", { detail: { wsId: "other" } })));
  expect(api.get).not.toHaveBeenCalled();
  await act(async () => window.dispatchEvent(new CustomEvent("arevei:lead-metrics-changed", { detail: { wsId: "workspace" } })));
  expect(api.get).toHaveBeenCalledWith("/workspaces/workspace/crm/performance", expect.any(Object));
});

test("core details save on blur, stage saves immediately, and attribution starts closed", async () => {
  let lead = { id: "autosave", status: "new", customer_status: "lead", field_values: { full_name: "Original" }, tags: [], created_at: "2026-09-25T00:00:00Z" };
  api.get.mockImplementation(async (url) => ({ data: url.includes("/crm/bootstrap?")
    ? { settings: { fields: [{ key: "full_name", label: "Name", active: true }], states: [{ key: "new", label: "New", color: "blue" }, { key: "contacted", label: "Contacted", color: "amber" }], templates: [], organization: {} }, agents: { agents: [] }, leads: { items: [lead], total: 1, page: 1, limit: 10 } }
    : url.endsWith("/crm/leads/autosave") ? lead : {} }));
  api.patch.mockImplementation(async (url, body) => { lead = { ...lead, ...body, field_values: { ...lead.field_values, ...body.field_values } }; return { data: lead }; });
  await act(async () => root.render(<CrmInbox />));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 80)); });
  await act(async () => container.querySelector("tbody tr").click());
  const detail = container.querySelector('[aria-label="Lead details"]');
  expect([...detail.querySelectorAll("button")].some((button) => button.textContent === "Save CRM")).toBe(false);
  expect([...detail.querySelectorAll("details")].find((element) => element.textContent.includes("Meta Attribution")).open).toBe(false);
  const name = detail.querySelector('[aria-label="Name"]');
  const tags = detail.querySelector('[aria-label="Lead tags and customer relationship"]');
  expect(name.compareDocumentPosition(tags) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(detail.querySelector('[aria-label="Payment mode"]').compareDocumentPosition(name) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(name, "Updated"); name.dispatchEvent(new Event("input", { bubbles: true })); });
  expect(api.patch).not.toHaveBeenCalled();
  await act(async () => name.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
  expect(api.patch).toHaveBeenLastCalledWith("/workspaces/workspace/crm/leads/autosave", { field_values: { full_name: "Updated" } });
  const stage = detail.querySelector('[aria-label="Lead state"]');
  await act(async () => { stage.value = "contacted"; stage.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(api.patch).toHaveBeenLastCalledWith("/workspaces/workspace/crm/leads/autosave", { status: "contacted" });
});
