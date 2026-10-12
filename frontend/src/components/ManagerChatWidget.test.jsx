import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { ManagerChatWidget, pageContext } from "./ManagerChatWidget";
import { useAiStatus } from "./AiStatus";
import { loadManagerConversation } from "../lib/managerAgent";

let mockLocation = { pathname: "/app/w/ws", search: "" };
jest.mock("react-router-dom", () => ({ useLocation: () => mockLocation }), { virtual: true });
jest.mock("sonner", () => ({ toast: { error: jest.fn() } }));
jest.mock("./AiStatus", () => ({ AiStatus: () => null, useAiStatus: jest.fn(), aiErrorMessage: () => "Please retry." }));
jest.mock("./ChatText", () => ({ ChatText: ({ text }) => <span>{text}</span> }));
jest.mock("../lib/managerAgent", () => ({
  conversationId: () => "conversation-test", newManagerId: () => "request-test",
  loadManagerConversation: jest.fn(async () => ({ messages: [] })),
}));

const LEAD = "65f1a2b3c4d5e6f708192a3b";
let container, root, run;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  loadManagerConversation.mockResolvedValue({ messages: [] });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  run = jest.fn(async (message, history, update, options) => {
    options.onEvent({ type: "tool_started", label: "Recording payment receipt" });
    options.onEvent({ type: "tool_finished", operation_id: "op1", status: "completed", writes: true, label: "Recording payment receipt", link: `/app/w/ws/crm?lead=${LEAD}` });
    options.onEvent({ type: "tool_finished", operation_id: "op2", status: "completed", writes: false, label: "Reading payments and receipts" });
    update("Recorded ₹5,000. Remaining due is ₹15,000.");
  });
  useAiStatus.mockReturnValue({ state: "untested", run });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test("page context tells the manager which page and lead the owner is viewing", () => {
  expect(pageContext("/app/w/ws/customers", "")).toBe("[Workspace section: Customers]");
  expect(pageContext("/app/w/ws/crm", `?lead=${LEAD}`)).toBe(`[Workspace section: CRM] [Viewing lead id: ${LEAD}]`);
  expect(pageContext("/app/w/ws/products-services", "?lead=not-an-id")).toBe("[Workspace section: Products]");
});

test("chat runs in agent mode from any page and lists saved changes with links", async () => {
  mockLocation = { pathname: "/app/w/ws/crm", search: `?lead=${LEAD}` };
  await act(async () => root.render(<ManagerChatWidget ws={{ id: "ws", name: "Studio" }} />));
  await act(async () => container.querySelector('button[title="Open AI manager"]').click());
  const input = container.querySelector('input[aria-label="Message AI manager"]');
  const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  await act(async () => { setValue.call(input, "Record 5000 paid by UPI today"); input.dispatchEvent(new Event("input", { bubbles: true })); });
  await act(async () => container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  const [message, , , options] = run.mock.calls[0];
  expect(message).toBe(`[Workspace section: CRM] [Viewing lead id: ${LEAD}] Record 5000 paid by UPI today`);
  expect(options).toMatchObject({ agentMode: true, conversationId: "conversation-test" });
  const changes = container.querySelector('[aria-label="Changes made"]');
  expect(changes.textContent).toContain("Saved: Recording payment receipt");
  expect(changes.textContent).not.toContain("Reading payments");
  expect(changes.querySelector("a").getAttribute("href")).toBe(`/app/w/ws/crm?lead=${LEAD}`);
  expect(container.textContent).toContain("Remaining due is ₹15,000.");
});

test("restored conversation hides internal page tags", async () => {
  loadManagerConversation.mockResolvedValue({ messages: [{ role: "user", content: "[Workspace section: Customers] Who owes money?" }] });
  mockLocation = { pathname: "/app/w/ws", search: "" };
  await act(async () => root.render(<ManagerChatWidget ws={{ id: "ws", name: "Studio" }} />));
  await act(async () => container.querySelector('button[title="Open AI manager"]').click());
  expect(container.querySelector('[role="log"]').textContent).toContain("Who owes money?");
  expect(container.querySelector('[role="log"]').textContent).not.toContain("[Workspace section");
});
