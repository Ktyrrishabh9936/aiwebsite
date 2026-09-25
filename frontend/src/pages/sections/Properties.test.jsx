import React, { act } from "react";
import { createRoot } from "react-dom/client";
import Properties from "./Properties";
import api from "../../lib/api";

jest.mock("../../lib/api", () => ({ __esModule: true, formatError: (value) => value, default: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() } }));
jest.mock("react-router-dom", () => ({ Link: ({ children, to, ...props }) => <a href={to} {...props}>{children}</a>, useOutletContext: () => ({ ws: { id: "ws", currency: "INR", modules: { real_estate: true } } }) }), { virtual: true });

let container, root;
const button = (label) => [...container.querySelectorAll("button")].find((node) => node.textContent.trim() === label);
const fields = (label) => [...container.querySelectorAll('[role="dialog"] label')].filter((node) => node.textContent.includes(label)).map((node) => node.querySelector("input"));
const enter = async (input, value) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
};

beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  api.get.mockResolvedValue({ data: { items: [], currency: "INR" } });
  api.post.mockResolvedValue({ data: { id: "property" } });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test("creates an apartment with grouped tower and BHK counts in three steps", async () => {
  await act(async () => root.render(<Properties />));
  await act(async () => button("Add property").click());
  const dialog = container.querySelector('[role="dialog"]');
  expect(dialog.textContent).toContain("Step 1 of 3");
  await enter(dialog.querySelectorAll("input")[0], "Lake View");
  await enter(dialog.querySelectorAll("input")[1], "Pune");
  await act(async () => button("Continue").click());
  expect(dialog.textContent).toContain("Step 2 of 3");
  await act(async () => button("Continue").click());
  expect(dialog.textContent).toContain("Step 3 of 3");
  await enter(dialog.querySelector('input[type="number"]'), "40");
  await enter(fields("First flat number")[0], "101");
  await enter(fields("Price from")[0], "2000000");
  await enter(fields("Price up to")[0], "2400000");
  await act(async () => button("Add another tower or BHK").click());
  await enter(fields("Number of flats")[1], "20");
  await enter(fields("First flat number")[1], "201");
  await enter(fields("Price from")[1], "1500000");
  await enter(fields("Price up to")[1], "1700000");
  expect(dialog.textContent).toContain("Total: 60 flats");
  await act(async () => button("Create property").click());
  expect(api.post).toHaveBeenCalledWith("/workspaces/ws/properties", expect.objectContaining({
    name: "Lake View", location: "Pune", container_kind: "project", subtype: "Apartment",
    inventory_setup: { mode: "unit_mix", total_units: 60, unit_mix: [
      { tower: "Tower A", bhk: "2 BHK", count: 40, start_number: "101", number_step: 1, price_min: "2000000", price_max: "2400000" },
      { tower: "Tower A", bhk: "1 BHK", count: 20, start_number: "201", number_step: 1, price_min: "1500000", price_max: "1700000" },
    ] },
  }));
});

test("edits tower counts on an existing apartment", async () => {
  api.get.mockResolvedValueOnce({ data: { currency: "INR", items: [{
    id: "property-1", name: "Lake View", location: "Pune", category: "residential",
    subtype: "Apartment", container_kind: "project", price: "", status: "available",
    inventory_setup: { mode: "unit_mix", total_units: 10, unit_mix: [{ tower: "Tower B", bhk: "1 BHK", count: 10, start_number: "101", price_min: "1000000", price_max: "1200000" }] },
  }] } });
  api.patch.mockResolvedValue({ data: { id: "property-1" } });
  await act(async () => root.render(<Properties />));
  await act(async () => button("Edit project").click());
  await act(async () => button("Continue").click());
  await act(async () => button("Continue").click());
  await enter(container.querySelector('[role="dialog"] input[type="number"]'), "12");
  await act(async () => button("Save changes").click());
  expect(api.patch).toHaveBeenCalledWith("/workspaces/ws/properties/property-1", expect.objectContaining({
    inventory_setup: { mode: "unit_mix", total_units: 12, unit_mix: [{ tower: "Tower B", bhk: "1 BHK", count: 12, start_number: "101", number_step: 1, price_min: "1000000", price_max: "1200000" }] },
  }));
});

test("generates saved flats before offering to manage them", async () => {
  const property = {
    id: "property-1", name: "7th Avenue", location: "Pune", category: "residential",
    subtype: "Apartment", container_kind: "project", price: "", status: "available", generated_units: 0,
    inventory_setup: { total_units: 10, unit_mix: [{ tower: "Tower A", bhk: "2 BHK", count: 10, start_number: "3091" }] },
  };
  api.get.mockResolvedValue({ data: { currency: "INR", items: [property] } });
  api.post.mockResolvedValue({ data: { generated_units: 10 } });
  await act(async () => root.render(<Properties />));
  expect(button("Manage flats")).toBeUndefined();
  expect(container.textContent).toContain("0 of 10 flats ready");
  await act(async () => button("Generate 10 flats").click());
  expect(api.post).toHaveBeenCalledWith("/workspaces/ws/properties/property-1/generate-units");
});

test("explains what project deletion removes before sending it", async () => {
  api.get.mockResolvedValue({ data: { currency: "INR", items: [{
    id: "property-1", name: "7th Avenue", location: "Pune", category: "residential", subtype: "Apartment",
    container_kind: "project", status: "available", generated_units: 10,
    inventory_setup: { total_units: 10, unit_mix: [{ tower: "A", bhk: "2 BHK", count: 10, start_number: "3091" }] },
  }] } });
  api.delete.mockResolvedValue({ data: { ok: true } });
  await act(async () => root.render(<Properties />));
  await act(async () => button("Delete project").click());
  expect(api.delete).not.toHaveBeenCalled();
  expect(container.querySelector('[aria-label="Delete property"]').textContent).toContain("10 generated flats");
  await act(async () => button("Delete project and flats").click());
  expect(api.delete).toHaveBeenCalledWith("/workspaces/ws/properties/property-1");
});
