import React, { act } from "react";
import { createRoot } from "react-dom/client";
import JoinWorkspace from "./JoinWorkspace";
import SalesPortal from "./SalesPortal";
import api from "../lib/api";
import { useAuth } from "../context/AuthContext";

const mockNavigate = jest.fn();
jest.mock("react-router-dom", () => ({ useNavigate: () => mockNavigate, useParams: () => ({ token: "token" }), useLocation: () => ({ search: "?lead=lead" }) }), { virtual: true });
jest.mock("../context/AuthContext", () => ({ useAuth: jest.fn() }));
jest.mock("../lib/api", () => ({ __esModule: true, formatError: (value) => value, default: { get: jest.fn(), post: jest.fn() } }));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
let root, container;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  useAuth.mockReturnValue({ user: { email: "agent@example.com" }, ready: true, logout: jest.fn() });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test("accepting an invitation opens its workspace", async () => {
  api.get.mockResolvedValue({ data: { name: "Agent", email: "agent@example.com", workspace_name: "Project", role: "sales_agent" } });
  api.post.mockResolvedValue({ data: { workspace_id: "workspace" } });
  await act(async () => root.render(<JoinWorkspace />));
  await act(async () => container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(api.post).toHaveBeenCalledWith("/membership-invitations/token/accept", {});
  expect(mockNavigate).toHaveBeenCalledWith("/app/w/workspace/crm", { replace: true });
});

test("an invitation cannot be accepted using a different account", async () => {
  useAuth.mockReturnValue({ user: { email: "other@example.com" }, ready: true, logout: jest.fn() });
  api.get.mockResolvedValue({ data: { name: "Agent", email: "agent@example.com", workspace_name: "Project", role: "sales_agent" } });
  await act(async () => root.render(<JoinWorkspace />));
  expect(container.textContent).toContain("Sign out and use the invited email");
  expect(container.querySelector("form")).toBeNull();
  expect(api.post).not.toHaveBeenCalled();
});

test("member portal clears lead details when workspace access is revoked", async () => {
  let revoked = false;
  const lead = { id: "lead", full_name: "Assigned lead", phone: "+14155550123", assigned_salesperson: "Current agent", follow_up: { last_response: "Shared brochure", next_action: { title: "Confirm visit", due_at: "2026-09-27T10:00:00Z" } }, notes: [] };
  api.get.mockImplementation(async (url) => {
    if (revoked) throw { response: { data: { detail: "Workspace access revoked" } } };
    if (url.endsWith("/performance")) return { data: { currency: "INR", item: { assigned_leads: 1, sales: 0, sales_minor: 0, introduced_leads: 0 } } };
    if (url.endsWith("/properties")) return { data: { items: [] } };
    if (url.endsWith("/leads/lead")) return { data: { lead, reminders: [] } };
    return { data: { items: [lead], total: 1 } };
  });
  await act(async () => root.render(<SalesPortal workspace={{ id: "workspace", name: "Project", access_role: "sales_agent" }} workspaces={[]} />));
  await act(async () => new Promise((resolve) => setTimeout(resolve, 300)));
  expect(container.textContent).toContain("Assigned lead");
  expect(container.textContent).not.toContain("Twilio");
  expect(container.textContent).toContain("Current agent");
  expect(container.textContent).toContain("Shared brochure");
  expect(container.textContent).toContain("Confirm visit");
  const tabs = container.querySelector('[aria-label="Lead sections"]');
  expect(tabs.textContent).toBe("DetailsQualificationFollow-upNotes");
  revoked = true;
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(container.textContent).toContain("Workspace access revoked");
  expect(container.textContent).not.toContain("Assigned lead");
});
