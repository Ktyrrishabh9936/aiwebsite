import React, { act } from "react";
import { createRoot } from "react-dom/client";
import QualificationReview from "./QualificationReview";
import api from "../lib/api";

jest.mock("../lib/api", () => ({ __esModule: true, formatError: (v) => v, default: { get: jest.fn(), put: jest.fn() } }));
let container, root;
const lead = { id: "lead", qualification_call: { engine_result: { qualification_data: { location: "Gurgaon" } } } };
const state = { has_qualification: true, source_version: "a".repeat(64), source: { engine_result: { lead_status: "QUALIFIED", qualification_data: { location: "Gurgaon" } } }, review: { status: "not_reviewed", note: "", incorrect_fields: [] } };
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  api.get.mockResolvedValue({ data: state });
  api.put.mockImplementation(async (_, body) => ({ data: { ...state, review: { ...body, reviewed_by_name: "John", reviewed_at: "2026-09-20T10:00:00Z" } } }));
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });
const render = async (item = lead) => { await act(async () => root.render(<QualificationReview wsId="workspace" lead={item} />)); };
const click = async (node) => { await act(async () => node.click()); };

test("review is optional and only appears for an AI result", async () => {
  await render({ id: "empty" }); expect(container.textContent).toBe(""); expect(api.get).not.toHaveBeenCalled();
  await render(); expect(container.textContent).toContain("AI Qualification Review");
  expect(container.querySelector('input[value="not_reviewed"]').checked).toBe(true);
  expect(container.textContent).toContain("Gurgaon");
});

test.each(["correct", "incorrect"])("saves %s with the note, result version and reviewer display", async (status) => {
  await render(); await click(container.querySelector(`input[value="${status}"]`));
  const textarea = container.querySelector("textarea");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(textarea, "Confirmed with salesperson");
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
  if (status === "incorrect") await click(container.querySelector('input[type="checkbox"]'));
  await click([...container.querySelectorAll("button")].find((b) => b.textContent === "Save Review"));
  expect(api.put).toHaveBeenCalledWith("/workspaces/workspace/crm/leads/lead/qualification-review", {
    status, note: "Confirmed with salesperson", source_version: state.source_version, incorrect_fields: status === "incorrect" ? ["location"] : [],
  });
  expect(container.textContent).toContain("Reviewed by: John"); expect(container.textContent).toContain("Review saved");
});

test("normal lead polling does not erase an unsaved review", async () => {
  await render(); await click(container.querySelector('input[value="incorrect"]'));
  await render({ ...lead, updated_at: "new timestamp" });
  expect(container.querySelector('input[value="incorrect"]').checked).toBe(true);
  expect(api.get).toHaveBeenCalledTimes(1);
});

test("presents readable findings, preserves false and zero, and collapses extra fields", async () => {
  api.get.mockResolvedValue({ data: { ...state, source: { engine_result: { lead_status: "UNQUALIFIED", qualification_data: {
    requirement: "NA", budget: { value: null, min: 5000000, max: 7000000, currency: "INR" }, location: "Gurgaon",
    purchase_timeline: "later", buying_intent: "low", decision_maker_status: "not_decision_maker",
    product_fit: false, preferences: ["NA"], attributes: { visits: 0 },
  } } } } });
  await render();
  expect(container.textContent).toContain("Unqualified");
  expect(container.textContent).toContain("Not Decision Maker");
  expect(container.textContent).toContain("50,00,000");
  expect(container.textContent).toContain("70,00,000");
  expect(container.textContent).toContain("Not provided");
  expect(container.textContent).toContain("Visits: 0");
  expect([...container.querySelectorAll("dd")].some((node) => node.textContent === "No")).toBe(true);
  expect(container.textContent).not.toContain('"value":null');
  expect(container.querySelector("details").open).toBe(false);
  expect(container.querySelector("fieldset").compareDocumentPosition(container.querySelector("dl")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test("new AI results reset the review and stale saves show a recoverable error", async () => {
  await render(); api.put.mockRejectedValue({ response: { data: { detail: "The AI qualification changed" } } });
  await click([...container.querySelectorAll("button")].find((b) => b.textContent === "Save Review"));
  expect(container.querySelector('[role="alert"]').textContent).toContain("The AI qualification changed");
  api.get.mockResolvedValue({ data: { ...state, stale: true } });
  await click([...container.querySelectorAll("button")].find((b) => b.textContent === "Reload review"));
  expect(container.textContent).toContain("previous review is preserved");
  expect(container.querySelector('input[value="not_reviewed"]').checked).toBe(true);
});

test("a late save response cannot replace a newer qualification result", async () => {
  let finishSave;
  api.put.mockImplementation(() => new Promise((resolve) => { finishSave = resolve; }));
  await render(); await click(container.querySelector('input[value="correct"]'));
  await click([...container.querySelectorAll("button")].find((b) => b.textContent === "Save Review"));
  api.get.mockResolvedValue({ data: { ...state, source_version: "b".repeat(64), source: { engine_result: { lead_status: "UNQUALIFIED", qualification_data: { location: "Delhi" } } } } });
  await render({ ...lead, qualification_call: { engine_result: { qualification_data: { location: "Delhi" } } } });
  await act(async () => finishSave({ data: { ...state, review: { status: "correct" } } }));
  expect(container.textContent).toContain("Delhi"); expect(container.textContent).not.toContain("Gurgaon");
  expect(container.querySelector('input[value="not_reviewed"]').checked).toBe(true);
  expect([...container.querySelectorAll("button")].find((b) => b.textContent === "Save Review").disabled).toBe(false);
});
