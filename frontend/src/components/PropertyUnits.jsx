import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";
import { formatMoneyMinor } from "../lib/currency";
import PropertyPlan, { statusStyle } from "./PropertyPlan";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog";

const LIMIT = 25;

export default function PropertyUnits({ wsId, property, onClose }) {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [currency, setCurrency] = useState("INR");
  const [tower, setTower] = useState("");
  const [bhk, setBhk] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState("list");
  const [planItems, setPlanItems] = useState([]);
  const [planLoading, setPlanLoading] = useState(false);
  const [selectedPlanId, setSelectedPlanId] = useState(null);
  const land = property.category === "land" || property.container_kind === "land";
  const unitLabel = land ? "block" : property.subtype === "Apartment" ? "flat" : "unit";
  const towers = [...new Set((property.inventory_setup?.unit_mix || []).map((row) => row.tower))];
  const bhks = [...new Set((property.inventory_setup?.unit_mix || []).map((row) => row.bhk))];

  useEffect(() => {
    let active = true;
    setLoading(true);
    api.get(`/workspaces/${wsId}/properties/${property.id}/units`, { params: { tower, bhk, status, offset: page * LIMIT, limit: LIMIT } })
      .then(({ data }) => { if (active) { setItems(data.items || []); setTotal(data.total || 0); setCurrency(data.currency || "INR"); } })
      .catch((error) => { if (active) toast.error(formatError(error.response?.data?.detail)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [wsId, property.id, tower, bhk, status, page, revision]);

  useEffect(() => {
    if (view !== "plan") return undefined;
    let active = true;
    setPlanLoading(true);
    api.get(`/workspaces/${wsId}/properties/${property.id}/units/plan`)
      .then(({ data }) => { if (active) { setPlanItems(data.items || []); setCurrency(data.currency || "INR"); } })
      .catch((error) => { if (active) toast.error(formatError(error.response?.data?.detail)); })
      .finally(() => { if (active) setPlanLoading(false); });
    return () => { active = false; };
  }, [wsId, property.id, view, revision]);
  const visiblePlanItems = useMemo(() => planItems.filter((unit) => (!tower || unit.tower === tower) && (!bhk || unit.bhk === bhk) && (!status || unit.status === status)), [planItems, tower, bhk, status]);
  const selectedPlanUnit = visiblePlanItems.find((unit) => unit.id === selectedPlanId);

  return <section className="rounded-xl border bg-card p-4 sm:p-6 space-y-5" aria-label="Property inventory">
    <button onClick={onClose} className="rounded-lg border px-3 py-2 text-sm font-semibold">← Back to properties</button>
    <div><h1 className="font-display text-2xl font-bold">{property.name}</h1><p className="text-sm text-muted-foreground">Choose a {unitLabel} to see its status or change its availability.</p></div>
    <div className="inline-flex rounded-lg border bg-muted/30 p-1" role="group" aria-label="Inventory view">
      <button type="button" onClick={() => setView("list")} aria-pressed={view === "list"} className={`rounded-md px-4 py-2 text-sm font-semibold ${view === "list" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>List view</button>
      <button type="button" onClick={() => setView("plan")} aria-pressed={view === "plan"} className={`rounded-md px-4 py-2 text-sm font-semibold ${view === "plan" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>Plan view</button>
    </div>
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
      {!land && <Filter label="Tower" value={tower} onChange={(value) => { setTower(value); setPage(0); }} options={towers} />}
      {!land && <Filter label="BHK" value={bhk} onChange={(value) => { setBhk(value); setPage(0); }} options={bhks} />}
      <Filter label="Status" value={status} onChange={(value) => { setStatus(value); setPage(0); }} options={["available", "reserved", "sold", "rented", "inactive"]} />
    </div>
    {view === "list" ? <>
      {loading ? <p className="text-sm text-muted-foreground">Loading units...</p> : items.length === 0 ? <p className="text-sm text-muted-foreground">No units match these filters.</p> : <div className="divide-y rounded-lg border">{items.map((unit) => <UnitCard key={unit.id} wsId={wsId} propertyId={property.id} unit={unit} unitLabel={unitLabel} currency={currency} onSaved={() => setRevision((value) => value + 1)} />)}</div>}
      <div className="flex items-center justify-between text-sm"><span>{total ? `${page * LIMIT + 1}-${Math.min((page + 1) * LIMIT, total)} of ${total}` : "0 units"}</span><div className="flex gap-2"><button disabled={page === 0} onClick={() => setPage(page - 1)} className="rounded-lg border px-3 py-1 disabled:opacity-40">Previous</button><button disabled={(page + 1) * LIMIT >= total} onClick={() => setPage(page + 1)} className="rounded-lg border px-3 py-1 disabled:opacity-40">Next</button></div></div>
    </> : planLoading ? <p className="text-sm text-muted-foreground">Loading plan...</p> : <>
      <PropertyPlan property={property} units={planItems} visibleUnits={visiblePlanItems} selectedId={selectedPlanId} onSelect={setSelectedPlanId} />
    </>}
    <Dialog open={Boolean(selectedPlanUnit)} onOpenChange={(open) => { if (!open) setSelectedPlanId(null); }}>
      {selectedPlanUnit && <DialogContent className="max-w-xl max-h-[90dvh] overflow-y-auto" aria-label="Selected unit details">
        <DialogHeader><DialogTitle>{selectedPlanUnit.unit_number}</DialogTitle></DialogHeader>
        <UnitCard key={selectedPlanUnit.id} wsId={wsId} propertyId={property.id} unit={selectedPlanUnit} unitLabel={unitLabel} currency={currency} onSaved={() => { setSelectedPlanId(null); setRevision((value) => value + 1); }} />
      </DialogContent>}
    </Dialog>
  </section>;
}

function Filter({ label, value, onChange, options }) { return <label className="block text-xs font-semibold text-muted-foreground">{label}<select value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 block w-full h-10 rounded-lg border bg-background px-2 text-sm text-foreground"><option value="">All</option>{options.map((option) => <option key={option} value={option}>{option}</option>)}</select></label>; }

function UnitCard({ wsId, propertyId, unit, unitLabel, currency, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [price, setPrice] = useState(String((unit.asking_price_minor || 0) / 100));
  const [listingType, setListingType] = useState(unit.listing_type || "sale");
  const [status, setStatus] = useState(unit.status);
  const [saving, setSaving] = useState(false);
  const occupied = unit.status === "sold" || unit.status === "rented";
  useEffect(() => {
    setPrice(String((unit.asking_price_minor || 0) / 100));
    setListingType(unit.listing_type || "sale");
    setStatus(unit.status);
  }, [unit.id, unit.updated_at, unit.asking_price_minor, unit.listing_type, unit.status]);
  const save = async () => {
    setSaving(true);
    try {
      await api.patch(`/workspaces/${wsId}/properties/${propertyId}/units/${unit.id}`, {
        asking_price: price, listing_type: listingType, status: occupied ? "available" : status,
        expected_updated_at: unit.updated_at,
      });
      toast.success(occupied ? `${unitLabel} active again` : `${unitLabel} updated`);
      setEditing(false);
      onSaved();
    } catch (error) { toast.error(formatError(error.response?.data?.detail)); }
    finally { setSaving(false); }
  };
  return <article className="p-3 sm:p-4">
    <div className="flex flex-wrap items-center gap-3">
      <div className="min-w-[110px]"><strong>{unitLabel === "block" ? unit.unit_number : `${unit.tower} · ${unit.unit_number}`}</strong><p className="text-xs text-muted-foreground">{unit.bhk} · {unit.listing_type === "rent" ? "Rent" : "Sale"}</p></div>
      <div className="min-w-[110px] text-sm"><strong>{formatMoneyMinor(unit.asking_price_minor, currency)}</strong><p className="text-xs text-muted-foreground">Asking price</p></div>
      <span className={`rounded-md border px-2 py-1 text-xs font-semibold ${statusStyle[unit.status]?.className || ""}`}>{statusStyle[unit.status]?.label || unit.status}</span>
      <button onClick={() => setEditing((current) => !current)} className="ml-auto rounded-lg border px-3 py-2 text-sm font-semibold">{editing ? "Close" : occupied ? "Relist" : `Edit ${unitLabel}`}</button>
    </div>
    {editing && <div className="mt-4 space-y-3 rounded-lg bg-muted/40 p-3">
      {occupied && <p className="text-sm">{unit.status === "rented" ? "Rent" : "Sold"} for {formatMoneyMinor(unit.sold_value_minor, currency)}. Relisting keeps the sale history.</p>}
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-xs font-semibold">Asking price ({currency})<input type="number" min="0" step="0.01" value={price} onChange={(event) => setPrice(event.target.value)} className="mt-1 block w-full h-9 rounded-lg border bg-background px-2 text-sm font-normal" /></label>
        <label className="text-xs font-semibold">Listing<select value={listingType} onChange={(event) => setListingType(event.target.value)} className="mt-1 block w-full h-9 rounded-lg border bg-background px-2 text-sm font-normal"><option value="sale">For sale</option><option value="rent">For rent</option></select></label>
        {!occupied && <label className="text-xs font-semibold">Availability<select value={status} onChange={(event) => setStatus(event.target.value)} className="mt-1 block w-full h-9 rounded-lg border bg-background px-2 text-sm font-normal"><option value="available">Available</option><option value="reserved">Reserved / locked</option><option value="inactive">Inactive</option></select></label>}
      </div>
      <div className="flex flex-wrap gap-2"><button disabled={saving || !price} onClick={save} className="rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50">{occupied ? `Relist ${unitLabel}` : `Save ${unitLabel}`}</button><button onClick={() => setEditing(false)} className="rounded-lg border px-3 py-2 text-sm">Cancel</button></div>
      {!!unit.transactions?.length && <details className="text-xs"><summary className="cursor-pointer text-muted-foreground">Sale and rental history ({unit.transactions.length})</summary><ul className="mt-2 space-y-1">{unit.transactions.map((entry, index) => <li key={index}>{entry.type === "rent" ? "Rented" : "Sold"} ? {formatMoneyMinor(entry.value_minor, entry.currency || currency)} ? {new Date(entry.at).toLocaleDateString()}</li>)}</ul></details>}
    </div>}
  </article>;
}
