import { useCallback, useEffect, useMemo, useState } from "react";
import { useOutletContext, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  Play, Check, Clock, Loader2, Trash2, CheckCircle2, XCircle, FileText, Eye,
  Copy, Share2, SearchCheck, Megaphone,
} from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../components/ui/dialog";

const agentColors = {
  content: "bg-primary/10 text-primary",
  seo: "bg-emerald-500/10 text-emerald-500",
  creative: "bg-amber-500/10 text-amber-500",
  analytics: "bg-sky-500/10 text-sky-500",
};

const priorityColors = {
  high: "bg-destructive/10 text-destructive border-destructive/20",
  medium: "bg-amber-500/10 text-amber-500 border-amber-500/20",
  low: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
};

const statusMeta = {
  pending: { icon: Clock, label: "Scheduled", cls: "text-muted-foreground" },
  running: { icon: Loader2, label: "Running", cls: "text-primary animate-spin" },
  awaiting_approval: { icon: Clock, label: "Awaiting approval", cls: "text-amber-500" },
  done: { icon: CheckCircle2, label: "Done", cls: "text-primary" },
  failed: { icon: XCircle, label: "Failed", cls: "text-destructive" },
};

const platforms = [
  { id: "linkedin", label: "LinkedIn" },
  { id: "x", label: "X" },
  { id: "instagram", label: "Instagram" },
  { id: "facebook", label: "Facebook" },
];

const copyText = async (text) => {
  try {
    await navigator.clipboard.writeText(text);
    toast.success("Copied");
  } catch {
    toast.error("Copy failed");
  }
};

function FallbackOutput({ task }) {
  return (
    <div className="rounded-md border border-border bg-secondary/30 p-4">
      <p className="whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
        {task?.output_summary || "No output available yet."}
      </p>
    </div>
  );
}

