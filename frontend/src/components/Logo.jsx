import { Link } from "react-router-dom";

export function Logo({ className = "", to = "/", onDark }) {
  const inner = (
    <span className={`inline-flex items-center gap-2 font-display font-black tracking-tight ${className}`}>
      <span className="grid place-items-center w-7 h-7 rounded-md bg-primary text-primary-foreground text-sm">A</span>
      <span>Arevei</span>
    </span>
  );
  if (to) return <Link to={to} data-testid="logo-link">{inner}</Link>;
  return inner;
}
