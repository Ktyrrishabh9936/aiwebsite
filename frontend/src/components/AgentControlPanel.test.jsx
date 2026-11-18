import React, { act } from "react";
import { createRoot } from "react-dom/client";
import AgentControlPanel from "./AgentControlPanel";
import api from "../lib/api";

jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock("./VoiceAgentSetup", () => () => <div data-testid="voice-setup">voice agent setup</div>);
jest.mock("../lib/api", () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() }, formatError: (detail) => String(detail || "error") }));

const agent = (id, name, role, stages, extra = {}) => ({
  id, name, role, role_label: name, builtin: true, description: `${name} description`, enabled: true, stages, actions: ["call", "email"], status: "ready", instructions: "",
  capabilities: [{ action: "call", available: true, note: "Calls from +911234567890" }, { action: "email", available: true, note: "Sent from hello@studio.test" }],
  updated_at: "2026-11-17T05:00:00+00:00", ...extra,
});
const team = (changes = {}, voice = { connected: true, reason: "" }) => ({
  agents: [agent("a1", "First Call Agent", "first_call", [{ key: "new", label: "New" }]),
    agent("a2", "Follow-up Agent", "follow_up", [{ key: "contacted", label: "Contacted" }], changes)],
  channels: { voice },
  stages: [{ key: "new", label: "New" }, { key: "contacted", label: "Contacted" }, { key: "proposal", label: "Proposal" }],
  unassigned_stages: [{ key: "proposal", label: "Proposal" }],
});

let container, root;
beforeEach(() => { global.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

const type = async (element, value) => act(async () => {
  Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), "value").set.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
});
const button = (text) => [...container.querySelectorAll("button")].find((item) => item.textContent.trim() === text);
const submit = () => act(async () => container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));

test("lists the voice agent and every agent, and shows one agent as a short page", async () => {
  api.get.mockResolvedValue({ data: team() });
  await act(async () => root.render(<AgentControlPanel wsId="ws" />));
  expect(api.get).toHaveBeenCalledWith("/workspaces/ws/ai-agents");
  expect([...container.querySelectorAll("nav button")].map((item) => item.textContent)).toEqual(["Voice agent", "First Call Agent", "Follow-up Agent", "New agent"]);
  expect(container.querySelector("form").getAttribute("aria-label")).toBe("First Call Agent details");
  expect([...container.querySelectorAll("form h4")].map((item) => item.textContent)).toEqual(["Role", "Works on leads in", "Can do", "Instructions"]);
  expect(container.textContent).toContain("No agent works on Proposal leads");
  await act(async () => button("Voice agent").click());
  expect(container.querySelector('[data-testid="voice-setup"]')).not.toBeNull(); // the existing voice agent screen, unchanged
  expect(container.querySelector("form")).toBeNull();
});

test("editing an agent saves only what changed", async () => {
  api.get.mockResolvedValue({ data: team() });
  api.patch.mockResolvedValue({ data: team({ instructions: "Offer a site visit.", stages: [{ key: "contacted", label: "Contacted" }, { key: "proposal", label: "Proposal" }], updated_at: "2026-11-17T06:00:00+00:00" }) });
  await act(async () => root.render(<AgentControlPanel wsId="ws" />));
  await act(async () => button("Follow-up Agent").click());
  expect(button("Save").disabled).toBe(true); // nothing to save yet
  await type(container.querySelector('[aria-label="Instructions"]'), "Offer a site visit.");
  await act(async () => [...container.querySelectorAll("form button[aria-pressed]")].find((item) => item.textContent === "Proposal").click());
  await submit();
  expect(api.patch).toHaveBeenCalledWith("/workspaces/ws/ai-agents/a2", { instructions: "Offer a site visit.", stages: ["contacted", "proposal"] });
  expect(button("Save").disabled).toBe(true); // the saved agent is now what the form shows
});

test("says plainly when calls cannot run, and points to the voice agent", async () => {
  const noVoice = { capabilities: [{ action: "call", available: false, note: "No voice agent is set up yet." }, { action: "email", available: true, note: "" }], status: "limited" };
  api.get.mockResolvedValue({ data: team(noVoice, { connected: false, reason: "No voice agent is set up yet." }) });
  await act(async () => root.render(<AgentControlPanel wsId="ws" compact />));
  await act(async () => button("Follow-up Agent").click());
  expect(container.textContent).toContain("Phone calls cannot run yet: No voice agent is set up yet.");
  await act(async () => button("Set up the voice agent").click());
  expect(container.querySelector('[data-testid="voice-setup"]')).not.toBeNull();
});

test("an agent can be switched off and a new one created", async () => {
  api.get.mockResolvedValue({ data: team() });
  api.patch.mockResolvedValue({ data: team({ enabled: false, status: "off" }) });
  const created = team();
  created.agents.push(agent("a3", "Site Visit Agent", "custom", [{ key: "proposal", label: "Proposal" }], { builtin: false, actions: ["email"] }));
  api.post.mockResolvedValue({ data: created });
  await act(async () => root.render(<AgentControlPanel wsId="ws" />));
  await act(async () => button("Follow-up Agent").click());
  await act(async () => container.querySelector('[aria-label="Agent is on"]').click());
  await submit();
  expect(api.patch).toHaveBeenCalledWith("/workspaces/ws/ai-agents/a2", { enabled: false });

  await act(async () => button("New agent").click());
  expect(button("Create agent").disabled).toBe(true); // needs a name and a stage
  await type(container.querySelector('[aria-label="Agent name"]'), "Site Visit Agent");
  await act(async () => [...container.querySelectorAll("form button[aria-pressed]")].find((item) => item.textContent === "Proposal").click());
  await submit();
  expect(api.post).toHaveBeenCalledWith("/workspaces/ws/ai-agents", { name: "Site Visit Agent", description: "", stages: ["proposal"], actions: ["email"], instructions: "", enabled: true });
  expect(container.querySelector("form").getAttribute("aria-label")).toBe("Site Visit Agent details");
  expect(button("Delete")).toBeTruthy(); // only custom agents can be deleted
});
