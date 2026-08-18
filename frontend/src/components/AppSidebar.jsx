import { useNavigate } from "react-router-dom";
import { LayoutDashboard, Boxes, Brain, TrendingUp, FileText, Settings, LogOut } from "lucide-react";
import { Logo } from "./Logo";
import { useAuth } from "../context/AuthContext";

const ITEMS = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "workspace", label: "Workspace", icon: Boxes },
  { id: "brain", label: "Brain", icon: Brain },
  { id: "growth", label: "Growth", icon: TrendingUp },
  { id: "content", label: "Content", icon: FileText },
  { id: "settings", label: "Settings", icon: Settings },
];

export function AppSidebar({ active, onNavigate }) {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  return (
    <aside className="hidden md:flex flex-col w-60 shrink-0 border-r border-border bg-card min-h-screen">
      <div className="h-16 flex items-center px-5 border-b border-border">
        <Logo className="text-base" to={null} />
      </div>
      <nav className="flex-1 p-3 space-y-1">
        {ITEMS.map((it) => {
          const on = active === it.id;
          return (
            <button
              key={it.id}
              onClick={() => onNavigate(it.id)}
              data-testid={`side-${it.id}`}
              className={on
                ? "flex items-center gap-3 w-full px-3 py-2.5 rounded-md text-sm font-medium bg-primary text-primary-foreground"
                : "flex items-center gap-3 w-full px-3 py-2.5 rounded-md text-sm font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"}
            >
              <it.icon className="w-4 h-4" /> {it.label}
            </button>
          );
        })}
      </nav>
      <div className="p-4 border-t border-border">
        <div className="text-xs text-muted-foreground truncate mb-2">{user?.email}</div>
        <button onClick={() => { logout(); nav("/"); }} data-testid="side-logout" className="flex items-center gap-2 text-sm text-muted-foreground hover:text-destructive transition-colors">
          <LogOut className="w-4 h-4" /> Log out
        </button>
      </div>
    </aside>
  );
}
