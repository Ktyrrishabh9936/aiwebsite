import { useEffect, useMemo, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { Plus, RefreshCw, Save, Loader2, Building2, Trash2, Code2 } from "lucide-react";
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

const BRAIN_TEMPLATE = {
  business_profile: {
    company_name: "",
    industry: "",
    description: "",
    offers: [""],
    pricing_summary: "",
    locations: [""],
    founders: [""],
  },
  organization: {
    company_name: "",
    logo_url: "",
    address: "",
    phone: "",
    email: "",
    website: "",
    tax_number: "",
    bank_details: "",
    authorized_signatory: "",
    receipt_prefix: "",
    invoice_prefix: "",
    document_accent_color: "",
    document_text_color: "",
    document_muted_color: "",
    document_table_header_color: "",
  },
  brand_identity: {
    voice: "",
    personality: "",
    tone_words: [""],
    approved_wording: [""],
  },
  audience: {
    icps: [{ name: "", pains: [""], motivations: [""], objections: [""] }],
    buying_triggers: [""],
  },
  goals_constraints: {
    kpis: [""],
    priorities: [""],
    restrictions: [""],
    publishing_cadence: "",
  },
  evidence: {
    summary: "",
    testimonials: [""],
    differentiators: [""],
  },
  decision_memory: {
    approved: [""],
    rejected: [""],
    notes: [""],
  },
};

const COLOR_FIELDS = new Set(["document_accent_color", "document_text_color", "document_muted_color", "document_table_header_color"]);
const LONG_TEXT_FIELDS = new Set(["description", "summary", "address", "bank_details", "personality"]);

function clone(value) {
  return JSON.parse(JSON.stringify(value ?? {}));
}

function mergeTemplate(template, source) {
  if (Array.isArray(template)) {
    return Array.isArray(source) && source.length ? source.map((item) => mergeTemplate(template[0] ?? "", item)) : clone(template);
  }
  if (template && typeof template === "object") {
    const out = {};
    for (const [key, val] of Object.entries(template)) out[key] = mergeTemplate(val, source?.[key]);
    for (const [key, val] of Object.entries(source || {})) if (!(key in out) && !key.startsWith("_")) out[key] = val;
    return out;
  }
  return source == null ? template : source;
}

function withOrganizationFallback(brain, websiteUrl = "") {
  const source = brain || {};
  const businessProfile = source.business_profile || {};
  const organization = source.organization || {};
  return {
    ...source,
    organization: {
      ...organization,
      company_name: organization.company_name || businessProfile.company_name || "",
      website: organization.website || source._source_url || websiteUrl || "",
    },
  };
}

function emptyLike(sample) {
  if (Array.isArray(sample)) return [emptyLike(sample[0] ?? "")];
  if (sample && typeof sample === "object") return Object.fromEntries(Object.entries(sample).map(([key, val]) => [key, emptyLike(val)]));
  return "";
}

function titleize(key) {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function updateAt(value, path, nextValue) {
  if (!path.length) return nextValue;
  const [head, ...rest] = path;
  const copy = Array.isArray(value) ? [...value] : { ...(value || {}) };
  copy[head] = updateAt(copy[head], rest, nextValue);
  return copy;
}

function removeAt(value, path, index) {
  const list = path.reduce((acc, key) => acc?.[key], value) || [];
  const next = list.filter((_, i) => i !== index);
  return updateAt(value, path, next.length ? next : [emptyLike(list[0] ?? "")]);
}

function addAt(value, path) {
  const list = path.reduce((acc, key) => acc?.[key], value) || [];
  return updateAt(value, path, [...list, emptyLike(list[0] ?? "")]);
}

function TextField({ label, value, path, onChange, multiline = false }) {
  const setValue = (next) => onChange((draft) => updateAt(draft, path, next));
  const key = path[path.length - 1];

  return (
    <label className="space-y-1.5 block">
      <span className="text-xs font-semibold text-muted-foreground uppercase">{label}</span>
      {multiline || LONG_TEXT_FIELDS.has(key) ? (
        <textarea value={value ?? ""} onChange={(e) => setValue(e.target.value)} rows={3} className="w-full px-3 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
      ) : COLOR_FIELDS.has(key) ? (
        <div className="flex gap-2">
          <input type="color" value={/^#[0-9a-f]{6}$/i.test(value || "") ? value : "#000000"} onChange={(e) => setValue(e.target.value)} className="h-10 w-12 rounded-lg border bg-background p-1" />
          <input value={value ?? ""} onChange={(e) => setValue(e.target.value)} placeholder="#000000" className="w-full h-10 px-3 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
        </div>
      ) : (
        <input value={value ?? ""} onChange={(e) => setValue(e.target.value)} className="w-full h-10 px-3 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
      )}
    </label>
  );
}

function ListField({ label, values = [""], path, onChange }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-semibold text-muted-foreground uppercase">{label}</div>
        <button type="button" onClick={() => onChange((draft) => addAt(draft, path))} className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-md border border-border text-xs hover:bg-accent">
          <Plus className="w-3.5 h-3.5" /> Add
        </button>
      </div>
      <div className="space-y-2">
        {(values || [""]).map((item, index) => (
          <div key={index} className="flex gap-2">
            <input value={item ?? ""} onChange={(e) => onChange((draft) => updateAt(draft, [...path, index], e.target.value))} className="min-w-0 flex-1 h-10 px-3 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
            <button type="button" onClick={() => onChange((draft) => removeAt(draft, path, index))} className="grid place-items-center w-10 h-10 rounded-lg border border-border hover:bg-accent text-muted-foreground" title="Remove item">
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function IcpEditor({ values = [], path, onChange }) {
  return (
    <div className="space-y-3 md:col-span-2">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-semibold text-muted-foreground uppercase">ICPs</div>
        <button type="button" onClick={() => onChange((draft) => addAt(draft, path))} className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-md border border-border text-xs hover:bg-accent">
          <Plus className="w-3.5 h-3.5" /> Add ICP
        </button>
      </div>
      {(values || []).map((item, index) => (
        <div key={index} className="rounded-md border border-border bg-background p-3 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-mono text-muted-foreground">ICP {index + 1}</span>
            <button type="button" onClick={() => onChange((draft) => removeAt(draft, path, index))} className="grid place-items-center w-8 h-8 rounded-md border border-border hover:bg-accent text-muted-foreground" title="Remove ICP">
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
          <TextField label="Name" value={item.name} path={[...path, index, "name"]} onChange={onChange} />
          <ListField label="Pains" values={item.pains} path={[...path, index, "pains"]} onChange={onChange} />
          <ListField label="Motivations" values={item.motivations} path={[...path, index, "motivations"]} onChange={onChange} />
          <ListField label="Objections" values={item.objections} path={[...path, index, "objections"]} onChange={onChange} />
        </div>
      ))}
    </div>
  );
}

function GenericExtraEditor({ domainKey, data, onChange }) {
  const known = BRAIN_TEMPLATE[domainKey] || {};
  const extras = Object.entries(data || {}).filter(([key]) => !(key in known));
  if (!extras.length) return null;
  return (
    <div className="md:col-span-2 rounded-md border border-dashed border-border p-3 space-y-3">
      <div className="text-xs font-semibold text-muted-foreground uppercase">Extra fields</div>
      {extras.map(([key, value]) => (
        <TextField key={key} label={titleize(key)} value={typeof value === "string" ? value : JSON.stringify(value, null, 2)} path={[domainKey, key]} onChange={onChange} multiline={typeof value !== "string"} />
      ))}
    </div>
  );
}

function DomainEditor({ domain, value, onChange }) {
  const k = domain.key;
  if (k === "business_profile") {
    return (
      <div className="grid md:grid-cols-2 gap-3">
        <TextField label="Company Name" value={value.company_name} path={[k, "company_name"]} onChange={onChange} />
        <TextField label="Industry" value={value.industry} path={[k, "industry"]} onChange={onChange} />
        <div className="md:col-span-2"><TextField label="Description" value={value.description} path={[k, "description"]} onChange={onChange} /></div>
        <div className="md:col-span-2"><ListField label="Offers" values={value.offers} path={[k, "offers"]} onChange={onChange} /></div>
        <TextField label="Pricing Summary" value={value.pricing_summary} path={[k, "pricing_summary"]} onChange={onChange} />
        <ListField label="Locations" values={value.locations} path={[k, "locations"]} onChange={onChange} />
        <div className="md:col-span-2"><ListField label="Founders" values={value.founders} path={[k, "founders"]} onChange={onChange} /></div>
        <GenericExtraEditor domainKey={k} data={value} onChange={onChange} />
      </div>
    );
  }
  if (k === "organization") {
    return (
      <div className="grid md:grid-cols-2 gap-3">
        {Object.keys(BRAIN_TEMPLATE.organization).map((key) => (
          <div key={key} className={LONG_TEXT_FIELDS.has(key) ? "md:col-span-2" : ""}>
            <TextField label={titleize(key)} value={value[key]} path={[k, key]} onChange={onChange} />
          </div>
        ))}
        <GenericExtraEditor domainKey={k} data={value} onChange={onChange} />
      </div>
    );
  }
  if (k === "brand_identity") {
    return (
      <div className="grid md:grid-cols-2 gap-3">
        <TextField label="Voice" value={value.voice} path={[k, "voice"]} onChange={onChange} />
        <TextField label="Personality" value={value.personality} path={[k, "personality"]} onChange={onChange} />
        <div className="md:col-span-2"><ListField label="Tone Words" values={value.tone_words} path={[k, "tone_words"]} onChange={onChange} /></div>
        <div className="md:col-span-2"><ListField label="Approved Wording" values={value.approved_wording} path={[k, "approved_wording"]} onChange={onChange} /></div>
        <GenericExtraEditor domainKey={k} data={value} onChange={onChange} />
      </div>
    );
  }
  if (k === "audience") {
    return (
      <div className="grid md:grid-cols-2 gap-3">
        <IcpEditor values={value.icps} path={[k, "icps"]} onChange={onChange} />
        <div className="md:col-span-2"><ListField label="Buying Triggers" values={value.buying_triggers} path={[k, "buying_triggers"]} onChange={onChange} /></div>
        <GenericExtraEditor domainKey={k} data={value} onChange={onChange} />
      </div>
    );
  }
  if (k === "goals_constraints") {
    return (
      <div className="grid md:grid-cols-2 gap-3">
        <ListField label="KPIs" values={value.kpis} path={[k, "kpis"]} onChange={onChange} />
        <ListField label="Priorities" values={value.priorities} path={[k, "priorities"]} onChange={onChange} />
        <div className="md:col-span-2"><ListField label="Restrictions" values={value.restrictions} path={[k, "restrictions"]} onChange={onChange} /></div>
        <div className="md:col-span-2"><TextField label="Publishing Cadence" value={value.publishing_cadence} path={[k, "publishing_cadence"]} onChange={onChange} /></div>
        <GenericExtraEditor domainKey={k} data={value} onChange={onChange} />
      </div>
    );
  }
  if (k === "evidence") {
    return (
      <div className="grid md:grid-cols-2 gap-3">
        <div className="md:col-span-2"><TextField label="Summary" value={value.summary} path={[k, "summary"]} onChange={onChange} /></div>
        <div className="md:col-span-2"><ListField label="Testimonials" values={value.testimonials} path={[k, "testimonials"]} onChange={onChange} /></div>
        <div className="md:col-span-2"><ListField label="Differentiators" values={value.differentiators} path={[k, "differentiators"]} onChange={onChange} /></div>
        <GenericExtraEditor domainKey={k} data={value} onChange={onChange} />
      </div>
    );
  }
  return (
    <div className="grid md:grid-cols-2 gap-3">
      <ListField label="Approved" values={value.approved} path={[k, "approved"]} onChange={onChange} />
      <ListField label="Rejected" values={value.rejected} path={[k, "rejected"]} onChange={onChange} />
      <div className="md:col-span-2"><ListField label="Notes" values={value.notes} path={[k, "notes"]} onChange={onChange} /></div>
      <GenericExtraEditor domainKey={k} data={value} onChange={onChange} />
    </div>
  );
}
function stripEmpty(value) {
  if (Array.isArray(value)) return value.map(stripEmpty).filter((item) => {
    if (Array.isArray(item)) return item.length > 0;
    if (item && typeof item === "object") return Object.keys(item).length > 0;
    return String(item ?? "").trim() !== "";
  });
  if (value && typeof value === "object") {
    const out = {};
    for (const [key, val] of Object.entries(value)) {
      const next = stripEmpty(val);
      if (Array.isArray(next) ? next.length : next && typeof next === "object" ? Object.keys(next).length : String(next ?? "").trim() !== "") out[key] = next;
    }
    return out;
  }
  return typeof value === "string" ? value.trim() : value;
}

export default function BrainView() {
  const { ws, refresh } = useOutletContext();
  const brain = useMemo(() => withOrganizationFallback(ws.brain || {}, ws.website_url), [ws.brain, ws.website_url]);
  const [editOpen, setEditOpen] = useState(false);
  const [json, setJson] = useState("");
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState(() => mergeTemplate(BRAIN_TEMPLATE, brain));
  const trainedPages = brain._pages_crawled || [];
  const emptyTraining = ws.brain_status === "ready" && trainedPages.length === 0;

  useEffect(() => {
    setDraft(mergeTemplate(BRAIN_TEMPLATE, brain));
  }, [brain]);

  const visibleDraft = useMemo(() => mergeTemplate(BRAIN_TEMPLATE, draft), [draft]);

  const openEdit = () => {
    setJson(JSON.stringify(visibleDraft, null, 2));
    setEditOpen(true);
  };

  const saveJson = async () => {
    setSaving(true);
    try {
      const parsed = JSON.parse(json);
      const nextBrain = { ...parsed, _source_url: brain._source_url, _pages_crawled: brain._pages_crawled };
      await api.put(`/workspaces/${ws.id}/brain`, { brain: nextBrain });
      await refresh();
      toast.success("Brain updated");
      setEditOpen(false);
    } catch (e) {
      toast.error("Invalid JSON - please fix and retry");
    } finally {
      setSaving(false);
    }
  };

  const saveBrain = async () => {
    setSaving(true);
    try {
      const nextBrain = { ...stripEmpty(visibleDraft), _source_url: brain._source_url, _pages_crawled: brain._pages_crawled };
      await api.put(`/workspaces/${ws.id}/brain`, { brain: nextBrain });
      await refresh();
      toast.success("Brain saved");
    } catch (e) {
      toast.error("Could not save brain");
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
            <p className="text-sm text-muted-foreground mt-2">You can edit the Brain manually below or switch models and re-train.</p>
          </div>
          <button onClick={retrain} data-testid="rebrain-btn" className="inline-flex items-center gap-2 px-4 h-10 rounded-full border border-border hover:bg-accent text-sm font-medium">
            <RefreshCw className="w-4 h-4" /> Re-train
          </button>
        </div>
        <EditableBrainShell draft={visibleDraft} setDraft={setDraft} brain={brain} ws={ws} saving={saving} saveBrain={saveBrain} editOpen={editOpen} setEditOpen={setEditOpen} openEdit={openEdit} json={json} setJson={setJson} saveJson={saveJson} emptyTraining />
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
    <EditableBrainShell draft={visibleDraft} setDraft={setDraft} brain={brain} ws={ws} saving={saving} saveBrain={saveBrain} retrain={retrain} editOpen={editOpen} setEditOpen={setEditOpen} openEdit={openEdit} json={json} setJson={setJson} saveJson={saveJson} emptyTraining={emptyTraining} />
  );
}

function EditableBrainShell({ draft, setDraft, brain, ws, saving, saveBrain, retrain, editOpen, setEditOpen, openEdit, json, setJson, saveJson, emptyTraining }) {
  return (
    <div className="p-6 sm:p-10 max-w-6xl mx-auto space-y-8">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <h1 className="font-display text-3xl font-black tracking-tight">The Brain</h1>
          <p className="text-muted-foreground mt-1">
            Trained from {(brain._pages_crawled || []).length} pages - <span className="font-mono text-xs">{brain._source_url || ws.website_url}</span>
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {retrain && (
            <button onClick={retrain} data-testid="rebrain-btn" className="inline-flex items-center gap-2 px-4 h-10 rounded-full border border-border hover:bg-accent text-sm font-medium">
              <RefreshCw className="w-4 h-4" /> Re-train
            </button>
          )}
          <button onClick={saveBrain} disabled={saving} data-testid="save-brain-form-btn" className="inline-flex items-center gap-2 px-4 h-10 rounded-full bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-60">
            <Save className="w-4 h-4" /> {saving ? "Saving..." : "Save brain"}
          </button>
          <Dialog open={editOpen} onOpenChange={setEditOpen}>
            <DialogTrigger asChild>
              <button onClick={openEdit} data-testid="edit-brain-btn" className="inline-flex items-center gap-2 px-4 h-10 rounded-full border border-border hover:bg-accent text-sm font-medium">
                <Code2 className="w-4 h-4" /> JSON
              </button>
            </DialogTrigger>
            <DialogContent className="max-w-2xl">
              <DialogHeader><DialogTitle className="font-display">Edit brain (JSON)</DialogTitle></DialogHeader>
              <Textarea value={json} onChange={(e) => setJson(e.target.value)} rows={18} className="font-mono text-xs" data-testid="brain-json-editor" />
              <button onClick={saveJson} disabled={saving} data-testid="save-brain-btn" className="inline-flex items-center justify-center gap-2 h-11 rounded-full bg-primary text-primary-foreground font-semibold disabled:opacity-60">
                <Save className="w-4 h-4" /> {saving ? "Saving..." : "Save JSON"}
              </button>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {emptyTraining && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-600">
          This Brain was saved with 0 crawled pages. Fill it manually here or re-train after fixing the crawler/model issue.
        </div>
      )}

      <section className="border border-border rounded-md bg-card p-6 space-y-4">
        <h2 className="font-display text-xl font-bold flex items-center gap-2"><Building2 className="w-5 h-5 text-primary" /> Editable Brain</h2>
        <p className="text-sm text-muted-foreground">All fields are saved into the same Brain data used by Manager, Blogs, CRM receipts, and invoices.</p>
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {DOMAINS.map((domain) => (
          <section key={domain.key} className="border border-border rounded-md bg-card p-6 space-y-4" data-testid={`brain-domain-${domain.key}`}>
            <div className="text-xs uppercase tracking-[0.2em] font-bold text-primary">{domain.label}</div>
            <DomainEditor domain={domain} value={draft[domain.key] || {}} onChange={setDraft} />
          </section>
        ))}
      </div>
    </div>
  );
}
