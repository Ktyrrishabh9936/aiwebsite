import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Globe, Loader2, LogOut, Plus } from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";
import { Logo } from "../components/Logo";
import { ModelPicker } from "../components/ModelPicker";
import { ThemeToggle } from "../components/ThemeToggle";
import { useAuth } from "../context/AuthContext";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "../components/ui/dialog";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export default function Dashboard() {
  const nav = useNavigate();
  const { logout } = useAuth();
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [modelId, setModelId] = useState("gemini-3-flash-preview");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    api.get("/workspaces").then((r) => {
      const latest = r.data?.[0];
      if (latest) nav(`/app/w/${latest.id}`, { replace: true });
    }).finally(() => setLoading(false));
  }, [nav]);

  const create = async (e) => {
    e.preventDefault();
    setCreating(true);
    try {
      const r = await api.post("/workspaces", { website_url: url, model_id: modelId });
      toast.success("Workspace created - training brain");
      setOpen(false);
      setUrl("");
      nav(`/app/w/${r.data.id}`, { replace: true });
    } catch (err) {
      toast.error(formatError(err.response?.data?.detail));
    } finally {
      setCreating(false);
    }
  };

  if (loading) {
    return <div className="min-h-screen grid place-items-center text-muted-foreground"><Loader2 className="w-5 h-5 animate-spin" /></div>;
  }

  return (
    <div className="h-screen overflow-hidden md:pl-60">
      <aside className="hidden md:flex fixed inset-y-0 left-0 z-30 flex-col w-60 border-r border-border bg-card">
        <div className="h-16 flex items-center px-5 border-b border-border">
          <Logo className="text-base" to="/app" />
        </div>
        <div className="px-3 py-4">
          <div className="flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium bg-primary text-primary-foreground">
            <Globe className="w-4 h-4" /> Overview
          </div>
        </div>
        <div className="mt-auto p-4 border-t border-border">
          <button onClick={() => { logout(); nav("/"); }} data-testid="side-logout" className="flex items-center gap-2 text-sm text-muted-foreground hover:text-destructive transition-colors">
            <LogOut className="w-4 h-4" /> Log out
          </button>
        </div>
      </aside>

      <div className="h-screen flex flex-col min-w-0">
        <header className="sticky top-0 z-20 glass border-b border-border">
          <div className="h-16 px-5 flex items-center justify-between gap-3">
            <div className="min-w-0">
              <h2 className="font-display font-bold truncate">Arevei</h2>
              <p className="text-xs text-muted-foreground truncate">Create your first dashboard workspace</p>
            </div>
            <ThemeToggle />
          </div>
        </header>

        <main className="flex-1 overflow-y-auto">
          <div className="p-6 sm:p-10 max-w-5xl mx-auto">
            <div className="border border-dashed border-border rounded-md p-10 sm:p-16 text-center bg-card/40">
              <Globe className="w-10 h-10 mx-auto text-muted-foreground mb-4" />
              <h1 className="font-display text-2xl sm:text-3xl font-black tracking-tight">Create your first workspace</h1>
              <p className="text-muted-foreground mt-2 mb-6">Paste a website URL to train the business brain and open the unified dashboard.</p>
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
                      {creating ? "Creating..." : "Train brain"}
                    </button>
                  </form>
                </DialogContent>
              </Dialog>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
