import { Link, useOutletContext, useSearchParams } from "react-router-dom";
import { Bot, CalendarClock, Plug } from "lucide-react";
import AgentControlPanel from "../../components/AgentControlPanel";
import ConnectorsSettings from "../../components/ConnectorsSettings";
import DailyAiSettings from "../../components/DailyAiSettings";

const TABS = [
  { key: "agents", label: "Agents", icon: Bot },
  { key: "daily", label: "Daily plan", icon: CalendarClock },
  { key: "connections", label: "Connectors", icon: Plug },
];

/** The AI side of the CRM in three simple tabs: the agents, the daily plan and the connectors. */
export default function AiControl() {
  const { ws } = useOutletContext();
  const [params, setParams] = useSearchParams();
  const asked = params.get("tab");
  const voice = asked === "voice" || params.get("agent") === "voice"; // older links to the voice settings
  const tab = TABS.some((item) => item.key === asked) ? asked : "agents";

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-5 sm:p-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-black tracking-tight">AI Control</h1>
          <p className="mt-1 text-sm text-muted-foreground">Your agents, when they work, and what they are connected to.</p>
        </div>
        <Link to={`/app/w/${ws.id}/daily-plan`} className="inline-flex h-10 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90"><CalendarClock className="h-4 w-4" />Today's plan</Link>
      </div>

      <div role="tablist" aria-label="AI control sections" className="flex w-fit max-w-full gap-1 overflow-x-auto rounded-xl border bg-card p-1">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setParams(key === "agents" ? {} : { tab: key }, { replace: true })}
            className={`inline-flex h-10 shrink-0 items-center gap-2 rounded-lg px-4 text-sm font-medium transition ${tab === key ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:bg-accent hover:text-foreground"}`}>
            <Icon className="h-4 w-4" />{label}
          </button>
        ))}
      </div>

      <div key={tab} role="tabpanel" className="animate-fade-up">
        {tab === "agents" && <AgentControlPanel wsId={ws.id} initial={voice ? "voice" : null} />}
        {tab === "daily" && <section className="max-w-3xl rounded-2xl border bg-card p-5 sm:p-6"><DailyAiSettings wsId={ws.id} /></section>}
        {tab === "connections" && <div className="max-w-3xl"><ConnectorsSettings wsId={ws.id} onOpenVoice={() => setParams({ agent: "voice" }, { replace: true })} /></div>}
      </div>
    </div>
  );
}