function SeoAuditView({ payload }) {
  const sections = Array.isArray(payload?.sections) ? payload.sections : [];
  const actions = Array.isArray(payload?.action_plan) ? payload.action_plan : [];

  if (!sections.length && !actions.length) return null;

  return (
    <div className="space-y-5">
      {payload?.summary && <p className="text-sm leading-6 text-muted-foreground">{payload.summary}</p>}

      <div className="grid gap-3">
        {sections.map((section, index) => {
          const priority = String(section.priority || "Medium").toLowerCase();
          const issues = Array.isArray(section.issues) ? section.issues : [];
          return (
            <section key={`${section.title}-${index}`} className="rounded-md border border-border bg-card p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="font-display text-lg font-bold">{section.title || "SEO Section"}</h3>
                <span className={`rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase ${priorityColors[priority] || priorityColors.medium}`}>
                  {section.priority || "Medium"}
                </span>
              </div>
              <div className="space-y-3">
                {issues.map((issue, issueIndex) => (
                  <div key={`${issue.title}-${issueIndex}`} className="border-t border-border pt-3 first:border-t-0 first:pt-0">
                    <div className="font-semibold text-sm">{issue.title || "Issue"}</div>
                    {issue.impact && <p className="mt-1 text-xs leading-5 text-muted-foreground">{issue.impact}</p>}
                    {issue.recommendation && (
                      <div className="mt-2 rounded-md bg-secondary/50 px-3 py-2 text-xs leading-5">
                        {issue.recommendation}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          );
        })}
      </div>

      {actions.length > 0 && (
        <section className="rounded-md border border-border bg-secondary/30 p-4">
          <div className="mb-3 flex items-center gap-2 font-display font-bold">
            <SearchCheck className="h-4 w-4 text-primary" /> Action plan
          </div>
          <div className="space-y-2">
            {actions.map((action, index) => (
              <div key={`${action}-${index}`} className="flex gap-3 text-sm leading-6">
                <span className="mt-1 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-primary/10 text-[10px] font-bold text-primary">
                  {index + 1}
                </span>
                <span>{action}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function SocialPostPackView({ payload }) {
  const [platform, setPlatform] = useState("linkedin");
  const posts = payload?.posts || {};
  const activePost = posts[platform] || {};
  const hashtags = Array.isArray(activePost.hashtags) ? activePost.hashtags.join(" ") : "";
  const copyValue = [activePost.caption, hashtags, activePost.cta].filter(Boolean).join("\n\n");
  const notes = Array.isArray(payload?.recommended_publish_notes) ? payload.recommended_publish_notes : [];

  if (!Object.keys(posts).length && !payload?.creative_brief) return null;

  return (
    <div className="space-y-5">
      {payload?.summary && <p className="text-sm leading-6 text-muted-foreground">{payload.summary}</p>}

      <div className="flex flex-wrap gap-2">
        {platforms.map((item) => (
          <button
            key={item.id}
            onClick={() => setPlatform(item.id)}
            className={`h-9 rounded-md px-3 text-sm font-medium transition-colors ${platform === item.id ? "bg-primary text-primary-foreground" : "border border-border hover:bg-accent"}`}
          >
            {item.label}
          </button>
        ))}
      </div>

      <section className="rounded-md border border-border bg-card p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h3 className="font-display text-lg font-bold">{platforms.find((item) => item.id === platform)?.label} draft</h3>
          <button
            onClick={() => copyText(copyValue)}
            disabled={!copyValue}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs font-medium hover:bg-accent disabled:opacity-50"
          >
            <Copy className="h-3.5 w-3.5" /> Copy
          </button>
        </div>
        <p className="whitespace-pre-wrap text-sm leading-6">{activePost.caption || "No caption generated for this platform."}</p>
        {hashtags && <div className="mt-3 text-sm font-medium text-primary">{hashtags}</div>}
        {activePost.cta && <div className="mt-3 rounded-md bg-secondary/50 px-3 py-2 text-sm">{activePost.cta}</div>}
      </section>

      {payload?.creative_brief && (
        <section className="rounded-md border border-border bg-secondary/30 p-4">
          <div className="mb-3 flex items-center gap-2 font-display font-bold">
            <Megaphone className="h-4 w-4 text-amber-500" /> Creative brief
          </div>
          <div className="grid gap-3 text-sm leading-6">
            {payload.creative_brief.concept && <p><span className="font-semibold">Concept:</span> {payload.creative_brief.concept}</p>}
            {payload.creative_brief.visual_direction && <p><span className="font-semibold">Visual direction:</span> {payload.creative_brief.visual_direction}</p>}
            {payload.creative_brief.asset_prompt && <p><span className="font-semibold">Asset prompt:</span> {payload.creative_brief.asset_prompt}</p>}
            {payload.creative_brief.production_notes && <p><span className="font-semibold">Production notes:</span> {payload.creative_brief.production_notes}</p>}
          </div>
        </section>
      )}

      {notes.length > 0 && (
        <section className="rounded-md border border-border bg-card p-4">
          <div className="mb-2 font-display font-bold">Publish notes</div>
          <ul className="list-disc space-y-1 pl-5 text-sm leading-6 text-muted-foreground">
            {notes.map((note, index) => <li key={`${note}-${index}`}>{note}</li>)}
          </ul>
        </section>
      )}

      <section className="flex items-center justify-between gap-4 rounded-md border border-dashed border-border bg-secondary/20 p-4">
        <div>
          <div className="font-display font-bold">Social connectors</div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {payload?.connector_status?.message || "Connector publishing is coming soon. Review and copy drafts for now."}
          </p>
        </div>
        <button disabled className="inline-flex h-9 shrink-0 items-center gap-2 rounded-md border border-border px-3 text-sm font-medium opacity-50">
          <Share2 className="h-4 w-4" /> Coming soon
        </button>
      </section>
    </div>
  );
}

function TaskDeliverable({ task, onOpenBlog }) {
  const payload = task?.output_payload || {};
  const isSeo = payload.type === "seo_audit" || task?.deliverable_type === "seo_audit";
  const isCreative = payload.type === "social_post_pack" || task?.deliverable_type === "social_post_pack";
  const rendered = isSeo ? <SeoAuditView payload={payload} /> : isCreative ? <SocialPostPackView payload={payload} /> : null;

  return (
    <div className="space-y-5">
      {rendered || <FallbackOutput task={task} />}
      {task?.output_ref && (
        <button onClick={onOpenBlog} className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground">
          <FileText className="h-4 w-4" /> Open in editor
        </button>
      )}
    </div>
  );
}

export default function Tasks() {
  const { ws, loadNotes } = useOutletContext();
  const nav = useNavigate();
  const [tasks, setTasks] = useState([]);
  const [busy, setBusy] = useState(null);
  const [detail, setDetail] = useState(null);

  const load = useCallback(() => api.get(`/workspaces/${ws.id}/tasks`).then((r) => setTasks(r.data)).catch(() => {}), [ws.id]);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);

  const detailTitle = useMemo(() => {
    if (!detail) return "";
    if (detail.output_payload?.type === "seo_audit") return `SEO Audit: ${detail.title}`;
    if (detail.output_payload?.type === "social_post_pack") return `Creative Drafts: ${detail.title}`;
    return detail.title;
  }, [detail]);

  const run = async (id) => {
    setBusy(id);
    try { await api.post(`/tasks/${id}/run`); toast.success("Task executed"); load(); loadNotes(); }
    catch { toast.error("Execution failed"); }
    finally { setBusy(null); }
  };
  const approve = async (id) => {
    setBusy(id);
    try { await api.post(`/tasks/${id}/approve`); toast.success("Approved & published"); load(); loadNotes(); }
    finally { setBusy(null); }
  };
  const del = async (id) => { await api.delete(`/tasks/${id}`); load(); };

  if ((ws.roadmap || []).length === 0) {
    return <div className="p-10 max-w-4xl mx-auto text-center text-muted-foreground border border-dashed border-border rounded-md py-16 m-6 sm:m-10">Generate a roadmap first (Overview -> Generate roadmap) to schedule tasks.</div>;
  }

  return (
    <div className="p-6 sm:p-10 max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="font-display text-3xl font-black tracking-tight">Tasks</h1>
        <p className="text-muted-foreground mt-1">Auto-scheduled by the manager. The scheduler runs due tasks automatically every ~30s.</p>
      </div>

      <div className="space-y-3">
        {tasks.map((t, i) => {
          const s = statusMeta[t.status] || statusMeta.pending;
          return (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(i * 0.03, 0.3) }}
              className="border border-border rounded-md bg-card p-4 sm:p-5 flex items-center gap-4 relative overflow-hidden"
              data-testid={`task-${t.id}`}
            >
              {t.status === "running" && <div className="absolute inset-x-0 top-0 h-0.5 tracing-beam" />}
              <span className={`text-[10px] uppercase font-bold px-2.5 py-1 rounded-full shrink-0 ${agentColors[t.agent] || "bg-secondary"}`}>{t.agent}</span>
              <div className="min-w-0 flex-1">
                <div className="font-medium truncate">{t.title}</div>
                <div className="text-xs text-muted-foreground truncate">{t.objective}</div>
              </div>
              <div className="hidden sm:flex items-center gap-1.5 text-xs shrink-0">
                <s.icon className={`w-3.5 h-3.5 ${s.cls}`} />
                <span className="text-muted-foreground">{s.label}</span>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                {(t.status === "done" || t.status === "awaiting_approval") && (
                  <button onClick={() => setDetail(t)} data-testid={`task-view-${t.id}`} className="grid place-items-center w-9 h-9 rounded-full border border-border hover:bg-accent" title="View output"><Eye className="w-4 h-4" /></button>
                )}
                {t.status === "pending" && (
                  <button onClick={() => run(t.id)} disabled={busy === t.id} data-testid={`task-run-${t.id}`} className="inline-flex items-center gap-1.5 px-3 h-9 rounded-full bg-primary text-primary-foreground text-sm font-medium disabled:opacity-60">
                    {busy === t.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />} Run
                  </button>
                )}
                {t.status === "awaiting_approval" && (
                  <button onClick={() => approve(t.id)} disabled={busy === t.id} data-testid={`task-approve-${t.id}`} className="inline-flex items-center gap-1.5 px-3 h-9 rounded-full bg-primary text-primary-foreground text-sm font-medium disabled:opacity-60">
                    <Check className="w-3.5 h-3.5" /> Approve
                  </button>
                )}
                <button onClick={() => del(t.id)} data-testid={`task-delete-${t.id}`} className="grid place-items-center w-9 h-9 rounded-full border border-border hover:bg-accent text-muted-foreground hover:text-destructive"><Trash2 className="w-4 h-4" /></button>
              </div>
            </motion.div>
          );
        })}
      </div>

      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-h-[85vh] max-w-4xl overflow-y-auto">
          <DialogHeader><DialogTitle className="font-display">{detailTitle}</DialogTitle></DialogHeader>
          {detail && (
            <TaskDeliverable
              task={detail}
              onOpenBlog={() => nav(`../blogs/${detail.output_ref}`)}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
