import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { ArrowUpRight, Loader2, MessageSquare, Send, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { AiStatus, useAiStatus, aiErrorMessage } from "./AiStatus";
import { ChatText } from "./ChatText";
import { conversationId, loadManagerConversation, newManagerId } from "../lib/managerAgent";

// Route segment -> AI Manager section, so the manager starts from the page the owner is looking at.
const PAGE_SECTIONS = { "": "Overview", crm: "CRM", customers: "Customers", properties: "Properties", "products-services": "Products",
  projects: "Projects", tasks: "Tasks", manager: "Overview", agents: "AI Agents", qualification: "Qualification", brain: "Brain",
  workflows: "Workflows", blogs: "Blogs", embed: "Blogs", settings: "Settings", setup: "Settings" };

export function pageContext(pathname, search) {
  const section = PAGE_SECTIONS[pathname.split("/")[4] || ""];
  const lead = new URLSearchParams(search).get("lead");
  return [section && `[Workspace section: ${section}]`, /^[a-f0-9]{24}$/i.test(lead || "") && `[Viewing lead id: ${lead}]`].filter(Boolean).join(" ");
}

const withoutContext = (text = "") => text.replace(/^(\[(Workspace section|Viewing lead id):[^\]]*\]\s*)+/, "");

export function ManagerChatWidget({ ws }) {
  const aiStatus = useAiStatus(ws);
  const location = useLocation();
  const welcome = useMemo(() => ({ role: "assistant", content: `I'm your AI manager for ${ws.name}. I can work on any page for you: leads, customers, payments and receipts, products, properties, tasks, Brain, forms and blogs.` }), [ws.name]);
  const conversation = useMemo(() => conversationId(ws.id), [ws.id]);
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([welcome]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [progress, setProgress] = useState("");
  const [unread, setUnread] = useState(false);
  const scrollRef = useRef(null);
  const pendingRef = useRef(false);

  // Shares memory with Agent Mode: the same conversation continues in either view.
  useEffect(() => {
    let live = true;
    setMessages([welcome]);
    setUnread(false);
    loadManagerConversation(ws.id, conversation).then((data) => {
      if (live && !pendingRef.current && data.messages?.length) setMessages([welcome, ...data.messages.slice(-20).map((message) => ({ ...message, content: withoutContext(message.content) }))]);
    }).catch(() => { /* A fresh conversation still works. */ });
    return () => { live = false; };
  }, [ws.id, conversation, welcome]);

  useEffect(() => {
    if (open) {
      setUnread(false);
      scrollRef.current?.scrollTo?.(0, scrollRef.current.scrollHeight);
    }
  }, [messages, open, progress]);

  const send = async (e) => {
    e?.preventDefault();
    const msg = input.trim();
    if (!msg || pendingRef.current || aiStatus.state === "checking") return;
    pendingRef.current = true;
    const context = pageContext(location.pathname, location.search);
    const actions = [];
    const setLast = (patch) => setMessages((current) => [...current.slice(0, -1), { ...current[current.length - 1], ...patch }]);
    setMessages((current) => [...current, { role: "user", content: msg }, { role: "assistant", content: "", actions }]);
    setInput("");
    setStreaming(true);
    const onEvent = (event) => {
      if (event.type === "tool_started") setProgress(event.label);
      if (event.type === "tool_finished" && event.writes && ["completed", "delegated", "failed"].includes(event.status) && !event.reused) {
        actions.push({ id: event.operation_id, label: event.label, link: event.link, status: event.status, summary: event.summary });
        setLast({ actions: [...actions] });
      }
    };
    try {
      await aiStatus.run(context ? `${context} ${msg}` : msg, [], (text) => setLast({ content: text }), {
        agentMode: true, conversationId: conversation, requestId: newManagerId(), onEvent,
      });
      if (!open) setUnread(true);
    } catch (err) {
      const explanation = aiErrorMessage(err);
      toast.error(explanation);
      setLast({ content: explanation });
    } finally {
      setStreaming(false);
      setProgress("");
      pendingRef.current = false;
    }
  };

  return (
    <div className="fixed bottom-5 right-5 z-40 flex flex-col items-end gap-3">
      {open && (
        <div className="w-[calc(100vw-2.5rem)] max-w-sm h-[560px] max-h-[calc(100vh-7rem)] rounded-xl border bg-card shadow-2xl overflow-hidden flex flex-col">
          <div className="h-12 px-4 border-b flex items-center justify-between">
            <div className="flex items-center gap-2 min-w-0">
              <Sparkles className="w-4 h-4 text-primary shrink-0" />
              <span className="font-display font-bold text-sm truncate">AI Manager</span>
            </div>
            <button onClick={() => setOpen(false)} className="grid place-items-center w-8 h-8 rounded-md hover:bg-accent text-muted-foreground" title="Close manager chat">
              <X className="w-4 h-4" />
            </button>
          </div>
          <AiStatus status={aiStatus} busy={streaming} />
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3" role="log" aria-live="polite" aria-busy={streaming}>
            {messages.map((message, index) => (
              <div key={index} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[86%] rounded-md px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap ${message.role === "user" ? "bg-primary text-primary-foreground" : "bg-secondary"}`}>
                  {message.content ? (message.role === "assistant" ? <ChatText text={message.content} /> : message.content) : (streaming && index === messages.length - 1 ? <span className="flex items-center gap-2 text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin shrink-0" />{progress || "Thinking…"}</span> : "")}
                  {message.actions?.length > 0 && (
                    <ul className="mt-2 space-y-1 border-t border-border/60 pt-2 text-xs" aria-label="Changes made">
                      {message.actions.map((action) => (
                        <li key={action.id} className={`flex items-center gap-1.5 ${action.status === "failed" ? "text-amber-600" : "text-emerald-700 dark:text-emerald-400"}`}>
                          <span className="min-w-0 flex-1 truncate" title={action.summary}>{action.status === "failed" ? "Not saved: " : action.status === "delegated" ? "Started: " : "Saved: "}{action.label}</span>
                          {action.link && action.status !== "failed" && <a href={action.link} className="shrink-0 hover:underline inline-flex items-center" aria-label={`Open ${action.label}`}>Open <ArrowUpRight className="w-3 h-3" /></a>}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            ))}
          </div>
          <form onSubmit={send} className="p-3 border-t flex items-center gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask or tell me what to do…"
              aria-label="Message AI manager"
              className="flex-1 h-10 px-3 rounded-full bg-background border border-border text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
            <button type="submit" disabled={streaming || aiStatus.state === "checking" || !input.trim()} className="grid place-items-center w-10 h-10 rounded-full bg-primary text-primary-foreground disabled:opacity-50" title="Send">
              {streaming ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </form>
        </div>
      )}
      <button
        onClick={() => setOpen((current) => !current)}
        className="relative grid place-items-center w-14 h-14 rounded-full bg-primary text-primary-foreground shadow-xl hover:scale-105 transition"
        title={open ? "Close AI manager" : "Open AI manager"}
      >
        <MessageSquare className="w-6 h-6" />
        {unread && <span className="absolute right-1 top-1 w-3 h-3 rounded-full bg-amber-400 ring-2 ring-background" />}
      </button>
    </div>
  );
}
