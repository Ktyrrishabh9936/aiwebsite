import { useCallback, useEffect, useMemo, useState } from "react";
import { Building2, ChevronLeft, ChevronRight, Loader2, Plus, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Link, useOutletContext } from "react-router-dom";
import api, { formatError } from "../../lib/api";
import { formatMoney } from "../../lib/currency";
import PropertyUnits from "../../components/PropertyUnits";

const SUBTYPES = {
  residential: ["Apartment", "Villa", "Farmhouse", "Independent House", "Plot", "Other"],
  commercial: ["Office", "Shop", "Showroom", "Mall / Retail Space", "Warehouse", "Commercial Building", "Other"],
  land: ["Residential Plot", "Commercial Plot", "Agricultural Land", "Industrial Land", "Other Land"],
  industrial: ["Warehouse", "Factory", "Industrial Plot", "Industrial Shed", "Other"],
  other: ["Custom Property"],
};
const CATEGORIES = [["residential", "Residential"], ["commercial", "Commercial"], ["land", "Land / plots"], ["industrial", "Industrial"], ["other", "Other"]];
const STEPS = ["Project details", "Property type", "Inventory"];
const EMPTY = {
  user_role: "developer", inventory_source: "own_inventory", container_kind: "project",
  category: "residential", subtype: "Apartment", structure: "tower", name: "", location: "",
  price: "", status: "available", inventory_owner: "", attributes: {},
  inventory_setup: { mode: "unit_mix", unit_mix: [{ tower: "Tower A", bhk: "2 BHK", count: "", start_number: "", price_min: "", price_max: "" }], total_units: 0 },
};

const isApartmentProject = (form) => form.category === "residential" && form.subtype === "Apartment" && form.container_kind === "project";
const positiveCount = (value) => /^\d+$/.test(String(value)) && Number(value) > 0 && Number(value) <= 100000;
const validPrice = (value) => /^\d+(\.\d{1,2})?$/.test(String(value));
const validMix = (rows, projectPrice) => rows.length > 0 && rows.every((row) => row.tower.trim() && row.bhk.trim() && positiveCount(row.count) &&
  /^[A-Za-z0-9_-]*\d+$/.test(row.start_number || "") && validPrice(row.price_min || projectPrice) &&
  (!row.price_max || (validPrice(row.price_max) && Number(row.price_max) >= Number(row.price_min || projectPrice)))) &&
  rows.every((row) => positiveCount(row.number_step ?? 1) && Number(row.number_step ?? 1) <= 1000) &&
  rows.length <= 100 && rows.reduce((sum, row) => sum + Number(row.count || 0), 0) <= 5000;

