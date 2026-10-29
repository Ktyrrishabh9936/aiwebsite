import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bot, Building2, Check, LogOut, Plus, Share2, UserCircle, Users } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../context/AuthContext";
import api, { formatError } from "../lib/api";
import { formatMoneyMinor } from "../lib/currency";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";
import { ModelPicker } from "../components/ModelPicker";
import { AgentWorkspace } from "../components/AgentWorkspace";
import { Popover, PopoverContent, PopoverTrigger } from "../components/ui/popover";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "../components/ui/dialog";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import CrmInbox from "./sections/CrmInbox";

const ROLE_LABELS = { sales_agent: "Sales agent", channel_partner: "Channel partner" };
const ROLE_ACCESS = { sales_agent: "leads assigned to you", channel_partner: "leads assigned to you or introduced by you" };

// The shared workspace for sales agents and channel partners: the owner's CRM on their permitted leads, with Agent Mode.
export default function SalesPortal({ workspace, workspaces }) {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [agentMode, setAgentMode] = useState(false);
  const [agentVisited, setAgentVisited] = useState(false);
  const [performance, setPerformance] = useState(null);
  const organization = workspace.organization || workspace.name;
  const sharedBy = workspace.shared_by || {};
  const role = ROLE_LABELS[workspace.access_role] || "Team member";

  const loadPerformance = useCallback(() => {
    api.get(`/workspaces/${workspace.id}/sales-portal/performance`).then(({ data }) => setPerformance(data)).catch(() => setPerformance(null));
  }, [workspace.id]);
  useEffect(() => {
    loadPerformance();
    const timer = setInterval(() => { if (!document.hidden) loadPerformance(); }, 15000);
    window.addEventListener("focus", loadPerformance);
    window.addEventListener("arevei:manager-changed", loadPerformance);
    return () => { clearInterval(timer); window.removeEventListener("focus", loadPerformance); window.removeEventListener("arevei:manager-changed", loadPerformance); };
  }, [loadPerformance]);

  const signOut = () => { logout(); navigate("/login"); };
  const modeClass = (active) => `inline-flex items-center gap-2 rounded-full px-3 py-2 text-xs font-semibold ${active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent"}`;

  return (
    <div className="app-shell h-[100dvh] flex flex-col overflow-hidden">
      <header className="app-topbar sticky top-0 z-20 glass border-b border-border">
        <div className="min-h-16 px-3 sm:px-5 py-2 flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0 flex items-center gap-3">
            <Logo className="text-base hidden sm:flex" to="/app" />
            <div className="min-w-0 sm:border-l sm:pl-3">
              <p className="text-[11px] text-muted-foreground truncate max-w-56">{organization}</p>
              <h2 className="font-semibold truncate">{agentMode ? "AI Manager" : "CRM"}</h2>
            </div>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/40 bg-primary/10 px-2.5 py-1 text-[11px] font-semibold text-primary"><Share2 size={12} /> Shared workspace</span>
          </div>
          <div className="app-mode-switch flex rounded-full border border-border p-1 gap-1" role="group" aria-label="Workspace mode">
            <button type="button" aria-pressed={!agentMode} onClick={() => setAgentMode(false)} className={modeClass(!agentMode)}><Users size={14} /> Human Mode</button>
            <button type="button" aria-pressed={agentMode} onClick={() => { setAgentVisited(true); setAgentMode(true); }} className={modeClass(agentMode)}><Bot size={14} /> Agent Mode</button>
          </div>
          <div className="flex items-center gap-2.5">
            <WorkspaceSwitcher current={workspace} workspaces={workspaces} navigate={navigate} />
            <Popover>
              <PopoverTrigger asChild><button aria-label="Account" className="grid place-items-center w-9 h-9 rounded-full border border-border hover:bg-accent transition-colors"><UserCircle className="w-4 h-4" /></button></PopoverTrigger>
              <PopoverContent align="end" className="w-72 max-w-[calc(100vw-24px)] p-0">
                <div className="px-4 py-3 border-b border-border"><div className="font-medium text-sm truncate">{user?.name || workspace.member_name || "Account"}</div><div className="text-xs text-muted-foreground truncate">{user?.email}</div><div className="mt-1 text-xs text-muted-foreground">{role} in {organization}</div></div>
                <div className="p-2"><button onClick={signOut} className="flex items-center gap-2 w-full h-9 px-2 rounded-md text-sm text-muted-foreground hover:text-destructive hover:bg-accent"><LogOut className="w-4 h-4" /> Log out</button></div>
              </PopoverContent>
            </Popover>
            <ThemeToggle />
          </div>
        </div>
        <div role="note" aria-label="Shared workspace details" className="border-t border-border bg-primary/5 px-3 sm:px-5 py-2 text-xs text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1">
          <span>Shared by <strong className="text-foreground">{sharedBy.name || "the workspace owner"}</strong>{sharedBy.email && ` (${sharedBy.email})`}</span>
          <span>Organization: <strong className="text-foreground">{organization}</strong></span>
          <span>You: <strong className="text-foreground">{workspace.member_name || user?.name || "Team member"}</strong> · {role}</span>
          <span>You control the {ROLE_ACCESS[workspace.access_role] || "leads shared with you"}</span>
        </div>
      </header>

      <main id="workspace-content" tabIndex={-1} hidden={agentMode} className={agentMode ? "hidden" : "flex-1 min-h-0 overflow-y-auto overscroll-contain"}>
        {performance && <section aria-label="Your performance" className="max-w-7xl mx-auto px-4 sm:px-8 pt-6 grid grid-cols-2 lg:grid-cols-4 gap-3">
          {[["Assigned leads", performance.item.assigned_leads], ["Booked sales", performance.item.sales], ["Booked sales value", formatMoneyMinor(performance.item.sales_minor, performance.currency || workspace.currency)], ["Leads introduced", performance.item.introduced_leads]].map(([label, value]) => <div key={label} className="rounded-xl border bg-card p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-xl font-semibold">{value}</p></div>)}
        </section>}
        <CrmInbox key={workspace.id} member={workspace} />
      </main>
      {agentVisited && <div hidden={!agentMode} className={agentMode ? "flex-1 min-h-0 overflow-y-auto" : "hidden"}><AgentWorkspace key={workspace.id} ws={workspace} active={agentMode} /></div>}
    </div>
  );
}

