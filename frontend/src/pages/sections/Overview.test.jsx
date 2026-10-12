import React, { act } from "react";
import { createRoot } from "react-dom/client";
import Overview from "./Overview";
import api from "../../lib/api";

jest.mock("../../components/SalesBriefing", () => () => null);
jest.mock("../../components/onboarding/SetupChecklist", () => () => null);
const mockNavigate = jest.fn();
let mockWorkspace;
jest.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
  useOutletContext: () => ({ ws: mockWorkspace, refresh: jest.fn() }),
}), { virtual: true });
jest.mock("../../lib/api", () => ({ __esModule: true, default: { get: jest.fn() } }));
jest.mock("recharts", () => ({
  ResponsiveContainer: ({ children }) => <div>{children}</div>,
  BarChart: ({ children }) => <div>{children}</div>,
  Bar: ({ dataKey }) => <div data-chart-metric={dataKey} />,
  CartesianGrid: () => null, Tooltip: () => null, XAxis: () => null, YAxis: () => null,
}));

let container, root;
beforeEach(() => {
  mockWorkspace = { id: "workspace", brain_status: "ready", roadmap: [{}], strategy_summary: "Legacy SEO strategy" };
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  api.get.mockImplementation((url) => Promise.resolve({ data: url.endsWith("/overview") ? {
    totals: { leads: 12, customers: 3, payments_collected: "250000", due_amount: "10000" },
    day_buckets: [{ date: "2026-09-25", leads: 2, payments_collected: "5000" }],
    month_buckets: [{ month: "2026-09", leads: 12, payments_collected: "250000" }],
  } : [] }));
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test("shows sales figures and opens the CRM from the primary action", async () => {
  await act(async () => root.render(<Overview />));
  expect(container.querySelector('[data-testid="stat-crm-total-leads"]').textContent).toContain("12");
  const openCrm = [...container.querySelectorAll("button")].find((button) => button.textContent.includes("Open CRM"));
  await act(async () => openCrm.click());
  expect(mockNavigate).toHaveBeenCalledWith("crm");
});

test("legacy strategy and roadmap are replaced by sales setup", async () => {
  await act(async () => root.render(<Overview />));
  expect(container.textContent).not.toContain("Legacy SEO strategy");
  expect(container.querySelector('[data-testid="stat-roadmap"]').textContent).toContain("0");
  await act(async () => container.querySelector('[data-testid="generate-roadmap-btn"]').click());
  expect(mockNavigate).toHaveBeenCalledWith("setup");
});

test("overview uses the saved sales strategy instead of the legacy summary", async () => {
  mockWorkspace.sales_strategy = { strategy_summary: "Increase qualified pipeline and conversion", months: [{ month: 1 }] };
  await act(async () => root.render(<Overview />));
  expect(container.textContent).toContain("Increase qualified pipeline and conversion");
  expect(container.textContent).not.toContain("Legacy SEO strategy");
  expect(container.querySelector('[data-testid="generate-roadmap-btn"]')).toBeNull();
});

test("charts switch between lead counts and payments without mixing units", async () => {
  await act(async () => root.render(<Overview />));
  const daily = container.querySelector('[aria-label="Daily activity"]');
  expect(daily.querySelectorAll("[data-chart-metric]")).toHaveLength(1);
  expect(daily.querySelector("[data-chart-metric]").dataset.chartMetric).toBe("leads");
  await act(async () => [...daily.querySelectorAll("button")].find((button) => button.textContent === "Collected").click());
  expect(daily.querySelector("[data-chart-metric]").dataset.chartMetric).toBe("payments");
  expect(daily.querySelector('[aria-pressed="true"]').textContent).toBe("Collected");
});

test("failed analytics hide zero totals and recover on retry", async () => {
  api.get.mockRejectedValueOnce(new Error("Unavailable")); // tasks
  api.get.mockResolvedValueOnce({ data: [] }); // blogs
  api.get.mockRejectedValueOnce(new Error("Unavailable")); // analytics
  await act(async () => root.render(<Overview />));
  expect(container.querySelector('[role="alert"]').textContent).toContain("couldn’t be refreshed");
  expect(container.querySelector('[data-testid="stat-crm-total-leads"]').textContent).toContain("—");
  expect(container.querySelector('[aria-label="Daily activity"]')).toBeNull();
  await act(async () => container.querySelector('[role="alert"] button').click());
  expect(container.querySelector('[role="alert"]')).toBeNull();
  expect(container.querySelector('[data-testid="stat-crm-total-leads"]').textContent).toContain("12");
});
