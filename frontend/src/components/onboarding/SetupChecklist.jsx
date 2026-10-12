import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, CheckCircle2, Circle, Clock, Rocket, X } from "lucide-react";
import api from "../../lib/api";

/** "What should I set up next?" checklist built from live workspace state. */
export default function SetupChecklist({ wsId, dismissible = true, title = "Get the most out of Arevei" }) {
  const storageKey = `arevei_checklist_hidden_${wsId}`;
  const [data, setData] = useState(null);
  const [hidden, setHidden] = useState(() => { try { return localStorage.getItem(storageKey) === "1"; } catch { return false; } });

  useEffect(() => {
    let live = true;
    api.get(`/workspaces/${wsId}/onboarding/checklist`).then(({ data }) => { if (live) setData(data); }).catch(() => {});
    return () => { live = false; };
  }, [wsId]);

  if (!data || (dismissible && hidden) || (dismissible && data.done === data.total)) return null;
  const pct = Math.round((data.done / data.total) * 100);
  const hide = () => { try { localStorage.setItem(storageKey, "1"); } catch { /* per-browser preference only */ } setHidden(true); };

  return (
    <section aria-labelledby="setup-checklist-title" className="rounded-2xl border bg-card p-5 sm:p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary"><Rocket className="h-5 w-5" /></span>
          <div>
            <h2 id="setup-checklist-title" className="font-semibold">{title}</h2>
            <p className="mt-0.5 text-sm text-muted-foreground">{data.done} of {data.total} done{data.next ? ` · Next: ${data.next.title.toLowerCase()}` : ""}</p>
          </div>
        </div>
        {dismissible && <button type="button" onClick={hide} aria-label="Hide setup checklist" className="rounded-md p-1.5 text-muted-foreground hover:bg-accent"><X className="h-4 w-4" /></button>}
      </div>
      <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} /></div>
      <ul className="mt-4 grid gap-2 sm:grid-cols-2">
        {data.items.map((item) => (
          <li key={item.key}>
            <Link to={item.href} className={`group flex items-start gap-3 rounded-xl border p-3 transition ${item.done ? "bg-muted/30" : "hover:border-primary/40 hover:bg-primary/5"} ${data.next?.key === item.key ? "border-primary/40" : ""}`}>
              {item.done ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" /> : <Circle className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground/50" />}
              <span className="min-w-0 flex-1">
                <span className={`block text-sm font-medium ${item.done ? "text-muted-foreground line-through" : ""}`}>{item.title}</span>
                {!item.done && <span className="mt-0.5 block text-xs text-muted-foreground">{item.description}</span>}
              </span>
              {!item.done && <span className="inline-flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground"><Clock className="h-3 w-3" />{item.minutes}m<ArrowRight className="h-3.5 w-3.5 opacity-0 transition group-hover:opacity-100" /></span>}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
