import { act } from "react";
import { createRoot } from "react-dom/client";
import InstallPanel from "./InstallPanel";

jest.mock("../../lib/api", () => ({ API: "https://example.lambda-url.ap-south-1.on.aws/api" }));

let container;
let root;

beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

test("shows a share link, responsive iframe and Lambda safety guidance without nested tabs", () => {
  const form = { form_key: "lf_demo", name: "Demo form", allowed_origins: ["example.com"] };
  act(() => root.render(<InstallPanel form={form} onOriginsChange={jest.fn()} onRotate={jest.fn()} />));
  expect(container.textContent).toContain("Share this form as a page");
  expect(container.textContent).toContain("/public/forms/lf_demo/view");
  expect(container.textContent).toContain("data-arevei-frame");
  expect(container.textContent).toContain("form-frame.js");
  expect(container.textContent).toContain("raw AWS Lambda URL");
  expect(container.querySelector('[role="tablist"]')).toBeNull();
});
