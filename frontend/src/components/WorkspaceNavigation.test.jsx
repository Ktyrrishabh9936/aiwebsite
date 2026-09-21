import React, { act } from "react";
import { createRoot } from "react-dom/client";
import WorkspaceNavigation from "./WorkspaceNavigation";

jest.mock("react-router-dom", () => ({ NavLink: ({ to, end, className, children, ...props }) => <a href={to} className={className({ isActive: to.endsWith("/crm") })} {...props}>{children}</a> }), { virtual: true });
let container, root;
beforeEach(() => { global.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); container.remove(); });

test("groups pages and retains accessible destinations in compact mode", async () => {
  await act(async () => root.render(<WorkspaceNavigation wsId="workspace" />));
  expect(container.textContent).toContain("AI & automation");
  expect(container.querySelector('[aria-label="Settings"]').getAttribute("href")).toBe("/app/w/workspace/settings");
  const count = container.querySelectorAll("a").length;
  await act(async () => root.render(<WorkspaceNavigation wsId="workspace" collapsed />));
  expect(container.querySelectorAll("a")).toHaveLength(count);
  expect(container.querySelector('[aria-label="CRM"]').title).toBe("CRM");
  expect(container.querySelector("input")).toBeNull();
});

test("filters destinations and notifies the drawer when navigating", async () => {
  const onNavigate = jest.fn();
  await act(async () => root.render(<WorkspaceNavigation wsId="workspace" onNavigate={onNavigate} />));
  const input = container.querySelector("input");
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, "crm"); input.dispatchEvent(new Event("input", { bubbles: true })); });
  expect(container.querySelectorAll("a")).toHaveLength(1);
  await act(async () => container.querySelector("a").dispatchEvent(new MouseEvent("click", { bubbles: true })));
  expect(onNavigate).toHaveBeenCalledTimes(1);
});

test("shows only the installed vertical modules", async () => {
  await act(async () => root.render(<WorkspaceNavigation wsId="workspace" modules={{ real_estate: false, agency: true }} />));
  expect(container.querySelector('[aria-label="Properties"]')).toBeNull();
  expect(container.querySelector('[aria-label="Products & Services"]')).not.toBeNull();
});
