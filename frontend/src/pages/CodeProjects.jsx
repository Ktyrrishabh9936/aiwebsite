import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Plus, Code2, ArrowLeft, Loader2, CheckCircle2, AlertCircle, Terminal, Trash2, Github, PlugZap } from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "../components/ui/dialog";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "../components/ui/dropdown-menu";

const statusMeta = {
  provisioning: { icon: Loader2, label: "Provisioning sandbox…", cls: "text-primary animate-spin" },
  ready: { icon: CheckCircle2, label: "Ready", cls: "text-primary" },
  error: { icon: AlertCircle, label: "Error", cls: "text-destructive" },
};

export default function CodeProjects() {
  const nav = useNavigate();
  const [projects, setProjects] = useState([]);
  const [models, setModels] = useState([]);
  const [providers, setProviders] = useState({});
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [modelId, setModelId] = useState("gpt-4o");
  const [template, setTemplate] = useState("react-vite");
  const [source, setSource] = useState("template");
  const [repoUrl, setRepoUrl] = useState("");
  const [branch, setBranch] = useState("");
  const [creating, setCreating] = useState(false);

  const load = () => api.get("/code/projects").then((r) => setProjects(r.data)).finally(() => setLoading(false));
  useEffect(() => { load(); api.get("/code/models").then((r) => { setModels(r.data.models); setModelId(r.data.default); setTemplates(r.data.templates || []); setProviders(r.data.providers || {}); }); }, []);
  useEffect(() => {
    if (projects.some((p) => p.sandbox_status === "provisioning")) {
      const t = setInterval(load, 4000); return () => clearInterval(t);
    }
  }, [projects]);

  const create = async (e) => {
    e.preventDefault();
    setCreating(true);
    try {
      const payload = { name, model_id: modelId, template };
      const r = source === "github"
        ? await api.post("/code/projects/import/github", { ...payload, repo_url: repoUrl, branch: branch || undefined })
        : await api.post("/code/projects", payload);
      toast.success(source === "github" ? "Import started - cloning GitHub repo" : "Project created - provisioning sandbox");
      nav(`/app/code/${r.data.id}`);
    } catch (err) { toast.error(formatError(err.response?.data?.detail)); }
    finally { setCreating(false); }
  };

  const del = async (e, id) => { e.preventDefault(); e.stopPropagation(); await api.delete(`/code/projects/${id}`); load(); toast.success("Deleted"); };

  const currentModel = models.find((m) => m.id === modelId);

  return (
    <div className="min-h-screen grain">
      <header className="sticky top-0 z-30 glass border-b border-border">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Logo className="text-lg" to="/app" />
            <span className="text-muted-foreground">/</span>
            <span className="font-display font-bold">Workspace</span>
          </div>
          <div className="flex items-center gap-3">
            <ThemeToggle />
            <Link to="/app" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="w-4 h-4" /> Dashboard</Link>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-12">
        <div className="flex items-end justify-between mb-8 flex-wrap gap-4">
          <div>
            <h1 className="font-display text-3xl sm:text-4xl font-black tracking-tight">AI Coding Workspace</h1>
            <p className="text-muted-foreground mt-1">Describe an app, the agent builds it in a live cloud sandbox — edit, run, preview.</p>
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
              {Object.entries(providers).map(([key, value]) => (
                <span key={key} className={value.configured ? "inline-flex items-center gap-1 rounded-full border border-border px-2 py-1 text-primary" : "inline-flex items-center gap-1 rounded-full border border-border px-2 py-1"}>
                  <PlugZap className="w-3 h-3" /> {key}: {value.configured ? "connected" : value.env}
                </span>
              ))}
            </div>
          </div>
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <button data-testid="new-code-project-btn" className="inline-flex items-center gap-2 px-5 h-11 rounded-full bg-primary text-primary-foreground font-semibold hover:-translate-y-0.5 transition-transform">
                <Plus className="w-4 h-4" /> New project
              </button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader><DialogTitle className="font-display">New coding project</DialogTitle></DialogHeader>
              <form onSubmit={create} className="space-y-5 pt-2" data-testid="create-code-form">
                <div className="grid grid-cols-2 gap-2">
                  <button type="button" onClick={() => setSource("template")} className={source === "template" ? "h-10 rounded-md border-2 border-primary bg-primary/10 text-sm font-semibold" : "h-10 rounded-md border border-border text-sm hover:bg-accent"}>Template</button>
                  <button type="button" onClick={() => setSource("github")} className={source === "github" ? "h-10 rounded-md border-2 border-primary bg-primary/10 text-sm font-semibold inline-flex items-center justify-center gap-2" : "h-10 rounded-md border border-border text-sm hover:bg-accent inline-flex items-center justify-center gap-2"}><Github className="w-4 h-4" /> GitHub</button>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="pn">Project name</Label>
                  <Input id="pn" data-testid="code-name-input" value={name} onChange={(e) => setName(e.target.value)} placeholder={source === "github" ? "Optional, inferred from repo" : "Jewelry store app"} required={source === "template"} />
                </div>
                {source === "github" ? (
                  <div className="space-y-3">
                    <div className="space-y-2">
                      <Label htmlFor="repo">GitHub repository URL</Label>
                      <Input id="repo" data-testid="github-repo-input" value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} placeholder="https://github.com/org/repo.git" required={source === "github"} />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="branch">Branch (optional)</Label>
                      <Input id="branch" data-testid="github-branch-input" value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="main" />
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <Label>Template / language</Label>
                    <div className="grid grid-cols-2 gap-2">
                      {templates.map((t) => (
                        <button type="button" key={t.id} onClick={() => setTemplate(t.id)} data-testid={`template-${t.id}`}
                          className={template === t.id ? "px-3 h-11 rounded-md border-2 border-primary bg-primary/10 text-sm font-medium" : "px-3 h-11 rounded-md border border-border text-sm hover:bg-accent"}>
                          {t.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                <div className="space-y-2">
                  <Label>Coding model</Label>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button type="button" data-testid="code-model-picker" className="w-full inline-flex items-center justify-between px-4 h-11 rounded-md border border-border text-sm">
                        <span>{currentModel?.label || "Select"}</span>
                        <Code2 className="w-4 h-4 opacity-60" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="w-64">
                      {models.map((m) => (
                        <DropdownMenuItem key={m.id} onClick={() => setModelId(m.id)} className="flex justify-between cursor-pointer">
                          <span>{m.label}</span><span className={m.configured ? "text-[10px] uppercase text-primary" : "text-[10px] uppercase text-amber-500"}>{m.configured ? m.tier : "key needed"}</span>
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
                <button type="submit" disabled={creating} data-testid="create-code-submit" className="w-full h-11 rounded-full bg-primary text-primary-foreground font-semibold disabled:opacity-60 inline-flex items-center justify-center gap-2">
                  {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : source === "github" ? <Github className="w-4 h-4" /> : <Terminal className="w-4 h-4" />} {source === "github" ? "Import repository" : "Create & provision"}
                </button>
              </form>
            </DialogContent>
          </Dialog>
        </div>

        {loading ? <div className="text-muted-foreground">Loading…</div> : projects.length === 0 ? (
          <div className="border border-dashed border-border rounded-md p-16 text-center">
            <Code2 className="w-10 h-10 mx-auto text-muted-foreground mb-4" />
            <h3 className="font-display text-xl font-bold">No projects yet</h3>
            <p className="text-muted-foreground mt-1">Create one to open the AI coding IDE.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {projects.map((p, i) => {
              const s = statusMeta[p.sandbox_status] || statusMeta.provisioning;
              return (
                <motion.div key={p.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
                  <Link to={`/app/code/${p.id}`} data-testid={`code-project-${p.id}`} className="block border border-border rounded-md bg-card p-6 hover:-translate-y-1 transition-transform group relative">
                    <button onClick={(e) => del(e, p.id)} className="absolute top-4 right-4 grid place-items-center w-8 h-8 rounded-full border border-border hover:bg-accent text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100 transition-opacity"><Trash2 className="w-3.5 h-3.5" /></button>
                    <div className="w-10 h-10 rounded-md bg-primary/10 text-primary grid place-items-center mb-4"><Code2 className="w-5 h-5" /></div>
                    <h3 className="font-display text-lg font-bold truncate">{p.name}</h3>
                    <p className="text-sm text-muted-foreground font-mono">{p.template}</p>
                    <div className="mt-4 flex items-center gap-1.5 text-xs font-medium">
                      <s.icon className={`w-3.5 h-3.5 ${s.cls}`} /><span className="text-muted-foreground">{s.label}</span>
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
