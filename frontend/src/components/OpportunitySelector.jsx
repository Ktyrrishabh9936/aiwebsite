import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Loader2, ShoppingBag } from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";
import { formatMoneyMinor } from "../lib/currency";

export default function OpportunitySelector({ wsId, lead, onUpdated }) {
  const [offerings, setOfferings] = useState([]);
  const [currency, setCurrency] = useState(lead.opportunity?.currency || "INR");
  const [choice, setChoice] = useState(lead.opportunity ? `${lead.opportunity.module}:${lead.opportunity.item_id}` : "");
  const [quantity, setQuantity] = useState(lead.opportunity?.quantity || 1);
  const [amount, setAmount] = useState(lead.opportunity?.unit_price_minor != null ? String(lead.opportunity.unit_price_minor / 100) : "");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const sold = lead.opportunity?.sale_status === "sold";

  useEffect(() => {
    let active = true;
    api.get(`/workspaces/${wsId}/crm/offerings`).then(({ data }) => {
      if (!active) return;
      setOfferings(data.items || []); setCurrency(data.currency || "INR");
    }).catch((error) => { if (active) toast.error(formatError(error.response?.data?.detail)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [wsId]);

  const selected = useMemo(() => offerings.find((item) => `${item.module}:${item.id}` === choice), [choice, offerings]);
  useEffect(() => {
    if (selected) { setAmount(String(Number(selected.price_minor || 0) / 100)); if (selected.kind === "property") setQuantity(1); }
  }, [selected]);
  const save = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      const { data } = await api.patch(`/workspaces/${wsId}/crm/leads/${lead.id}/opportunity`, { module: selected.module, item_id: selected.id, quantity, amount });
      onUpdated(data); toast.success("Opportunity linked to this lead");
    } catch (error) { toast.error(formatError(error.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  if (sold) return <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4"><div className="flex items-center gap-2 text-sm font-semibold text-emerald-600"><CheckCircle2 className="w-4 h-4" /> Sold: {lead.opportunity.name}</div><p className="mt-1 text-xs text-muted-foreground">{lead.opportunity.quantity || 1} × {formatMoneyMinor(lead.opportunity.unit_price_minor, lead.opportunity.currency)} · {formatMoneyMinor(lead.opportunity.total_minor, lead.opportunity.currency)} total</p></div>;
  if (loading) return <div className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading inventory and catalog...</div>;
  if (!offerings.length) return null;
  return <div className="rounded-lg border bg-background p-4 space-y-3"><div><h4 className="flex items-center gap-2 text-sm font-semibold"><ShoppingBag className="w-4 h-4 text-primary" /> Sales opportunity</h4><p className="mt-1 text-xs text-muted-foreground">Link inventory, a product, or a service. Its value will appear in the CRM pipeline.</p></div><label className="block space-y-1"><span className="text-xs font-semibold text-muted-foreground">Offering</span><select value={choice} onChange={(event) => setChoice(event.target.value)} className="w-full h-10 rounded-md border bg-background px-3 text-sm"><option value="">Choose an offering</option>{offerings.map((item) => <option key={`${item.module}:${item.id}`} value={`${item.module}:${item.id}`}>{item.name} · {formatMoneyMinor(item.price_minor, currency)}</option>)}</select></label>{selected && <div className="grid grid-cols-2 gap-3"><label className="space-y-1"><span className="text-xs font-semibold text-muted-foreground">Quantity</span><input type="number" min="1" max={selected.available_quantity || undefined} disabled={selected.kind === "property"} value={quantity} onChange={(event) => setQuantity(event.target.value)} className="w-full h-10 rounded-md border bg-background px-3 text-sm disabled:opacity-60" /></label><label className="space-y-1"><span className="text-xs font-semibold text-muted-foreground">Unit amount ({currency})</span><input type="number" min="0" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} className="w-full h-10 rounded-md border bg-background px-3 text-sm" /></label></div>}<button type="button" onClick={save} disabled={!selected || saving} className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-semibold text-primary-foreground disabled:opacity-50">{saving && <Loader2 className="w-4 h-4 animate-spin" />} Link opportunity</button></div>;
}
