import React, { act } from "react";
import { createRoot } from "react-dom/client";
import LeadNotes from "./LeadNotes";

let root, container;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

test("shared lead notes display call responses, transcripts and WhatsApp history", async () => {
  const notes = [
    { id: "call", source: "call_agent", call_provider: "plivo", body: "Customer wants a visit", transcript: "Please arrange a visit", answers: ["Budget confirmed"], author: "AI", created_at: "2026-09-26T10:00:00Z" },
    { id: "whatsapp", source: "manual_whatsapp", body: "Brochure sent", author: "Sales agent", created_at: "2026-09-26T11:00:00Z" },
  ];
  await act(async () => root.render(<LeadNotes notes={notes} onAdd={async () => true} />));
  expect(container.textContent).toContain("AI call");
  expect(container.textContent).toContain("Please arrange a visit");
  expect(container.textContent).toContain("Budget confirmed");
  expect(container.textContent).toContain("WhatsApp");
  expect(container.textContent).toContain("Brochure sent");
  expect(container.querySelector('[title="Remove note"]')).toBeNull();
  const remove = jest.fn();
  await act(async () => root.render(<LeadNotes notes={notes} onAdd={async () => true} onDelete={remove} />));
  await act(async () => container.querySelector('[title="Remove note"]').click());
  expect(remove).toHaveBeenCalledWith("call");
});
