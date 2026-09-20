import React, { act } from "react";
import { createRoot } from "react-dom/client";
import Qualification from "./Qualification";
import api from "../../lib/api";

jest.mock("react-router-dom", () => ({ useOutletContext: () => ({ ws: { id: "workspace" }, refresh: async () => {} }), Link: ({ children, to }) => <a href={to}>{children}</a> }), { virtual: true });
jest.mock("../../lib/api", () => ({ __esModule: true, default: { get: jest.fn(), put: jest.fn(), post: jest.fn() } }));
jest.mock("sonner", () => ({ toast: { success: jest.fn() } }));

const template = {
  voice_provider: "plivo",
  product_name: "Software", product_description: "", target_customer: "", campaign_id: null,
  price_range: { min: null, max: null, currency: null },
  mandatory_qualification_criteria: [], disqualification_criteria: [], qualification_criteria: [], special_rules: [],
  required_information: ["product_fit"], service_locations: [], weights: { product_fit: 100 }, scoring_rules: {},
  qualified_threshold: 50, sales_ready_threshold: 85, desired_next_action: "SALES_CALL", available_next_actions: ["SALES_CALL"],
  retry: { max_attempts: 4, retry_rules: [] },
};
let container, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test("retrying a failed default assignment updates the saved profile instead of creating another", async () => {
  let profiles = [];
  api.get.mockImplementation(async () => ({ data: { template, profiles, default_profile_id: null } }));
  api.post.mockImplementation(async (url, draft) => {
    if (url.endsWith("/default")) throw new Error("Default update unavailable");
    const saved = { ...draft, id: "saved-profile" }; profiles = [saved]; return { data: saved };
  });
  api.put.mockImplementation(async (url, draft) => ({ data: { ...draft, id: "saved-profile" } }));
  await act(async () => root.render(<Qualification />));
  const save = () => [...container.querySelectorAll("button")].find((b) => b.textContent === "Save as workspace default");
  await act(async () => save().click());
  expect(container.querySelector('[role="alert"]').textContent).toBe("Default update unavailable");
  expect(container.querySelector("select").value).toBe("saved-profile");
  await act(async () => save().click());
  expect(api.post.mock.calls.filter(([url]) => url.endsWith("/profiles"))).toHaveLength(1);
  expect(api.put).toHaveBeenCalledWith("/workspaces/workspace/crm/qualification/profiles/saved-profile", template);
});

test("reopens the workspace default profile with its saved Sarvam provider", async () => {
  const saved = { ...template, id: "default-profile", voice_provider: "sarvam", product_name: "Sarvam qualification" };
  api.get.mockResolvedValue({ data: { template, profiles: [saved], default_profile_id: saved.id, default_voice_provider: "sarvam" } });
  await act(async () => root.render(<Qualification />));
  const selects = [...container.querySelectorAll("select")];
  expect(selects[0].value).toBe(saved.id);
  expect(selects.find((select) => [...select.options].some((option) => option.value === "sarvam")).value).toBe("sarvam");
});

test("saves automatic new-lead timing for the workspace", async () => {
  api.get.mockResolvedValue({ data: { template, profiles: [], default_profile_id: null, calling_settings: { call_mode: "manual", initial_delay_seconds: 300, timezone: "Asia/Kolkata", calling_window: { start: "09:30", end: "19:00" } } } });
  api.put.mockResolvedValue({ data: { call_mode: "automatic", initial_delay_seconds: 30, timezone: "Asia/Kolkata", calling_window: { start: "09:30", end: "19:00" } } });
  await act(async () => root.render(<Qualification />));
  const automatic = container.querySelector('input[value="automatic"]');
  await act(async () => automatic.click());
  const delay = container.querySelector('[aria-label="Automatic call delay"]');
  await act(async () => { delay.value = "30"; delay.dispatchEvent(new Event("change", { bubbles: true })); });
  const save = [...container.querySelectorAll("button")].find((button) => button.textContent === "Save call mode");
  await act(async () => save.click());
  expect(api.put).toHaveBeenCalledWith("/workspaces/workspace/crm/qualification/calling-settings", expect.objectContaining({ call_mode: "automatic", initial_delay_seconds: 30 }));
});
