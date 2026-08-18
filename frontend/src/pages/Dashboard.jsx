import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Plus, Globe, ArrowRight, Loader2, CheckCircle2, AlertCircle, Code2 } from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";
import { AppSidebar } from "../components/AppSidebar";
import { ThemeToggle } from "../components/ThemeToggle";
import { ModelPicker } from "../components/ModelPicker";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "../components/ui/dialog";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";

const statusMeta = {
  building: { icon: Loader2, label: "Training brain…", cls: "text-primary animate-spin" },
  ready: { icon: CheckCircle2, label: "Brain ready", cls: "text-primary" },
  error: { icon: AlertCircle, label: "Brain error", cls: "text-destructive" },
  pending: { icon: Loader2, label: "Queued", cls: "text-muted-foreground" },
};

function SettingsView({ user }) {
  return (
    <div className="max-w-3xl">
      <h1 className="font-display text-3xl font-black tracking-tight mb-1">Settings</h1>
      <p className="text-muted-foreground mb-6">Account, team, billing and history in one place.</p>
      <Tabs defaultValue="account">
        <TabsList>
          <TabsTrigger value="account" data-testid="settings-account">Account</TabsTrigger>
          <TabsTrigger value="team" data-testid="settings-team">Team</TabsTrigger>
          <TabsTrigger value="billing" data-testid="settings-billing">Billing</TabsTrigger>
          <TabsTrigger value="history" data-testid="settings-history">History</TabsTrigger>
        </TabsList>
        <TabsContent value="account" className="pt-5">
          <div className="border border-border rounded-md bg-card p-6 space-y-3">
            <div><div className="text-xs uppercase tracking-wider text-muted-foreground">Name</div><div className="font-medium">{user?.name || "—"}</div></div>
            <div><div className="text-xs uppercase tracking-wider text-muted-foreground">Email</div><div className="font-medium">{user?.email}</div></div>
            <div><div className="text-xs uppercase tracking-wider text-muted-foreground">Role</div><div className="font-medium capitalize">{user?.role || "user"}</div></div>
          </div>
        </TabsContent>
        <TabsContent value="team" className="pt-5">
          <div className="border border-border rounded-md bg-card p-6 text-sm text-muted-foreground">Invite teammates to collaborate on your website. <span className="text-primary">Coming soon.</span></div>
        </TabsContent>
        <TabsContent value="billing" className="pt-5">
          <div className="border border-border rounded-md bg-card p-6 text-sm text-muted-foreground">You're on the <span className="text-foreground font-medium">Starter</span> plan. Usage-based billing arrives with public launch.</div>
        </TabsContent>
        <TabsContent value="history" className="pt-5">
          <div className="border border-border rounded-md bg-card p-6 text-sm text-muted-foreground">Your recent agent actions and generations appear here.</div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default function Dashboard() {
  const nav = useNavigate();
  const [user, setUser] = useState(null);
  const [workspaces, setWorkspaces] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [modelId, setModelId] = useState("gpt-5.4");
  const [creating, setCreating] = useState(false);
  const [view, setView] = useState("dashboard");

  const load = () => api.get("/workspaces").then((r) => setWorkspaces(r.data)).finally(() => setLoading(false));
  useEffect(() => { load(); api.get("/auth/me").then((r) => setUser(r.data)).catch(() => {}); }, []);
  useEffect(() => {
    if (workspaces.some((w) => w.brain_status === "building")) {
      const t = setInterval(load, 4000); return () => clearInterval(t);
    }
  }, [workspaces]);

  const create = async (e) => {
    e.preventDefault();
    setCreating(true);
    try {
      const r = await api.post("/workspaces", { website_url: url, model_id: modelId });
      toast.success("Workspace created — training brain");
      setOpen(false); setUrl("");
      nav(`/app/w/${r.data.id}`);
    } catch (err) { toast.error(formatError(err.response?.data?.detail)); }
    finally { setCreating(false); }
  };

  const latest = workspaces[0];
  const goSection = (section) => {
    if (section === "dashboard") return setView("dashboard");
    if (section === "settings") return setView("settings");
    if (section === "workspace") return nav("/app/code");
    if (!latest) { toast.info("Create a website workspace first"); return; }
    if (section === "brain") return nav(`/app/w/${latest.id}/brain`);
    if (section === "growth") return nav(`/app/w/${latest.id}/tasks`);
    if (section === "content") return nav(`/app/w/${latest.id}/blogs`);
  };

  return (
    <div className="min-h-screen flex grain">
      <AppSidebar active={view} onNavigate={goSection} />
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="sticky top-0 z-20 glass border-b border-border h-16 flex items-center px-6 justify-between">
          <div className="font-display font-bold capitalize">{view}</div>
          <div className="flex items-center gap-3">
            <Link to="/app/code" data-testid="nav-workspace" className="inline-flex items-center gap-1.5 text-sm font-medium px-3 py-2 rounded-full hover:bg-accent transition-colors">
              <Code2 className="w-4 h-4" /> Workspace
            </Link>
            <ThemeToggle />
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-6 sm:p-10">
          {view === "settings" ? (
            <SettingsView user={user} />
          ) : (
            <>
              <div className="flex items-end justify-between mb-8 flex-wrap gap-4">
                <div>
                  <h1 className="font-display text-3xl sm:text-4xl font-black tracking-tight">Your websites</h1>
                  <p className="text-muted-foreground mt-1">Each workspace is a website your AI manager runs.</p>
                </div>
                <Dialog open={open} onOpenChange={setOpen}>
                  <DialogTrigger asChild>
                    <button data-testid="new-workspace-btn" className="inline-flex items-center gap-2 px-5 h-11 rounded-full bg-primary text-primary-foreground font-semibold hover:-translate-y-0.5 transition-transform">
                      <Plus className="w-4 h-4" /> New workspace
                    </button>
                  </DialogTrigger>
                  <DialogContent>
                    <DialogHeader><DialogTitle className="font-display">Create workspace</DialogTitle></DialogHeader>
                    <form onSubmit={create} className="space-y-5 pt-2" data-testid="create-workspace-form">
                      <div className="space-y-2">
                        <Label htmlFor="wsurl">Website URL</Label>
                        <Input id="wsurl" data-testid="workspace-url-input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://yourcompany.com" required />
                        <p className="text-xs text-muted-foreground">We crawl this URL to train the business brain.</p>
                      </div>
                      <div className="space-y-2"><Label>Model</Label><ModelPicker value={modelId} onChange={setModelId} /></div>
                      <button type="submit" disabled={creating} data-testid="create-workspace-submit" className="w-full h-11 rounded-full bg-primary text-primary-foreground font-semibold disabled:opacity-60">
                        {creating ? "Creating…" : "Train brain"}
                      </button>
                    </form>
                  </DialogContent>
                </Dialog>
              </div>

              {loading ? (
                <div className="text-muted-foreground">Loading…</div>
              ) : workspaces.length === 0 ? (
                <div className="border border-dashed border-border rounded-md p-16 text-center">
                  <Globe className="w-10 h-10 mx-auto text-muted-foreground mb-4" />
                  <h3 className="font-display text-xl font-bold">No workspaces yet</h3>
                  <p className="text-muted-foreground mt-1">Create one and paste a website URL to begin.</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {workspaces.map((w, i) => {
                    const s = statusMeta[w.brain_status] || statusMeta.pending;
                    return (
                      <motion.div key={w.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
                        <Link to={`/app/w/${w.id}`} data-testid={`workspace-card-${w.id}`} className="block border border-border rounded-md bg-card p-6 hover:-translate-y-1 transition-transform group">
                          <div className="flex items-center justify-between mb-4">
                            <div className="w-10 h-10 rounded-md bg-primary/10 text-primary grid place-items-center font-display font-black">{(w.name || "?").charAt(0).toUpperCase()}</div>
                            <ArrowRight className="w-4 h-4 text-muted-foreground group-hover:translate-x-1 transition-transform" />
                          </div>
                          <h3 className="font-display text-lg font-bold truncate">{w.name}</h3>
                          <p className="text-sm text-muted-foreground truncate">{w.website_url}</p>
                          <div className="mt-4 flex items-center gap-1.5 text-xs font-medium"><s.icon className={`w-3.5 h-3.5 ${s.cls}`} /><span className="text-muted-foreground">{s.label}</span></div>
                        </Link>
                      </motion.div>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
