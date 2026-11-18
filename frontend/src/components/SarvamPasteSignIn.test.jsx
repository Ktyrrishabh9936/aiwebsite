import React, { act } from "react";
import { createRoot } from "react-dom/client";
import SarvamPasteSignIn from "./SarvamPasteSignIn";
import api from "../lib/api";

jest.mock("../lib/api", () => ({
  __esModule: true,
  default: { post: jest.fn() },
  formatError: (detail) => String(detail),
}));

let container, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

const button = (text) => [...container.querySelectorAll("button")].find((b) => b.textContent.includes(text));
const type = (el, value) => { const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value").set; setter.call(el, value); el.dispatchEvent(new Event("input", { bubbles: true })); };
const flush = () => act(async () => { await Promise.resolve(); });

test("sends the pasted address and reports success", async () => {
  api.post.mockResolvedValue({ data: { status: "connected" } });
  const onConnected = jest.fn();
  act(() => root.render(<SarvamPasteSignIn workspaceId="ws1" onConnected={onConnected} />));
  expect(button("Finish connecting").disabled).toBe(true);
  const address = "http://127.0.0.1:53682/arevei/sarvam/callback?code=abc&state=xyz";
  act(() => type(container.querySelector("input"), `  ${address} `));
  await act(async () => { button("Finish connecting").click(); });
  await flush();
  expect(api.post).toHaveBeenCalledWith("/workspaces/ws1/voice-providers/sarvam/account/complete", { callback_url: address });
  expect(onConnected).toHaveBeenCalled();
});

test("shows the server's explanation when the address is wrong", async () => {
  api.post.mockRejectedValue({ response: { data: { detail: { code: "invalid_paste", message: "That is not the Sarvam sign-in address." } } } });
  const onConnected = jest.fn();
  act(() => root.render(<SarvamPasteSignIn workspaceId="ws1" onConnected={onConnected} />));
  act(() => type(container.querySelector("input"), "https://example.com"));
  await act(async () => { button("Finish connecting").click(); });
  await flush();
  expect(container.querySelector("[role=alert]").textContent).toContain("That is not the Sarvam sign-in address.");
  expect(onConnected).not.toHaveBeenCalled();
});

test("finishes by itself when the Sarvam address is pasted", async () => {
  api.post.mockResolvedValue({ data: { status: "connected" } });
  const onConnected = jest.fn();
  act(() => root.render(<SarvamPasteSignIn workspaceId="ws1" onConnected={onConnected} />));
  const address = "http://127.0.0.1:53682/arevei/sarvam/callback?code=abc&state=xyz";
  const paste = new Event("paste", { bubbles: true, cancelable: true });
  paste.clipboardData = { getData: () => ` ${address}\n` };
  await act(async () => { container.querySelector("input").dispatchEvent(paste); });
  await flush();
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post).toHaveBeenCalledWith("/workspaces/ws1/voice-providers/sarvam/account/complete", { callback_url: address });
  expect(onConnected).toHaveBeenCalled();
});

test("reads the copied address with one click and rejects other clipboard text", async () => {
  api.post.mockResolvedValue({ data: { status: "connected" } });
  const readText = jest.fn().mockResolvedValue("just some text");
  Object.defineProperty(navigator, "clipboard", { value: { readText }, configurable: true });
  const onConnected = jest.fn();
  act(() => root.render(<SarvamPasteSignIn workspaceId="ws1" onConnected={onConnected} />));
  await act(async () => { button("Use copied address").click(); });
  await flush();
  expect(api.post).not.toHaveBeenCalled();
  expect(container.querySelector("[role=alert]").textContent).toContain("not the Sarvam address");
  readText.mockResolvedValue("http://127.0.0.1:53682/arevei/sarvam/callback?code=c1&state=s1");
  await act(async () => { button("Use copied address").click(); });
  await flush();
  expect(api.post).toHaveBeenCalledWith("/workspaces/ws1/voice-providers/sarvam/account/complete", { callback_url: "http://127.0.0.1:53682/arevei/sarvam/callback?code=c1&state=s1" });
  expect(onConnected).toHaveBeenCalled();
  delete navigator.clipboard;
});
