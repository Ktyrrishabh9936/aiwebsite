import React, { act } from "react";
import { createRoot } from "react-dom/client";
import VoiceProviders from "./VoiceProviders";
import api from "../lib/api";

jest.mock("../lib/api", () => ({ __esModule: true, default: { get: jest.fn(), put: jest.fn(), post: jest.fn() } }));
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
