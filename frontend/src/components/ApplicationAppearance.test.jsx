import { act } from "react";
import { createRoot } from "react-dom/client";
import ApplicationAppearance from "./ApplicationAppearance";
let mockPathname = "/app/w/workspace/crm";
jest.mock("react-router-dom", () => ({ useLocation: () => ({ pathname: mockPathname }) }), { virtual: true });
test("applies application theme to portal roots and clears it on public routes", () => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(<ApplicationAppearance><main>Workspace</main></ApplicationAppearance>));
  expect(document.documentElement.getAttribute("data-app-ui")).toBe("true");
  expect(container.querySelector(".application-ui")).not.toBeNull();
  mockPathname = "/login";
  act(() => root.render(<ApplicationAppearance><main>Login</main></ApplicationAppearance>));
  expect(document.documentElement.hasAttribute("data-app-ui")).toBe(false);
  act(() => root.unmount());
  container.remove();
});
