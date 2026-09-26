import React, { act } from "react";
import { createRoot } from "react-dom/client";
import LeadSmsCompose from "./LeadSmsCompose";
import api from "../lib/api";

jest.mock("../lib/api", () => ({ __esModule: true, formatError: (value) => value, default: { get: jest.fn(), post: jest.fn() } }));

let container;
let root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  api.get.mockImplementation(async (url) => ({ data: url.endsWith("/config")
    ? { configured: true, enabled: true }
    : [] }));
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  jest.clearAllMocks();
});

test("opens the SMS composer and renders its controls", async () => {
  await act(async () => root.render(<LeadSmsCompose open onOpenChange={() => {}} wsId="workspace" lead={{ id: "lead-1", full_name: "Vinay", phone: "9876543210" }} />));
  expect(document.body.textContent).toContain("Send SMS");
  expect(document.body.textContent).toContain("+919876543210");
  expect(document.querySelector('textarea[aria-label="SMS message"]')).not.toBeNull();
});


test("agent SMS uses the permitted lead endpoints", async () => {
  await act(async () => root.render(<LeadSmsCompose open onOpenChange={() => {}} wsId="workspace" lead={{ id: "lead", phone: "+14155550123" }} apiBase="/workspaces/workspace/sales-portal/sms" />));
  expect(api.get).toHaveBeenCalledWith("/workspaces/workspace/sales-portal/sms/config");
  expect(api.get).toHaveBeenCalledWith("/workspaces/workspace/sales-portal/sms/leads/lead");
});
