import { useEffect, useState, useCallback } from "react";
import { NavLink, Outlet, useParams, useNavigate, Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard, Brain as BrainIcon, MessageSquare, ListChecks, FileText, Code2,
  AlertCircle, Bell, CheckCircle2, Globe, Loader2, LogOut, Plus, Boxes, Settings as SettingsIcon,
  UserCircle, Workflow, Users,
} from "lucide-react";
import { toast } from "sonner";
import api from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";
import { ModelPicker } from "../components/ModelPicker";
import { Popover, PopoverContent, PopoverTrigger } from "../components/ui/popover";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "../components/ui/dialog";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

const nav = [
  { to: "", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "projects", label: "Projects", icon: Boxes },
  { to: "brain", label: "Brain", icon: BrainIcon },
  { to: "manager", label: "Manager", icon: MessageSquare },
  { to: "tasks", label: "Tasks", icon: ListChecks },
  { to: "blogs", label: "Blogs", icon: FileText },
  { to: "embed", label: "Add Blog System", icon: Code2 },
  { to: "workflows", label: "Workflows", icon: Workflow },
  { to: "crm", label: "CRM Leads", icon: Users },
];

const kindDot = { success: "bg-primary", approval: "bg-amber-500", error: "bg-destructive", info: "bg-muted-foreground" };
const workspaceStatus = {
  building: { icon: Loader2, label: "Training", cls: "text-primary animate-spin" },
  ready: { icon: CheckCircle2, label: "Ready", cls: "text-primary" },
  error: { icon: AlertCircle, label: "Error", cls: "text-destructive" },
  pending: { icon: Loader2, label: "Queued", cls: "text-muted-foreground" },
};

