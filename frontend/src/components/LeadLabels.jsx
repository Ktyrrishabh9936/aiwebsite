import { useState } from "react";
import api, { formatError } from "../lib/api";
import { defaultTagLibrary, tagColor, tagColors } from "../lib/leadTags";

export function LeadTagBadges({ tags = [], library = defaultTagLibrary }) {
  return <div className="flex flex-wrap gap-1.5">{tags.map((tag) => <span key={tag} className={`rounded border px-2 py-1 text-[11px] uppercase break-words max-w-full ${tagColors[tagColor(tag, library)]}`}>{tag}</span>)}</div>;
}

export default function LeadLabels({ wsId, lead, onUpdated, disabled = false, library = defaultTagLibrary, onLibraryUpdated = () => {} }) {
  const [draft, setDraft] = useState("");
  const [color, setColor] = useState("blue");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const tags = lead.tags || [];
  async function save(body) {
    if (busy || disabled) return false;
    setBusy(true); setError("");
    try {
      const { data } = await api.patch(`/workspaces/${wsId}/crm/leads/${lead.id}/labels`, body);
      onUpdated(data);
      return true;
    } catch (error) { setError(formatError(error.response?.data?.detail || error.message)); return false; }
    finally { setBusy(false); }
  }
  async function addTags() {
    const additions = draft.split(",").map((tag) => tag.trim()).filter(Boolean);
    if (!additions.length || busy || disabled) return;
    if (await updateLibrary(additions, color) && await save({ tags: [...tags, ...additions] })) setDraft("");
  }
  async function updateLibrary(names, newColor) {
    setBusy(true); setError("");
    try {
      const { data } = await api.put(`/workspaces/${wsId}/crm/tag-library`, { names, color: newColor });
      onLibraryUpdated(data.tags);
      return true;
    } catch (error) { setError(formatError(error.response?.data?.detail || error.message)); return false; }
    finally { setBusy(false); }
  }
  return <section className="rounded-lg border bg-background p-3 space-y-3" aria-label="Lead tags and customer relationship">
    <label className="flex items-start gap-3"><input type="checkbox" aria-label="Existing customer" checked={lead.customer_status === "customer"} disabled={busy || disabled} onChange={(event) => save({ customer_status: event.target.checked ? "customer" : "lead" })} className="mt-1 h-4 w-4" /><span><span className="block text-sm font-semibold">Customer</span><span className="block text-xs text-muted-foreground mt-1">This relationship is separate from the lead stage. A customer can also be a New lead for another enquiry.</span></span></label>
    <div><h4 className="text-sm font-semibold mb-2">Tags on this lead</h4><div className="flex flex-wrap gap-2">{tags.map((tag) => <span key={tag} className={`inline-flex items-center gap-1 rounded border pl-3 text-xs ${tagColors[tagColor(tag, library)]}`}><span className="break-words">{tag}</span><select aria-label={`Color for tag ${tag}`} title="Color applies to this tag across the workspace" value={tagColor(tag, library)} disabled={busy || disabled} onChange={(event) => updateLibrary([tag], event.target.value)} className="max-w-20 h-9 rounded bg-background text-foreground text-[10px]">{Object.keys(tagColors).map((name) => <option key={name} value={name}>{name}</option>)}</select><button type="button" aria-label={`Remove tag ${tag}`} disabled={busy || disabled} onClick={() => save({ tags: tags.filter((item) => item !== tag) })} className="h-9 w-9 rounded hover:bg-accent disabled:opacity-40">×</button></span>)}</div></div>
    <div><h4 className="text-sm font-semibold mb-2">Reusable tags</h4><div className="flex flex-wrap gap-2">{library.map((item) => {
      const applied = tags.some((tag) => tag.toLowerCase() === item.label.toLowerCase());
      return <button key={item.label} type="button" aria-label={`Toggle tag ${item.label}`} aria-pressed={applied} disabled={busy || disabled} onClick={() => save({ tags: applied ? tags.filter((tag) => tag.toLowerCase() !== item.label.toLowerCase()) : [...tags, item.label] })} className={`min-h-9 rounded border px-3 py-1 text-xs disabled:opacity-40 ${tagColors[item.color] || tagColors.slate} ${applied ? "ring-1 ring-current" : ""}`}>{applied && "✓ "}{item.label}</button>;
    })}</div></div>
    <label className="flex items-center gap-2 text-xs text-muted-foreground">New tag color<select aria-label="New tag color" disabled={busy || disabled} value={color} onChange={(event) => setColor(event.target.value)} className="h-9 px-2 rounded border bg-background text-foreground">{Object.keys(tagColors).map((name) => <option key={name} value={name}>{name}</option>)}</select></label>
    <div className="flex gap-2"><input aria-label="Add lead tags" placeholder="VIP, repeat enquiry, interested in 3 BHK" maxLength={2550} value={draft} disabled={busy || disabled} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addTags(); } }} className="min-w-0 flex-1 h-10 rounded-lg border bg-background px-3 text-sm" /><button type="button" disabled={busy || disabled || !draft.trim()} onClick={addTags} className="h-10 px-3 rounded-lg border hover:bg-accent text-sm disabled:opacity-40">Add tags</button></div>
    <p className="text-xs text-muted-foreground">Pick reusable tags above, or create your own with a color. Separate multiple names with commas. Tag colors are shared across this workspace. Changes save automatically.</p>
    {busy && <p role="status" className="text-xs text-muted-foreground">Saving labels...</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </section>;
}
