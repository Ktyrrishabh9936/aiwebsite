import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { RefreshCw, Save, Loader2 } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "../../components/ui/dialog";
import { Textarea } from "../../components/ui/textarea";

const DOMAINS = [
  { key: "business_profile", label: "Business Profile" },
  { key: "brand_identity", label: "Brand Identity" },
  { key: "audience", label: "Audience" },
  { key: "goals_constraints", label: "Goals & Constraints" },
  { key: "evidence", label: "Evidence" },
  { key: "decision_memory", label: "Decision Memory" },
];

function renderValue(v) {
  if (v == null) return <span className="text-muted-foreground">—</span>;
  if (Array.isArray(v)) {
    return (
      <ul className="space-y-1.5">
        {v.map((item, i) => (
          <li key={i} className="flex gap-2 text-sm">
            <span className="mt-1.5 w-1 h-1 rounded-full bg-primary shrink-0" />
            <span>{typeof item === "object" ? Object.entries(item).map(([k, val]) => `${k}: ${Array.isArray(val) ? val.join(", ") : val}`).join(" · ") : String(item)}</span>
          </li>
        ))}
      </ul>
    );
  }
  if (typeof v === "object") {
    return (
      <div className="space-y-3">
        {Object.entries(v).map(([k, val]) => (
          <div key={k}>
            <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">{k.replace(/_/g, " ")}</div>
            <div className="text-sm">{renderValue(val)}</div>
          </div>
        ))}
      </div>
    );
  }
  return <span className="text-sm leading-relaxed">{String(v)}</span>;
}

export default function BrainView() {
  const { ws, refresh } = useOutletContext();
  const brain = ws.brain || {};
  const [editOpen, setEditOpen] = useState(false);
  const [json, setJson] = useState("");
  const [saving, setSaving] = useState(false);

  const openEdit = () => {
    const clean = { ...brain };
    delete clean._source_url; delete clean._pages_crawled;
    setJson(JSON.stringify(clean, null, 2));
    setEditOpen(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      const parsed = JSON.parse(json);
      await api.put(`/workspaces/${ws.id}/brain`, { brain: { ...parsed, _source_url: brain._source_url, _pages_crawled: brain._pages_crawled } });
      await refresh();
      toast.success("Brain updated");
      setEditOpen(false);
    } catch (e) {
      toast.error("Invalid JSON — please fix and retry");
    } finally {
      setSaving(false);
    }
  };

  if (ws.brain_status !== "ready") {
    return (
      <div className="p-10 max-w-4xl mx-auto">
        <div className="border border-border rounded-md bg-card p-10 text-center text-muted-foreground flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 animate-spin text-primary" />
          The brain is still training. Hang tight.
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 sm:p-10 max-w-5xl mx-auto space-y-8">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <h1 className="font-display text-3xl font-black tracking-tight">The Brain</h1>
          <p className="text-muted-foreground mt-1">
            Trained from {(brain._pages_crawled || []).length} pages · <span className="font-mono text-xs">{brain._source_url}</span>
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => api.post(`/workspaces/${ws.id}/rebrain`).then(() => { refresh(); toast.success("Re-training brain"); })} data-testid="rebrain-btn" className="inline-flex items-center gap-2 px-4 h-10 rounded-full border border-border hover:bg-accent text-sm font-medium">
            <RefreshCw className="w-4 h-4" /> Re-train
          </button>
          <Dialog open={editOpen} onOpenChange={setEditOpen}>
            <DialogTrigger asChild>
              <button onClick={openEdit} data-testid="edit-brain-btn" className="inline-flex items-center gap-2 px-4 h-10 rounded-full bg-primary text-primary-foreground text-sm font-semibold">
                Edit brain
              </button>
            </DialogTrigger>
            <DialogContent className="max-w-2xl">
              <DialogHeader><DialogTitle className="font-display">Edit brain (JSON)</DialogTitle></DialogHeader>
              <Textarea value={json} onChange={(e) => setJson(e.target.value)} rows={18} className="font-mono text-xs" data-testid="brain-json-editor" />
              <button onClick={save} disabled={saving} data-testid="save-brain-btn" className="inline-flex items-center justify-center gap-2 h-11 rounded-full bg-primary text-primary-foreground font-semibold disabled:opacity-60">
                <Save className="w-4 h-4" /> {saving ? "Saving…" : "Save brain"}
              </button>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {DOMAINS.map((d) => (
          <div key={d.key} className="border border-border rounded-md bg-card p-6" data-testid={`brain-domain-${d.key}`}>
            <div className="text-xs uppercase tracking-[0.2em] font-bold text-primary mb-4">{d.label}</div>
            {renderValue(brain[d.key])}
          </div>
        ))}
      </div>
    </div>
  );
}
