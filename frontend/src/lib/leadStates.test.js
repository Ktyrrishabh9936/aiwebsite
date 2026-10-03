import { moveLeadState, moveLeadStateToPosition } from "./leadStates";

const states = [
  { key: "new", label: "New", color: "blue", order: 1 },
  { key: "won", label: "Won", color: "green", order: 8 },
  { key: "ai_qualified", label: "AI Qualified", color: "emerald", order: 20 },
];

test("moves a state up and normalizes sparse positions while preserving stable keys", () => {
  const moved = moveLeadState(states, "ai_qualified", -1);
  expect(moved.map((state) => state.key)).toEqual(["new", "ai_qualified", "won"]);
  expect(moved.map((state) => state.order)).toEqual([1, 2, 3]);
  expect(moved[1]).toEqual({ ...states[2], order: 2 });
  expect(states[2].order).toBe(20);
});

test("moves the New state down without changing lead status identifiers", () => {
  expect(moveLeadState(states, "new", 1).map((state) => state.key)).toEqual(["won", "new", "ai_qualified"]);
});

test("keeps the order at boundaries and for unknown states", () => {
  expect(moveLeadState(states, "new", -1)).toBe(states);
  expect(moveLeadState(states, "ai_qualified", 1)).toBe(states);
  expect(moveLeadState(states, "unknown", 1)).toBe(states);
});

test("moves directly from last to first and first to last while keeping other states in order", () => {
  expect(moveLeadStateToPosition(states, "ai_qualified", 0).map((state) => state.key)).toEqual(["ai_qualified", "new", "won"]);
  const moved = moveLeadStateToPosition(states, "new", 2);
  expect(moved.map((state) => state.key)).toEqual(["won", "ai_qualified", "new"]);
  expect(moved.map((state) => state.order)).toEqual([1, 2, 3]);
  expect(states.map((state) => state.order)).toEqual([1, 8, 20]);
});

test("ignores unchanged and invalid target positions", () => {
  for (const target of [0, -1, 3, 1.5, NaN]) expect(moveLeadStateToPosition(states, "new", target)).toBe(states);
});
