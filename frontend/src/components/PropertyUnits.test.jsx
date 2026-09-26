import React, { act } from "react";
import { createRoot } from "react-dom/client";
import PropertyUnits from "./PropertyUnits";
import api from "../lib/api";

jest.mock("./ui/dialog", () => ({
  Dialog: ({ children, open }) => open ? <div>{children}</div> : null,
  DialogContent: ({ children, ...props }) => <div {...props}>{children}</div>,
  DialogHeader: ({ children }) => <div>{children}</div>,
  DialogTitle: ({ children }) => <h2>{children}</h2>,
}));
jest.mock("../lib/api", () => ({ __esModule: true, formatError: (value) => value, default: { get: jest.fn(), patch: jest.fn() } }));

let container, root;
beforeEach(() => { global.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test("switching a land property from list to plan opens a block's inventory details", async () => {
  const property = { id: "site", name: "Five Block Site", category: "land", container_kind: "land", attributes: { area_sqft: "5000" }, inventory_setup: { total_units: 5 } };
  const units = Array.from({ length: 5 }, (_, index) => ({ id: String(index + 1), tower: "Site", unit_number: `Block 0${index + 1}`, bhk: "Plot", status: index === 1 ? "reserved" : "available", asking_price_minor: 100000000, updated_at: "2026-09-25" }));
  api.get.mockImplementation((url) => Promise.resolve({ data: { items: url.endsWith("/plan") ? units : units.slice(0, 2), total: 5, currency: "INR" } }));
  await act(async () => root.render(<PropertyUnits wsId="ws" property={property} onClose={() => {}} />));
  expect(container.querySelector('[aria-label="Property plan view"]')).toBeNull();
  await act(async () => [...container.querySelectorAll("button")].find((button) => button.textContent === "Plan view").click());
  expect(api.get).toHaveBeenCalledWith("/workspaces/ws/properties/site/units/plan");
  expect(container.querySelectorAll('button[aria-label*="block"]')).toHaveLength(5);
  await act(async () => container.querySelector('[aria-label="Block 02, Locked block"]').click());
  expect(container.querySelector('[aria-label="Selected unit details"]').textContent).toContain("Block 02");
  expect(container.textContent).toContain("Edit block");
});
