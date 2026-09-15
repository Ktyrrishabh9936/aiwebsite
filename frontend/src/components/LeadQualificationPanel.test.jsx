import React, { act } from "react";
import { createRoot } from "react-dom/client";
import LeadQualificationPanel from "./LeadQualificationPanel";
import api from "../lib/api";

jest.mock("react-router-dom", () => ({ useParams: () => ({ wsId: "workspace" }), Link: ({ children, to, ...props }) => <a href={to} {...props}>{children}</a> }), { virtual: true });
jest.mock("../lib/api", () => ({ __esModule: true, default: { get: jest.fn(), put: jest.fn() } }));
jest.mock("../pages/sections/Qualification", () => ({ qualificationError: (e) => e.message }));

let container, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  api.get.mockImplementation(async (url) => ({ data: url.endsWith("/profiles") ? { profiles: [{ id: "profile", product_name: "Software" }] } : [] }));
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test("shows unknown score, call outcome and lead status separately", async () => {
  await act(async () => root.render(<LeadQualificationPanel lead={{ id: "lead", lead_status: "PENDING", call_outcome: "NO_ANSWER", qualification_call: { engine_result: { lead_status: "PENDING", call_outcome: "NO_ANSWER", qualification_score: null, confidence_score: 0, next_action: "RETRY_CALL", retry_eligible: true, missing_information: [] } } }} />));
  expect(container.textContent).toContain("NO ANSWER"); expect(container.textContent).toContain("PENDING"); expect(container.textContent).toContain("Not scored"); expect(container.textContent).toContain("Retry eligible");
});

test("shows blocked calling and processing failure clearly", async () => {
  await act(async () => root.render(<LeadQualificationPanel lead={{ id: "lead", do_not_call: true, qualification_processing: { status: "failed" } }} />));
  expect(container.textContent).toContain("future calls are blocked"); expect(container.querySelector('[role="alert"]').textContent).toContain("could not be processed");
});

test("failed assignment retains the selected profile and shows an error", async () => {
  api.put.mockRejectedValue(new Error("Profile could not be saved"));
  await act(async () => root.render(<LeadQualificationPanel lead={{ id: "lead" }} />));
  const select = container.querySelector("select");
  await act(async () => { select.value = "profile"; select.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(select.value).toBe(""); expect(container.textContent).toContain("Profile could not be saved");
  expect(api.put).toHaveBeenCalledWith("/workspaces/workspace/crm/qualification/leads/lead/profile", { profile_id: "profile" });
});

test("a call refresh does not reset a just-saved profile or reload the profile list", async () => {
  api.put.mockResolvedValue({ data: { profile_id: "profile" } });
  await act(async () => root.render(<LeadQualificationPanel lead={{ id: "lead", updated_at: "before" }} />));
  const select = container.querySelector("select");
  await act(async () => { select.value = "profile"; select.dispatchEvent(new Event("change", { bubbles: true })); });
  await act(async () => root.render(<LeadQualificationPanel lead={{ id: "lead", updated_at: "after" }} />));
  expect(select.value).toBe("profile");
  expect(api.get.mock.calls.filter(([url]) => url.endsWith("/profiles"))).toHaveLength(1);
  expect(api.get.mock.calls.filter(([url]) => url.endsWith("/history"))).toHaveLength(2);
});
