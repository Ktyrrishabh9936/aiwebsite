import React, { act } from "react";
import { createRoot } from "react-dom/client";
import SalesTeam, { SalesAssignment } from "./SalesTeam";
import api from "../lib/api";

jest.mock("../lib/api", () => ({ __esModule: true, formatError: (value) => value, default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), patch: jest.fn() } }));
let root, container;
const people = [{ id: "agent", name: "Sales Person", role: "sales_agent", active: true }, { id: "partner", name: "Referral Partner", role: "channel_partner", active: true }];
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  api.get.mockImplementation(async (url) => ({ data: url.endsWith("/summary") ? { currency: "INR", properties: [{ id: "property", name: "Land Project" }], items: [] } : { items: people } }));
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test("renders owner team management and a property filter", async () => {
  await act(async () => root.render(<SalesTeam wsId="workspace" />));
  expect(container.textContent).toContain("Sales agents & channel partners");
  const select = container.querySelector('[aria-label="Performance property"]');
  await act(async () => { select.value = "property"; select.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(api.get).toHaveBeenCalledWith("/workspaces/workspace/crm/sales-team/performance/summary", { params: { property_id: "property" } });
});

test("saves assignment and introduction separately", async () => {
  const updated = jest.fn();
  api.put.mockResolvedValue({ data: { id: "lead", sales_assignment: { sales_agent_id: "agent" } } });
  await act(async () => root.render(<SalesAssignment wsId="workspace" lead={{ id: "lead" }} onUpdated={updated} />));
  const selects = container.querySelectorAll("select");
  await act(async () => { selects[0].value = "agent"; selects[0].dispatchEvent(new Event("change", { bubbles: true })); });
  await act(async () => { selects[2].value = "partner"; selects[2].dispatchEvent(new Event("change", { bubbles: true })); });
  await act(async () => container.querySelector("button").click());
  expect(api.put).toHaveBeenCalledWith("/workspaces/workspace/crm/sales-team/leads/lead", { sales_agent_id: "agent", introduced_by_id: "partner" });
  expect(updated).toHaveBeenCalled();
});

test("deactivate sends one update and visibly changes status", async () => {
  let finish;
  api.patch.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  api.get.mockImplementation(async (url) => ({ data: url.endsWith("/summary") ? { currency: "INR", properties: [], items: [{ ...people[0], assigned_leads: 0, sales: 0, sales_minor: 0, introduced_leads: 0, marketing_leads: 0, referral_leads: 0, introduced_sales: 0 }] } : { items: people } }));
  await act(async () => root.render(<SalesTeam wsId="workspace" />));
  const button = Array.from(container.querySelectorAll("button")).find((item) => item.textContent === "Deactivate");
  act(() => { button.click(); button.click(); });
  expect(api.patch).toHaveBeenCalledTimes(1);
  expect(button.disabled).toBe(true);
  expect(button.textContent).toBe("Saving...");
  await act(async () => finish({ data: { ok: true } }));
  expect(container.textContent).toContain("Inactive");
  expect(button.textContent).toBe("Reactivate");
  expect(api.patch).toHaveBeenCalledWith("/workspaces/workspace/crm/sales-team/agent", { active: false });
});
