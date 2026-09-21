import React, { act } from "react";
import { createRoot } from "react-dom/client";
import CrmPerformance from "./CrmPerformance";
import CrmInbox from "./CrmInbox";
import api from "../../lib/api";

jest.mock("react-router-dom", () => ({ useParams: () => ({ wsId: "workspace" }), Link: ({ children, to, ...props }) => <a href={to} {...props}>{children}</a> }), { virtual: true });
jest.mock("../../lib/api", () => ({ __esModule: true, API: "/api", formatError: (v) => v, default: { get: jest.fn() } }));
jest.mock("../../components/LeadQualificationPanel", () => () => null);
let container, root, response;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  response = { funnel: { total_leads: 102, eligible_leads: 100, leads_attempted: 90 }, calling: { calls_attempted: 95, connected: 85, no_answer: 5, busy: 3, failed: 2, completed_conversations: 80, connection_rate: 89.5, average_duration_seconds: 62 }, qualification: { qualified: 65, disqualified: 15, follow_up_required: 5, completion_rate: 80 }, reviews: { reviewed: 100, correct: 85, incorrect: 15, not_reviewed: 2, accuracy: 85 } };
  api.get.mockImplementation(async (url) => ({ data: url.endsWith("/profiles") ? { profiles: [{ id: "profile", product_name: "Homes" }] } : url.endsWith("/performance") ? response : url.includes("/leads?") ? { items: [], total: 0 } : { fields: [], states: [], agents: [], templates: [] } }));
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
