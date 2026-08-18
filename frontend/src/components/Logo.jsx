import { Link } from "react-router-dom";

export function LogoMark({ className = "w-7 h-7" }) {
  return (
    <svg viewBox="0 0 48 48" className={className} fill="none" aria-hidden="true">
      <path d="M24 5 L44 41 H4 Z" stroke="hsl(var(--primary))" strokeWidth="3.5" strokeLinejoin="round" />
      <path d="M24 20 L33 37 H15 Z" stroke="hsl(var(--primary))" strokeWidth="3" strokeLinejoin="round" opacity="0.55" />
    </svg>
  );
}

export function Logo({ className = "", to = "/" }) {
  const inner = (
    <span className={`inline-flex items-center gap-2 font-display font-black tracking-tight ${className}`}>
      <LogoMark className="w-7 h-7" />
      <span>Arevei</span>
    </span>
  );
  if (to) return <Link to={to} data-testid="logo-link">{inner}</Link>;
  return inner;
}
