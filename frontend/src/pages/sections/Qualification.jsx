import { useCallback, useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { toast } from "sonner";
import api from "../../lib/api";

const inputClass = "w-full rounded-md border bg-background px-3 py-2 text-sm";
const buttonClass = "rounded-md border px-3 py-2 text-sm hover:bg-accent disabled:opacity-50";
const ruleGroups = { mandatory_qualification_criteria: "Mandatory rules (all must pass)", disqualification_criteria: "Disqualifying rules (any match stops qualification)", qualification_criteria: "Product fit criteria", special_rules: "Additional mandatory rules" };
const sample = { product_fit: true, eligibility: true, buying_intent: "high", purchase_timeline: "immediate", decision_maker_status: "decision_maker" };
export function qualificationError(error) {
  const detail = error.response?.data?.detail;
  return Array.isArray(detail) ? detail.map((e) => `${e.loc?.slice(1).join(".")}: ${e.msg}`).join("; ") : typeof detail === "string" ? detail : error.message || "Request failed";
}
function Field({ label, children }) { return <label className="block space-y-1 text-sm"><span className="text-muted-foreground">{label}</span>{children}</label>; }
function RuleList({ title, rules, onChange }) {
  const set = (index, field, value) => onChange(rules.map((r, i) => i === index ? { ...r, [field]: value } : r));
  return <section className="space-y-2"><h3 className="font-semibold text-sm">{title}</h3>{rules.map((rule, i) => <div key={i} className="rounded-lg border p-3 grid sm:grid-cols-3 gap-2">
    <Field label="Fact"><input className={inputClass} value={rule.field} placeholder="budget.value or attributes.seats" onChange={(e) => set(i, "field", e.target.value)} /></Field>
    <Field label="Comparison"><select className={inputClass} value={rule.operator} onChange={(e) => set(i, "operator", e.target.value)}>{["eq", "ne", "gte", "lte", "gt", "lt", "contains", "in", "exists"].map((op) => <option key={op}>{op}</option>)}</select></Field>
    <Field label="Value (text, number, true/false or JSON list)"><input className={inputClass} value={typeof rule.value === "string" ? rule.value : JSON.stringify(rule.value)} onChange={(e) => { let v = e.target.value; try { v = JSON.parse(v); } catch {} set(i, "value", v); }} /></Field>
    <Field label="Reason"><input className={inputClass} value={rule.reason || ""} onChange={(e) => set(i, "reason", e.target.value)} /></Field><button type="button" className={`${buttonClass} self-end`} onClick={() => onChange(rules.filter((_, j) => j !== i))}>Remove rule</button>
  </div>)}<button type="button" className={buttonClass} onClick={() => onChange([...rules, { field: "product_fit", operator: "eq", value: true, reason: "" }])}>Add rule</button></section>;
}

export default function Qualification() {
  const { ws, refresh } = useOutletContext();
  const base = `/workspaces/${ws.id}/crm/qualification`;
  const [catalog, setCatalog] = useState(null);
  const [draft, setDraft] = useState(null);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [facts, setFacts] = useState(JSON.stringify(sample, null, 2));
  const [outcome, setOutcome] = useState("CONNECTED");
  const [preview, setPreview] = useState(null);
  const load = useCallback(async () => {
    try { const { data } = await api.get(`${base}/profiles`); setCatalog(data); return data; }
    catch (e) { setError(qualificationError(e)); return null; }
  }, [base]);
  useEffect(() => { setCatalog(null); setDraft(null); setSelected(""); setError(""); load().then((data) => { if (data) setDraft(data.template); }); }, [load]);
  const set = (key, value) => { setDraft((d) => ({ ...d, [key]: value })); setPreview(null); };
  const choose = (id) => {
    const source = catalog.profiles.find((p) => p.id === id) || catalog.template;
    setSelected(id); setDraft(Object.fromEntries(Object.keys(catalog.template).map((key) => [key, source[key] ?? catalog.template[key]]))); setPreview(null); setError("");
  };
  const save = async (makeDefault = false) => {
    setBusy(true); setError("");
    try {
      const { data } = selected ? await api.put(`${base}/profiles/${selected}`, draft) : await api.post(`${base}/profiles`, draft);
      // Remember a successful save even if setting the default fails afterward.
      setSelected(data.id);
      setCatalog((current) => ({ ...current, profiles: [data, ...current.profiles.filter((p) => p.id !== data.id)] }));
      setDraft(Object.fromEntries(Object.keys(catalog.template).map((key) => [key, data[key] ?? catalog.template[key]])));
      if (makeDefault) await api.post(`${base}/profiles/${data.id}/default`);
      await load(); await refresh(); toast.success(makeDefault ? "Profile saved as workspace default" : "Qualification profile saved");
    } catch (e) { setError(qualificationError(e)); }
    finally { setBusy(false); }
  };
  const test = async () => {
    setBusy(true); setError("");
    try { const { data } = await api.post(`${base}/preview`, { profile: draft, call: { provider: "preview", provider_call_id: "preview", lead_id: "preview", outcome_hint: outcome, extracted_data: JSON.parse(facts) } }); setPreview(data); }
    catch (e) { setError(qualificationError(e)); } finally { setBusy(false); }
  };
  return <div className="p-5 sm:p-8 max-w-6xl mx-auto space-y-6">
    <div><Link to={`/app/w/${ws.id}/agents`} className="text-sm text-primary">AI Agents</Link><h1 className="text-3xl font-bold mt-2">Lead qualification</h1><p className="text-muted-foreground text-sm mt-2">Plivo runs the call. Arevei evaluates the facts, applies your rules, and updates the CRM.</p></div>
    {error && <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">{error}</p>}
    {!catalog && <button className={buttonClass} onClick={() => load().then((data) => { if (data) setDraft(data.template); })}>Load qualification profiles</button>}
    {catalog && draft && <>
      <section className="border rounded-xl p-5 bg-card space-y-3"><Field label="Product / campaign profile"><select className={inputClass} disabled={busy} value={selected} onChange={(e) => choose(e.target.value)}><option value="">New profile</option>{catalog.profiles.map((p) => <option key={p.id} value={p.id}>{p.product_name}{catalog.default_profile_id === p.id ? " (workspace default)" : ""}</option>)}</select></Field><p className="text-xs text-muted-foreground">Selection order: lead override, campaign profile, workspace default. Calls keep a snapshot of the profile used.</p><p className="text-xs text-muted-foreground">Webhook authentication: {catalog.callback_authentication}. This indicates configuration, not a successful live call.</p>{!catalog.default_profile_id && <p className="text-sm text-amber-600">Set a default profile to enable automatic qualification for leads without an assigned campaign profile. Until then, connected calls require review.</p>}
      {catalog.legacy_config?.criteria?.length > 0 && <details className="text-sm"><summary className="cursor-pointer">Previous rules to review</summary><p className="my-2 text-muted-foreground">Your previous text rules are preserved here. Recreate them as explicit comparisons below, then save a default profile. They are not applied by the new engine.</p><pre className="text-xs overflow-auto p-3 bg-secondary rounded">{JSON.stringify(catalog.legacy_config, null, 2)}</pre></details>}</section>
      <div className="grid lg:grid-cols-[1fr_320px] gap-6 items-start">
        <fieldset disabled={busy} className="border rounded-xl bg-card p-5 space-y-5 min-w-0">
          <h2 className="font-semibold">Product and rules</h2>
          <div className="grid sm:grid-cols-2 gap-3">{[["product_name", "Product / service name"], ["campaign_id", "Campaign ID (optional)"], ["product_description", "Description"], ["target_customer", "Target customer"]].map(([key, label]) => <Field key={key} label={label}><input className={inputClass} value={draft[key] || ""} onChange={(e) => set(key, e.target.value || (key === "campaign_id" ? null : ""))} /></Field>)}</div>
          <div className="grid sm:grid-cols-3 gap-3">{["min", "max", "currency"].map((key) => <Field key={key} label={`Price ${key}`}><input className={inputClass} type={key === "currency" ? "text" : "number"} value={draft.price_range[key] ?? ""} onChange={(e) => set("price_range", { ...draft.price_range, [key]: e.target.value === "" ? null : key === "currency" ? e.target.value : Number(e.target.value) })} /></Field>)}</div>
          <Field label="Service locations (comma separated; exact matches)"><input className={inputClass} value={draft.service_locations.join(",")} onChange={(e) => set("service_locations", e.target.value ? e.target.value.split(",") : [])} /></Field>
          <Field label="Required facts (comma separated)"><input className={inputClass} value={draft.required_information.join(",")} onChange={(e) => set("required_information", e.target.value ? e.target.value.split(",") : [])} /></Field>
          <p className="text-xs text-muted-foreground">Unknown facts stay unknown. A failed mandatory rule blocks qualification regardless of score. A minimum price requires a known budget in the same currency.</p>
          {Object.entries(ruleGroups).map(([key, title]) => <RuleList key={key} title={title} rules={draft[key]} onChange={(value) => set(key, value)} />)}
          <details className="space-y-3"><summary className="cursor-pointer font-semibold text-sm">Scoring weights and thresholds</summary><div className="grid sm:grid-cols-2 gap-3">{Object.entries(draft.weights).map(([key, value]) => <Field key={key} label={key.replaceAll("_", " ")}><input type="number" min="0" max="100" className={inputClass} value={value} onChange={(e) => set("weights", { ...draft.weights, [key]: Number(e.target.value) })} /></Field>)}{["qualified_threshold", "sales_ready_threshold"].map((key) => <Field key={key} label={key.replaceAll("_", " ")}><input type="number" className={inputClass} value={draft[key]} onChange={(e) => set(key, Number(e.target.value))} /></Field>)}</div><p className="text-xs text-muted-foreground">Weights must total 100. Intent: high / medium / low. Timeline: immediate / soon / later. Decision: decision_maker / shared / not_decision_maker.</p></details>
          <div className="flex flex-wrap gap-2"><button type="button" className={buttonClass} onClick={() => save(false)}>Save profile</button><button type="button" className="rounded-md bg-primary text-primary-foreground px-3 py-2 text-sm disabled:opacity-50" onClick={() => save(true)}>Save as workspace default</button></div>
        </fieldset>
        <div className="space-y-5 min-w-0">
          <fieldset disabled={busy} className="border rounded-xl bg-card p-5 space-y-3"><h2 className="font-semibold">Actions and retries</h2><Field label="Action when qualified"><select className={inputClass} value={draft.desired_next_action} onChange={(e) => set("desired_next_action", e.target.value)}>{draft.available_next_actions.map((action) => <option key={action}>{action}</option>)}</select></Field><Field label="Available actions (comma separated)"><input className={inputClass} value={draft.available_next_actions.join(",")} onChange={(e) => set("available_next_actions", e.target.value.split(","))} /></Field><Field label="Maximum call attempts"><input className={inputClass} type="number" min="1" max="20" value={draft.retry.max_attempts} onChange={(e) => set("retry", { ...draft.retry, max_attempts: Number(e.target.value) })} /></Field>{["NO_ANSWER", "BUSY", "SWITCHED_OFF", "UNREACHABLE", "TECHNICAL_ISSUE", "DROPPED_CALL"].map((outcome) => <Field key={outcome} label={`${outcome.replaceAll("_", " ")} delay (minutes)`}><input className={inputClass} type="number" min="1" placeholder="No automatic retry" value={draft.retry.retry_rules.find((r) => r.outcome === outcome)?.delay_minutes ?? ""} onChange={(e) => set("retry", { ...draft.retry, retry_rules: [...draft.retry.retry_rules.filter((r) => r.outcome !== outcome), ...(e.target.value ? [{ outcome, delay_minutes: Number(e.target.value) }] : [])] })} /></Field>)}<p className="text-xs text-muted-foreground">Retries use the CRM calling window and workflow switch. Sales actions create reviewable tasks. DND always blocks future calls.</p></fieldset>
          <section className="border rounded-xl bg-card p-5 space-y-3"><h2 className="font-semibold">Test your rules</h2><p className="text-xs text-muted-foreground">Preview only. No call, AI request, task, or CRM update.</p><Field label="Call outcome"><select className={inputClass} value={outcome} onChange={(e) => setOutcome(e.target.value)}>{["CONNECTED", "NO_ANSWER", "BUSY", "INVALID_NUMBER", "CALLBACK_REQUESTED", "DND_REQUESTED"].map((v) => <option key={v}>{v}</option>)}</select></Field><Field label="Sample facts (JSON)"><textarea className={`${inputClass} font-mono text-xs`} rows={10} value={facts} onChange={(e) => setFacts(e.target.value)} /></Field><button disabled={busy} className={buttonClass} onClick={test}>Preview decision</button>{preview && <div role="status" className="text-sm space-y-2"><strong>{preview.lead_status.replaceAll("_", " ")}</strong><p>Score: {preview.qualification_score ?? "Not scored"} · {preview.lead_temperature || "No temperature"}</p><p>{preview.disqualification_reason || preview.qualification_reason}</p><p>Next: {preview.next_action}</p>{preview.missing_information.length > 0 && <p>Missing: {preview.missing_information.join(", ")}</p>}</div>}</section>
        </div>
      </div>
    </>}
  </div>;
}
