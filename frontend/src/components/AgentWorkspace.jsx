import { useEffect, useRef, useState } from "react";
import { Bot, Boxes, Brain, Building2, Code2, FileText, LayoutDashboard, ListChecks, Loader2, Mic, MicOff, Send, Sparkles, Users, Workflow, CheckCircle2, AlertCircle, Clock3, ArrowUpRight } from "lucide-react";
import { useAiStatus, aiErrorMessage } from "./AiStatus";
import { ChatText } from "./ChatText";
import { conversationId, loadManagerConversation, getManagerRun, newManagerId } from "../lib/managerAgent";
import "./AgentWorkspace.css";

const sections = [
  { name: "Overview", icon: LayoutDashboard, description: "The big picture", prompt: "Give me an overview of this workspace and its priorities.", color: "#a9bfff" },
  { name: "Projects", icon: Boxes, description: "Ideas into outcomes", prompt: "Help me plan the next steps for my projects.", color: "#baabff" },
  { name: "Properties", icon: Building2, description: "Your portfolio", prompt: "Help me work on my properties.", color: "#e7b1ee" },
  { name: "Brain", icon: Brain, description: "Business knowledge", prompt: "Summarize what you know about my business and any knowledge gaps.", color: "#89d8f1" },
  { name: "AI Agents", icon: Bot, description: "Your specialist team", prompt: "Help me understand which agents can help with my priorities.", color: "#8be2c7" },
  { name: "Tasks", icon: ListChecks, description: "What happens next", prompt: "Help me prioritize my tasks and decide what to do next.", color: "#e8d59b" },
  { name: "Blogs", icon: FileText, description: "Your content studio", prompt: "Help me plan blog content for my business.", color: "#f3b4aa" },
  { name: "Blog System", icon: Code2, description: "Content on your site", prompt: "Help me integrate the blog system into my website.", color: "#c4aafa" },
  { name: "Workflows", icon: Workflow, description: "Connected processes", prompt: "Help me improve my business workflows.", color: "#96bffa" },
  { name: "CRM", icon: Users, description: "Customer relationships", prompt: "Review my CRM leads and suggest who needs attention.", color: "#9edbb1" },
];

