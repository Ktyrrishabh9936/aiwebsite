import React, { act } from "react";
import { createRoot } from "react-dom/client";
import Settings from "./Settings";
import api from "../../lib/api";

const mockSetWs = jest.fn();
const mockRefresh = jest.fn(async () => ({}));
const mockWorkspace = { id: "ws", name: "Studio", modules: { real_estate: true, agency: false }, currency: "INR", allowed_blog_origins: [] };

jest.mock("../../components/VoiceProviders", () => () => null);
jest.mock("../../context/AuthContext", () => ({ useAuth: () => ({ user: { name: "User", email: "user@example.com" } }) }));
jest.mock("react-router-dom", () => ({ Link: ({ children, ...props }) => <a {...props}>{children}</a>, useOutletContext: () => ({ ws: mockWorkspace, setWs: mockSetWs, refresh: mockRefresh }) }), { virtual: true });
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock("../../lib/api", () => ({ __esModule: true, default: { get: jest.fn(), patch: jest.fn(), put: jest.fn(), delete: jest.fn(), post: jest.fn() } }));

let container;
let root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  api.get.mockResolvedValue({ data: { connected: false, caller_phone: "", service_enabled: false } });
  api.patch.mockResolvedValue({ data: { ...mockWorkspace, modules: { real_estate: true, agency: true } } });
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test("module buttons persist immediately and update their visible state", async () => {
  await act(async () => root.render(<Settings />));
  const install = [...container.querySelectorAll("button")].find((button) => button.textContent.includes("Install & activate"));
  await act(async () => install.click());
  expect(api.patch).toHaveBeenCalledWith("/workspaces/ws", { modules: { real_estate: true, agency: true } });
  expect(mockSetWs).toHaveBeenCalledWith(expect.objectContaining({ modules: { real_estate: true, agency: true } }));
  expect(container.textContent).toContain("Deactivate");
});
