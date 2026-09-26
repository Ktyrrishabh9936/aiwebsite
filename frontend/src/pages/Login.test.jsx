import React, { act } from "react";
import { createRoot } from "react-dom/client";
import Login from "./Login";
import { useAuth } from "../context/AuthContext";

const mockNavigate = jest.fn();
jest.mock("react-router-dom", () => ({
  Link: ({ children, to, ...props }) => <a href={to} {...props}>{children}</a>,
  useNavigate: () => mockNavigate,
  useLocation: () => ({ state: {} }),
}), { virtual: true });
jest.mock("../context/AuthContext", () => ({ useAuth: jest.fn() }));
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock("../components/ui/input", () => ({ Input: (props) => <input {...props} /> }));
jest.mock("../components/ui/label", () => ({ Label: (props) => <label {...props} /> }));
jest.mock("../components/Logo", () => ({ Logo: () => <div>Arevei</div> }));
jest.mock("../components/ThemeToggle", () => ({ ThemeToggle: () => null }));

let container;
let root;

beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.setItem("arevei_onboarded", "true");
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  mockNavigate.mockClear();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  localStorage.clear();
});

test("navigates directly to the default workspace returned by login", async () => {
  const login = jest.fn().mockResolvedValue({ default_workspace_id: "workspace-123" });
  useAuth.mockReturnValue({ login });
  await act(async () => root.render(<Login />));
  const inputs = container.querySelectorAll("input");
  await act(async () => {
    inputs[0].value = "user@example.com";
    inputs[0].dispatchEvent(new Event("input", { bubbles: true }));
    inputs[1].value = "secret1";
    inputs[1].dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(login).toHaveBeenCalled();
  expect(mockNavigate).toHaveBeenCalledWith("/app/w/workspace-123");
});
