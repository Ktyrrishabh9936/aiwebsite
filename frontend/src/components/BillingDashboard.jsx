import { useCallback, useEffect, useState } from "react";
import { CircleAlert, CreditCard, RefreshCw } from "lucide-react";
import api, { formatError } from "../lib/api";

const money = (value) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(value || 0));
const number = (value) => new Intl.NumberFormat().format(Number(value || 0));

export default function BillingDashboard({ wsId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await api.get(`/workspaces/${wsId}/billing`);
      setData(response.data);
    } catch (requestError) {
      setError(formatError(requestError.response?.data?.detail || requestError.message));
    } finally {
      setLoading(false);
    }
  }, [wsId]);
  useEffect(() => { load(); }, [load]);

  const credit = Number(data?.monthly_credit_usd || 0);
  const used = Number(data?.estimated_usage_usd || 0);
  const progress = credit > 0 ? Math.min(100, (used / credit) * 100) : 0;
  return <section aria-labelledby="billing-heading" className="rounded-xl border border-border bg-card p-6 space-y-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex items-start gap-3">
        <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary"><CreditCard className="h-5 w-5" /></div>
        <div><h2 id="billing-heading" className="font-display text-xl font-bold">Billing and AI credit</h2><p className="mt-1 text-sm text-muted-foreground">Monthly account usage across all your workspaces. Amounts are estimates in USD.</p></div>
      </div>
      <button type="button" onClick={load} disabled={loading} className="inline-flex h-9 items-center gap-2 rounded-md border px-3 text-xs font-semibold hover:bg-accent disabled:opacity-50"><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Refresh</button>
    </div>
    {error ? <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p> : loading && !data ? <p className="text-sm text-muted-foreground">Loading billing usage…</p> : data && <>
      <p className="text-xs text-muted-foreground">Current period: {data.period_start} to {data.period_end_exclusive} (exclusive), UTC · {number(data.workspace_count)} workspace{data.workspace_count === 1 ? "" : "s"}</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <Metric label="Monthly AI credit" value={money(data.monthly_credit_usd)} />
        <Metric label="Estimated Bedrock usage" value={money(data.estimated_usage_usd)} />
        <Metric label="Estimated remaining" value={data.estimated_remaining_usd == null ? "Pending" : money(data.estimated_remaining_usd)} />
      </div>
      <div><div className="mb-2 flex justify-between text-xs"><span>Priced usage against monthly credit</span><span>{credit > 0 ? Math.round((used / credit) * 100) : 0}%</span></div><div role="progressbar" aria-label="AI credit used" aria-valuenow={Math.round(progress)} aria-valuemin={0} aria-valuemax={100} className="h-2 overflow-hidden rounded-full bg-secondary"><div className={`h-full rounded-full ${used >= credit ? "bg-amber-500" : "bg-primary"}`} style={{ width: `${progress}%` }} /></div></div>
      {used >= credit && credit > 0 && <p role="status" className="text-sm font-semibold text-amber-600">Priced usage has reached the monthly AI credit{data.estimate_complete ? ` by ${money(Math.max(0, used - credit))}` : ""}. AI requests remain available while billing is in report and warn mode.</p>}
      {used >= credit * 0.8 && used < credit && credit > 0 && <p role="status" className="text-sm font-semibold text-amber-600">Priced AI usage has reached 80% of the monthly credit.</p>}
      {!data.estimate_complete && <div role="status" className="flex gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm"><CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" /><span>The balance is pending: {number(data.unpriced_calls)} unpriced {data.unpriced_calls === 1 ? "call" : "calls"} and {number(data.unmetered_calls)} {data.unmetered_calls === 1 ? "call" : "calls"} without token counts. The displayed usage is only the priced portion. Ask the account operator to configure Bedrock rates before treating this as a full estimate.</span></div>}
      <p className="text-xs text-muted-foreground">{number(data.priced_calls)} priced calls · {number(data.input_tokens)} input tokens · {number(data.output_tokens)} output tokens. Rates are configured by the account operator; this is an estimate, not an AWS invoice. Voice, telephony, SMS, and other provider charges are not included. AI requests are not blocked at the credit limit.</p>
      {data.models?.length > 0 && <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr className="border-b text-muted-foreground"><th className="py-2 pr-3 font-semibold">Model</th><th className="py-2 pr-3 font-semibold">Calls</th><th className="py-2 pr-3 font-semibold">Tokens in / out</th><th className="py-2 font-semibold">Estimated cost</th></tr></thead><tbody>{data.models.map((row) => <tr key={`${row.provider}:${row.model}`} className="border-b last:border-0"><td className="py-2 pr-3"><span className="font-medium">{row.model}</span><span className="block text-muted-foreground">{row.provider}{row.unpriced_calls ? ` · ${row.unpriced_calls} unpriced` : ""}</span></td><td className="py-2 pr-3">{number(row.calls)}</td><td className="py-2 pr-3">{number(row.input_tokens)} / {number(row.output_tokens)}</td><td className="py-2">{row.unpriced_calls ? `At least ${money(row.estimated_cost_usd)}` : money(row.estimated_cost_usd)}</td></tr>)}</tbody></table></div>}
    </>}
  </section>;
}

function Metric({ label, value }) { return <div className="rounded-lg border bg-background p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 font-display text-2xl font-bold">{value}</p></div>; }
