import React, { act } from "react";
import { createRoot } from "react-dom/client";
import ShareLead from "./ShareLead";
import api from "../lib/api";

jest.mock("../lib/api", () => ({ __esModule: true, API: "http://127.0.0.1:8000/api", formatError: (value) => value, default: { get: jest.fn(), post: jest.fn(), delete: jest.fn() } }));
let container, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  api.get.mockResolvedValue({ data: { items: [{ id: "agent", name: "Agent", role: "sales_agent", active: true }, { id: "inactive", name: "Inactive", role: "sales_agent", active: false }] } });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test("shares with an available agent and exposes the private link", async () => {
  const updated = jest.fn();
  api.post.mockResolvedValue({ data: { share_path: "/app/w/workspace/crm?lead=lead", lead: { id: "lead" } } });
  await act(async () => root.render(<ShareLead wsId="workspace" lead={{ id: "lead" }} onUpdated={updated} />));
  expect(container.textContent).not.toContain("Inactive");
  const select = container.querySelector("select");
  await act(async () => { select.value = "agent"; select.dispatchEvent(new Event("change", { bubbles: true })); });
  await act(async () => container.querySelector("button").click());
  expect(api.post).toHaveBeenCalledWith("/workspaces/workspace/crm/sales-team/leads/lead/share", { sales_agent_id: "agent" });
  expect(container.querySelector('[aria-label="Lead link"]').value).toBe(`${window.location.origin}/app/w/workspace/crm?lead=lead`);
  expect(updated).toHaveBeenCalled();
});

test("owner can revoke existing sharing", async () => {
  api.delete.mockResolvedValue({ data: { id: "lead" } });
  await act(async () => root.render(<ShareLead wsId="workspace" lead={{ id: "lead", lead_share: { agent_name: "Agent", expires_at: "2026-10-26" } }} onUpdated={() => {}} />));
  await act(async () => Array.from(container.querySelectorAll("button")).find((button) => button.textContent.includes("Revoke")).click());
  expect(api.delete).toHaveBeenCalledWith("/workspaces/workspace/crm/sales-team/leads/lead/share");
});
