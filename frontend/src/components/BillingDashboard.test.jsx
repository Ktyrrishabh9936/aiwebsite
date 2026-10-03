import React, { act } from "react";
import { createRoot } from "react-dom/client";
import BillingDashboard from "./BillingDashboard";
import api from "../lib/api";

jest.mock("../lib/api", () => ({ __esModule: true, default: { get: jest.fn() }, formatError: (value) => value }));

test("shows account credit, incomplete estimate, and unpriced model usage", async () => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  api.get.mockResolvedValue({ data: {
    period_start: "2026-10-01", period_end_exclusive: "2026-11-01", workspace_count: 2,
    monthly_credit_usd: "100.00", estimated_usage_usd: "7.00", estimated_remaining_usd: null,
    estimate_complete: false, priced_calls: 2, unpriced_calls: 1, unmetered_calls: 0,
    input_tokens: 1500100, output_tokens: 500020,
    models: [{ provider: "bedrock", model: "unknown", calls: 1, input_tokens: 100, output_tokens: 20,
      estimated_cost_usd: "0.00", unpriced_calls: 1 }],
  } });
  const container = document.createElement("div");
  const root = createRoot(container);
  document.body.appendChild(container);
  try {
    await act(async () => root.render(<BillingDashboard wsId="workspace" />));
    expect(api.get).toHaveBeenCalledWith("/workspaces/workspace/billing");
    expect(container.textContent).toContain("$100.00");
    expect(container.textContent).toContain("Pending");
    expect(container.textContent).toContain("1 unpriced call");
    expect(container.textContent).toContain("At least $0.00");
  } finally {
    act(() => root.unmount());
    container.remove();
    jest.clearAllMocks();
  }
});
