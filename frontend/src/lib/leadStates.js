export const STATE_CLASSES = {
  blue: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  amber: "bg-amber-500/10 text-amber-500 border-amber-500/20",
  emerald: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
  red: "bg-destructive/10 text-destructive border-destructive/20",
  slate: "bg-muted text-muted-foreground border-border"
};

export function moveLeadState(states, key, direction) {
  const index = states.findIndex((state) => state.key === key);
  if (![-1, 1].includes(direction)) return states;
  return moveLeadStateToPosition(states, key, index + direction);
}

export function moveLeadStateToPosition(states, key, target) {
  const index = states.findIndex((state) => state.key === key);
  if (index < 0 || !Number.isInteger(target) || target < 0 || target >= states.length || target === index) return states;
  const next = [...states];
  const [state] = next.splice(index, 1);
  next.splice(target, 0, state);
  return next.map((state, position) => ({ ...state, order: position + 1 }));
}
