import React, { act } from "react";
import { createRoot } from "react-dom/client";
import VoiceAgentSetup, { VoiceAgentBanner, canCall } from "./VoiceAgentSetup";
import api from "../lib/api";

jest.mock("react-router-dom", () => ({ Link: ({ to, children, ...rest }) => <a href={to} {...rest}>{children}</a> }), { virtual: true });
jest.mock("./InboundCallsSetup", () => () => <div data-testid="inbound-setup" />);
jest.mock("./DedicatedAgentSetup",() => (props) => <div data-testid="dedicated-setup">dedicated setup for {props.profile?.business_name}</div>);
jest.mock("../lib/api", () => ({
  __esModule: true,
  default: { get: jest.fn(), put: jest.fn(), post: jest.fn() },
  formatError: (detail) => String(detail),
}));
let container, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  try { localStorage.clear(); } catch { /* ignore */ }
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

const button = (text) => [...container.querySelectorAll("button")].find((b) => b.textContent.includes(text));
const field = (label) => [...container.querySelectorAll("label")].find((l) => l.textContent.startsWith(label)).querySelector("input, textarea");
const type = (el, value) => { const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value").set; setter.call(el, value); el.dispatchEvent(new Event("input", { bubbles: true })); };
const state = (overrides = {}) => ({
  active_type: null, calling_enabled: false, profile: null, defaults: { agent_name: "Priya", business_name: "Acme Homes" },
  trial: { status: "available", days: 14, days_left: null, expires_at: null, calling_number: "+917971413693" },
  dedicated: { configured: false, status: "missing_configuration", calling_number: null, agent_name: null }, ...overrides,
});
const PROFILE = { agent_name: "Priya", business_name: "Acme Homes", business_details: "Villas in Pune.", behaviour: "Ask budget first." };

test("a new workspace chooses the free trial, drafts details with AI and starts the trial", async () => {
  api.get.mockResolvedValue({ data: state() });
  api.post.mockImplementation((url) => Promise.resolve({ data: url.endsWith("/generate")
    ? { business_details: "Villas in Pune.", behaviour: "Ask budget first." }
    : state({ active_type: "master", calling_enabled: true, profile: PROFILE, trial: { status: "active", days: 14, days_left: 14, expires_at: "2026-11-26T00:00:00+00:00" } }) }));
  await act(async () => root.render(<VoiceAgentSetup workspaceId="A" />));
  expect(container.textContent).toContain("Not set up");
  await act(async () => button("Start 14-day free trial").click());
  // The trial path never mentions providers, accounts or keys (only the "own agent" option does).
  expect(button("Start 14-day free trial").textContent).not.toMatch(/sarvam|plivo|api key/i);
  expect(container.querySelector("p.text-xs").textContent).not.toMatch(/sarvam|plivo|api key/i);
  expect(field("Business name").value).toBe("Acme Homes");
  await act(async () => button("Generate with AI").click());
  expect(field("Agent behaviour").value).toBe("Ask budget first.");
  await act(async () => type(field("Agent name"), "Riya"));
  const start = [...container.querySelectorAll("button")].filter((b) => b.textContent.includes("Start 14-day free trial")).pop();
  await act(async () => start.click());
  expect(api.post).toHaveBeenLastCalledWith("/workspaces/A/voice-agent/trial", { ...PROFILE, agent_name: "Riya" });
  expect(container.textContent).toContain("Free trial · 14 days left");
});

test("connect your own agent shows the dedicated setup with the workspace details", async () => {
  api.get.mockResolvedValue({ data: state() });
  await act(async () => root.render(<VoiceAgentSetup workspaceId="A" />));
  await act(async () => button("Connect your own agent").click());
  expect(container.querySelector('[data-testid="dedicated-setup"]').textContent).toContain("Acme Homes");
});

test("an ended trial explains that calls stopped and offers the own agent", async () => {
  api.get.mockResolvedValue({ data: state({ active_type: "master", calling_enabled: true, profile: PROFILE,
    trial: { status: "expired", days: 14, days_left: 0, expires_at: "2026-11-01T00:00:00+00:00" } }) });
  await act(async () => root.render(<VoiceAgentSetup workspaceId="A" />));
  expect(container.textContent).toContain("Trial ended");
  expect(container.querySelector('[role="alert"]').textContent).toContain("Trial calls have stopped");
  expect(button("Resume calling")).toBeUndefined();
  expect(button("Connect your own agent")).toBeDefined();
});

test("switching to the own agent asks for confirmation first", async () => {
  api.get.mockResolvedValue({ data: state({ active_type: "master", calling_enabled: true, profile: PROFILE,
    trial: { status: "active", days: 14, days_left: 9, expires_at: "2026-11-21T00:00:00+00:00" },
    dedicated: { configured: true, status: "connected", calling_number: "+14155550123", agent_name: "Acme Qualifier" } }) });
  api.post.mockResolvedValue({ data: state({ active_type: "dedicated", calling_enabled: true, profile: PROFILE,
    dedicated: { configured: true, status: "connected", calling_number: "+14155550123", agent_name: "Acme Qualifier" } }) });
  await act(async () => root.render(<VoiceAgentSetup workspaceId="A" />));
  await act(async () => button("Switch to your own agent").click());
  expect(api.post).not.toHaveBeenCalled();
  expect(container.querySelector('[role="alertdialog"]').textContent).toContain("New calls will be placed by your own agent");
  await act(async () => [...container.querySelectorAll('[role="alertdialog"] button')].find((b) => b.textContent === "Switch").click());
  expect(api.post).toHaveBeenCalledWith("/workspaces/A/voice-agent/switch", { agent_type: "dedicated" });
  expect(container.textContent).toContain("Your own agent · active");
});

test("banner recommends setup until an agent exists and flags an ended trial", async () => {
  api.get.mockResolvedValue({ data: state() });
  await act(async () => root.render(<VoiceAgentBanner workspaceId="A" />));
  expect(container.textContent).toContain("Try it free for 14 days");
  api.get.mockResolvedValue({ data: state({ active_type: "dedicated", calling_enabled: true }) });
  await act(async () => root.render(<VoiceAgentBanner workspaceId="B" />));
  expect(container.textContent).not.toContain("Set up your AI voice agent");
  api.get.mockResolvedValue({ data: state({ active_type: "master", trial: { status: "expired", days: 14 } }) });
  await act(async () => root.render(<VoiceAgentBanner workspaceId="C" />));
  expect(container.textContent).toContain("trial has ended");
});

test("calling is only possible with an active agent", () => {
  expect(canCall(state())).toBe(false);
  expect(canCall(state({ active_type: "master", calling_enabled: true, trial: { status: "active" } }))).toBe(true);
  expect(canCall(state({ active_type: "master", calling_enabled: true, trial: { status: "expired" } }))).toBe(false);
  expect(canCall(state({ active_type: "dedicated", calling_enabled: false }))).toBe(false);
  expect(canCall(state({ active_type: "dedicated", calling_enabled: true, trial: { status: "expired" } }))).toBe(true);
});
