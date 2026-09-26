import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { AuthProvider, useAuth } from "./AuthContext";
import api from "../lib/api";

jest.mock("../lib/api", () => ({ __esModule: true, default: { get: jest.fn() } }));

let container, root;
function Status() {
  const { ready, user, connectionError, retryAuth } = useAuth();
  return <div><span>{ready ? "ready" : "loading"}</span><span>{connectionError ? "offline" : user ? "signed in" : "signed out"}</span><button onClick={retryAuth}>Retry</button></div>;
}
beforeEach(() => { global.IS_REACT_ACT_ENVIRONMENT = true; localStorage.clear(); container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test("a timed-out auth check keeps the session and can be retried", async () => {
  localStorage.setItem("arevei_token", "saved-token");
  api.get.mockRejectedValueOnce(new Error("timeout")).mockResolvedValueOnce({ data: { name: "User" } });
  await act(async () => root.render(<AuthProvider><Status /></AuthProvider>));
  expect(api.get).toHaveBeenCalledWith("/auth/me", { timeout: 8000 });
  expect(container.textContent).toContain("offline");
  expect(localStorage.getItem("arevei_token")).toBe("saved-token");
  await act(async () => container.querySelector("button").click());
  expect(container.textContent).toContain("signed in");
});

test("an invalid session still clears its token", async () => {
  localStorage.setItem("arevei_token", "expired-token");
  api.get.mockRejectedValue({ response: { status: 401 } });
  await act(async () => root.render(<AuthProvider><Status /></AuthProvider>));
  expect(container.textContent).toContain("signed out");
  expect(localStorage.getItem("arevei_token")).toBeNull();
});
