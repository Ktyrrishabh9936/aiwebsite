import React, { act } from "react";
import { createRoot } from "react-dom/client";
import DedicatedAgentSetup from "./DedicatedAgentSetup";
import VoiceAgentDetails from "./VoiceAgentDetails";
import api from "../lib/api";

jest.mock("./SarvamPasteSignIn", () => () => null);
jest.mock("./VoiceProviders", () => () => <div data-testid="manual-setup" />);
jest.mock("../lib/api", () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn() }, formatError: (detail) => String(detail) }));

const PROFILE = { agent_name: "Priya", business_name: "Doon Alliance", business_details: "Premium gated townships.", behaviour: "Ask the budget first." };
const routes = (keySaved) => (url) => Promise.resolve({ data:
  url.endsWith("/sarvam/account") ? { status: "connected", connected_by: "owner@example.com" }
  : url.endsWith("/sarvam/account/connections") ? { connections: [{ connection_id: "conn-1", name: "Main line", provider: "exotel", phone_numbers: ["+917971413693"] }] }
  : url.endsWith("/sarvam/account/voices") ? { voices: [] }
  : [{ provider: "sarvam", configured_secrets: keySaved ? ["api_key"] : [] }] });

let container, root;
beforeEach(() => { global.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });
const button = (text) => [...container.querySelectorAll("button")].find((item) => item.textContent.trim() === text);
const options = () => [...container.querySelectorAll("details")].find((item) => item.textContent.includes("More options"));

test("auto-filled Sarvam fields stay folded away and the agent is created with the same request as before", async () => {
  api.get.mockImplementation(routes(true));
  api.post.mockResolvedValue({ data: { creation: { agent_name: "Doon Alliance Lead Qualifier" }, provider: { status: "connected" } } });
  const onConnected = jest.fn();
  await act(async () => root.render(<DedicatedAgentSetup workspaceId="A" profile={PROFILE} configured={false} onConnected={onConnected} />));
  expect(container.textContent).toContain("Connected as owner@example.com");
  expect(container.textContent).toContain("Calls will come from +917971413693 (Main line).");
  expect(options().open).toBe(false);                                   // nothing technical on show
  expect(container.querySelector('input[type="password"]')).toBeNull(); // the saved key is never asked for again
  await act(async () => button("Create my agent").click());
  expect(api.post).toHaveBeenCalledWith("/workspaces/A/voice-providers/sarvam/agents", {
    creation_key: expect.any(String), agent_name: "Doon Alliance Lead Qualifier", business_name: "Doon Alliance", offer: "Premium gated townships.", objective: "",
    instructions: "Ask the budget first.", connection_id: "conn-1", agent_phone_number: "+917971413693", initial_language: "English", supported_languages: ["English", "Hindi"] });
  expect(onConnected).toHaveBeenCalledTimes(1);
  expect(container.querySelector('[role="status"]').textContent).toContain("Connection verified");
});

test("the options open by themselves when the calling key is still needed", async () => {
  api.get.mockImplementation(routes(false));
  await act(async () => root.render(<DedicatedAgentSetup workspaceId="A" profile={PROFILE} configured={false} />));
  expect(options().open).toBe(true);
  expect(options().textContent).toContain("needs your input");
  expect(container.querySelector('input[type="password"]')).not.toBeNull();
  expect(button("Create my agent").disabled).toBe(true);
});

test("the connected agent is shown as a readable page with its greeting and instructions", async () => {
  api.get.mockResolvedValue({ data: { available: true, type: "own", name: "Doon Alliance", version: 2, greeting: ["Hi, am I speaking with ", { variable: "lead_name" }, "?"],
    sections: [{ title: "Role", lines: ["You are the voice lead-qualification assistant for Doon Alliance."] }, { title: "Call inputs", lines: ["Every call receives these:", "- lead_name: the lead's name"] },
      { title: "Objective", lines: ["Qualify the lead."] }, { title: "Business and offer", lines: ["Premium gated townships."] }, { title: "Conversation rules", lines: ["- Ask one question at a time."] }],
    inputs: [{ name: "lead_name", description: "Lead name" }], outputs: [{ name: "budget", description: "Explicit amount" }], settings: [["Calls from", "+917971413693"]], note: "Created with these instructions." } });
  await act(async () => root.render(<VoiceAgentDetails workspaceId="A" />));
  expect(api.get).toHaveBeenCalledWith("/workspaces/A/ai-agents/voice-details");
  expect(container.textContent).toContain("Doon Alliance/ v2");
  expect(container.textContent).toContain("Hi, am I speaking with {} lead_name?");
  expect([...container.querySelectorAll("h5")].map((item) => item.textContent)).toEqual(["Role", "Call inputs", "Objective", "Business and offer"]);
  expect(container.querySelector("li").textContent).toBe("lead_name: the lead's name");
  await act(async () => button("Show all instructions (1 more sections)").click());
  expect(container.querySelectorAll("h5")).toHaveLength(5);
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find((item) => item.textContent === "Variables").click());
  expect(container.textContent).toContain("budget");
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find((item) => item.textContent === "Settings").click());
  expect(container.textContent).toContain("+917971413693");
});