export default function Properties() {
  const { ws } = useOutletContext();
  const [properties, setProperties] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [editingId, setEditingId] = useState(null);
  const [step, setStep] = useState(0);
  const [open, setOpen] = useState(false);
  const [selectedProperty, setSelectedProperty] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [currency, setCurrency] = useState(ws.currency || "INR");
  const enabled = ws.modules?.real_estate !== false;

  const load = useCallback(async () => {
    if (!enabled) { setLoading(false); return; }
    try {
      const { data } = await api.get(`/workspaces/${ws.id}/properties`, { params: { search } });
      setProperties(data.items || []);
      setCurrency(data.currency || ws.currency || "INR");
    } catch (error) { toast.error(formatError(error.response?.data?.detail)); }
    finally { setLoading(false); }
  }, [enabled, search, ws.currency, ws.id]);

  useEffect(() => { load(); }, [load]);
  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const setCategory = (category) => setForm((current) => {
    const subtype = SUBTYPES[category][0];
    const container_kind = category === "land" ? "land" : subtype === "Apartment" ? "project" : "individual";
    return { ...current, category, subtype, container_kind, structure: subtype === "Apartment" ? "tower" : category === "land" ? "plot" : container_kind === "project" ? "multiple" : "single" };
  });
  const setSubtype = (subtype) => setForm((current) => {
    const container_kind = subtype === "Apartment" ? "project" : current.category === "land" ? "land" : "individual";
    return { ...current, subtype, container_kind, structure: subtype === "Apartment" ? "tower" : current.category === "land" ? "plot" : container_kind === "project" ? "multiple" : "single" };
  });
  const setContainer = (container_kind) => setForm((current) => ({ ...current, container_kind, structure: container_kind === "project" ? current.subtype === "Apartment" ? "tower" : "multiple" : container_kind === "land" ? "plot" : "single" }));
  const setInventory = (key, value) => setForm((current) => ({ ...current, inventory_setup: { ...current.inventory_setup, [key]: value } }));
  const setMixRow = (index, key, value) => setForm((current) => ({
    ...current,
    inventory_setup: { ...current.inventory_setup, unit_mix: current.inventory_setup.unit_mix.map((row, rowIndex) => rowIndex === index ? { ...row, [key]: value } : row) },
  }));
  const addMixRow = () => setForm((current) => ({
    ...current,
    inventory_setup: { ...current.inventory_setup, unit_mix: [...current.inventory_setup.unit_mix, { tower: current.inventory_setup.unit_mix.at(-1)?.tower || "Tower A", bhk: "1 BHK", count: "", start_number: "", price_min: "", price_max: "" }] },
  }));
  const removeMixRow = (index) => setForm((current) => ({
    ...current,
    inventory_setup: { ...current.inventory_setup, unit_mix: current.inventory_setup.unit_mix.length > 1 ? current.inventory_setup.unit_mix.filter((_, rowIndex) => rowIndex !== index) : current.inventory_setup.unit_mix },
  }));
  const startNew = () => { setEditingId(null); setForm(EMPTY); setStep(0); setOpen(true); };
  const startEdit = (property) => {
    const setup = property.inventory_setup || {};
    setEditingId(property.id);
    setForm({ ...EMPTY, ...property, inventory_setup: {
      ...EMPTY.inventory_setup, ...setup,
      unit_mix: setup.unit_mix?.length ? setup.unit_mix : [{ tower: "Tower A", bhk: "2 BHK", count: "", start_number: "", price_min: "", price_max: "" }],
    } });
    setStep(0);
    setOpen(true);
  };
  const close = () => { setOpen(false); setEditingId(null); setStep(0); setForm(EMPTY); };
  const apartment = isApartmentProject(form);
  const totalUnits = useMemo(() => apartment
    ? form.inventory_setup.unit_mix.reduce((sum, row) => sum + (Number(row.count) || 0), 0)
    : Number(form.inventory_setup.total_units) || 0, [apartment, form.inventory_setup]);
  const canContinue = step === 0 ? Boolean(form.name.trim() && form.location.trim()) :
    step === 1 ? Boolean(form.category && form.subtype) : apartment ? validMix(form.inventory_setup.unit_mix, form.price) : positiveCount(form.inventory_setup.total_units);

  const create = async (event) => {
    event.preventDefault();
    if (step < 2) { if (canContinue) setStep(step + 1); return; }
    if (!canContinue || saving) return;
    setSaving(true);
    const previousSetup = { ...form.inventory_setup };
    delete previousSetup.unit_mix;
    const inventory_setup = apartment
      ? { mode: "unit_mix", unit_mix: form.inventory_setup.unit_mix.map((row) => ({
          tower: row.tower.trim(), bhk: row.bhk.trim(), count: Number(row.count),
          start_number: row.start_number.trim(), price_min: row.price_min || form.price, price_max: row.price_max || row.price_min || form.price,
          number_step: Number(row.number_step ?? 1),
        })), total_units: totalUnits }
      : { ...previousSetup, mode: previousSetup.mode === "unit_mix" ? "manual" : previousSetup.mode || "manual", total_units: totalUnits };
    try {
      if (editingId) await api.patch(`/workspaces/${ws.id}/properties/${editingId}`, { ...form, inventory_setup });
      else await api.post(`/workspaces/${ws.id}/properties`, { ...form, inventory_setup });
      toast.success(editingId ? "Property updated" : "Property added");
      close();
      load();
    } catch (error) { toast.error(formatError(error.response?.data?.detail)); }
    finally { setSaving(false); }
  };
  const remove = async () => {
    if (!deleteTarget || deleting) return;
    setDeleting(true);
    try {
      await api.delete(`/workspaces/${ws.id}/properties/${deleteTarget.id}`);
      setProperties((items) => items.filter((item) => item.id !== deleteTarget.id));
      if (selectedProperty?.id === deleteTarget.id) setSelectedProperty(null);
      toast.success(`${deleteTarget.name} deleted`);
      setDeleteTarget(null);
      setDeleteError("");
    } catch (error) { setDeleteError(formatError(error.response?.data?.detail)); }
    finally { setDeleting(false); }
  };
  const generate = async (property) => {
    try {
      const { data } = await api.post(`/workspaces/${ws.id}/properties/${property.id}/generate-units`);
      toast.success(`${data.generated_units} flats ready to manage`);
      await load();
      setSelectedProperty(property);
    } catch (error) { toast.error(formatError(error.response?.data?.detail)); }
  };

  if (!enabled) return <div className="p-6 sm:p-10 max-w-3xl mx-auto"><div className="rounded-xl border border-dashed bg-card p-10 text-center"><Building2 className="w-10 h-10 mx-auto text-muted-foreground" /><h1 className="mt-4 font-display text-2xl font-black">Properties is not active</h1><p className="mt-2 text-sm text-muted-foreground">Install the Real Estate module in workspace settings to manage property inventory.</p><Link to={`/app/w/${ws.id}/settings`} className="mt-5 inline-flex h-10 items-center rounded-full bg-primary px-4 text-sm font-semibold text-primary-foreground">Open settings</Link></div></div>;
  return <div className="p-6 sm:p-10 max-w-7xl mx-auto space-y-8">
    {!selectedProperty && <><header className="flex items-end justify-between gap-4 flex-wrap"><div><div className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.2em] font-bold text-primary"><Building2 className="w-4 h-4" /> Property management</div><h1 className="mt-2 font-display text-3xl font-black tracking-tight">Properties</h1><p className="text-muted-foreground mt-1">Open a project to see and edit its flats.</p></div><button onClick={startNew} className="inline-flex items-center gap-2 px-4 h-10 rounded-full bg-primary text-primary-foreground text-sm font-semibold"><Plus className="w-4 h-4" /> Add property</button></header>
    <div className="flex items-center gap-2 max-w-xl"><Search className="w-4 h-4 text-muted-foreground" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search properties or locations" className="w-full h-10 px-3 rounded-lg border bg-background text-sm" /></div>
    {loading ? <div className="text-muted-foreground">Loading properties...</div> : properties.length === 0 ? <EmptyState onAdd={startNew} /> : <div className="grid gap-4 md:grid-cols-2">{properties.map((property) => <PropertyCard key={property.id} property={property} currency={currency} onEdit={startEdit} onManage={setSelectedProperty} onGenerate={generate} onDelete={(item) => { setDeleteError(""); setDeleteTarget(item); }} />)}</div>}</>}
    {selectedProperty && <PropertyUnits wsId={ws.id} property={selectedProperty} onClose={() => setSelectedProperty(null)} />}
    {deleteTarget && <div className="fixed inset-0 z-50 grid place-items-center bg-background/80 p-4" role="dialog" aria-modal="true" aria-label="Delete property"><div className="w-full max-w-md rounded-xl border bg-card p-6 shadow-xl space-y-4"><h2 className="text-xl font-bold">Delete {deleteTarget.name}?</h2><p className="text-sm text-muted-foreground">This removes the project and its {deleteTarget.generated_units || 0} generated flats. Flats linked to leads or with sale history are protected.</p>{deleteError && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{deleteError}</p>}<div className="flex justify-end gap-2"><button onClick={() => setDeleteTarget(null)} disabled={deleting} className="rounded-lg border px-4 py-2 text-sm">Cancel</button><button onClick={remove} disabled={deleting} className="rounded-lg bg-destructive px-4 py-2 text-sm font-semibold text-destructive-foreground disabled:opacity-50">{deleting ? "Deleting..." : "Delete project and flats"}</button></div></div></div>}
    {open && <div className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm p-4 overflow-y-auto" role="dialog" aria-modal="true" aria-label={editingId ? "Edit property" : "Add property"}><form onSubmit={create} className="max-w-3xl mx-auto my-8 rounded-xl border bg-card p-6 sm:p-8 space-y-7">
      <div className="flex items-start justify-between gap-4"><div><div className="text-xs uppercase tracking-[0.2em] font-bold text-primary">{editingId ? "Edit" : "Add"} property · Step {step + 1} of 3</div><h2 className="mt-2 font-display text-2xl font-black">{STEPS[step]}</h2></div><button type="button" onClick={close} className="text-sm text-muted-foreground">Close</button></div>
      <div className="grid grid-cols-3 gap-2">{STEPS.map((label, index) => <div key={label} className={`rounded-lg px-2 py-2 text-center text-xs font-semibold ${index === step ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"}`}>{index + 1}. {label}</div>)}</div>
      {step === 0 && <section className="space-y-4"><p className="text-sm text-muted-foreground">Add the building or project once. Flats can be entered together in the inventory step.</p><div className="grid sm:grid-cols-2 gap-3"><Field label="Apartment / project name" value={form.name} onChange={(value) => set("name", value)} required /><Field label="Location" value={form.location} onChange={(value) => set("location", value)} required /><Field label="Builder / owner" value={form.inventory_owner} onChange={(value) => set("inventory_owner", value)} /><Field label="Starting price (optional)" value={form.price} onChange={(value) => set("price", value)} /></div><label className="block space-y-1.5 text-xs font-semibold text-muted-foreground uppercase">Inventory source<select value={form.inventory_source} onChange={(event) => set("inventory_source", event.target.value)} className="w-full h-10 px-3 rounded-lg border bg-background text-sm normal-case text-foreground"><option value="own_inventory">My inventory</option><option value="builder_inventory">Builder inventory</option><option value="third_party">Third party inventory</option><option value="existing_inventory">Assigned inventory</option></select></label></section>}
      {step === 1 && <section className="space-y-4"><p className="text-sm text-muted-foreground">Choose the property type. Apartment projects use tower-wise flat counts automatically.</p><div className="grid sm:grid-cols-2 gap-3"><SelectField label="Category" value={form.category} onChange={setCategory} options={CATEGORIES} /><SelectField label="Property type" value={form.subtype} onChange={setSubtype} options={SUBTYPES[form.category].map((type) => [type, type])} /></div>{form.subtype !== "Apartment" && form.category !== "land" && <SelectField label="Listing type" value={form.container_kind} onChange={setContainer} options={[["individual", "Individual property"], ["project", "Project with multiple units"]]} />}{apartment && <div className="rounded-lg border bg-primary/5 p-4 text-sm">One apartment project can contain multiple towers and BHK types.</div>}</section>}
      {step === 2 && (apartment ? <section className="space-y-4">
        <div><h3 className="font-semibold">Flats by tower and BHK</h3><p className="text-sm text-muted-foreground">One row generates numbered flats with the chosen price range. You can edit any flat afterward.</p></div>
        {form.inventory_setup.unit_mix.map((row, index) => <div key={index} className="rounded-lg border p-3 space-y-3">
          <div className="flex items-center justify-between"><strong className="text-sm">Flat group {index + 1}</strong><button type="button" title={form.inventory_setup.unit_mix.length === 1 ? "Delete the project to remove its last group" : "Remove this flat group"} aria-label={`Remove inventory row ${index + 1}`} disabled={form.inventory_setup.unit_mix.length === 1} onClick={() => removeMixRow(index)} className="h-9 w-9 grid place-items-center rounded-lg border text-muted-foreground hover:text-destructive disabled:opacity-40"><Trash2 className="w-4 h-4" /></button></div>
          <div className="grid sm:grid-cols-3 gap-3">
            <Field label="Tower / block" value={row.tower} onChange={(value) => setMixRow(index, "tower", value)} required />
            <SelectField label="Flat type" value={row.bhk} onChange={(value) => setMixRow(index, "bhk", value)} options={["Studio", "1 BHK", "2 BHK", "3 BHK", "4 BHK", "5+ BHK"].map((type) => [type, type])} />
            <NumberField label="Number of flats" value={row.count} onChange={(value) => setMixRow(index, "count", value)} />
            <Field label="First flat number" value={row.start_number || ""} onChange={(value) => setMixRow(index, "start_number", value)} required />
            <NumberField label="Number increment" value={row.number_step ?? 1} onChange={(value) => setMixRow(index, "number_step", value)} />
            <Field label={`Price from (${currency})`} value={row.price_min || ""} onChange={(value) => setMixRow(index, "price_min", value)} />
            <Field label={`Price up to (${currency})`} value={row.price_max || ""} onChange={(value) => setMixRow(index, "price_max", value)} />
          </div><p className="text-xs text-muted-foreground">Start 101, increment 1: 101, 102, 103. Increment 100: 101, 201, 301. Prefixes such as A-101 are supported. Each flat starts at the minimum asking price; edit it in Manage flats.</p>
        </div>)}
        <button type="button" onClick={addMixRow} className="inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold"><Plus className="w-4 h-4" /> Add another tower or BHK</button>
        <div className="rounded-lg bg-primary/5 p-4 text-sm font-semibold">Total: {totalUnits} flats</div>
        {!validMix(form.inventory_setup.unit_mix, form.price) && <p className="text-xs text-muted-foreground">Each row needs a tower, flat type, count, first number and price. Maximum 5,000 flats and 100 groups. Flat number ranges within a tower cannot overlap.</p>}
      </section> : <section className="space-y-4"><h3 className="font-semibold">How many units are in this property?</h3><p className="text-sm text-muted-foreground">Enter the total number of units.</p><div className="max-w-48"><NumberField label="Total units" value={form.inventory_setup.total_units || ""} onChange={(value) => setInventory("total_units", value)} /></div></section>)}
      <div className="flex items-center justify-between border-t pt-5"><button type="button" onClick={() => setStep((current) => Math.max(0, current - 1))} disabled={step === 0} className="inline-flex items-center gap-1.5 px-3 h-10 rounded-lg border text-sm font-semibold disabled:opacity-40"><ChevronLeft className="w-4 h-4" /> Back</button>{step < 2 ? <button type="button" onClick={() => setStep((current) => current + 1)} disabled={!canContinue} className="inline-flex items-center gap-1.5 px-4 h-10 rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-40">Continue <ChevronRight className="w-4 h-4" /></button> : <button type="submit" disabled={!canContinue || saving} className="inline-flex items-center gap-2 px-5 h-10 rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50">{saving && <Loader2 className="w-4 h-4 animate-spin" />} {editingId ? "Save changes" : "Create property"}</button>}</div>
    </form></div>}
  </div>;
}

