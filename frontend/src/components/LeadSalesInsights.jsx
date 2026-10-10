import { useEffect, useState } from "react";
import { Brain } from "lucide-react";
import api from "../lib/api";

export default function LeadSalesInsights({ wsId, leadId }) {
  const [insight, setInsight] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController(); setInsight(null); setError("");
    const load = async () => {
      try { const { data } = await api.get(`/workspaces/${wsId}/sales/leads/${leadId}/insights`, { signal: controller.signal }); if (!controller.signal.aborted) { setInsight(data); setError(""); } }
      catch { if (!controller.signal.aborted) setError("Lead insights are unavailable. Your CRM actions remain available."); }
    };
    load(); const timer = setInterval(() => { if (!document.hidden) load(); }, 30000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [wsId, leadId]);
  return <section className="rounded-xl border border-primary/20 bg-primary/5 p-5 space-y-4 max-h-[60dvh] overflow-y-auto" aria-label="AI Manager lead insights"><h4 className="text-lg font-bold flex gap-2 items-center"><Brain size={16} className="text-primary"/>AI Manager Insights</h4>
    {error ? <p role="status" className="text-base leading-relaxed text-muted-foreground">{error}</p> : !insight ? <p className="text-base leading-relaxed text-muted-foreground">Reviewing recorded activity...</p> : <><p className="text-base leading-relaxed font-medium">{insight.next_action}</p>{insight.signals.map(s => <p key={s.code} className="text-base leading-relaxed text-muted-foreground">{s.reason}</p>)}<p className="text-sm leading-relaxed text-muted-foreground">{insight.basis}</p>{insight.customer && <div className="border-t pt-4 space-y-2"><h5 className="font-semibold">Customer lifecycle</h5><p>{insight.customer.name} ? Collected LTV: {insight.customer.currency} {Number(insight.customer.ltv).toLocaleString()}</p><p className="text-sm">{insight.customer.deals.length} linked deals ? {insight.customer.open_opportunities} open opportunities ? Outstanding {insight.customer.currency} {insight.customer.outstanding}</p>{insight.request && <p>Current request: {insight.request}</p>}<a className="text-primary underline" href={`/app/w/${wsId}/customers`}>View customer lifecycle</a></div>}</>}
  </section>;
}
