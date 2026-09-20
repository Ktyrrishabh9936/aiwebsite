import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { AgentWorkspace } from "./AgentWorkspace";
import { useAiStatus } from "./AiStatus";

jest.mock("./AiStatus", () => ({ useAiStatus: jest.fn(), aiErrorMessage: () => "Please retry the connection." }));
jest.mock("./ChatText", () => ({ ChatText: ({ text }) => <span>{text}</span> }));
let container, root, run;
const ws = { id: "one", name: "My business" };
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  run = jest.fn(async (message, history, update) => update("Here is your plan."));
  useAiStatus.mockReturnValue({ state: "untested", run });
});
afterEach(() => { act(() => root.unmount()); container.remove(); delete window.SpeechRecognition; jest.clearAllMocks(); });
const button = (text) => Array.from(container.querySelectorAll("button")).find((node) => node.textContent.includes(text));

test("a galaxy section focuses the real manager request without sending on selection", async () => {
  await act(async () => root.render(<AgentWorkspace ws={ws} active />));
  await act(async () => button("CRM").click());
  expect(run).not.toHaveBeenCalled();
  await act(async () => button("Ask about CRM").click());
  await act(async () => container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(run).toHaveBeenCalledWith(expect.stringContaining("[Workspace section: CRM]"), [], expect.any(Function));
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
