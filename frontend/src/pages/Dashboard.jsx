import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Plus, Globe, ArrowRight, LogOut, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";
import { ModelPicker } from "../components/ModelPicker";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "../components/ui/dialog";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

const statusMeta = {
  building: { icon: Loader2, label: "Training brain…", cls: "text-primary animate-spin" },
  ready: { icon: CheckCircle2, label: "Brain ready", cls: "text-primary" },
  error: { icon: AlertCircle, label: "Brain error", cls: "text-destructive" },
  pending: { icon: Loader2, label: "Queued", cls: "text-muted-foreground" },
};

export default function Dashboard() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [workspaces, setWorkspaces] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [modelId, setModelId] = useState("gpt-5.4");
  const [creating, setCreating] = useState(false);

  const load = () => api.get("/workspaces").then((r) => setWorkspaces(r.data)).finally(() => setLoading(false));

  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (workspaces.some((w) => w.brain_status === "building")) {
      const t = setInterval(load, 4000);
      return () => clearInterval(t);
    }
  }, [workspaces]);

  const create = async (e) => {
    e.preventDefault();
    setCreating(true);
    try {
      const r = await api.post("/workspaces", { website_url: url, model_id: modelId });
      toast.success("Workspace created — training brain");
      setOpen(false);
      setUrl("");
      nav(`/app/w/${r.data.id}`);
    } catch (err) {
      toast.error(formatError(err.response?.data?.detail));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="min-h-screen grain">
      <header className="sticky top-0 z-30 glass border-b border-border">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <Logo className="text-lg" />
          <div className="flex items-center gap-3">
            <ThemeToggle />
            <span className="text-sm text-muted-foreground hidden sm:block">{user?.email}</span>
            <button onClick={() => { logout(); nav("/"); }} data-testid="logout-btn" className="grid place-items-center w-9 h-9 rounded-full border border-border hover:bg-accent transition-colors" aria-label="Log out">
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-12">
        <div className="flex items-end justify-between mb-8">
          <div>
            <h1 className="font-display text-3xl sm:text-4xl font-black tracking-tight">Workspaces</h1>
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
                <div className="space-y-2">
                  <Label>Model</Label>
                  <ModelPicker value={modelId} onChange={setModelId} />
                </div>
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
                      <div className="w-10 h-10 rounded-md bg-primary/10 text-primary grid place-items-center font-display font-black">
                        {(w.name || "?").charAt(0).toUpperCase()}
                      </div>
                      <ArrowRight className="w-4 h-4 text-muted-foreground group-hover:translate-x-1 transition-transform" />
                    </div>
                    <h3 className="font-display text-lg font-bold truncate">{w.name}</h3>
                    <p className="text-sm text-muted-foreground truncate">{w.website_url}</p>
                    <div className="mt-4 flex items-center gap-1.5 text-xs font-medium">
                      <s.icon className={`w-3.5 h-3.5 ${s.cls}`} />
                      <span className="text-muted-foreground">{s.label}</span>
                    </div>
                  </Link>
                </motion.div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
