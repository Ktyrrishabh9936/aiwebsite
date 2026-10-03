import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { AgentWorkspace } from "./AgentWorkspace";
import { useAiStatus } from "./AiStatus";
import { loadManagerConversation, getManagerRun } from "../lib/managerAgent";

jest.mock("./AiStatus", () => ({ useAiStatus: jest.fn(), aiErrorMessage: () => "Please retry the connection." }));
jest.mock("./ChatText", () => ({ ChatText: ({ text }) => <span>{text}</span> }));
jest.mock("../lib/managerAgent", () => ({
  conversationId: () => "conversation-test", newManagerId: () => "request-test",
  loadManagerConversation: jest.fn(async () => ({ messages: [], runs: [] })),
  getManagerRun: jest.fn(async () => ({ run_id: "run-test", status: "completed", events: [] })),
}));
let container, root, run;
const ws = { id: "one", name: "My business" };
beforeEach(() => {
  loadManagerConversation.mockResolvedValue({ messages: [], runs: [] });
  getManagerRun.mockResolvedValue({ run_id: "run-test", status: "completed", events: [] });
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  run = jest.fn(async (message, history, update) => update("Here is your plan."));
  useAiStatus.mockReturnValue({ state: "untested", run });
});
afterEach(() => { act(() => root.unmount()); container.remove(); delete window.SpeechRecognition; jest.clearAllMocks(); });
const button = (text) => Array.from(container.querySelectorAll("button")).find((node) => node.textContent.includes(text));

test("visual workspace opens on demand after a prompt and returns to the saved chat", async () => {
  await act(async () => root.render(<AgentWorkspace ws={ws} active />));
  expect(button("See it working").getAttribute("aria-expanded")).toBe("false");
  await act(async () => button("What should I focus on today?").click());
  await act(async () => container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  await act(async () => button("See it working").click());
  expect(button("See it working").getAttribute("aria-expanded")).toBe("true");
  expect(container.querySelector(".agent-space").classList.contains("show-workspace")).toBe(true);
  await act(async () => button("Back to chat").click());
  expect(button("See it working").getAttribute("aria-expanded")).toBe("false");
  expect(container.querySelector('[role="log"]').textContent).toContain("Here is your plan.");
  expect(document.activeElement).toBe(container.querySelector("textarea"));
});

test("activity restores saved changes and distinguishes pending delegation from a completed call", async () => {
  loadManagerConversation.mockResolvedValue({ messages: [{ role: "assistant", content: "Follow-up saved." }], runs: [{
    run_id: "saved-run", status: "completed", events: [
      { run_id: "saved-run", operation_id: "save", type: "tool_finished", status: "completed", writes: true, label: "Scheduling a human follow-up", agent: "AI Manager", section: "CRM", summary: "Saved in workspace" },
      { run_id: "saved-run", operation_id: "call", type: "tool_finished", status: "delegated", writes: true, label: "Delegating initial qualification", agent: "Qualification agent", section: "AI Agents", job: { state: "started" } },
    ],
  }] });
  await act(async () => root.render(<AgentWorkspace ws={ws} active={false} />));
  expect(container.textContent).toContain("1 saved changes");
  expect(container.textContent).toContain("1 pending delegations");
  expect(container.querySelector('[data-status="delegated"]').textContent).toContain("Qualification: started");
  expect(container.querySelector('[role="log"]').textContent).toContain("Follow-up saved.");
});

test("interrupted work stops spinning and does not count as a saved change", async () => {
  loadManagerConversation.mockResolvedValue({ messages: [], runs: [{ run_id: "stopped", status: "interrupted", events: [
    { run_id: "stopped", operation_id: "write", type: "tool_started", status: "running", writes: true, label: "Saving a note", agent: "AI Manager", section: "CRM" },
    { run_id: "stopped", type: "run_finished", status: "interrupted" },
  ] }] });
  await act(async () => root.render(<AgentWorkspace ws={ws} active={false} />));
  expect(container.querySelector('[data-status="failed"]').textContent).toContain("outcome is not confirmed");
  expect(container.querySelector(".agent-node.is-working")).toBeNull();
  expect(container.textContent).toContain("0 saved changes");
});

test("a galaxy section focuses the real manager request without sending on selection", async () => {
  await act(async () => root.render(<AgentWorkspace ws={ws} active />));
  await act(async () => button("CRM").click());
  expect(run).not.toHaveBeenCalled();
  await act(async () => button("Ask about CRM").click());
  await act(async () => container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(run).toHaveBeenCalledWith(expect.stringContaining("[Workspace section: CRM]"), [], expect.any(Function),
    expect.objectContaining({ agentMode: true, conversationId: "conversation-test", onEvent: expect.any(Function) }));
  expect(container.querySelector('[role="log"]').textContent).toContain("Here is your plan.");
});

test("unsupported voice leaves typing available and failed requests can be retried", async () => {
  run.mockRejectedValueOnce(new Error("offline"));
  await act(async () => root.render(<AgentWorkspace ws={ws} active />));
  expect(container.querySelector('[aria-label="Start voice input"]').disabled).toBe(true);
  await act(async () => button("What should I focus on today?").click());
  await act(async () => container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(container.textContent).toContain("Please retry the connection.");
  expect(container.querySelector("textarea").disabled).toBe(false);
});

test("voice transcription stays in the draft and stops when Human Mode opens", async () => {
  let recognition;
  window.SpeechRecognition = class {
    constructor() { recognition = this; this.start = jest.fn(); this.abort = jest.fn(); }
  };
  await act(async () => root.render(<AgentWorkspace ws={ws} active />));
  await act(async () => container.querySelector('[aria-label="Start voice input"]').click());
  await act(async () => recognition.onresult({ results: [[{ transcript: "Plan my week" }]] }));
  expect(container.querySelector("textarea").value).toBe("Plan my week");
  expect(run).not.toHaveBeenCalled();
  await act(async () => root.render(<AgentWorkspace ws={ws} active={false} />));
  expect(recognition.abort).toHaveBeenCalled();
  expect(container.querySelector("textarea").value).toBe("Plan my week");
});
