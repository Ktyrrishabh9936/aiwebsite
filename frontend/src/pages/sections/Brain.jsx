import { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { RefreshCw, Save, Loader2, Building2 } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "../../components/ui/dialog";
import { Textarea } from "../../components/ui/textarea";

const DOMAINS = [
  { key: "business_profile", label: "Business Profile" },
  { key: "organization", label: "Organization" },
  { key: "brand_identity", label: "Brand Identity" },
  { key: "audience", label: "Audience" },
  { key: "goals_constraints", label: "Goals & Constraints" },
  { key: "evidence", label: "Evidence" },
  { key: "decision_memory", label: "Decision Memory" },
];

const ORG_FIELDS = [
  ["company_name", "Company Name"],
  ["logo_url", "Logo URL"],
  ["address", "Address"],
  ["phone", "Phone"],
  ["email", "Email"],
  ["website", "Website"],
  ["tax_number", "Tax Number"],
  ["bank_details", "Bank Details"],
  ["authorized_signatory", "Authorized Signatory"],
  ["receipt_prefix", "Receipt Prefix"],
  ["invoice_prefix", "Invoice Prefix"],
  ["document_accent_color", "Document Accent Color"],
  ["document_text_color", "Document Text Color"],
  ["document_muted_color", "Document Muted Color"],
  ["document_table_header_color", "Table Header Color"],
];
const COLOR_FIELDS = new Set(["document_accent_color", "document_text_color", "document_muted_color", "document_table_header_color"]);

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
  const [orgDraft, setOrgDraft] = useState(brain.organization || {});

  useEffect(() => {
    setOrgDraft(brain.organization || {});
  }, [brain.organization]);

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

  const saveOrganization = async () => {
    setSaving(true);
    try {
      const cleanOrg = Object.fromEntries(ORG_FIELDS.map(([key]) => [key, String(orgDraft[key] || "").trim()]));
      await api.put(`/workspaces/${ws.id}/brain`, { brain: { ...brain, organization: cleanOrg, _source_url: brain._source_url, _pages_crawled: brain._pages_crawled } });
      await refresh();
      toast.success("Organization saved to brain");
    } catch (e) {
      toast.error("Could not save organization");
    } finally {
      setSaving(false);
    }
  };

  const retrain = () => api.post(`/workspaces/${ws.id}/rebrain`).then(() => { refresh(); toast.success("Re-training brain"); });

  if (ws.brain_status === "error") {
    return (
      <div className="p-10 max-w-4xl mx-auto">
        <div className="border border-destructive/40 rounded-md bg-destructive/5 p-10 text-center flex flex-col items-center gap-4">
          <div>
            <h1 className="font-display text-2xl font-black text-destructive">Brain training failed</h1>
            <p className="text-sm text-muted-foreground mt-2">Switch to a working model in the top bar, then re-train the brain.</p>
          </div>
          <button onClick={retrain} data-testid="rebrain-btn" className="inline-flex items-center gap-2 px-4 h-10 rounded-full border border-border hover:bg-accent text-sm font-medium">
            <RefreshCw className="w-4 h-4" /> Re-train
          </button>
        </div>
      </div>
    );
  }

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
          <button onClick={retrain} data-testid="rebrain-btn" className="inline-flex items-center gap-2 px-4 h-10 rounded-full border border-border hover:bg-accent text-sm font-medium">
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

      <section className="border border-border rounded-md bg-card p-6 space-y-5">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <h2 className="font-display text-xl font-bold flex items-center gap-2"><Building2 className="w-5 h-5 text-primary" /> Organization</h2>
            <p className="text-sm text-muted-foreground mt-1">Used on CRM receipts and final invoices.</p>
          </div>
          <button onClick={saveOrganization} disabled={saving} className="inline-flex items-center gap-2 px-4 h-10 rounded-full bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-60">
            <Save className="w-4 h-4" /> {saving ? "Saving..." : "Save organization"}
          </button>
        </div>
        <div className="grid md:grid-cols-2 gap-3">
          {ORG_FIELDS.map(([key, label]) => (
            <label key={key} className={key === "address" || key === "bank_details" ? "space-y-1.5 md:col-span-2" : "space-y-1.5"}>
              <span className="text-xs font-semibold text-muted-foreground uppercase">{label}</span>
              {key === "address" || key === "bank_details" ? (
                <textarea value={orgDraft[key] || ""} onChange={(e) => setOrgDraft({ ...orgDraft, [key]: e.target.value })} rows={3} className="w-full px-3 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
              ) : COLOR_FIELDS.has(key) ? (
                <div className="flex gap-2">
                  <input type="color" value={orgDraft[key] || (key === "document_accent_color" ? "#f5c400" : key === "document_table_header_color" ? "#1f2937" : key === "document_muted_color" ? "#6b7280" : "#111827")} onChange={(e) => setOrgDraft({ ...orgDraft, [key]: e.target.value })} className="h-10 w-12 rounded-lg border bg-background p-1" />
                  <input value={orgDraft[key] || ""} onChange={(e) => setOrgDraft({ ...orgDraft, [key]: e.target.value })} placeholder="#111827" className="w-full h-10 px-3 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
                </div>
              ) : (
                <input value={orgDraft[key] || ""} onChange={(e) => setOrgDraft({ ...orgDraft, [key]: e.target.value })} className="w-full h-10 px-3 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
              )}
            </label>
          ))}
        </div>
      </section>

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
