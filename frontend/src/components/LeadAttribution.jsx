import { Globe, Megaphone } from "lucide-react";
import { formatDateTime } from "../lib/timezone";

const LABELS = [["utm_source", "Source"], ["utm_medium", "Medium"], ["utm_campaign", "Campaign"], ["utm_term", "Term"], ["utm_content", "Content"], ["gclid", "Google click ID"], ["fbclid", "Facebook click ID"]];

function Touch({ title, data }) {
  const rows = LABELS.filter(([key]) => data?.[key]);
  if (!rows.length && !data?.landing_page) return null;
  return (
    <div className="rounded-md border bg-background p-3">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</p>
      <dl className="mt-2 grid grid-cols-2 gap-2 text-xs">
        {rows.map(([key, label]) => <div key={key} className="min-w-0"><dt className="text-muted-foreground">{label}</dt><dd className="mt-0.5 break-words font-medium">{data[key]}</dd></div>)}
        {data.landing_page && <div className="col-span-2 min-w-0"><dt className="text-muted-foreground">Landing page</dt><dd className="mt-0.5 break-all">{data.landing_page}</dd></div>}
      </dl>
    </div>
  );
}

/** Landing page form source and UTM attribution for a CRM lead. */
export default function LeadAttribution({ lead }) {
  const utm = lead.utm;
  if (!utm && !lead.form_id) return null;
  const pageUrl = lead.landing_page_url || utm?.page_url;
  return (
    <details className="rounded-lg border p-3" open>
      <summary className="cursor-pointer text-sm font-semibold">Source attribution{lead.form_name ? ` · ${lead.form_name}` : ""}</summary>
      <div className="mt-3 space-y-3">
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-2.5 py-1 font-medium text-primary"><Megaphone className="h-3.5 w-3.5" />{utm?.utm_source ? `${utm.utm_source}${utm.utm_medium ? ` / ${utm.utm_medium}` : ""}` : "Direct / organic"}</span>
          {utm?.utm_campaign && <span className="rounded-full bg-muted px-2.5 py-1">Campaign: <span className="font-medium">{utm.utm_campaign}</span></span>}
          {lead.phone_country_code && <span className="rounded-full bg-muted px-2.5 py-1">Country code {lead.phone_country_code}</span>}
        </div>
        {pageUrl && <p className="flex items-start gap-1.5 text-xs"><Globe className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" /><a href={pageUrl} target="_blank" rel="noreferrer noopener" className="break-all text-primary hover:underline">{pageUrl}</a></p>}
        {utm?.referrer && <p className="break-all text-xs text-muted-foreground">Referrer: {utm.referrer}</p>}
        <div className="grid gap-2 sm:grid-cols-2">
          <Touch title="This visit" data={utm} />
          <Touch title="First visit" data={utm?.first_touch} />
          {lead.utm_last_touch && <Touch title={`Latest re-submission${lead.utm_last_touch.captured_at ? ` · ${formatDateTime(lead.utm_last_touch.captured_at)}` : ""}`} data={lead.utm_last_touch} />}
        </div>
      </div>
    </details>
  );
}