// Members keep their own workspaces alongside the ones shared with them, and can start one of their own.
function WorkspaceSwitcher({ current, workspaces, navigate }) {
  const own = workspaces.filter((item) => item.access_role === "owner");
  const shared = workspaces.filter((item) => item.access_role !== "owner");
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [modelId, setModelId] = useState("openai.gpt-oss-120b");
  const create = async (event) => {
    event.preventDefault();
    setCreating(true);
    try {
      const { data } = await api.post("/workspaces", { website_url: url, model_id: modelId });
      toast.success("Workspace created - training brain");
      setOpen(false);
      navigate(`/app/w/${data.id}/sales-strategy`);
    } catch (error) { toast.error(formatError(error.response?.data?.detail)); }
    finally { setCreating(false); }
  };
  const row = (item, path) => <button key={item.id} onClick={() => navigate(path)} aria-current={item.id === current.id ? "true" : undefined} className={`w-full flex items-center justify-between gap-2 rounded-md border p-2.5 text-left text-sm ${item.id === current.id ? "border-primary/50 bg-primary/5" : "border-border hover:bg-accent"}`}><span className="min-w-0 truncate">{item.name}</span>{item.id === current.id ? <Check className="w-4 h-4 text-primary shrink-0" /> : item.access_role !== "owner" && <span className="text-[11px] text-muted-foreground shrink-0">{ROLE_LABELS[item.access_role] || "Shared"}</span>}</button>;
  return <Popover>
    <PopoverTrigger asChild><button className="inline-flex items-center gap-2 h-9 rounded-full border border-border px-3 text-xs font-semibold hover:bg-accent"><Building2 className="w-4 h-4" /><span className="hidden sm:inline">Workspaces</span></button></PopoverTrigger>
    <PopoverContent align="end" className="w-80 max-w-[calc(100vw-24px)] p-3 space-y-3">
      <div className="space-y-1.5"><p className="text-xs uppercase tracking-wider font-bold text-muted-foreground">Your workspaces</p>{own.length ? own.map((item) => row(item, `/app/w/${item.id}`)) : <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">You have no workspace of your own yet.</p>}</div>
      <div className="space-y-1.5"><p className="text-xs uppercase tracking-wider font-bold text-muted-foreground">Shared with you</p>{shared.map((item) => row(item, `/app/w/${item.id}/crm`))}</div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild><button className="w-full inline-flex items-center justify-center gap-1.5 h-9 rounded-md bg-primary text-primary-foreground text-xs font-semibold"><Plus className="w-3.5 h-3.5" /> Create your own workspace</button></DialogTrigger>
        <DialogContent>
          <DialogHeader><DialogTitle className="font-display">Create workspace</DialogTitle></DialogHeader>
          <form onSubmit={create} className="space-y-5 pt-2">
            <div className="space-y-2"><Label htmlFor="shared-ws-url">Website URL</Label><Input id="shared-ws-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://yourcompany.com" required /><p className="text-xs text-muted-foreground">Your own workspace is separate from the workspaces shared with you.</p></div>
            <div className="space-y-2"><Label>Model</Label><ModelPicker value={modelId} onChange={setModelId} /></div>
            <button type="submit" disabled={creating} className="w-full h-11 rounded-full bg-primary text-primary-foreground font-semibold disabled:opacity-60">{creating ? "Creating..." : "Train brain"}</button>
          </form>
        </DialogContent>
      </Dialog>
    </PopoverContent>
  </Popover>;
}
