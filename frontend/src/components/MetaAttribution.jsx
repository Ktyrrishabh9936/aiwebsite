import { useState } from "react";
import api, { formatError } from "../lib/api";
import { META_FIELDS as fields } from "../lib/metaFields";

export default function MetaAttribution({ lead, wsId, onUpdate }) {
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState("");
  const hasAttribution = fields.some(([key]) => lead[key] != null && lead[key] !== "");
  const retry = async () => {
    setRetrying(true); setError("");
    try {
      const result = await api.post(`/google/workspaces/${wsId}/leads/${lead.id}/retry`);
      onUpdate(result.data);
    } catch (err) { setError(formatError(err)); }
    finally { setRetrying(false); }
  };
  return (
    <details open={!hasAttribution} className="rounded-lg border p-3">
      <summary className="cursor-pointer text-sm font-semibold">Meta Attribution{lead.google_sheet_sync_status ? ` · Sheet sync: ${lead.google_sheet_sync_status}` : ""}</summary>
      {!hasAttribution && <p className="mt-3 text-xs text-muted-foreground">No Meta data has been imported for this lead. <a className="underline text-primary" href={`/app/w/${wsId}/workflows/ads-to-crm`}>Configure Google Sheet mapping</a> to import the Meta Lead ID, campaign, ad set, ad, and form information. Custom form answers use your normal CRM fields.</p>}
      <dl className="grid grid-cols-2 gap-3 mt-3 text-xs">
        {fields.map(([key, label]) => <div key={key}><dt className="text-muted-foreground">{label}</dt><dd className="break-words mt-1">{lead[key] == null || lead[key] === "" ? "—" : typeof lead[key] === "boolean" ? (lead[key] ? "Yes" : "No") : String(lead[key])}</dd></div>)}
        <div><dt className="text-muted-foreground">Last successful Sheet sync</dt><dd>{lead.last_google_sheet_sync_at ? new Date(lead.last_google_sheet_sync_at).toLocaleString() : "—"}</dd></div>
      </dl>
      {lead.google_sheet_sync_error && <p className="mt-3 text-xs text-destructive" role="alert">{lead.google_sheet_sync_error}</p>}
      {["failed", "pending"].includes(lead.google_sheet_sync_status) && <button onClick={retry} disabled={retrying} className="mt-3 text-xs underline">{retrying ? "Retrying…" : "Retry Sheet sync"}</button>}
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
    </details>
  );
}
