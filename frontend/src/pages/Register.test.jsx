import { act } from "react";
import { createRoot } from "react-dom/client";
import Register from "./Register";
import { useAuth } from "../context/AuthContext";
const mockNavigate = jest.fn();
jest.mock("react-router-dom", () => ({
  Link: ({ children, to, ...props }) => <a href={to} {...props}>{children}</a>,
  useNavigate: () => mockNavigate,
  useLocation: () => ({ state: { name: "Sarah Mitchell", email: "sarah@example.com" } }),
}), { virtual: true });
jest.mock("../context/AuthContext", () => ({ useAuth: jest.fn() }));
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock("../components/ThemeToggle", () => ({ ThemeToggle: () => null }));
let container;
let root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  mockNavigate.mockClear();
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
test("keeps landing page prefill and submits signup to onboarding", async () => {
  const register = jest.fn().mockResolvedValue(undefined);
  useAuth.mockReturnValue({ register });
  act(() => root.render(<Register/>));
  expect(container.querySelector('[data-testid="register-name"]').value).toBe("Sarah Mitchell");
  expect(container.querySelector('[data-testid="register-email"]').value).toBe("sarah@example.com");
  const password = container.querySelector('[data-testid="register-password"]');
  expect(password.minLength).toBe(6);
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(password, "secret123");
    password.dispatchEvent(new Event("input", { bubbles: true }));
  });
  act(() => container.querySelector('[aria-label="Show password"]').click());
  expect(password.type).toBe("text");
  expect(password.value).toBe("secret123");
  act(() => container.querySelector('[aria-label="Hide password"]').click());
  expect(password.type).toBe("password");
  await act(async () => container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(register).toHaveBeenCalledWith("Sarah Mitchell", "sarah@example.com", "secret123");
  expect(mockNavigate).toHaveBeenCalledWith("/welcome");
});