function Field({ label, value, onChange, required }) { return <label className="block space-y-1.5"><span className="text-xs font-semibold text-muted-foreground uppercase">{label}</span><input required={required} value={value} onChange={(event) => onChange(event.target.value)} className="w-full h-10 px-3 rounded-lg border bg-background text-sm" /></label>; }
function NumberField({ label, value, onChange }) { return <label className="block space-y-1.5"><span className="text-xs font-semibold text-muted-foreground uppercase">{label}</span><input type="number" min="1" max="100000" step="1" value={value} onChange={(event) => onChange(event.target.value)} className="w-full h-10 px-3 rounded-lg border bg-background text-sm" /></label>; }
function SelectField({ label, value, onChange, options }) { return <label className="block space-y-1.5"><span className="text-xs font-semibold text-muted-foreground uppercase">{label}</span><select value={value} onChange={(event) => onChange(event.target.value)} className="w-full h-10 px-3 rounded-lg border bg-background text-sm">{options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></label>; }
function EmptyState({ onAdd }) { return <div className="border border-dashed rounded-xl p-12 text-center bg-card"><Building2 className="w-10 h-10 mx-auto text-muted-foreground" /><h2 className="mt-4 font-display text-xl font-bold">No properties yet</h2><p className="mt-1 text-sm text-muted-foreground">Add a project, individual property, or land parcel to begin.</p><button onClick={onAdd} className="mt-5 inline-flex items-center gap-2 px-4 h-10 rounded-full bg-primary text-primary-foreground text-sm font-semibold"><Plus className="w-4 h-4" /> Add property</button></div>; }
function PropertyCard({ property, currency, onEdit, onManage, onGenerate, onDelete }) {
  const numericPrice = Number(String(property.price || "").replaceAll(",", ""));
  const unitMix = property.inventory_setup?.unit_mix || [];
  const generatedUnits = property.generated_units || 0;
  const plannedUnits = property.inventory_setup?.total_units || 0;
  const numbered = unitMix.length > 0 && unitMix.every((row) => row.start_number);
  const allGenerated = generatedUnits >= plannedUnits;
  const towers = new Set(unitMix.map((row) => row.tower)).size;
  const action = generatedUnits > 0 && allGenerated ? "View flats" : numbered ? `Generate ${plannedUnits} flats` : "Set flat numbers & prices";
  const openInventory = () => generatedUnits > 0 && allGenerated ? onManage(property) : numbered ? onGenerate(property) : onEdit(property);
  return <article className="rounded-xl border bg-card p-5 space-y-4">
    <div className="flex items-start justify-between gap-3"><div className="min-w-0"><h2 className="font-display text-lg font-bold truncate">{property.name}</h2><p className="text-sm text-muted-foreground">{property.location || "Location not set"}</p></div><span className="shrink-0 rounded-md border px-2 py-1 text-xs capitalize">{property.status}</span></div>
    <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm"><span>{property.subtype || property.category}</span>{unitMix.length > 0 && <span className="font-semibold">{generatedUnits} of {plannedUnits} flats ready ? {towers} {towers === 1 ? "tower" : "towers"}</span>}{unitMix.length === 0 && plannedUnits > 0 && <span>{plannedUnits} units</span>}</div>
    {property.inventory_owner && <p className="text-sm text-muted-foreground">Builder: {property.inventory_owner}</p>}
    {property.price && Number.isFinite(numericPrice) && <p className="text-sm">Starting price: <strong>{formatMoney(numericPrice, currency)}</strong></p>}
    {unitMix.length > 0 && <div className="flex flex-wrap gap-1.5">{unitMix.map((row, index) => <span key={`${row.tower}-${row.bhk}-${index}`} className="rounded-md bg-muted px-2 py-1 text-xs">{row.tower} ? {row.bhk} ? {row.count}</span>)}</div>}
    <div className="flex flex-wrap items-center gap-3 border-t pt-4">{unitMix.length > 0 && <button onClick={openInventory} className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground">{action}</button>}<button onClick={() => onEdit(property)} className="rounded-lg border px-4 py-2 text-sm font-semibold">Edit project</button><button onClick={() => onDelete(property)} className="ml-auto inline-flex items-center gap-1.5 rounded-lg px-2 py-2 text-sm text-destructive hover:bg-destructive/10"><Trash2 className="h-4 w-4" /> Delete project</button></div>
  </article>;
}
