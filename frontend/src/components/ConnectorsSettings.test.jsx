import React, { act } from "react";
import { createRoot } from "react-dom/client";
import ConnectorsSettings from "./ConnectorsSettings";
import api from "../lib/api";

jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock("react-router-dom", () => ({ Link: ({ to, children, ...props }) => <a href={to} {...props}>{children}</a> }), { virtual: true });
jest.mock("../lib/api", () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), patch: jest.fn(), delete: jest.fn() }, formatError: (detail) => String(detail || "error") }));

const status = (changes = {}) => ({
  email: { mode: "platform", platform_ready: true, sending_from: "hello@arevei.test", smtp: null },
  google: { connected: false, services: [] }, calendly: { connected: false, url: null }, calendar: { connected: false, google: false, provider: null }, ...changes,
});

let container, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  api.get.mockImplementation((url) => Promise.resolve({ data: url.endsWith("/voice-agent") ? { active_type: null } : status() }));
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

const type = async (element, value) => act(async () => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
});
const button = (text, scope = container) => [...scope.querySelectorAll("button")].find((item) => item.textContent.trim() === text);
const row = (name) => [...container.querySelectorAll("li")].find((item) => item.querySelector("p").textContent.startsWith(name));

test("lists every connector with its state and one button each", async () => {
  await act(async () => root.render(<ConnectorsSettings wsId="ws" />));
  expect([...container.querySelectorAll("li")].map((item) => item.querySelector("p").textContent.replace("Connected", ""))).toEqual(["Email", "Google Calendar", "Calendly", "Voice agent", "SMS"]);
  expect(row("Email").textContent).toContain("Working now from hello@arevei.test. Nothing to set up.");
  expect(button("Connect", row("Google Calendar"))).toBeTruthy();
  expect(row("Voice agent").querySelector("a").getAttribute("href")).toBe("/app/w/ws/ai?agent=voice");
  expect(container.querySelector('input[type="password"]')).toBeNull(); // no form until the owner asks for one
});

test("your own email needs only the address and password", async () => {
  api.put.mockResolvedValue({ data: status({ email: { mode: "smtp", platform_ready: true, sending_from: "sales@gmail.com", smtp: {} } }) });
  await act(async () => root.render(<ConnectorsSettings wsId="ws" />));
  await act(async () => button("Use my own email").click());
  expect(button("Continue with Gmail")).toBeTruthy();
  await type(container.querySelector('input[type="email"]'), "sales@gmail.com");
  await type(container.querySelector('input[type="password"]'), "app-password");
  expect(container.textContent).not.toContain("Mail server"); // known provider: nothing technical to fill in
  await act(async () => row("Email").querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(api.put).toHaveBeenCalledWith("/workspaces/ws/connectors/email/smtp", { host: "smtp.gmail.com", port: 587, username: "sales@gmail.com", password: "app-password", from_email: "sales@gmail.com", from_name: "" });
  expect(row("Email").textContent).toContain("Sending from sales@gmail.com");
  expect(button("Disconnect", row("Email"))).toBeTruthy();
});

test("an unknown email provider shows the guessed mail server, and Calendly takes a link", async () => {
  api.put.mockResolvedValue({ data: status({ calendly: { connected: true, url: "https://calendly.com/studio/demo" }, calendar: { connected: true, google: false, provider: "calendly" } }) });
  await act(async () => root.render(<ConnectorsSettings wsId="ws" />));
  await act(async () => button("Use my own email").click());
  await type(container.querySelector('input[type="email"]'), "sales@studio.example");
  expect(row("Email").querySelector('label:last-of-type input').value).toBe("smtp.studio.example");
  await act(async () => button("Connect", row("Calendly")).click());
  await type(container.querySelector('[aria-label="Your Calendly link"]'), "calendly.com/studio/demo");
  await act(async () => row("Calendly").querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(api.put).toHaveBeenCalledWith("/workspaces/ws/connectors/calendly", { url: "calendly.com/studio/demo" });
  expect(row("Calendly").textContent).toContain("calendly.com/studio/demo. Leads who ask for a meeting get this link.");
});
