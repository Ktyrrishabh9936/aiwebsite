import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Loader2, ShoppingBag } from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";
import { formatMoneyMinor } from "../lib/currency";

export default function OpportunitySelector({ wsId, lead, onUpdated }) {
  const [offerings, setOfferings] = useState([]);
  const [currency, setCurrency] = useState(lead.opportunity?.currency || "INR");
  const [choice, setChoice] = useState(lead.opportunity ? `${lead.opportunity.module}:${lead.opportunity.item_id}` : "");
  const [kind, setKind] = useState(lead.opportunity?.kind === "unit" ? "flat" : "other");
  const [projectId, setProjectId] = useState(lead.opportunity?.project_id || "");
  const [tower, setTower] = useState(lead.opportunity?.tower || "");
  const [quantity, setQuantity] = useState(lead.opportunity?.quantity || 1);
  const [amount, setAmount] = useState(lead.opportunity?.unit_price_minor != null ? String(lead.opportunity.unit_price_minor / 100) : "");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const completed = ["sold", "rented"].includes(lead.opportunity?.sale_status);
  const opportunity = lead.opportunity;
  const hasOpportunity = Boolean(opportunity);

  useEffect(() => {
    setChoice(opportunity ? `${opportunity.module}:${opportunity.item_id}` : "");
    setProjectId(opportunity?.project_id || "");
    setTower(opportunity?.tower || "");
    setKind(opportunity?.kind === "unit" || (!opportunity && offerings.some((item) => item.kind === "unit")) ? "flat" : "other");
    setQuantity(opportunity?.quantity || 1);
    setAmount(opportunity?.unit_price_minor != null ? String(opportunity.unit_price_minor / 100) : "");
    // Server polling replaces the opportunity object every six seconds. Keep an in-progress
    // apartment, tower, or flat choice unless the saved opportunity itself changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lead.id, opportunity?.module, opportunity?.item_id, opportunity?.project_id,
    opportunity?.tower, opportunity?.kind, opportunity?.quantity, opportunity?.unit_price_minor,
    opportunity?.sale_status]);

  useEffect(() => {
    let active = true;
    api.get(`/workspaces/${wsId}/crm/offerings`).then(({ data }) => {
      if (!active) return;
      setOfferings(data.items || []);
      setCurrency(data.currency || "INR");
      if (!hasOpportunity && (data.items || []).some((item) => item.kind === "unit")) setKind("flat");
    }).catch((error) => { if (active) toast.error(formatError(error.response?.data?.detail)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [wsId, lead.id, hasOpportunity, opportunity?.item_id, opportunity?.sale_status]);

  const flats = useMemo(() => offerings.filter((item) => item.kind === "unit"), [offerings]);
  const other = useMemo(() => offerings.filter((item) => item.kind !== "unit"), [offerings]);
  const projects = useMemo(() => [...new Map(flats.map((item) => [item.project_id, item.project_name])).entries()], [flats]);
  const towers = useMemo(() => [...new Set(flats.filter((item) => item.project_id === projectId).map((item) => item.tower))], [flats, projectId]);
  const visibleFlats = flats.filter((item) => item.project_id === projectId && item.tower === tower);
  const selected = useMemo(() => offerings.find((item) => `${item.module}:${item.id}` === choice), [choice, offerings]);
  useEffect(() => {
    if (selected && lead.opportunity?.item_id !== selected.id) {
      setAmount(String(Number(selected.price_minor || 0) / 100));
      if (["property", "unit"].includes(selected.kind)) setQuantity(1);
    }
  }, [selected, lead.opportunity?.item_id]);

  const save = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      const { data } = await api.patch(`/workspaces/${wsId}/crm/leads/${lead.id}/opportunity`, {
        module: selected.module, item_id: selected.id, quantity, amount,
      });
      onUpdated(data);
      toast.success("Opportunity linked to this lead");
    } catch (error) { toast.error(formatError(error.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  if (completed) return <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4"><div className="flex items-center gap-2 text-sm font-semibold text-emerald-600"><CheckCircle2 className="w-4 h-4" /> {lead.opportunity.sale_status === "rented" ? "Rented" : "Sold"}: {lead.opportunity.name}</div><p className="mt-1 text-xs text-muted-foreground">{formatMoneyMinor(lead.opportunity.sold_value_minor ?? lead.opportunity.total_minor, lead.opportunity.currency)} {lead.opportunity.sale_status === "rented" ? "rent value" : "sold value"}</p></div>;
  if (loading) return <div className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading inventory and catalog...</div>;
  if (!offerings.length) return <div className="rounded-lg border p-4 text-sm text-muted-foreground">No available flats or other offerings. Add flat numbers and prices in Properties first.</div>;
  return <div className="rounded-lg border bg-background p-4 space-y-3"><div><h4 className="flex items-center gap-2 text-sm font-semibold"><ShoppingBag className="w-4 h-4 text-primary" /> Sales opportunity</h4><p className="mt-1 text-xs text-muted-foreground">Choose the exact flat before converting this lead.</p></div>
    {lead.opportunity && !selected && <p className="text-xs text-amber-600">The previous selection is no longer available. Choose an available flat or offering before converting this lead.</p>}
    {flats.length > 0 && other.length > 0 && <Select label="Offering type" value={kind} onChange={(value) => { setKind(value); setChoice(""); }} options={[["flat", "Apartment flat"], ["other", "Other property, product or service"]]} />}
    {(kind === "flat" || !other.length) && flats.length > 0 ? <>
      <Select label="Apartment" value={projectId} onChange={(value) => { setProjectId(value); setTower(""); setChoice(""); }} options={[["", "Choose apartment"], ...projects]} />
      {projectId && <Select label="Tower" value={tower} onChange={(value) => { setTower(value); setChoice(""); }} options={[["", "Choose tower"], ...towers.map((value) => [value, value])]} />}
      {tower && <Select label="Flat" value={choice} onChange={setChoice} options={[["", "Choose available flat"], ...visibleFlats.map((item) => [`${item.module}:${item.id}`, `Flat ${item.unit_number} · ${item.bhk} · ${item.listing_type === "rent" ? "Rent" : "Sale"} · ${formatMoneyMinor(item.price_minor, currency)}`])]} />}
    </> : <Select label="Offering" value={choice} onChange={setChoice} options={[["", "Choose an offering"], ...other.map((item) => [`${item.module}:${item.id}`, `${item.name} · ${formatMoneyMinor(item.price_minor, currency)}`])]} />}
    {selected && <div className="grid grid-cols-2 gap-3"><label className="space-y-1"><span className="text-xs font-semibold text-muted-foreground">Quantity</span><input type="number" min="1" max={selected.available_quantity || undefined} disabled={["property", "unit"].includes(selected.kind)} value={quantity} onChange={(event) => setQuantity(event.target.value)} className="w-full h-10 rounded-md border bg-background px-3 text-sm disabled:opacity-60" /></label><label className="space-y-1"><span className="text-xs font-semibold text-muted-foreground">{selected.listing_type === "rent" ? "Rent amount" : "Unit amount"} ({currency})</span><input type="number" min="0" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} className="w-full h-10 rounded-md border bg-background px-3 text-sm" /></label></div>}
    <button type="button" onClick={save} disabled={!selected || saving} className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-semibold text-primary-foreground disabled:opacity-50">{saving && <Loader2 className="w-4 h-4 animate-spin" />} Link opportunity</button>
  </div>;
}

function Select({ label, value, onChange, options }) { return <label className="block space-y-1"><span className="text-xs font-semibold text-muted-foreground">{label}</span><select value={value} onChange={(event) => onChange(event.target.value)} className="w-full h-10 rounded-md border bg-background px-3 text-sm">{options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></label>; }
