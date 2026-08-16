import { useEffect, useState, useCallback } from "react";
import { NavLink, Outlet, useParams, useNavigate, Link } from "react-router-dom";
import {
  LayoutDashboard, Brain as BrainIcon, MessageSquare, ListChecks, FileText, Code2,
  Bell, LogOut, ChevronLeft, Loader2,
} from "lucide-react";
import { toast } from "sonner";
import api from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";
import { ModelPicker } from "../components/ModelPicker";
import { Popover, PopoverContent, PopoverTrigger } from "../components/ui/popover";

const nav = [
  { to: "", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "brain", label: "Brain", icon: BrainIcon },
  { to: "manager", label: "Manager", icon: MessageSquare },
  { to: "tasks", label: "Tasks", icon: ListChecks },
  { to: "blogs", label: "Blogs", icon: FileText },
  { to: "embed", label: "Add Blog System", icon: Code2 },
];

const kindDot = { success: "bg-primary", approval: "bg-amber-500", error: "bg-destructive", info: "bg-muted-foreground" };

export default function WorkspaceLayout() {
  const { wsId } = useParams();
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [ws, setWs] = useState(null);
  const [notes, setNotes] = useState([]);
  const [notFound, setNotFound] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await api.get(`/workspaces/${wsId}`);
      setWs(r.data);
      return r.data;
    } catch {
      setNotFound(true);
    }
  }, [wsId]);

  const loadNotes = useCallback(() => {
    api.get(`/workspaces/${wsId}/notifications`).then((r) => setNotes(r.data)).catch(() => {});
  }, [wsId]);

  useEffect(() => { refresh(); loadNotes(); }, [refresh, loadNotes]);

  // poll while brain building
  useEffect(() => {
    if (ws?.brain_status === "building") {
      const t = setInterval(() => { refresh(); loadNotes(); }, 4000);
      return () => clearInterval(t);
    }
  }, [ws?.brain_status, refresh, loadNotes]);

  const changeModel = async (modelId) => {
    const r = await api.patch(`/workspaces/${wsId}`, { model_id: modelId });
    setWs(r.data);
    toast.success("Model updated");
  };

  if (notFound) return <div className="min-h-screen grid place-items-center text-muted-foreground">Workspace not found. <Link to="/app" className="text-primary ml-1">Back</Link></div>;
  if (!ws) return <div className="min-h-screen grid place-items-center text-muted-foreground"><Loader2 className="w-5 h-5 animate-spin" /></div>;

  return (
    <div className="min-h-screen flex">
      <aside className="hidden md:flex flex-col w-60 border-r border-border bg-card shrink-0">
        <div className="h-16 flex items-center px-5 border-b border-border">
          <Logo className="text-base" to="/app" />
        </div>
        <div className="px-3 py-4">
          <Link to="/app" data-testid="back-to-workspaces" className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground px-3 py-2 mb-2">
            <ChevronLeft className="w-4 h-4" /> Workspaces
          </Link>
          <nav className="space-y-1">
            {nav.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                data-testid={`nav-${n.label.toLowerCase().replace(/\s/g, "-")}`}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors ${
                    isActive ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground"
                  }`
                }
              >
                <n.icon className="w-4 h-4" /> {n.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="mt-auto p-4 border-t border-border">
          <div className="text-xs text-muted-foreground truncate mb-1">{ws.name}</div>
          <button onClick={() => { logout(); navigate("/"); }} data-testid="sidebar-logout" className="flex items-center gap-2 text-sm text-muted-foreground hover:text-destructive transition-colors">
            <LogOut className="w-4 h-4" /> Log out
          </button>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="sticky top-0 z-20 glass border-b border-border">
          <div className="h-16 px-5 flex items-center justify-between gap-3">
            <div className="min-w-0">
              <h2 className="font-display font-bold truncate">{ws.name}</h2>
              <p className="text-xs text-muted-foreground truncate">{ws.website_url}</p>
            </div>
            <div className="flex items-center gap-2.5">
              <ModelPicker value={ws.model_id} onChange={changeModel} />
              <Popover onOpenChange={(o) => o && loadNotes()}>
                <PopoverTrigger asChild>
                  <button data-testid="notifications-btn" className="relative grid place-items-center w-9 h-9 rounded-full border border-border hover:bg-accent transition-colors">
                    <Bell className="w-4 h-4" />
                    {notes.length > 0 && <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-primary" />}
                  </button>
                </PopoverTrigger>
                <PopoverContent align="end" className="w-80 p-0">
                  <div className="px-4 py-3 border-b border-border font-medium text-sm">Activity</div>
                  <div className="max-h-96 overflow-y-auto">
                    {notes.length === 0 ? (
                      <div className="px-4 py-6 text-sm text-muted-foreground text-center">No activity yet.</div>
                    ) : notes.map((n) => (
                      <div key={n.id} className="px-4 py-3 border-b border-border last:border-0" data-testid="notification-item">
                        <div className="flex items-start gap-2">
                          <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${kindDot[n.kind] || kindDot.info}`} />
                          <div className="min-w-0">
                            <div className="text-sm font-medium">{n.title}</div>
                            {n.body && <div className="text-xs text-muted-foreground truncate">{n.body}</div>}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </PopoverContent>
              </Popover>
              <ThemeToggle />
            </div>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto">
          <Outlet context={{ ws, setWs, refresh, loadNotes }} />
        </main>
      </div>
    </div>
  );
}
