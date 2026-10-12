import { TextEncoder, TextDecoder } from "util";
import { streamManagerAgent } from "./managerAgent";

jest.mock("./api", () => ({ __esModule: true, default: { get: jest.fn() }, API: "http://api.test" }));

beforeEach(() => { global.TextDecoder = TextDecoder; global.fetch = jest.fn(); });
afterEach(() => { delete global.fetch; });

function response(events, cut = 17) {
  const bytes = new TextEncoder().encode(": heartbeat\n\n" + events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""));
  let index = 0;
  const reader = {
    read: async () => { if (index >= bytes.length) return { done: true }; const value = bytes.slice(index, index + cut); index += cut; return { value, done: false }; },
    cancel: async () => {}, releaseLock: () => {},
  };
  return { ok: true, headers: { get: () => "text/event-stream" }, body: { getReader: () => reader } };
}

test("split stream frames preserve activity, answer and confirmed changes", async () => {
  fetch.mockResolvedValue(response([
    { type: "tool_finished", status: "completed", writes: true },
    { type: "answer", content: "Rahul's follow-up saved." },
    { type: "run_finished", status: "completed" },
  ]));
  const onEvent = jest.fn(), onText = jest.fn(), changed = jest.fn();
  window.addEventListener("arevei:manager-changed", changed);
  try {
    expect(await streamManagerAgent("workspace", "Schedule it", { conversationId: "conversation", requestId: "request", onEvent }, onText)).toBe("Rahul's follow-up saved.");
    expect(onEvent).toHaveBeenCalledTimes(3);
    expect(changed).toHaveBeenCalledTimes(1);
    expect(onText).toHaveBeenCalledWith("Rahul's follow-up saved.");
  } finally { window.removeEventListener("arevei:manager-changed", changed); }
});

test("a disconnected stream cannot report success", async () => {
  fetch.mockResolvedValue(response([{ type: "tool_started", status: "running" }]));
  await expect(streamManagerAgent("workspace", "Save", {}, jest.fn())).rejects.toThrow("before completion");
});

test("failed terminal events preserve an explicit failure", async () => {
  fetch.mockResolvedValue(response([{ type: "run_finished", status: "failed", label: "Provider unavailable" }]));
  await expect(streamManagerAgent("workspace", "Save", {}, jest.fn())).rejects.toThrow("Provider unavailable");
});

test("saved changes name the page that changed so open pages can refresh", async () => {
  fetch.mockResolvedValue(response([
    { type: "tool_finished", status: "completed", writes: true, page: "customers", tool: "record_payment" },
    { type: "tool_finished", status: "completed", writes: false, page: "products-services", tool: "list_products" },
    { type: "answer", content: "Payment recorded." },
    { type: "run_finished", status: "completed" },
  ]));
  const changed = jest.fn();
  window.addEventListener("arevei:manager-changed", changed);
  try {
    await streamManagerAgent("workspace", "Record it", { conversationId: "conversation", requestId: "request" }, jest.fn());
    expect(changed).toHaveBeenCalledTimes(1);
    expect(changed.mock.calls[0][0].detail).toEqual({ page: "customers", tool: "record_payment" });
  } finally { window.removeEventListener("arevei:manager-changed", changed); }
});
