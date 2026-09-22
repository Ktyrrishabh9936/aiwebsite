import { useCallback, useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { ArrowRight, Bot, Brain, MessageSquare, FileText, Search, Palette, BarChart3, UserCheck, Code2, Phone, RefreshCw, Loader2, Settings2 } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { ModelPicker } from "../../components/ModelPicker";
import { AiStatus, useAiStatus } from "../../components/AiStatus";

// This directory describes existing execution paths; controls use their existing APIs.
const AGENTS = [
  { id: "brain", name: "Brain Builder", icon: Brain, group: "Workspace", role: "Builds business knowledge from your website.", trigger: "When you create a workspace or retrain its Brain.", inputs: ["Crawled website pages"], outputs: ["Company profile, brand voice, audience and business knowledge"], note: "Retraining replaces the saved Brain. Review manual edits before retraining.", link: "brain", action: "Edit Brain", context: "Website → Brain" },
  { id: "manager", name: "AI Manager", icon: MessageSquare, group: "Workspace", role: "Answers business and CRM questions, and plans growth work.", trigger: "When you chat or generate a roadmap.", inputs: ["Business profile and strategy summary", "Recent conversation", "Workspace CRM analytics and lead summaries"], outputs: ["Chat replies", "12-month roadmap and specialist tasks"], note: "CRM updates use existing application actions. Chat does not automatically read project files, all Brain fields, or full call transcripts.", link: "manager", action: "Open Manager", context: "Brain + CRM → Answers & plans" },
  { id: "content", name: "Content Agent", icon: FileText, group: "Workspace", role: "Writes blog articles, metadata and structured content.", trigger: "When you generate a blog or run a content task.", inputs: ["Business profile", "Brand identity", "Topic and objective"], outputs: ["Blog title, sections, tags and SEO metadata"], note: "Blog tasks without an approval requirement can publish automatically. Other blog tasks create drafts for approval.", link: "blogs", action: "Manage blogs", taskAgent: "content", context: "Brand + topic → Blog" },
  { id: "seo", name: "SEO Agent", icon: Search, group: "Workspace", role: "Produces SEO recommendations and action plans.", trigger: "When an SEO task runs.", inputs: ["Business profile", "Goals and constraints", "Task objective"], outputs: ["Prioritized SEO report and recommendations"], note: "Recommendations use business context, not a live technical crawl or backlink measurement.", link: "tasks", action: "Review tasks", taskAgent: "seo", context: "Business goals → Recommendations" },
  { id: "creative", name: "Creative Agent", icon: Palette, group: "Workspace", role: "Creates social post drafts and visual briefs.", trigger: "When a creative task runs.", inputs: ["Business profile, brand identity and audience", "Task objective"], outputs: ["LinkedIn, X, Instagram and Facebook copy", "Creative brief and image prompt"], note: "Produces text drafts and briefs. Image generation and social publishing are not connected to this agent.", link: "tasks", action: "Review drafts", taskAgent: "creative", context: "Brand + audience → Social drafts" },
  { id: "analytics", name: "Analytics Agent", icon: BarChart3, group: "Workspace", role: "Produces short written deliverables for analytics tasks.", trigger: "When an analytics task runs.", inputs: ["Task title and objective"], outputs: ["Text recommendations"], note: "Limited implementation: this task agent does not receive live analytics or Brain data. Manager chat has a separate CRM analytics context.", link: "tasks", action: "Review tasks", taskAgent: "analytics", limited: true, context: "Task objective → Written advice" },
  { id: "qualification", name: "Lead Qualification", icon: UserCheck, group: "Workspace", role: "Applies product rules to call facts and updates CRM qualification.", trigger: "When the configured voice provider sends a call result, transcript or recording callback.", inputs: ["Call events and conversation facts", "Product profile, mandatory rules and retry policy"], outputs: ["Call outcome, lead status, score and temperature", "Missing information, follow-up tasks and retry schedule"], note: "The selected provider conducts calls. AI extracts facts; application rules decide qualification. View outcomes inside each CRM lead.", link: "qualification", action: "Configure qualification", context: "Call facts + product rules → CRM decision" },
  { id: "lead-context", name: "Lead Context Agent", icon: Bot, group: "Workspace", role: "Prepares a concise briefing from each lead's campaign form and CRM history.", trigger: "Immediately before a Sarvam qualification call using Lead context mode.", inputs: ["Dynamic CRM fields and their labels", "Campaign attribution, prior confirmed answers and qualification profile"], outputs: ["lead_context briefing for the voice agent", "An audit note on the CRM lead"], note: "Uses the workspace model when available and automatically falls back to a deterministic briefing. It treats form values as data and does not decide the qualification result.", link: "settings", action: "Configure voice provider", context: "Form + CRM history → Lead briefing" },
  { id: "coding", name: "Coding Agent", icon: Code2, group: "Separate setup", role: "Builds and edits websites in a project sandbox.", trigger: "When you send a message in a coding project.", inputs: ["Project conversation and files", "Sandbox tool results and linked blog context"], outputs: ["File changes and terminal results"], note: "Uses a separate model registry and a model saved on each project. Changing the workspace model does not change coding projects.", link: "projects", action: "Configure a project", context: "Project + tools → Website changes" },
  { id: "voice", name: "Voice Agents", icon: Phone, group: "Separate setup", role: "Run customer calls through your configured voice flows.", trigger: "When a call is started by a user or an enabled workflow.", inputs: ["Lead details", "Configured call flow and variable mappings"], outputs: ["Call events, transcript and qualification callbacks"], note: "External voice flow configuration is managed in CRM. The workspace model extracts transcript facts, not the voice provider's model.", link: "crm", action: "Configure voice agents", context: "Lead + voice flow → Call" },
];

export default function Agents() {
  const { ws, setWs, refresh } = useOutletContext();
  const [selected, setSelected] = useState("manager");
  const [query, setQuery] = useState("");
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const status = useAiStatus(ws);
  const base = `/app/w/${ws.id}`;
  const agent = AGENTS.find((a) => a.id === selected);
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { const r = await api.get(`/workspaces/${ws.id}/tasks`); setTasks(r.data); }
    catch { setError("Task activity could not be loaded. Retry to see current counts."); }
    finally { setLoading(false); }
  }, [ws.id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const timer = setInterval(() => { if (!document.hidden) load(); }, 30000);
    return () => clearInterval(timer);
  }, [load]);
  const changeModel = async (modelId) => {
    if (saving) return;
    setSaving(true);
    try {
      const r = await api.patch(`/workspaces/${ws.id}`, { model_id: modelId });
      setWs(r.data);
      await refresh();
      toast.success("Workspace agent model updated");
    } catch { toast.error("Could not update the workspace model"); }
    finally { setSaving(false); }
  };
  const relevant = tasks.filter((task) => task.agent === agent.taskAgent);
  const counts = (items, state) => items.filter((task) => task.status === state).length;
  const label = (a) => a.limited ? "Limited" : a.id === "brain" ? `Brain: ${ws.brain_status}` : a.id === "qualification" ? (ws.qualification_profile_id ? "Default profile set" : "Profile setup needed") : a.group === "Separate setup" ? "Separate configuration" : "Uses workspace model";
  return (
    <div className="p-5 sm:p-8 space-y-6 max-w-[1500px] mx-auto">
      <div className="flex items-start justify-between gap-3">
        <div><div className="text-xs font-semibold uppercase tracking-widest text-primary mb-2">Workspace intelligence</div><h1 className="font-display text-3xl font-bold">AI Agents</h1><p className="mt-2 text-sm text-muted-foreground max-w-2xl">See who does what, where their knowledge comes from, and where to configure their work.</p></div>
        <button type="button" onClick={load} disabled={loading} className="border rounded-lg p-2.5 hover:bg-accent disabled:opacity-50" aria-label="Refresh task activity"><RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} /></button>
      </div>
      <section className="rounded-xl border bg-card p-5 grid lg:grid-cols-2 gap-5">
        <div className="space-y-3"><h2 className="font-semibold flex items-center gap-2"><Settings2 className="w-4 h-4 text-primary" /> Shared AI model</h2><p className="text-sm text-muted-foreground">Brain, Manager, content, SEO, creative, analytics and qualification use this workspace selection. Coding and voice agents have separate settings.</p><div className="flex flex-wrap items-center gap-3"><ModelPicker value={ws.model_id} onChange={changeModel} />{saving && <Loader2 className="w-4 h-4 animate-spin" />}<Link to={`${base}/brain`} className="text-sm text-primary hover:underline">Edit shared Brain knowledge</Link></div><p className="text-xs text-muted-foreground">Test AI checks Manager's connection. It does not test every agent or external voice flow.</p></div>
        <AiStatus status={status} busy={saving} />
      </section>
      <div className="grid sm:grid-cols-3 gap-3">
        {[{ title: "1. Knowledge", text: "Website pages build the Brain", id: "brain" }, { title: "2. Planning", text: "Manager uses context to answer and plan", id: "manager" }, { title: "3. Execution", text: "Specialists produce task deliverables", id: "content" }].map((step) => <button key={step.id} onClick={() => setSelected(step.id)} className="text-left border rounded-xl p-4 hover:bg-accent flex items-center justify-between gap-3"><span><span className="block text-sm font-semibold">{step.title}</span><span className="block text-xs text-muted-foreground mt-1">{step.text}</span></span><ArrowRight className="w-4 h-4 text-muted-foreground shrink-0" /></button>)}
      </div>
      {error && <p role="alert" className="text-sm text-amber-600">{error}</p>}
      <div className="grid xl:grid-cols-[1fr_380px] gap-6 items-start">
        <section className="space-y-4">
          <div className="flex flex-wrap justify-between items-center gap-3"><h2 className="font-semibold">Agent directory <span className="text-muted-foreground font-normal">· {AGENTS.length} roles</span></h2><label className="flex items-center gap-2 border rounded-lg px-3 bg-background"><Search className="w-4 h-4 text-muted-foreground" /><input aria-label="Search agents" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find an agent…" className="bg-transparent text-sm h-9 outline-none w-40" /></label></div>
          <div className="grid sm:grid-cols-2 gap-3">
            {AGENTS.filter((a) => `${a.name} ${a.role}`.toLowerCase().includes(query.toLowerCase())).map((a) => <button key={a.id} onClick={() => setSelected(a.id)} aria-pressed={selected === a.id} className={`text-left rounded-xl border p-4 space-y-3 transition-colors ${selected === a.id ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "bg-card hover:bg-accent"}`}><div className="flex justify-between items-center gap-2"><a.icon className="w-5 h-5 text-primary" /><span className={`text-[10px] rounded-full px-2 py-1 ${a.limited ? "bg-amber-500/10 text-amber-600" : "bg-secondary text-muted-foreground"}`}>{label(a)}</span></div><div><h3 className="font-semibold">{a.name}</h3><p className="text-sm text-muted-foreground mt-1">{a.role}</p></div><div className="text-xs text-muted-foreground">{a.taskAgent && !error && !loading ? `${counts(tasks.filter((t) => t.agent === a.taskAgent), "running")} running · ${counts(tasks.filter((t) => t.agent === a.taskAgent), "failed")} failed` : a.group}</div></button>)}
          </div>
          {!AGENTS.some((a) => `${a.name} ${a.role}`.toLowerCase().includes(query.toLowerCase())) && <p className="text-sm text-muted-foreground py-6">No agents match your search.</p>}
        </section>
        <aside className="rounded-xl border bg-card p-5 space-y-5 xl:sticky xl:top-20" aria-label="Selected agent details">
          <div className="flex items-center gap-3"><agent.icon className="w-6 h-6 text-primary" /><div><div className="text-xs text-muted-foreground">{agent.group}</div><h2 className="text-xl font-semibold">{agent.name}</h2></div></div>
          <p className="text-xs font-medium text-primary bg-primary/5 rounded-lg p-3">{agent.context}</p>
          <div><h3 className="text-xs uppercase tracking-wide font-semibold text-muted-foreground mb-2">When it runs</h3><p className="text-sm">{agent.trigger}</p></div>
          {[{ title: "What it reads", values: agent.inputs }, { title: "What it produces", values: agent.outputs }].map((section) => <div key={section.title}><h3 className="text-xs uppercase tracking-wide font-semibold text-muted-foreground mb-2">{section.title}</h3><ul className="text-sm space-y-2 list-disc pl-4">{section.values.map((value) => <li key={value}>{value}</li>)}</ul></div>)}
          <div className="rounded-lg bg-secondary p-3 text-sm text-muted-foreground">{agent.note}</div>
          {agent.taskAgent && <div><h3 className="text-xs uppercase tracking-wide font-semibold text-muted-foreground mb-2">Task activity</h3><p className="text-xs text-muted-foreground mb-2">From the workspace's first 200 scheduled tasks.</p>{loading ? <p className="text-sm">Loading…</p> : error ? <p className="text-sm text-amber-600">Activity unavailable</p> : <div className="flex flex-wrap gap-2">{["pending", "running", "awaiting_approval", "done", "failed"].map((state) => <span key={state} className="text-xs border rounded-md px-2 py-1">{state.replaceAll("_", " ")}: {counts(relevant, state)}</span>)}</div>}</div>}
          <Link to={`${base}/${agent.link}`} className="flex items-center justify-center gap-2 rounded-lg bg-primary text-primary-foreground px-4 py-2.5 text-sm font-semibold">{agent.action}<ArrowRight className="w-4 h-4" /></Link>
          <p className="text-xs text-muted-foreground">{agent.group === "Workspace" ? "Model changes above apply to all workspace roles, not only this agent." : "Open its configuration to manage the provider and behavior."}</p>
        </aside>
      </div>
      <p className="text-xs text-muted-foreground flex items-center gap-2"><Bot className="w-4 h-4" /> Roles describe the current application. Task counts refresh every 30 seconds; they are not provider health checks.</p>
    </div>
  );
}
