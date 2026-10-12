import { useMemo, useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "./ui/popover";
import { COUNTRIES, countryByIso } from "../lib/countries";

/** Searchable country calling-code picker. `value` is an ISO code such as "IN". */
export default function CountryCodeSelect({ value, onChange, label = "Country code", className = "", showName = false }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const selected = countryByIso(value);
  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return COUNTRIES;
    return COUNTRIES.filter((c) => c.name.toLowerCase().includes(q) || c.dial.includes(q) || c.iso.toLowerCase() === q);
  }, [query]);

  return (
    <Popover open={open} onOpenChange={(next) => { setOpen(next); if (!next) setQuery(""); }}>
      <PopoverTrigger asChild>
        <button type="button" aria-label={`${label}: ${selected.name} ${selected.dial}`} className={`inline-flex h-10 items-center gap-1.5 rounded-lg border bg-background px-2.5 text-sm hover:bg-accent focus:outline-none focus:ring-2 focus:ring-primary/30 ${className}`}>
          <span className="text-base leading-none" aria-hidden="true">{selected.flag}</span>
          <span className="font-medium tabular-nums">{selected.dial}</span>
          {showName && <span className="truncate text-muted-foreground">{selected.name}</span>}
          <ChevronDown className="ml-auto h-3.5 w-3.5 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-0">
        <div className="flex items-center gap-2 border-b px-3">
          <Search className="h-4 w-4 text-muted-foreground" />
          <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search country or code" aria-label="Search countries" className="h-10 w-full bg-transparent text-sm outline-none" />
        </div>
        <ul role="listbox" aria-label={label} className="max-h-64 overflow-y-auto p-1">
          {results.map((c) => (
            <li key={c.iso} role="option" aria-selected={c.iso === selected.iso}>
              <button type="button" onClick={() => { onChange(c.iso); setOpen(false); }} className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm hover:bg-accent">
                <span className="text-base" aria-hidden="true">{c.flag}</span>
                <span className="flex-1 truncate">{c.name}</span>
                <span className="tabular-nums text-muted-foreground">{c.dial}</span>
                {c.iso === selected.iso && <Check className="h-3.5 w-3.5 text-primary" />}
              </button>
            </li>
          ))}
          {results.length === 0 && <li className="px-3 py-6 text-center text-sm text-muted-foreground">No matching country</li>}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
