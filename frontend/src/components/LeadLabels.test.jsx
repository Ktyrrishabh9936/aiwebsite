import React, { act, useState } from "react";
import { createRoot } from "react-dom/client";
import LeadLabels from "./LeadLabels";
import api from "../lib/api";

jest.mock("../lib/api", () => ({ __esModule: true, formatError: (value) => value, default: { patch: jest.fn(), put: jest.fn() } }));
let container, root;
beforeEach(() => { global.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });
function Lead() {
  const [lead, setLead] = useState({ id: "lead", status: "new", customer_status: "lead", tags: ["VIP"] });
  return <LeadLabels wsId="workspace" lead={lead} onUpdated={setLead} />;
}

test("adds multiple tags, removes one, and marks a customer while keeping the New stage", async () => {
  let saved = { id: "lead", status: "new", customer_status: "lead", tags: ["VIP"] };
  api.put.mockResolvedValue({ data: { tags: [] } });
  api.patch.mockImplementation(async (url, body) => { saved = { ...saved, ...body }; return { data: saved }; });
  await act(async () => root.render(<Lead />));
  const input = container.querySelector('[aria-label="Add lead tags"]');
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, "Repeat enquiry, 3 BHK");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => [...container.querySelectorAll("button")].find((button) => button.textContent === "Add tags").click());
  expect(saved.tags).toEqual(["VIP", "Repeat enquiry", "3 BHK"]);
  expect(api.put).toHaveBeenCalledWith("/workspaces/workspace/crm/tag-library", { names: ["Repeat enquiry", "3 BHK"], color: "blue" });
  await act(async () => container.querySelector('[aria-label="Remove tag VIP"]').click());
  expect(saved.tags).toEqual(["Repeat enquiry", "3 BHK"]);
  await act(async () => container.querySelector('[aria-label="Existing customer"]').click());
  expect(saved.customer_status).toBe("customer");
  expect(saved.status).toBe("new");
  expect(api.patch).toHaveBeenLastCalledWith("/workspaces/workspace/crm/leads/lead/labels", { customer_status: "customer" });
});

test("failed saves show an error and keep the original labels", async () => {
  api.patch.mockRejectedValue(new Error("Unable to save"));
  await act(async () => root.render(<Lead />));
  await act(async () => container.querySelector('[aria-label="Remove tag VIP"]').click());
  expect(container.querySelector('[role="alert"]').textContent).toBe("Unable to save");
  expect(container.querySelector('[aria-label="Remove tag VIP"]')).not.toBeNull();
});

test("reusable tags toggle and their color can be changed for the workspace", async () => {
  let saved = { id: "lead", status: "new", customer_status: "lead", tags: ["VIP"] };
  api.patch.mockImplementation(async (url, body) => { saved = { ...saved, ...body }; return { data: saved }; });
  const onLibraryUpdated = jest.fn();
  api.put.mockResolvedValue({ data: { tags: [{ label: "VIP", color: "rose" }] } });
  await act(async () => root.render(<LeadLabels wsId="workspace" lead={saved} onUpdated={jest.fn()} onLibraryUpdated={onLibraryUpdated} />));
  const vip = container.querySelector('[aria-label="Toggle tag VIP"]');
  expect(vip.className).toContain("violet");
  await act(async () => container.querySelector('[aria-label="Toggle tag Pending"]').click());
  expect(saved.tags).toEqual(["VIP", "Pending"]);
  const picker = container.querySelector('[aria-label="Color for tag VIP"]');
  await act(async () => { picker.value = "rose"; picker.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(api.put).toHaveBeenCalledWith("/workspaces/workspace/crm/tag-library", { names: ["VIP"], color: "rose" });
  expect(onLibraryUpdated).toHaveBeenCalledWith([{ label: "VIP", color: "rose" }]);
});
