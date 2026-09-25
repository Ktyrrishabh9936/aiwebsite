import React, { act } from "react";
import { createRoot } from "react-dom/client";
import OpportunitySelector from "./OpportunitySelector";
import api from "../lib/api";

jest.mock("../lib/api", () => ({ __esModule: true, formatError: (value) => value, default: { get: jest.fn(), patch: jest.fn() } }));

let container, root;
const select = (label) => [...container.querySelectorAll("label")].find((node) => node.textContent.startsWith(label)).querySelector("select");
const change = async (node, value) => act(async () => { node.value = value; node.dispatchEvent(new Event("change", { bubbles: true })); });

beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  api.get.mockResolvedValue({ data: { currency: "INR", items: [
    { id: "flat-4", module: "real_estate", kind: "unit", project_id: "project", project_name: "Lake View", tower: "A", unit_number: "4", bhk: "2 BHK", listing_type: "sale", price_minor: 200000000, available_quantity: 1 },
    { id: "flat-101", module: "real_estate", kind: "unit", project_id: "project", project_name: "Lake View", tower: "B", unit_number: "101", bhk: "1 BHK", listing_type: "sale", price_minor: 150000000, available_quantity: 1 },
  ] } });
  api.patch.mockResolvedValue({ data: { id: "lead" } });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test("selects apartment, tower and exact flat for a lead", async () => {
  const onUpdated = jest.fn();
  await act(async () => root.render(<OpportunitySelector wsId="ws" lead={{ id: "lead" }} onUpdated={onUpdated} />));
  await change(select("Apartment"), "project");
  await change(select("Tower"), "A");
  expect(select("Flat").textContent).toContain("Flat 4");
  expect(select("Flat").textContent).not.toContain("101");
  await change(select("Flat"), "real_estate:flat-4");
  await act(async () => [...container.querySelectorAll("button")].find((node) => node.textContent.includes("Link opportunity")).click());
  expect(api.patch).toHaveBeenCalledWith("/workspaces/ws/crm/leads/lead/opportunity", {
    module: "real_estate", item_id: "flat-4", quantity: 1, amount: "2000000",
  });
  expect(onUpdated).toHaveBeenCalled();
});

test("keeps an unsaved flat choice when the lead is polled", async () => {
  const opportunity = { module: "real_estate", item_id: "flat-4", kind: "unit", project_id: "project", tower: "A", quantity: 1, unit_price_minor: 200000000 };
  const onUpdated = jest.fn();
  await act(async () => root.render(<OpportunitySelector wsId="ws" lead={{ id: "lead", opportunity }} onUpdated={onUpdated} />));
  await change(select("Tower"), "B");
  await change(select("Flat"), "real_estate:flat-101");
  expect(select("Tower").value).toBe("B");
  expect(select("Flat").value).toBe("real_estate:flat-101");

  await act(async () => root.render(<OpportunitySelector wsId="ws" lead={{ id: "lead", opportunity: { ...opportunity } }} onUpdated={onUpdated} />));
  expect(select("Tower").value).toBe("B");
  expect(select("Flat").value).toBe("real_estate:flat-101");
  expect(api.get).toHaveBeenCalledTimes(1);
});
