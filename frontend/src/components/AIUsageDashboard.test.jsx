import React, { act } from "react";
import { createRoot } from "react-dom/client";
import AIUsageDashboard from "./AIUsageDashboard";
import api from "../lib/api";

jest.mock("../lib/api", () => ({ __esModule: true, formatError: (value) => value, default: { get: jest.fn() } }));
jest.mock("recharts", () => ({
  ResponsiveContainer: ({ children }) => <div>{children}</div>, AreaChart: ({ children }) => <div>{children}</div>,
  Area: () => null, CartesianGrid: () => null, Tooltip: () => null, XAxis: () => null, YAxis: () => null,
}));

let container;
let root;
beforeEach(() => { global.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); container.remove(); jest.clearAllMocks(); });

test("shows total and process-level AI consumption", async () => {
  api.get.mockResolvedValue({ data: {
    totals: { input_tokens: 900, output_tokens: 100, total_tokens: 1000, calls: 2, failed_calls: 0, metered_calls: 2, average_latency_ms: 450 },
    daily: [{ day: "2026-09-21", input_tokens: 900, output_tokens: 100, total_tokens: 1000, calls: 2 }],
    processes: [{ key: "manager_chat", label: "AI Manager chat", input_tokens: 900, output_tokens: 100, total_tokens: 1000, calls: 2 }],
    models: [{ provider: "bedrock_mantle", model: "openai.gpt-oss-120b", total_tokens: 1000, calls: 2 }], recent: [],
  } });
  await act(async () => root.render(<AIUsageDashboard wsId="workspace" />));
  expect(api.get).toHaveBeenCalledWith("/workspaces/workspace/ai-usage", { params: { days: 30 } });
  expect(container.textContent).toContain("1,000");
  expect(container.textContent).toContain("AI Manager chat");
  expect(container.textContent).toContain("openai.gpt-oss-120b");
});