export function AgentWorkspace({ ws, active }) {
  const status = useAiStatus(ws);
  const [selected, setSelected] = useState(null);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [voiceError, setVoiceError] = useState("");
  const [conversation] = useState(() => conversationId(ws.id));
  const [activity, setActivity] = useState([]);
  const [lastRun, setLastRun] = useState(null);
  const [activityError, setActivityError] = useState("");
  const recognitionRef = useRef(null);
  const inputRef = useRef(null);
  const scrollRef = useRef(null);
  const pendingRef = useRef(false);
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  useEffect(() => {
    let live = true;
    loadManagerConversation(ws.id, conversation).then((data) => {
      if (!live || pendingRef.current) return;
      setMessages(data.messages || []);
      setActivity((data.runs || []).flatMap((run) => run.events || []));
      setLastRun(data.runs?.at(-1) || null);
    }).catch(() => { if (live) setActivityError("Saved work could not be loaded. New work will still appear here."); });
    return () => { live = false; };
  }, [ws.id, conversation]);

  const monitoredRuns = [...new Set([lastRun?.run_id, ...activity.filter((event) => event.status === "delegated").map((event) => event.run_id)].filter(Boolean))].join(",");
  useEffect(() => {
    if (!active || !monitoredRuns || busy) return;
    let live = true;
    const refresh = async () => {
      try {
        const runs = await Promise.all(monitoredRuns.split(",").map((id) => getManagerRun(ws.id, id)));
        if (!live) return;
        setActivity((current) => [...current.filter((event) => !runs.some((run) => run.run_id === event.run_id)), ...runs.flatMap((run) => run.events || [])].sort((a, b) => (a.at || "").localeCompare(b.at || "")));
        setLastRun((current) => runs.find((run) => run.run_id === current?.run_id) || current);
        setActivityError("");
      } catch { if (live) setActivityError("Work status could not refresh. Showing the last confirmed activity."); }
    };
    const timer = setInterval(refresh, 5000);
    refresh();
    return () => { live = false; clearInterval(timer); };
  }, [active, busy, ws.id, monitoredRuns]);

  function receiveActivity(event) {
    setActivity((current) => [...current.filter((item) => item.event_id !== event.event_id), event]);
    setLastRun((current) => ({ ...current, run_id: event.run_id, status: event.type === "run_finished" ? event.status : "running" }));
    if (event.type === "run_finished" && event.status !== "completed") setActivityError(event.label);
  }

  const finishedRuns = new Map(activity.filter((event) => event.type === "run_finished").map((event) => [event.run_id, event.status]));
  const operations = [...activity.reduce((map, event) => {
    if (event.operation_id) map.set(`${event.run_id}:${event.operation_id}`, event);
    return map;
  }, new Map()).values()].map((operation) => operation.status === "running" && finishedRuns.has(operation.run_id)
    ? { ...operation, status: "failed", summary: "Execution stopped; this action's outcome is not confirmed." } : operation);
  const runningOperation = [...operations].reverse().find((operation) => operation.status === "running");
  const currentSection = runningOperation?.section;
  const completedWrites = operations.filter((operation) => operation.writes && operation.status === "completed" && !operation.reused).length;
  const delegated = operations.filter((operation) => operation.status === "delegated" && !["completed", "failed", "cancelled", "no_answer", "busy"].includes(operation.job_status));

  useEffect(() => { scrollRef.current?.scrollTo?.(0, scrollRef.current.scrollHeight); }, [messages, active]);
  useEffect(() => {
    if (!active) { recognitionRef.current?.abort(); setListening(false); }
    return () => { recognitionRef.current?.abort(); };
  }, [active]);

  function selectSection(section) {
    setSelected(section);
    inputRef.current?.focus();
  }

  function toggleVoice() {
    if (listening) { recognitionRef.current?.stop(); return; }
    if (!SpeechRecognition) return;
    setVoiceError("");
    const recognition = new SpeechRecognition();
    recognitionRef.current = recognition;
    recognition.lang = navigator.language || "en-US";
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results).map((result) => result[0].transcript).join(" ");
      setInput((value) => `${value}${value ? " " : ""}${transcript}`);
      inputRef.current?.focus();
    };
    recognition.onend = () => setListening(false);
    recognition.onerror = (event) => {
      setListening(false);
      if (event.error !== "aborted") setVoiceError(event.error === "not-allowed" ? "Microphone access was denied. Allow access in your browser or type below." : "Voice input could not finish. Please try again or type below.");
    };
    try { recognition.start(); setListening(true); }
    catch { setVoiceError("Voice input is unavailable. You can still type your message."); }
  }

  async function send(event) {
    event.preventDefault();
    const text = input.trim();
    if (!text || pendingRef.current) return;
    pendingRef.current = true;
    recognitionRef.current?.stop();
    const message = selected ? `[Workspace section: ${selected.name}] ${text}` : text;
    const history = messages.slice(-6).map(({ role, content, request }) => ({ role, content: request || content }));
    setMessages((current) => [...current, { role: "user", content: text, request: message, section: selected?.name }, { role: "assistant", content: "" }]);
    setInput("");
    setBusy(true);
    const update = (content) => setMessages((current) => [...current.slice(0, -1), { role: "assistant", content }]);
    setActivityError("");
    try { await status.run(message, history, update, {
      agentMode: true, conversationId: conversation, requestId: newManagerId(), onEvent: receiveActivity,
    }); }
    catch (error) { update(aiErrorMessage(error)); }
    finally { setBusy(false); pendingRef.current = false; }
  }

  const statusLabel = busy ? (runningOperation?.label || "Manager is choosing the next action") : ({ loading: "Loading AI configuration", checking: "Connecting", working: "Last request succeeded", failed: "Connection needs attention", missing: "Provider setup needed", untested: "Ready for your first message" }[status.state]);

  return (
    <div className="agent-space">
      <section className="agent-universe" aria-label="Workspace galaxy">
        <div className="agent-space-heading"><span className="agent-eyebrow">ONE WORKSPACE. CONNECTED INTELLIGENCE.</span><h1>Your workspace, in orbit.</h1><p>Set the direction. Work through your AI manager.</p></div>
        <div className="agent-map">
          <svg className="agent-connections" viewBox="0 0 800 600" preserveAspectRatio="none" aria-hidden="true">
            <ellipse cx="400" cy="300" rx="295" ry="230" />
            <ellipse cx="400" cy="300" rx="205" ry="160" />
            {sections.map((section, i) => {
              const angle = (i * 36 - 90) * Math.PI / 180;
              return <line key={section.name} x1="400" y1="300" x2={400 + 295 * Math.cos(angle)} y2={300 + 230 * Math.sin(angle)} className={currentSection === section.name ? "is-working" : selected?.name === section.name ? "is-selected" : ""} />;
            })}
          </svg>
          <button type="button" className={`agent-core ${busy ? "is-thinking" : ""}`} onClick={() => selectSection(null)} aria-label="Focus AI manager on the whole workspace" aria-pressed={!selected}>
            <span className="agent-core-orb"><Sparkles size={30} /></span><strong>AI Manager</strong><span>{busy ? "Thinking…" : "Your point of connection"}</span>
          </button>
          {sections.map((section, i) => {
            const angle = (i * 36 - 90) * Math.PI / 180;
            const working = currentSection === section.name;
            const waiting = delegated.some((operation) => operation.section === section.name);
            return <button type="button" key={section.name} className={`agent-node ${selected?.name === section.name ? "is-selected" : ""} ${working ? "is-working" : ""} ${waiting ? "is-waiting" : ""}`} style={{ left: `${50 + 36.875 * Math.cos(angle)}%`, top: `${50 + 38.333 * Math.sin(angle)}%`, "--node-color": section.color }} onClick={() => selectSection(section)} aria-pressed={selected?.name === section.name} aria-label={`${section.name}${working ? " — working" : waiting ? " — waiting for outcome" : ""}`}>
              <span className="agent-node-icon">{working ? <Loader2 size={20} className="animate-spin" /> : <section.icon size={20} />}</span><strong>{section.name}</strong><small>{working ? runningOperation.agent : waiting ? "Waiting for outcome" : section.description}</small>
            </button>;
          })}
        </div>
        <div className="agent-map-footer"><span><i /> {completedWrites} saved changes · {delegated.length} pending delegations</span><span>Activity reflects actual application work</span></div>
        <section className="agent-work-panel" aria-label="Agent work activity">
          <header><div><h2>Team activity</h2><p>Confirmed actions and specialist handovers</p></div><span>{busy ? "Working" : lastRun?.status === "completed" ? "Request finished" : "Work history"}</span></header>
          {activityError && <p className="agent-error" role="alert">{activityError}</p>}
          {!operations.length ? <p className="agent-work-empty">Ask your manager to read information, update a lead, or coordinate a follow-up. Each action will appear here.</p> :
            <ol aria-live="polite">{operations.slice(-24).reverse().map((operation) => {
              const waiting = operation.status === "delegated";
              const failed = operation.status === "failed" || waiting && ["failed", "cancelled", "no_answer", "busy"].includes(operation.job_status);
              const done = operation.status === "completed" || waiting && operation.job_status === "completed";
              const Icon = failed ? AlertCircle : done ? CheckCircle2 : operation.status === "running" ? Loader2 : Clock3;
              return <li key={`${operation.run_id}:${operation.operation_id}`} data-status={failed ? "failed" : done ? "completed" : operation.status}>
                <Icon size={16} className={operation.status === "running" ? "animate-spin" : ""} />
                <div><strong>{operation.label}</strong><small>{operation.agent} · {operation.section}</small><p>{waiting ? `Qualification: ${operation.job_status || operation.job?.state || "pending"}` : operation.summary || "Working…"}</p></div>
                {operation.link && <a href={operation.link} aria-label={`Open result: ${operation.label}`} title="Open saved record"><ArrowUpRight size={16} /></a>}
              </li>;
            })}</ol>}
        </section>
      </section>

      <section className="agent-conversation" aria-label="AI manager conversation">
        <header className="agent-chat-heading"><span className="agent-chat-mark"><Sparkles size={20} /></span><div><h2>AI Manager</h2><p role="status">{statusLabel}</p></div><span className="agent-chat-tag">AGENT MODE</span></header>
        <div className="agent-focus"><span>Conversation focus</span><button onClick={() => selectSection(null)} title="Reset to whole workspace">{selected?.name || "Whole workspace"}{selected && " ×"}</button></div>
        <div className="agent-messages" ref={scrollRef} role="log" aria-label="Messages" aria-live="polite" aria-busy={busy}>
          {!messages.length && <div className="agent-welcome"><span className="agent-eyebrow">LET’S MAKE THINGS HAPPEN</span><h3>What would you like<br />to work on?</h3><p>I’m your AI manager for {ws.name}. Talk to me about your business, explore a section, or tell me what you want to achieve.</p><div className="agent-suggestions">{["What should I focus on today?", "Help me plan my next campaign", "Summarize my business strategy"].map((prompt) => <button key={prompt} onClick={() => { setInput(prompt); inputRef.current?.focus(); }}>{prompt}<span>↗</span></button>)}</div></div>}
          {messages.map((message, i) => <div key={i} className={`agent-message ${message.role}`}><div className="agent-message-label">{message.role === "user" ? "You" : "AI Manager"}{message.section && ` · ${message.section}`}</div>{message.content ? <ChatText text={message.content} /> : <span className="agent-thinking"><Loader2 size={16} className="animate-spin" /> Thinking…</span>}</div>)}
        </div>
        <form className="agent-composer" onSubmit={send}>
          {selected && <button type="button" className="agent-context-prompt" onClick={() => { setInput(selected.prompt); inputRef.current?.focus(); }}>Ask about {selected.name} ↗</button>}
          {(voiceError || status.detail) && <p className="agent-error" role="alert">{voiceError || status.detail}</p>}
          <div className="agent-input-box"><textarea ref={inputRef} aria-label="Message AI manager" value={input} onChange={(event) => setInput(event.target.value)} placeholder={selected ? `Talk to your manager about ${selected.name.toLowerCase()}…` : "Tell your manager what you have in mind…"} rows={3} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(event); } }} /><div className="agent-input-actions"><button type="button" className={`agent-mic ${listening ? "is-listening" : ""}`} onClick={toggleVoice} disabled={!SpeechRecognition || busy} aria-label={listening ? "Stop voice input" : "Start voice input"} aria-pressed={listening}>{listening ? <MicOff size={17} /> : <Mic size={17} />}<span>{listening ? "Listening…" : "Speak"}</span></button><button className="agent-send" type="submit" disabled={!input.trim() || busy || status.state === "checking"} aria-label="Send message">{busy ? <Loader2 size={17} className="animate-spin" /> : <Send size={17} />}</button></div></div>
          <p className="agent-composer-hint">{!SpeechRecognition ? "Voice input isn’t supported in this browser. Type to chat." : "Speak or type · Review your words, then send"}</p>
        </form>
      </section>
    </div>
  );
}
