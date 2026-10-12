import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft, BarChart3, CheckCircle2, Copy, Eye, FileText, FlaskConical, Inbox, Loader2, Mail, MessageSquareText,
  Palette, Phone, Plus, Save, Settings2, Sparkles, Tag, Trash2, User, Users, Zap,
} from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../../lib/api";
import { formatDateTime } from "../../lib/timezone";
import { Switch } from "../../components/ui/switch";
import CountryCodeSelect from "../../components/CountryCodeSelect";
import FormPreview from "../../components/landingForms/FormPreview";
import InstallPanel from "../../components/landingForms/InstallPanel";

const FIELD_META = [
  { key: "full_name", label: "Name", icon: User },
  { key: "email", label: "Email ID", icon: Mail },
  { key: "phone", label: "Phone number + country code", icon: Phone },
  { key: "requirement", label: "Requirement / Query", icon: MessageSquareText },
];
const UTM = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"];
const TABS = [
  { key: "fields", label: "Fields", icon: FileText },
  { key: "defaults", label: "Lead defaults", icon: Settings2 },
  { key: "design", label: "Design", icon: Palette },
  { key: "install", label: "Install", icon: Zap },
  { key: "submissions", label: "Submissions", icon: Inbox },
];
const ACCENTS = ["#4f46e5", "#0057a8", "#0ea5e9", "#059669", "#d97706", "#dc2626", "#db2777", "#111827"];
const RESULT_STYLE = {
  created: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400", duplicate: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  rejected: "bg-destructive/10 text-destructive", spam: "bg-muted text-muted-foreground", test: "bg-primary/10 text-primary",
};
const input = "h-10 w-full rounded-lg border bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30";

