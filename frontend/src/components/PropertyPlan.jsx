import { useEffect, useMemo, useState } from "react";

const PAGE_SIZE = 120;
export const statusStyle = {
  available: { label: "Available", className: "border-emerald-600/60 bg-emerald-500/15 text-emerald-800 dark:text-emerald-200" },
  reserved: { label: "Locked", className: "border-amber-500/70 bg-amber-500/20 text-amber-900 dark:text-amber-100" },
  sold: { label: "SOLD", className: "border-rose-600/70 bg-rose-500/20 text-rose-900 dark:text-rose-100" },
  rented: { label: "Rented", className: "border-violet-500/60 bg-violet-500/15 text-violet-800 dark:text-violet-200" },
  inactive: { label: "Inactive", className: "border-border bg-muted text-muted-foreground" },
};

export default function PropertyPlan({ property, units, visibleUnits, selectedId, onSelect }) {
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [property.id, visibleUnits]);
  const land = property.category === "land" || property.container_kind === "land";
  const counts = useMemo(() => units.reduce((acc, unit) => { acc[unit.status] = (acc[unit.status] || 0) + 1; return acc; }, {}), [units]);
  const pageCount = Math.max(1, Math.ceil(visibleUnits.length / PAGE_SIZE));
  const pageUnits = visibleUnits.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const groups = useMemo(() => {
    const grouped = new Map();
    for (const unit of pageUnits) {
      const key = unit.tower || (land ? "Site" : "Property");
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(unit);
    }
    return [...grouped];
  }, [pageUnits, land]);
  const area = Number(property.attributes?.area_sqft);

  return <div className="space-y-4" aria-label="Property plan view">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-base font-semibold">Inventory plan</h2><p className="text-xs text-muted-foreground">Schematic layout · positions and dimensions are not surveyed</p></div>
      <p className="text-sm text-muted-foreground">{units.length} {land ? "blocks" : "units"}{land && area > 0 ? ` · ${area.toLocaleString()} sq ft site` : ""}</p>
    </div>
    <div className="flex flex-wrap gap-x-4 gap-y-2" aria-label="Status legend">
      {["available", "reserved", "sold", "rented", "inactive"].filter((status) => ["available", "reserved", "sold"].includes(status) || counts[status]).map((status) => <span key={status} className="inline-flex items-center gap-1.5 text-xs text-foreground/80"><span className={`h-3 w-3 rounded-sm border ${statusStyle[status].className}`} />{statusStyle[status].label} <strong className="text-foreground">{counts[status] || 0}</strong></span>)}
    </div>
    {visibleUnits.length === 0 ? <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">No units match the selected filters.</p> : <div className="space-y-5 rounded-xl border bg-muted/20 p-3 sm:p-5" style={{ backgroundImage: "linear-gradient(hsl(var(--border) / .35) 1px, transparent 1px), linear-gradient(90deg, hsl(var(--border) / .35) 1px, transparent 1px)", backgroundSize: "24px 24px" }}>
      {groups.map(([name, groupUnits]) => <section key={name} className="rounded-lg border-2 border-dashed border-foreground/25 bg-card/95 p-3 sm:p-4" aria-label={land ? "Site blocks" : name}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b pb-2"><h3 className="text-sm font-semibold">{land ? "Site blocks" : name}</h3><span className="text-xs text-muted-foreground">{groupUnits.length} shown</span></div>
        <div className="grid gap-2.5" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(126px, 1fr))" }}>
          {groupUnits.map((unit) => {
            const visual = statusStyle[unit.status] || statusStyle.inactive;
            return <button key={unit.id} type="button" onClick={() => onSelect(unit.id)} aria-label={`${unit.unit_number}, ${visual.label}${land ? " block" : `, ${unit.tower}`}`} aria-pressed={selectedId === unit.id} className={`min-h-24 rounded-md border-2 p-3 text-left transition-all hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${visual.className} ${selectedId === unit.id ? "ring-2 ring-primary ring-offset-2" : ""}`}>
              <span className="block truncate text-sm font-bold">{unit.unit_number}</span>
              <span className="mt-1 block text-xs">{land ? "Land block" : unit.bhk}</span>
              <span className="mt-3 block text-xs font-bold uppercase tracking-wide">{visual.label}</span>
            </button>;
          })}
        </div>
      </section>)}
    </div>}
    {pageCount > 1 && <div className="flex items-center justify-between gap-3 text-sm"><span>Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, visibleUnits.length)} of {visibleUnits.length}</span><div className="flex gap-2"><button type="button" disabled={page === 0} onClick={() => setPage((current) => current - 1)} className="rounded-lg border px-3 py-2 disabled:opacity-40">Previous</button><button type="button" disabled={page + 1 >= pageCount} onClick={() => setPage((current) => current + 1)} className="rounded-lg border px-3 py-2 disabled:opacity-40">Next</button></div></div>}
  </div>;
}
