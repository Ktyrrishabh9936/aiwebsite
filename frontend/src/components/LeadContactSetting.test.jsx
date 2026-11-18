import React, { act } from "react";
import { createRoot } from "react-dom/client";
import LeadContactSetting, { ContactBadge, contactPreference } from "./LeadContactSetting";
import api from "../lib/api";

jest.mock("../lib/api", () => ({ __esModule: true, default: { patch: jest.fn() }, formatError: (detail) => String(detail) }));
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

let container, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

const button = (text) => [...container.querySelectorAll("button")].find((b) => b.textContent.includes(text));
const choose = (el, value) => { const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value").set; setter.call(el, value); el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true })); };

test("a do-not-call set by a call shows as do not call, and the stage plays no part", () => {
  expect(contactPreference({ status: "won" })).toBe("normal");
  expect(contactPreference({ status: "lost", do_not_call: true })).toBe("do_not_call");
  expect(contactPreference({ do_not_call: true, contact_preference: "no_contact" })).toBe("no_contact");
  act(() => root.render(<ContactBadge lead={{ contact_preference: "no_contact" }} />));
  expect(container.textContent).toBe("Completed · no contact");
});

test("saves the chosen setting with its reason and hands back the updated lead", async () => {
  const updated = { id: "lead1", status: "won", contact_preference: "no_contact", do_not_call: true, do_not_email: true };
  api.patch.mockResolvedValue({ data: updated });
  const onUpdated = jest.fn();
  act(() => root.render(<LeadContactSetting wsId="ws1" lead={{ id: "lead1", status: "won" }} onUpdated={onUpdated} />));
  expect(button("Save")).toBeUndefined(); // nothing to save until the setting changes
  act(() => choose(container.querySelector("select"), "no_contact"));
  expect(container.textContent).toContain("never calls, emails or raises work");
  act(() => choose(container.querySelector("input"), "Project delivered and paid"));
  await act(async () => { button("Save").click(); });
  expect(api.patch).toHaveBeenCalledWith("/workspaces/ws1/crm/leads/lead1/contact-preference", { preference: "no_contact", reason: "Project delivered and paid" });
  expect(onUpdated).toHaveBeenCalledWith(updated);
});
