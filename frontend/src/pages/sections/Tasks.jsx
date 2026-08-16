import { useEffect, useState } from "react";
import { useOutletContext, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Play, Check, Clock, Loader2, Trash2, CheckCircle2, XCircle, FileText, Eye } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../components/ui/dialog";

const agentColors = {
  content: "bg-primary/10 text-primary",
  seo: "bg-emerald-500/10 text-emerald-500",
  creative: "bg-amber-500/10 text-amber-500",
  analytics: "bg-sky-500/10 text-sky-500",
};

const statusMeta = {
  pending: { icon: Clock, label: "Scheduled", cls: "text-muted-foreground" },
  running: { icon: Loader2, label: "Running", cls: "text-primary animate-spin" },
  awaiting_approval: { icon: Clock, label: "Awaiting approval", cls: "text-amber-500" },
  done: { icon: CheckCircle2, label: "Done", cls: "text-primary" },
  failed: { icon: XCircle, label: "Failed", cls: "text-destructive" },
};

export default function Tasks() {
  const { ws, loadNotes } = useOutletContext();
  const nav = useNavigate();
  const [tasks, setTasks] = useState([]);
  const [busy, setBusy] = useState(null);
  const [detail, setDetail] = useState(null);

  const load = () => api.get(`/workspaces/${ws.id}/tasks`).then((r) => setTasks(r.data)).catch(() => {});
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [ws.id]);

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
    return <div className="p-10 max-w-4xl mx-auto text-center text-muted-foreground border border-dashed border-border rounded-md py-16 m-6 sm:m-10">Generate a roadmap first (Overview → Generate roadmap) to schedule tasks.</div>;
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
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle className="font-display">{detail?.title}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">{detail?.output_summary}</p>
            {detail?.output_ref && (
              <button onClick={() => nav(`../blogs/${detail.output_ref}`)} className="inline-flex items-center gap-2 px-4 h-10 rounded-full bg-primary text-primary-foreground text-sm font-semibold">
                <FileText className="w-4 h-4" /> Open in editor
              </button>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