function Section({ title, description, children, icon: Icon }) {
  return (
    <section className="rounded-2xl border bg-card p-5">
      <h3 className="flex items-center gap-2 font-semibold">{Icon && <Icon className="h-4 w-4 text-primary" />}{title}</h3>
      {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function EmptyState({ onCreate, creating }) {
  const [name, setName] = useState("");
  const [country, setCountry] = useState("IN");
  return (
    <div className="overflow-hidden rounded-3xl border bg-gradient-to-br from-primary/10 via-card to-card">
      <div className="grid gap-8 p-6 sm:p-10 lg:grid-cols-[1.2fr_1fr]">
        <div>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary"><Sparkles className="h-3.5 w-3.5" />New connector</span>
          <h2 className="mt-4 text-2xl font-bold tracking-tight sm:text-3xl">Turn every landing page into a lead machine</h2>
          <p className="mt-3 text-muted-foreground">Capture name, email, phone with country code and requirement from any website. Leads land in your CRM with UTM tracking and get an instant AI qualification call.</p>
          <ul className="mt-5 space-y-2 text-sm">
            {["Works with WordPress, Webflow, Framer, Elementor or custom code", "Hidden UTM tracking — see which campaign brought each lead", "Duplicate protection and spam filtering built in"].map((t) => <li key={t} className="flex items-start gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />{t}</li>)}
          </ul>
        </div>
        <form onSubmit={(e) => { e.preventDefault(); onCreate({ name, default_country: country }); }} className="self-center rounded-2xl border bg-card p-5 shadow-sm">
          <p className="font-semibold">Create your first form</p>
          <label className="mt-4 block text-xs font-semibold">Form name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Diwali launch landing page" className={`${input} mt-1 font-normal`} /></label>
          <div className="mt-4 text-xs font-semibold">Default country code<div className="mt-1"><CountryCodeSelect value={country} onChange={setCountry} showName className="w-full" /></div></div>
          <button disabled={creating} className="mt-5 inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-primary text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60">{creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}Create form</button>
        </form>
      </div>
    </div>
  );
}

function Submissions({ wsId, formId, refreshKey }) {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    let live = true;
    api.get(`/workspaces/${wsId}/lead-forms/${formId}/submissions`).then(({ data }) => { if (live) setRows(data.items); }).catch(() => { if (live) setRows([]); });
    return () => { live = false; };
  }, [wsId, formId, refreshKey]);
  if (!rows) return <div className="grid h-40 place-items-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>;
  if (!rows.length) return <div className="rounded-2xl border border-dashed p-10 text-center text-sm text-muted-foreground"><Inbox className="mx-auto mb-3 h-8 w-8 opacity-50" />No submissions yet. Install the form or send a test lead.</div>;
  return (
    <div className="overflow-x-auto rounded-2xl border bg-card">
      <table className="w-full min-w-[640px] text-sm">
        <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground"><tr><th className="p-3 font-medium">When</th><th className="p-3 font-medium">Lead</th><th className="p-3 font-medium">Result</th><th className="p-3 font-medium">Campaign</th><th className="p-3" /></tr></thead>
        <tbody className="divide-y">
          {rows.map((r) => (
            <tr key={r.id} className="align-top">
              <td className="whitespace-nowrap p-3 text-xs text-muted-foreground">{formatDateTime(r.created_at)}</td>
              <td className="p-3"><div className="font-medium">{r.name || "—"}</div><div className="text-xs text-muted-foreground">{[r.phone, r.email].filter(Boolean).join(" · ")}</div>{r.error && <div className="mt-1 max-w-xs truncate text-xs text-destructive" title={r.error}>{r.error}</div>}</td>
              <td className="p-3"><span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold capitalize ${RESULT_STYLE[r.result] || "bg-muted"}`}>{r.result}</span></td>
              <td className="p-3 text-xs text-muted-foreground">{r.utm?.utm_source ? <><span className="font-medium text-foreground">{r.utm.utm_source}</span>{r.utm.utm_campaign ? ` / ${r.utm.utm_campaign}` : ""}</> : "Direct"}</td>
              <td className="p-3 text-right">{r.lead_id && <Link to={`/app/w/${wsId}/crm?lead=${r.lead_id}`} className="text-xs font-semibold text-primary hover:underline">Open lead</Link>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function LandingFormsWorkflow() {
  const { wsId } = useParams();
  const [forms, setForms] = useState(null);
  const [selectedId, setSelectedId] = useState("");
  const [draft, setDraft] = useState(null);
  const [tab, setTab] = useState("fields");
  const [saving, setSaving] = useState(false);
  const [creating, setCreating] = useState(false);
  const [testing, setTesting] = useState(false);
  const [crm, setCrm] = useState({ states: [], tags: [] });
  const [people, setPeople] = useState([]);
  const [subsKey, setSubsKey] = useState(0);

  const selected = useMemo(() => forms?.find((f) => f.id === selectedId) || null, [forms, selectedId]);
  const dirty = useMemo(() => selected && draft && JSON.stringify(pick(selected)) !== JSON.stringify(pick(draft)), [selected, draft]);

  const load = useCallback(async () => {
    const { data } = await api.get(`/workspaces/${wsId}/lead-forms`);
    setForms(data.items);
    setSelectedId((id) => (data.items.some((f) => f.id === id) ? id : data.items[0]?.id || ""));
  }, [wsId]);

  useEffect(() => {
    load().catch((e) => { toast.error(formatError(e.response?.data?.detail)); setForms([]); });
    api.get(`/workspaces/${wsId}/crm/settings`).then(({ data }) => setCrm({ states: data.states || [], tags: (data.tag_library || []).map((t) => t.label) })).catch(() => {});
    api.get(`/workspaces/${wsId}/crm/sales-team`).then(({ data }) => setPeople((data.items || []).filter((p) => p.role === "sales_agent" && p.active !== false))).catch(() => {});
  }, [wsId, load]);

  useEffect(() => { setDraft(selected ? structuredClone(selected) : null); }, [selected]);

  const replace = (doc) => setForms((list) => list.map((f) => (f.id === doc.id ? doc : f)));
  const patch = async (body, message) => {
    const { data } = await api.patch(`/workspaces/${wsId}/lead-forms/${selectedId}`, body);
    replace(data);
    if (message) toast.success(message);
    return data;
  };
  const save = async () => {
    setSaving(true);
    try { await patch(pick(draft), "Form saved"); }
    catch (e) { toast.error(formatError(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };
  const create = async (body = {}) => {
    setCreating(true);
    try {
      const { data } = await api.post(`/workspaces/${wsId}/lead-forms`, { name: body.name || `Landing page form ${(forms?.length || 0) + 1}`, default_country: body.default_country });
      setForms((list) => [data, ...(list || [])]); setSelectedId(data.id); setTab("fields");
      toast.success("Form created — customise it, then install it on your site");
    } catch (e) { toast.error(formatError(e.response?.data?.detail)); }
    finally { setCreating(false); }
  };
  const remove = async () => {
    if (!window.confirm(`Delete “${selected.name}”? Websites using it will stop sending leads. Existing leads stay in your CRM.`)) return;
    await api.delete(`/workspaces/${wsId}/lead-forms/${selectedId}`);
    toast.success("Form deleted");
    await load();
  };
  const toggleStatus = async (active) => {
    try { await patch({ status: active ? "active" : "paused" }, active ? "Form is live" : "Form paused"); }
    catch (e) { toast.error(formatError(e.response?.data?.detail)); }
  };
  const sendTest = async () => {
    setTesting(true);
    try {
      const { data } = await api.post(`/workspaces/${wsId}/lead-forms/${selectedId}/test`, {});
      toast.success("Test lead created in your CRM", { action: { label: "Open", onClick: () => window.open(`/app/w/${wsId}/crm?lead=${data.lead_id}`, "_self") } });
      await load(); setSubsKey((k) => k + 1);
    } catch (e) { toast.error(formatError(e.response?.data?.detail?.message || e.response?.data?.detail)); }
    finally { setTesting(false); }
  };
  const rotate = async () => {
    if (!window.confirm("Rotate this form's key? Update the snippet on your website or submissions will stop.")) return;
    const { data } = await api.post(`/workspaces/${wsId}/lead-forms/${selectedId}/rotate-key`);
    replace(data); toast.success("Key rotated — copy the new snippet");
  };

  const setField = (key, attr, value) => setDraft((d) => ({ ...d, fields: { ...d.fields, [key]: { ...d.fields[key], [attr]: value, ...(attr === "enabled" && !value ? { required: false } : {}) } } }));
  const setGroup = (group, attr, value) => setDraft((d) => ({ ...d, [group]: { ...d[group], [attr]: value } }));

  if (!forms) return <div className="grid min-h-[50vh] place-items-center"><Loader2 className="h-7 w-7 animate-spin text-primary" /></div>;

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 pb-28 sm:p-6 sm:pb-28">
      <Link to={`/app/w/${wsId}/workflows`} className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" />Back to Workflows</Link>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Landing Page Forms</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Add leads from any landing page. Each form captures contact details, requirement and hidden UTM parameters.</p>
        </div>
        {forms.length > 0 && <button type="button" onClick={() => create()} disabled={creating} className="inline-flex h-10 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60">{creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}New form</button>}
      </div>

      {forms.length === 0 ? <EmptyState onCreate={create} creating={creating} /> : (
        <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
          <nav aria-label="Forms" className="space-y-2">
            {forms.map((f) => (
              <button key={f.id} type="button" onClick={() => { if (dirty && !window.confirm("Discard unsaved changes?")) return; setSelectedId(f.id); }} className={`w-full rounded-xl border p-3.5 text-left transition ${f.id === selectedId ? "border-primary/50 bg-primary/5 ring-1 ring-primary/20" : "bg-card hover:border-primary/30"}`}>
                <div className="flex items-center gap-2"><span className={`h-2 w-2 shrink-0 rounded-full ${f.status === "active" ? "bg-emerald-500" : "bg-muted-foreground/40"}`} /><span className="truncate text-sm font-semibold">{f.name}</span></div>
                <div className="mt-1.5 flex gap-3 pl-4 text-xs text-muted-foreground"><span>{f.stats?.leads || 0} leads</span><span>{f.stats?.last_submission_at ? `Last ${formatDateTime(f.stats.last_submission_at)}` : "No submissions"}</span></div>
              </button>
            ))}
          </nav>

          {draft && (
            <div className="min-w-0 space-y-5">
              <div className="rounded-2xl border bg-card p-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} aria-label="Form name" className="w-full rounded-md bg-transparent px-1 -ml-1 text-xl font-bold hover:bg-accent/50 focus:bg-accent/50 focus:outline-none" />
                    <div className="mt-3 flex flex-wrap gap-2 text-xs">
                      {[[BarChart3, "Submissions", selected.stats?.submissions || 0], [Users, "Leads", selected.stats?.leads || 0], [Copy, "Repeat enquiries", selected.stats?.duplicates || 0]].map(([Icon, label, value]) => <span key={label} className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1"><Icon className="h-3.5 w-3.5 text-muted-foreground" /><span className="font-semibold tabular-nums">{value}</span><span className="text-muted-foreground">{label}</span></span>)}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <label className="inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium"><Switch checked={selected.status === "active"} onCheckedChange={toggleStatus} aria-label="Form active" />{selected.status === "active" ? "Live" : "Paused"}</label>
                    <button type="button" onClick={sendTest} disabled={testing} className="inline-flex h-10 items-center gap-1.5 rounded-lg border px-3 text-sm font-medium hover:bg-accent disabled:opacity-60">{testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <FlaskConical className="h-4 w-4" />}<span className="hidden sm:inline">Send test lead</span></button>
                    <button type="button" onClick={remove} aria-label="Delete form" className="grid h-10 w-10 place-items-center rounded-lg border text-muted-foreground hover:border-destructive/40 hover:text-destructive"><Trash2 className="h-4 w-4" /></button>
                  </div>
                </div>
              </div>

              <div role="tablist" aria-label="Form settings" className="flex gap-1 overflow-x-auto rounded-xl bg-muted p-1">
                {TABS.map((t) => <button key={t.key} role="tab" aria-selected={tab === t.key} type="button" onClick={() => setTab(t.key)} className={`inline-flex min-w-fit flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition ${tab === t.key ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}><t.icon className="h-4 w-4" />{t.label}</button>)}
              </div>

              <div className={`grid gap-5 ${["fields", "design", "defaults"].includes(tab) ? "xl:grid-cols-[1fr_340px]" : ""}`}>
                <div className="min-w-0 space-y-5">
                  {tab === "fields" && <>
                    <Section title="Form fields" description="Choose what visitors see and what's required. Phone is always required so your AI can call the lead." icon={FileText}>
                      <div className="divide-y rounded-xl border">
                        {FIELD_META.map(({ key, label, icon: Icon }) => {
                          const cfg = draft.fields[key];
                          return (
                            <div key={key} className={`space-y-3 p-4 ${cfg.enabled ? "" : "bg-muted/30"}`}>
                              <div className="flex flex-wrap items-center gap-3">
                                <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary/10 text-primary"><Icon className="h-4 w-4" /></span>
                                <span className="flex-1 text-sm font-semibold">{label}</span>
                                <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">Show<Switch checked={cfg.enabled} disabled={key === "phone"} onCheckedChange={(v) => setField(key, "enabled", v)} aria-label={`Show ${label}`} /></label>
                                <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">Required<Switch checked={cfg.required} disabled={key === "phone" || !cfg.enabled} onCheckedChange={(v) => setField(key, "required", v)} aria-label={`${label} required`} /></label>
                              </div>
                              {cfg.enabled && (
                                <div className={`grid gap-3 ${key === "phone" ? "sm:grid-cols-3" : "sm:grid-cols-2"}`}>
                                  <label className="text-xs font-medium text-muted-foreground">Label<input value={cfg.label} onChange={(e) => setField(key, "label", e.target.value)} className={`${input} mt-1 text-foreground`} /></label>
                                  <label className="text-xs font-medium text-muted-foreground">Placeholder<input value={cfg.placeholder || ""} onChange={(e) => setField(key, "placeholder", e.target.value)} className={`${input} mt-1 text-foreground`} /></label>
                                  {key === "phone" && <div className="text-xs font-medium text-muted-foreground">Default country<div className="mt-1"><CountryCodeSelect value={cfg.default_country} onChange={(v) => setField("phone", "default_country", v)} showName className="w-full text-foreground" /></div></div>}
                                </div>
                              )}
                            </div>
                          );
                        })}
                        <div className="flex flex-wrap items-center gap-3 bg-muted/20 p-4">
                          <span className="grid h-8 w-8 place-items-center rounded-lg bg-muted text-muted-foreground"><Eye className="h-4 w-4" /></span>
                          <div className="flex-1"><p className="text-sm font-semibold">UTM parameters <span className="ml-1 rounded bg-muted px-1.5 py-0.5 text-[10px] font-bold uppercase text-muted-foreground">Hidden</span></p><p className="text-xs text-muted-foreground">Captured automatically from the page URL, plus page URL, referrer, gclid and fbclid.</p></div>
                          <div className="flex flex-wrap gap-1">{UTM.map((u) => <code key={u} className="rounded bg-background px-1.5 py-0.5 text-[10px] text-muted-foreground ring-1 ring-border">{u}</code>)}</div>
                        </div>
                      </div>
                    </Section>
                  </>}

                  {tab === "defaults" && <>
                    <Section title="New lead settings" description="Optional defaults applied to every lead from this form." icon={Settings2}>
                      <div className="grid gap-4 sm:grid-cols-2">
                        <label className="text-xs font-semibold">Lead source label<input value={draft.defaults.source_label} onChange={(e) => setGroup("defaults", "source_label", e.target.value)} className={`${input} mt-1 font-normal`} /></label>
                        <label className="text-xs font-semibold">Pipeline stage<select value={draft.defaults.status} onChange={(e) => setGroup("defaults", "status", e.target.value)} className={`${input} mt-1 font-normal`}>{(crm.states.length ? crm.states : [{ key: "new", label: "New" }]).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</select></label>
                        <label className="text-xs font-semibold">Assign to<select value={draft.defaults.assign_to || ""} onChange={(e) => setGroup("defaults", "assign_to", e.target.value)} className={`${input} mt-1 font-normal`}><option value="">Nobody (unassigned)</option>{people.length > 0 && <option value="round_robin">Round-robin across sales team</option>}{people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
                        <label className="text-xs font-semibold">Repeat submissions<select value={draft.defaults.dedupe_days} onChange={(e) => setGroup("defaults", "dedupe_days", Number(e.target.value))} className={`${input} mt-1 font-normal`}>{[[0, "Always create a new lead"], [7, "Update lead if seen in last 7 days"], [30, "Update lead if seen in last 30 days"], [90, "Update lead if seen in last 90 days"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
                      </div>
                      <div className="mt-5">
                        <p className="flex items-center gap-1.5 text-xs font-semibold"><Tag className="h-3.5 w-3.5" />Tags</p>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {crm.tags.map((t) => { const on = draft.defaults.tags.includes(t); return <button key={t} type="button" aria-pressed={on} onClick={() => setGroup("defaults", "tags", on ? draft.defaults.tags.filter((x) => x !== t) : [...draft.defaults.tags, t])} className={`rounded-full border px-3 py-1 text-xs font-medium ${on ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent"}`}>{t}</button>; })}
                          {crm.tags.length === 0 && <span className="text-xs text-muted-foreground">No tags in your CRM yet.</span>}
                        </div>
                      </div>
                      <label className="mt-5 flex items-start justify-between gap-4 rounded-xl border bg-background p-4">
                        <span><span className="flex items-center gap-1.5 text-sm font-semibold"><Phone className="h-4 w-4 text-primary" />Trigger AI qualification call</span><span className="mt-0.5 block text-xs text-muted-foreground">Your voice agent calls new leads using your Qualification calling settings.</span></span>
                        <Switch checked={draft.defaults.trigger_ai_call} onCheckedChange={(v) => setGroup("defaults", "trigger_ai_call", v)} aria-label="Trigger AI qualification call" />
                      </label>
                    </Section>
                    <Section title="After submit" description="What visitors see once they submit." icon={CheckCircle2}>
                      <div className="grid gap-2 sm:grid-cols-2">
                        {[["message", "Show a thank-you message"], ["redirect", "Redirect to a page"]].map(([v, l]) => <label key={v} className={`flex cursor-pointer items-center gap-2.5 rounded-xl border p-3 text-sm ${draft.after_submit.mode === v ? "border-primary bg-primary/5" : ""}`}><input type="radio" name="after" checked={draft.after_submit.mode === v} onChange={() => setGroup("after_submit", "mode", v)} className="accent-[hsl(var(--primary))]" />{l}</label>)}
                      </div>
                      {draft.after_submit.mode === "message"
                        ? <textarea rows={2} value={draft.after_submit.message} onChange={(e) => setGroup("after_submit", "message", e.target.value)} aria-label="Thank-you message" className="mt-3 w-full rounded-lg border bg-background px-3 py-2 text-sm" />
                        : <input value={draft.after_submit.redirect_url} onChange={(e) => setGroup("after_submit", "redirect_url", e.target.value)} placeholder="https://yoursite.com/thank-you" aria-label="Redirect URL" className={`${input} mt-3`} />}
                    </Section>
                  </>}

                  {tab === "design" && (
                    <Section title="Design" description="Applies to the embed script form." icon={Palette}>
                      <div className="grid gap-4 sm:grid-cols-2">
                        <label className="text-xs font-semibold sm:col-span-2">Heading<input value={draft.appearance.title} onChange={(e) => setGroup("appearance", "title", e.target.value)} className={`${input} mt-1 font-normal`} /></label>
                        <label className="text-xs font-semibold sm:col-span-2">Subheading<input value={draft.appearance.subtitle} onChange={(e) => setGroup("appearance", "subtitle", e.target.value)} className={`${input} mt-1 font-normal`} /></label>
                        <label className="text-xs font-semibold">Button text<input value={draft.appearance.button_label} onChange={(e) => setGroup("appearance", "button_label", e.target.value)} className={`${input} mt-1 font-normal`} /></label>
                        <div className="text-xs font-semibold">Theme<div className="mt-1 grid grid-cols-2 gap-1 rounded-lg bg-muted p-1">{["light", "dark"].map((t) => <button key={t} type="button" onClick={() => setGroup("appearance", "theme", t)} className={`rounded-md py-1.5 text-xs font-medium capitalize ${draft.appearance.theme === t ? "bg-card shadow-sm" : "text-muted-foreground"}`}>{t}</button>)}</div></div>
                        <div className="text-xs font-semibold sm:col-span-2">Accent colour
                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            {ACCENTS.map((c) => <button key={c} type="button" aria-label={`Accent ${c}`} onClick={() => setGroup("appearance", "accent_color", c)} className={`h-8 w-8 rounded-full ring-offset-2 ring-offset-card ${draft.appearance.accent_color === c ? "ring-2 ring-foreground" : ""}`} style={{ background: c }} />)}
                            <label className="inline-flex items-center gap-2 rounded-lg border px-2 py-1 font-normal"><input type="color" value={draft.appearance.accent_color} onChange={(e) => setGroup("appearance", "accent_color", e.target.value)} className="h-6 w-6 cursor-pointer rounded border-0 bg-transparent p-0" aria-label="Custom accent colour" /><span className="font-mono text-xs">{draft.appearance.accent_color}</span></label>
                          </div>
                        </div>
                        <label className="flex items-center justify-between gap-3 rounded-xl border bg-background p-3 text-sm sm:col-span-2">Rounded corners<Switch checked={draft.appearance.rounded !== false} onCheckedChange={(v) => setGroup("appearance", "rounded", v)} aria-label="Rounded corners" /></label>
                      </div>
                    </Section>
                  )}

                  {tab === "install" && <InstallPanel form={draft} onOriginsChange={(origins) => setDraft({ ...draft, allowed_origins: origins })} onRotate={rotate} />}
                  {tab === "submissions" && <Submissions wsId={wsId} formId={selectedId} refreshKey={subsKey} />}
                </div>

                {["fields", "design", "defaults"].includes(tab) && (
                  <aside className="xl:sticky xl:top-20 xl:self-start">
                    <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground"><Eye className="h-3.5 w-3.5" />Live preview</p>
                    <div className="rounded-2xl border bg-[radial-gradient(hsl(var(--border))_1px,transparent_1px)] p-4 [background-size:14px_14px]"><FormPreview form={draft} /></div>
                  </aside>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {dirty && (
        <div className="fixed inset-x-0 bottom-0 z-40 border-t bg-card/95 backdrop-blur">
          <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-3 sm:px-6">
            <p className="text-sm text-muted-foreground">You have unsaved changes</p>
            <div className="flex gap-2">
              <button type="button" onClick={() => setDraft(structuredClone(selected))} className="h-10 rounded-lg px-4 text-sm hover:bg-accent">Discard</button>
              <button type="button" onClick={save} disabled={saving} className="inline-flex h-10 items-center gap-2 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground disabled:opacity-60">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}Save changes</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function pick(form) {
  if (!form) return null;
  const { name, fields, defaults, appearance, after_submit, allowed_origins } = form;
  return { name, fields, defaults, appearance, after_submit, allowed_origins };
}