export default function WorkspaceLayout() {
  const { wsId } = useParams();
  const location = useLocation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [ws, setWs] = useState(null);
  const [notes, setNotes] = useState([]);
  const [workspaces, setWorkspaces] = useState([]);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [workspaceUrl, setWorkspaceUrl] = useState("");
  const [workspaceModelId, setWorkspaceModelId] = useState("gemini-3-flash-preview");
  const [creatingWorkspace, setCreatingWorkspace] = useState(false);
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

  const loadWorkspaces = useCallback(() => {
    api.get("/workspaces").then((r) => setWorkspaces(r.data)).catch(() => {});
  }, []);

  useEffect(() => { refresh(); loadNotes(); }, [refresh, loadNotes]);
  useEffect(() => { loadWorkspaces(); }, [loadWorkspaces]);

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

  const createWorkspace = async (e) => {
    e.preventDefault();
    setCreatingWorkspace(true);
    try {
      const r = await api.post("/workspaces", { website_url: workspaceUrl, model_id: workspaceModelId });
      toast.success("Workspace created - training brain");
      setWorkspaceOpen(false);
      setWorkspaceUrl("");
      loadWorkspaces();
      navigate(`/app/w/${r.data.id}`);
    } catch {
      toast.error("Could not create workspace");
    } finally {
      setCreatingWorkspace(false);
    }
  };

  const signOut = () => {
    logout();
    navigate("/");
  };
  const isBlogEditor = /\/blogs\/[^/]+$/.test(location.pathname);

  if (notFound) return <div className="min-h-screen grid place-items-center text-muted-foreground">Workspace not found. <Link to="/app" className="text-primary ml-1">Back</Link></div>;
  if (!ws) return <div className="min-h-screen grid place-items-center text-muted-foreground"><Loader2 className="w-5 h-5 animate-spin" /></div>;

  return (
    <div className="h-screen overflow-hidden md:pl-60">
      <aside className="hidden md:flex fixed inset-y-0 left-0 z-30 flex-col w-60 border-r border-border bg-card">
        <div className="h-16 flex items-center px-5 border-b border-border">
          <Logo className="text-base" to="/app" />
        </div>
        <div className="px-3 py-4">
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
          <div className="text-xs text-muted-foreground truncate">{ws.website_url}</div>
        </div>
      </aside>

      <div className="h-screen flex flex-col min-w-0">
        <header className={`sticky top-0 z-20 glass border-b border-border ${isBlogEditor ? "hidden" : ""}`}>
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
              <Popover onOpenChange={(open) => open && loadWorkspaces()}>
                <PopoverTrigger asChild>
                  <button data-testid="account-menu-btn" className="grid place-items-center w-9 h-9 rounded-full border border-border hover:bg-accent transition-colors" title="Account">
                    <UserCircle className="w-4 h-4" />
                  </button>
                </PopoverTrigger>
                <PopoverContent align="end" className="w-96 p-0">
                  <div className="px-4 py-3 border-b border-border">
                    <div className="font-medium text-sm truncate">{user?.name || "Account"}</div>
                    <div className="text-xs text-muted-foreground truncate">{user?.email}</div>
                  </div>
                  <div className="p-3 border-b border-border space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-xs uppercase tracking-wider font-bold text-muted-foreground">Website workspaces</div>
                      <Dialog open={workspaceOpen} onOpenChange={setWorkspaceOpen}>
                        <DialogTrigger asChild>
                          <button data-testid="account-new-workspace" className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-md bg-primary text-primary-foreground text-xs font-semibold">
                            <Plus className="w-3.5 h-3.5" /> New
                          </button>
                        </DialogTrigger>
                        <DialogContent>
                          <DialogHeader><DialogTitle className="font-display">Create workspace</DialogTitle></DialogHeader>
                          <form onSubmit={createWorkspace} className="space-y-5 pt-2" data-testid="create-workspace-form">
                            <div className="space-y-2">
                              <Label htmlFor="account-ws-url">Website URL</Label>
                              <Input id="account-ws-url" data-testid="workspace-url-input" value={workspaceUrl} onChange={(e) => setWorkspaceUrl(e.target.value)} placeholder="https://yourcompany.com" required />
                              <p className="text-xs text-muted-foreground">We crawl this URL to train the business brain.</p>
                            </div>
                            <div className="space-y-2"><Label>Model</Label><ModelPicker value={workspaceModelId} onChange={setWorkspaceModelId} /></div>
                            <button type="submit" disabled={creatingWorkspace} data-testid="create-workspace-submit" className="w-full h-11 rounded-full bg-primary text-primary-foreground font-semibold disabled:opacity-60">
                              {creatingWorkspace ? "Creating..." : "Train brain"}
                            </button>
                          </form>
                        </DialogContent>
                      </Dialog>
                    </div>
                    <div className="max-h-64 overflow-y-auto space-y-1">
                      {workspaces.length === 0 ? (
                        <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground text-center">No workspaces yet.</div>
                      ) : workspaces.map((workspace) => {
                        const s = workspaceStatus[workspace.brain_status] || workspaceStatus.pending;
                        return (
                          <button
                            key={workspace.id}
                            onClick={() => navigate(`/app/w/${workspace.id}`)}
                            className={`w-full text-left rounded-md border p-3 transition-colors ${workspace.id === ws.id ? "border-primary/50 bg-primary/5" : "border-border hover:bg-accent"}`}
                          >
                            <div className="flex items-start gap-3">
                              <div className="w-8 h-8 rounded-md bg-primary/10 text-primary grid place-items-center shrink-0 font-display font-bold">
                                <Globe className="w-4 h-4" />
                              </div>
                              <div className="min-w-0 flex-1">
                                <div className="font-medium text-sm truncate">{workspace.name}</div>
                                <div className="text-xs text-muted-foreground truncate">{workspace.website_url}</div>
                                <div className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                                  <s.icon className={`w-3.5 h-3.5 ${s.cls}`} /> {workspace.id === ws.id ? "Current - " : ""}{s.label}
                                </div>
                              </div>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <div className="p-2">
                    <button onClick={() => navigate(`/app/w/${ws.id}/settings`)} className="flex items-center gap-2 w-full h-9 px-2 rounded-md text-sm hover:bg-accent">
                      <SettingsIcon className="w-4 h-4" /> Settings
                    </button>
                    <button onClick={signOut} data-testid="account-logout" className="flex items-center gap-2 w-full h-9 px-2 rounded-md text-sm text-muted-foreground hover:text-destructive hover:bg-accent">
                      <LogOut className="w-4 h-4" /> Log out
                    </button>
                  </div>
                </PopoverContent>
              </Popover>
              <ThemeToggle />
            </div>
          </div>
        </header>

        <main className={`flex-1 ${isBlogEditor ? "min-h-0 overflow-hidden" : "overflow-y-auto"}`}>
          <Outlet context={{ ws, setWs, refresh, loadNotes }} />
        </main>
      </div>
    </div>
  );
}
