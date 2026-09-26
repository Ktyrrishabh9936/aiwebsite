import React, { act } from "react";
import { createRoot } from "react-dom/client";
import PropertyPlan from "./PropertyPlan";

let container, root;
beforeEach(() => { global.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); container.remove(); });

test("land plan shows each block, site area, and distinct availability labels", async () => {
  const units = ["available", "reserved", "sold", "available", "available"].map((status, index) => ({ id: String(index), tower: "Site", unit_number: `Block 0${index + 1}`, status }));
  const onSelect = jest.fn();
  await act(async () => root.render(<PropertyPlan property={{ id: "land", category: "land", attributes: { area_sqft: "5000" } }} units={units} visibleUnits={units} selectedId={null} onSelect={onSelect} />));
  expect(container.textContent).toContain("5,000 sq ft site");
  expect(container.querySelectorAll('button[aria-pressed="false"]')).toHaveLength(5);
  expect(container.querySelector('[aria-label="Block 02, Locked block"]')).toBeTruthy();
  expect(container.querySelector('[aria-label="Block 03, SOLD block"]')).toBeTruthy();
  await act(async () => container.querySelector('[aria-label="Block 02, Locked block"]').click());
  expect(onSelect).toHaveBeenCalledWith("1");
});

test("a single unit is represented by one selectable block", async () => {
  const units = [{ id: "one", tower: "Property", unit_number: "Unit 01", bhk: "House", status: "available" }];
  await act(async () => root.render(<PropertyPlan property={{ id: "house", category: "residential" }} units={units} visibleUnits={units} selectedId={null} onSelect={() => {}} />));
  expect(container.querySelectorAll('button[aria-pressed="false"]')).toHaveLength(1);
  expect(container.textContent).toContain("Unit 01");
});

test("apartment units stay grouped under their towers", async () => {
  const units = [
    { id: "a", tower: "Tower A", unit_number: "101", bhk: "2 BHK", status: "available" },
    { id: "b", tower: "Tower B", unit_number: "201", bhk: "1 BHK", status: "sold" },
  ];
  await act(async () => root.render(<PropertyPlan property={{ id: "apartments", category: "residential", subtype: "Apartment" }} units={units} visibleUnits={units} selectedId={null} onSelect={() => {}} />));
  expect(container.querySelector('[aria-label="Tower A"]')).toBeTruthy();
  expect(container.querySelector('[aria-label="Tower B"]')).toBeTruthy();
  expect(container.querySelector('[aria-label="201, SOLD, Tower B"]')).toBeTruthy();
});
