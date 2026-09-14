import { useEffect, useState } from "react";
import { Check, ChevronDown, Zap, Sparkles, DollarSign } from "lucide-react";
import api from "../lib/api";
import { providerName } from "./AiStatus";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";

const tierIcon = { premium: Sparkles, fast: Zap, cheap: DollarSign };

export function ModelPicker({ value, onChange }) {
  const [models, setModels] = useState([]);
  const loadModels = () => api.get("/models").then((r) => setModels(r.data.models)).catch(() => {});

  useEffect(() => {
    api.get("/models").then((r) => setModels(r.data.models)).catch(() => {});
  }, []);

  const current = models.find((m) => m.id === value);
  const groups = ["AI Models"];

  return (
    <DropdownMenu onOpenChange={(open) => open && loadModels()}>
      <DropdownMenuTrigger asChild>
        <button
          data-testid="model-picker"
          className="inline-flex items-center gap-2 px-3.5 h-9 rounded-full border border-border glass hover:bg-accent transition-colors text-sm font-medium"
        >
          <span className={`w-2 h-2 rounded-full ${current?.configured ? "bg-primary" : "bg-amber-500"}`} />
          <span className="text-left leading-tight">
            <span className="block max-w-[160px] truncate">{current?.label || "Select model"}</span>
            <span className="block text-[10px] text-muted-foreground">{current ? `${providerName(current.provider)} · ${current.configured ? "Key configured" : "Key needed"}` : "Choose workspace AI"}</span>
          </span>
          <ChevronDown className="w-3.5 h-3.5 opacity-60" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        {groups.map((provider) => (
          <div key={provider}>
            <div className="px-2 py-1 text-[10px] uppercase tracking-wider font-bold text-muted-foreground">AI Models</div>
            {models.map((m) => {
              const Icon = tierIcon[m.tier] || Sparkles;
              return (
                <DropdownMenuItem
                  key={m.id}
                  data-testid={`model-option-${m.id}`}
                  onClick={() => onChange(m.id)}
                  className="flex items-center gap-2 cursor-pointer"
                >
                  <Icon className="w-4 h-4 opacity-70" />
                  <span className="flex-1">{m.label}<span className="block text-[10px] text-muted-foreground">{providerName(m.provider)}</span></span>
                  <span className={m.configured ? "text-[10px] uppercase tracking-wider text-muted-foreground" : "text-[10px] px-1.5 rounded-full bg-amber-500/15 text-amber-500"}>{m.configured ? m.tier : "key needed"}</span>
                  {m.id === value && <Check className="w-4 h-4 text-primary" />}
                </DropdownMenuItem>
              );
            })}
          </div>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
