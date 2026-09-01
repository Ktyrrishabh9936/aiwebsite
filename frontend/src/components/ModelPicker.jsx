import { useEffect, useState } from "react";
import { Check, ChevronDown, Zap, Sparkles, DollarSign } from "lucide-react";
import api from "../lib/api";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";

const tierIcon = { premium: Sparkles, fast: Zap, cheap: DollarSign };

export function ModelPicker({ value, onChange }) {
  const [models, setModels] = useState([]);

  useEffect(() => {
    api.get("/models").then((r) => setModels(r.data.models)).catch(() => {});
  }, []);

  const current = models.find((m) => m.id === value);
  const groups = [...new Set(models.map((m) => m.provider || "models"))];

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          data-testid="model-picker"
          className="inline-flex items-center gap-2 px-3.5 h-9 rounded-full border border-border glass hover:bg-accent transition-colors text-sm font-medium"
        >
          <span className="w-2 h-2 rounded-full bg-primary" />
          <span className="max-w-[140px] truncate">{current?.label || "Select model"}</span>
          <ChevronDown className="w-3.5 h-3.5 opacity-60" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        {groups.map((provider) => (
          <div key={provider}>
            <div className="px-2 py-1 text-[10px] uppercase tracking-wider font-bold text-muted-foreground">{provider}</div>
            {models.filter((m) => (m.provider || "models") === provider).map((m) => {
              const Icon = tierIcon[m.tier] || Sparkles;
              return (
                <DropdownMenuItem
                  key={m.id}
                  data-testid={`model-option-${m.id}`}
                  onClick={() => onChange(m.id)}
                  className="flex items-center gap-2 cursor-pointer"
                >
                  <Icon className="w-4 h-4 opacity-70" />
                  <span className="flex-1">{m.label}</span>
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
