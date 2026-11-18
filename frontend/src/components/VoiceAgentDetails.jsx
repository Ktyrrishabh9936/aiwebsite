import { useEffect, useState } from "react";
import { Braces, Loader2, Settings, Type } from "lucide-react";
import api from "../lib/api";

const TABS = [["instructions", "Instructions", Type], ["variables", "Variables", Braces], ["settings", "Settings", Settings]];

function Label({ children }) {
  return <h4 className="mb-2 w-fit border-b border-dashed border-muted-foreground/50 pb-0.5 text-sm font-semibold text-muted-foreground">{children}</h4>;
}

function Lines({ lines }) {
  // Lines starting with "- " are shown as a list, everything else as paragraphs.
  const bullets = lines.filter((line) => line.startsWith("- "));
  return (
    <>
      {lines.filter((line) => !line.startsWith("- ")).map((line) => <p key={line} className="text-[15px] leading-7">{line}</p>)}
      {bullets.length > 0 && <ul className="list-disc space-y-1 pl-5 text-[15px] leading-7">{bullets.map((line) => <li key={line}>{line.slice(2)}</li>)}</ul>}
    </>
  );
}

/** The connected voice agent as a readable page: its greeting, what it was told to do, and what it records. */
export default function VoiceAgentDetails({ workspaceId, refreshKey }) {
  const [agent, setAgent] = useState(null);
  const [tab, setTab] = useState("instructions");
  const [full, setFull] = useState(false);

  useEffect(() => {
    let live = true;
    api.get(`/workspaces/${workspaceId}/ai-agents/voice-details`).then(({ data }) => { if (live) setAgent(data); }).catch(() => { if (live) setAgent({ available: false }); });
    return () => { live = false; };
  }, [workspaceId, refreshKey]);

  if (!agent) return <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Loading agent…</p>;
  if (!agent.available) return null;
  const sections = full ? agent.sections : agent.sections.slice(0, 4);

  return (
    <div className="overflow-hidden rounded-2xl border bg-background" aria-label="Voice agent details">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 sm:px-5">
        <p className="flex min-w-0 items-center gap-2 font-semibold"><span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary/10 text-sm font-bold text-primary">{(agent.name || "A").slice(0, 1).toUpperCase()}</span><span className="truncate">{agent.name}</span>{agent.version && <span className="text-sm font-normal text-muted-foreground">/ v{agent.version}</span>}</p>
        <div role="tablist" aria-label="Agent sections" className="flex gap-1">
          {TABS.map(([key, label, Icon]) => <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)} className={`inline-flex h-9 items-center gap-1.5 rounded-lg px-3 text-sm font-medium transition ${tab === key ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/60"}`}><Icon className="h-4 w-4" />{label}</button>)}
        </div>
      </div>

      <div className="space-y-6 p-4 sm:p-6">
        {tab === "instructions" && <>
          <div>
            <Label>Greeting</Label>
            <p className="text-[15px] leading-7">{agent.greeting.map((part) => (typeof part === "string" ? part : <code key={part.variable} className="mx-0.5 rounded-md bg-muted px-1.5 py-0.5 text-sm">{`{} ${part.variable}`}</code>))}</p>
          </div>
          <div>
            <Label>Instructions</Label>
            <div className="space-y-5">
              {sections.map((section) => <div key={section.title}><h5 className="mb-1 font-display text-lg font-bold uppercase tracking-tight">{section.title}</h5><Lines lines={section.lines} /></div>)}
            </div>
            {agent.sections.length > 4 && <button type="button" onClick={() => setFull((open) => !open)} aria-expanded={full} className="mt-4 text-sm font-semibold text-primary hover:underline">{full ? "Show less" : `Show all instructions (${agent.sections.length - 4} more sections)`}</button>}
          </div>
          {agent.note && <p className="text-xs text-muted-foreground">{agent.note}</p>}
        </>}

        {tab === "variables" && <>
          <div>
            <Label>Given to the agent before each call</Label>
            <ul className="divide-y rounded-xl border">{agent.inputs.map((item) => <li key={item.name} className="flex flex-wrap items-baseline gap-x-3 px-3 py-2 text-sm"><code className="rounded-md bg-muted px-1.5 py-0.5">{item.name}</code><span className="text-muted-foreground">{item.description}</span></li>)}</ul>
          </div>
          <div>
            <Label>Recorded by the agent after each call</Label>
            <ul className="divide-y rounded-xl border">{agent.outputs.map((item) => <li key={item.name} className="flex flex-wrap items-baseline gap-x-3 px-3 py-2 text-sm"><code className="rounded-md bg-muted px-1.5 py-0.5">{item.name}</code><span className="text-muted-foreground">{item.description}</span></li>)}</ul>
          </div>
        </>}

        {tab === "settings" && <dl className="divide-y rounded-xl border">{agent.settings.map(([name, value]) => <div key={name} className="flex items-center justify-between gap-4 px-3 py-2.5 text-sm"><dt className="text-muted-foreground">{name}</dt><dd className="font-medium">{value}</dd></div>)}</dl>}
      </div>
    </div>
  );
}
