import React, { act } from "react";
import { createRoot } from "react-dom/client";
import VoiceProviders from "./VoiceProviders";
import api from "../lib/api";

jest.mock("../lib/api", () => ({
  __esModule: true,
  default: { get: jest.fn(), put: jest.fn(), post: jest.fn() },
  formatError: (detail) => Array.isArray(detail) ? detail.map((item) => item.msg || JSON.stringify(item)).join(" ") : String(detail),
}));
let container, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test("provider fields switch independently and saved secrets are never displayed or resubmitted", async () => {
  api.get.mockResolvedValue({ data: [
    { provider: "plivo", enabled: true, config: { auth_id: "account" }, configured_secrets: ["auth_token"], status: "connected", revision: 1 },
    { provider: "sarvam", enabled: false, config: { organization_id: "org", workspace_id: "sarvam-ws", app_id: "agent",
      app_version: 4, connection_id: "connection", agent_phone_number: "+14155550123" },
      configured_secrets: ["api_key"], callback_security_configured: true, status: "unverified", revision: 2 },
  ] });
  api.put.mockResolvedValue({ data: {} });
  api.post.mockResolvedValue({ data: { status: "invalid_credentials" } });
  await act(async () => root.render(<VoiceProviders workspaceId="A" />));
  expect(container.textContent).toContain("Auth ID");
  expect(container.textContent).not.toContain("Sarvam organization ID");
  expect([...container.querySelectorAll('input[type="password"]')].every((i) => i.value === "")).toBe(true);
  await act(async () => {
    const select = container.querySelector("select"); select.value = "sarvam"; select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(container.textContent).toContain("Sarvam organization ID");
  expect(container.textContent).toContain("Agent phone number");
  expect(container.textContent).toContain("Callback Security");
  expect(container.textContent).toContain("✓ Automatically configured");
  expect(container.textContent).not.toContain("Callback secret (choose 32+ characters)");
  expect(container.textContent).not.toContain("Auth ID");
  expect(container.querySelectorAll('input[type="password"]')).toHaveLength(1);
  await act(async () => [...container.querySelectorAll("button")].find((b) => b.textContent === "Regenerate Secret").click());
  expect(api.post).toHaveBeenCalledWith("/workspaces/A/voice-providers/sarvam/callback-secret/regenerate", { revision: 2 });
  expect(container.querySelector('[role="status"]').textContent).toBe("Callback security regenerated. Existing calls remain valid.");
  await act(async () => [...container.querySelectorAll("button")].find((b) => b.textContent === "Save & Test Connection").click());
  expect(api.put).toHaveBeenCalledWith("/workspaces/A/voice-providers/sarvam", expect.objectContaining({
    credentials: {}, revision: 2, enabled: false,
    config: { organization_id: "org", workspace_id: "sarvam-ws", app_id: "agent", app_version: 4,
      connection_id: "connection", agent_phone_number: "+14155550123" },
  }));
  expect(api.post).toHaveBeenCalledWith("/workspaces/A/voice-providers/sarvam/test", {});
  expect(container.querySelector('[role="status"]').textContent).toBe("invalid credentials");
});

test("opens the workspace default provider instead of resetting to Plivo", async () => {
  api.get.mockResolvedValue({ data: [
    { provider: "plivo", enabled: true, config: { auth_id: "account" }, configured_secrets: ["auth_token"], status: "connected", revision: 1, is_default: false },
    { provider: "sarvam", enabled: true, config: { organization_id: "org", payload_mode: "lead_context_v1" }, configured_secrets: ["api_key"], status: "connected", revision: 2, is_default: true },
  ] });

  await act(async () => root.render(<VoiceProviders workspaceId="A" />));

  expect(container.querySelector("select").value).toBe("sarvam");
  expect(container.textContent).toContain("Sarvam organization ID");
});

test("creates a simple Sarvam setup guide with the fixed variables", async () => {
  api.get.mockResolvedValue({ data: [
    { provider: "plivo", enabled: false, config: {}, status: "missing_configuration" },
    { provider: "sarvam", enabled: false, config: {}, status: "missing_configuration", callback_security_configured: false },
  ] });
  api.post.mockResolvedValue({ data: {
    prompt: "Use lead_name and lead_context.",
    variables: [{ name: "lead_name" }, { name: "lead_phone" }, { name: "lead_context" }],
    steps: ["Commit the agent."],
    output_prompt: "Create requirement and product_fit outputs.",
    output_variables: [{ name: "requirement", type: "String" }, { name: "product_fit", type: "String" }],
    fresh_agent_steps: ["Paste the output prompt."],
  } });
  await act(async () => root.render(<VoiceProviders workspaceId="A" />));
  await act(async () => {
    const select = container.querySelector("select"); select.value = "sarvam"; select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(container.querySelector('[aria-label="Agent input mode"]').value).toBe("lead_context_v1");
  const details = [...container.querySelectorAll("details")].find((item) => item.textContent.includes("Set up a new Sarvam agent"));
  details.open = true;
  await act(async () => [...container.querySelectorAll("button")].find((button) => button.textContent === "Generate setup guide").click());
  expect(api.post).toHaveBeenCalledWith("/workspaces/A/voice-providers/sarvam/setup-guide", {
    business_name: "", offer: "", objective: "", instructions: "",
  });
  expect(container.querySelector('[aria-label="Sarvam setup guide"]')).not.toBeNull();
  expect(container.textContent).toContain("lead_context");
  expect(container.textContent).toContain("existing qualification output variables will remain unchanged");
  expect(container.textContent).toContain("Creating a fresh agent? Add qualification outputs");
  expect(container.querySelector('[aria-label="Generated Sarvam output variable prompt"]').value).toContain("product_fit");
  expect(details.textContent).toContain("Setup guide ready");
});

test("shows setup guide API failures beside the button", async () => {
  api.get.mockResolvedValue({ data: [
    { provider: "plivo", enabled: false, config: {}, status: "missing_configuration" },
    { provider: "sarvam", enabled: false, config: {}, status: "missing_configuration" },
  ] });
  api.post.mockRejectedValue({ response: { status: 404 } });
  await act(async () => root.render(<VoiceProviders workspaceId="A" />));
  await act(async () => {
    const select = container.querySelector("select"); select.value = "sarvam"; select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const details = [...container.querySelectorAll("details")].find((item) => item.textContent.includes("Set up a new Sarvam agent"));
  details.open = true;
  await act(async () => [...container.querySelectorAll("button")].find((button) => button.textContent === "Generate setup guide").click());
  expect(details.querySelector('[role="status"]').textContent).toContain("not available on the running backend");
});

test("shows setup guide validation details", async () => {
  api.get.mockResolvedValue({ data: [
    { provider: "plivo", enabled: false, config: {}, status: "missing_configuration" },
    { provider: "sarvam", enabled: false, config: {}, status: "missing_configuration" },
  ] });
  api.post.mockRejectedValue({ response: { status: 422, data: { detail: [{ msg: "Instructions are too long" }] } } });
  await act(async () => root.render(<VoiceProviders workspaceId="A" />));
  await act(async () => {
    const select = container.querySelector("select"); select.value = "sarvam"; select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const details = [...container.querySelectorAll("details")].find((item) => item.textContent.includes("Set up a new Sarvam agent"));
  details.open = true;
  await act(async () => [...container.querySelectorAll("button")].find((button) => button.textContent === "Generate setup guide").click());
  expect(details.querySelector('[role="status"]').textContent).toBe("Instructions are too long");
});
