import { streamManager, aiErrorMessage } from "./AiStatus";

jest.mock("../lib/api", () => ({ __esModule: true, API: "/api", default: {} }));

const originalFetch = global.fetch;
const originalDecoder = global.TextDecoder;

afterEach(() => {
  jest.useRealTimers();
  global.fetch = originalFetch;
  global.TextDecoder = originalDecoder;
});

function response(chunks) {
  global.TextDecoder = class { decode(value) { return value || ""; } };
  const reader = {
    read: jest.fn(async () => chunks.length ? { value: chunks.shift(), done: false } : { done: true }),
    cancel: jest.fn(async () => {}),
    releaseLock: jest.fn(),
  };
  global.fetch = jest.fn(async () => ({ ok: true, body: { getReader: () => reader } }));
  return reader;
}

test("successful stream accumulates text and uses the saved workspace model", async () => {
  response(["There are ", "7 leads."]);
  const update = jest.fn();
  expect(await streamManager("workspace", "How many leads?", [], update)).toBe("There are 7 leads.");
  expect(update).toHaveBeenCalledWith("There are 7 leads.");
  const body = JSON.parse(global.fetch.mock.calls[0][1].body);
  expect(body).not.toHaveProperty("model_id");
});

test("HTTP 200 with a split provider error is a failed request", async () => {
  response(["[err", "or: Client error '402 Payment Required' for url 'private-url']"]);
  await expect(streamManager("workspace", "Question", [])).rejects.toThrow("402");
  const message = aiErrorMessage(new Error("402 Payment Required private-url"));
  expect(message).toContain("credits exhausted");
  expect(message).not.toContain("private-url");
});

test("empty responses are not shown as working", async () => {
  response([]);
  await expect(streamManager("workspace", "Question", [])).rejects.toThrow("empty response");
});

test("a stalled request times out instead of spinning forever", async () => {
  jest.useFakeTimers();
  global.fetch = jest.fn((url, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(new Error("aborted")));
  }));
  const result = streamManager("workspace", "Question", []);
  const assertion = expect(result).rejects.toThrow("timed out after 60 seconds");
  jest.advanceTimersByTime(60000);
  await assertion;
});
