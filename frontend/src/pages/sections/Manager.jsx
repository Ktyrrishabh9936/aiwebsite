import { useEffect, useRef, useState } from "react";
import { useOutletContext, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Send, Sparkles, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { AiStatus, useAiStatus, aiErrorMessage } from "../../components/AiStatus";
import { ChatText } from "../../components/ChatText";
import SalesBriefing from "../../components/SalesBriefing";
import { conversationId, newManagerId } from "../../lib/managerAgent";

export default function Manager() {
  const { ws, refresh } = useOutletContext();
  const nav = useNavigate();
  const aiStatus = useAiStatus(ws);
  const [messages, setMessages] = useState([
    { role: "assistant", content: `I'm your AI manager for ${ws.name}. Ask about your business, or tell me what to do on any page: leads, customers and payments, products, properties, tasks, Brain, forms or blogs.` },
  ]);
  const [conversation] = useState(() => conversationId(ws.id));
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [genning, setGenning] = useState(false);
  const [showRoadmap, setShowRoadmap] = useState(false);
  const [checkingInsights, setCheckingInsights] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => { scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight); }, [messages]);

  const checkInsights = async () => {
    if (checkingInsights || streaming) return;
    setCheckingInsights(true);
    setMessages(current => [...current, { role: "user", content: "Check Insights" }]);
    try {
      const { data } = await api.get(`/workspaces/${ws.id}/sales/briefing`);
      if (typeof data.total_leads !== "number") throw new Error("Invalid briefing");
      setMessages(current => [...current, data.total_leads > 0
        ? { role: "assistant", content: "Here are your current CRM insights and sales priorities.", insights: true }
        : { role: "assistant", content: "There are no leads in your CRM yet. Train your Brain with business knowledge, products, services and customer information, then build your sales strategy. Add or import leads to receive pipeline insights.", setup: true }]);
    } catch {
      setMessages(current => [...current, { role: "assistant", content: "I couldn't load the CRM insights. Please try Check Insights again." }]);
    } finally { setCheckingInsights(false); }
  };

  const send = async (e) => {
    e?.preventDefault();
    const msg = input.trim();
    if (!msg || streaming || aiStatus.state === "checking") return;
    const history = messages.slice(-6).map(({ role, content }) => ({ role, content }));
    setMessages((m) => [...m, { role: "user", content: msg }, { role: "assistant", content: "" }]);
    setInput("");
    setStreaming(true);
    try {
      await aiStatus.run(msg, history, (text) => {
        setMessages((current) => {
          const copy = [...current];
          copy[copy.length - 1] = { role: "assistant", content: text };
          return copy;
        });
      }, { agentMode: true, conversationId: conversation, requestId: newManagerId() });
    } catch (err) {
      const explanation = aiErrorMessage(err);
      toast.error(explanation);
      setMessages((current) => {
        const copy = [...current];
        copy[copy.length - 1] = { role: "assistant", content: explanation };
        return copy;
      });
    } finally {
      setStreaming(false);
    }
  };

  const genRoadmap = async () => {
    if (!ws.sales_profile) { nav(`/app/w/${ws.id}/sales-strategy`); return; }
    setGenning(true);
    try { await api.post(`/workspaces/${ws.id}/roadmap`); await refresh(); toast.success("Sales strategy updated"); }
    catch { toast.error("Failed"); }
    finally { setGenning(false); }
  };

  const roadmap = ws.sales_strategy ? ws.roadmap || [] : [];

  return (
    <div className="flex flex-col lg:flex-row h-[calc(100dvh-4rem)] min-h-0">
      {/* Roadmap */}
      {showRoadmap && <div id="manager-roadmap" className="order-last shrink-0 w-full lg:w-[360px] max-h-[40vh] lg:max-h-none overflow-y-auto p-6 border-t lg:border-t-0 lg:border-l border-border">
        <div className="flex items-end justify-between mb-6 flex-wrap gap-3">
          <div>
            <h2 className="font-display text-xl font-bold tracking-tight">Sales Strategy</h2>
            <p className="text-muted-foreground mt-1">Revenue, pipeline and conversion priorities.</p>
          </div>
          {ws.brain_status === "ready" && (
            <button onClick={genRoadmap} disabled={genning} data-testid="regen-roadmap-btn" className="inline-flex items-center gap-2 px-4 h-10 rounded-full border border-border hover:bg-accent text-sm font-medium disabled:opacity-60">
              {genning ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />} {roadmap.length ? "Update strategy" : "Sales setup"}
            </button>
          )}
        </div>

        {ws.strategy_summary && (
          <div className="border border-primary/30 bg-primary/5 rounded-md p-5 mb-6">
            <div className="text-xs uppercase tracking-[0.2em] font-bold text-primary mb-2">Strategy thesis</div>
            <p className="leading-relaxed">{ws.sales_strategy ? ws.strategy_summary : "Complete Sales Strategy setup to replace the previous website growth plan."}</p>
          </div>
        )}

        {roadmap.length === 0 ? (
          <div className="border border-dashed border-border rounded-md py-16 text-center text-muted-foreground">
            No roadmap yet. Generate one to schedule tasks.
          </div>
        ) : (
          <div className="space-y-3">
            {roadmap.map((m, i) => (
              <motion.div key={i} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: Math.min(i * 0.03, 0.3) }} className="border border-border rounded-md bg-card p-5" data-testid={`roadmap-month-${i + 1}`}>
                <div className="flex items-center gap-3 mb-2">
                  <span className="grid place-items-center w-8 h-8 rounded-md bg-primary text-primary-foreground font-display font-black text-sm">{m.month_number || i + 1}</span>
                  <div className="font-display font-bold">{m.theme}</div>
                </div>
                <p className="text-sm text-muted-foreground mb-3">{m.goal}</p>
                <div className="flex flex-wrap gap-1.5">
                  {(m.kpis || []).map((k, j) => <span key={j} className="text-[11px] px-2 py-0.5 rounded-full bg-secondary">{k}</span>)}
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>}

      {/* Chat */}
      <div className="flex flex-1 min-w-0 min-h-0 flex-col bg-card/40">
        <div className="px-5 sm:px-8 py-4 border-b border-border flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Sparkles className="w-5 h-5 text-primary shrink-0" />
            <div><h1 className="font-display text-xl font-bold">AI Manager</h1><p className="text-xs text-muted-foreground">Your business, leads, and strategy in one conversation.</p></div>
          </div>
          <button type="button" onClick={() => setShowRoadmap((open) => !open)} aria-expanded={showRoadmap} aria-controls="manager-roadmap" className="shrink-0 rounded-lg border px-3 py-2 text-xs font-medium hover:bg-accent">{showRoadmap ? "Hide roadmap" : "Sales strategy"}</button>
        </div>
        <AiStatus status={aiStatus} busy={streaming} />
        <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-5 sm:px-8 py-6 space-y-5" data-testid="chat-messages">
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[90%] sm:max-w-[85%] rounded-xl px-5 py-3.5 text-sm leading-relaxed ${m.role === "user" ? "bg-primary text-primary-foreground whitespace-pre-wrap" : "bg-secondary"}`}>
                {m.content ? (m.role === "assistant" ? <ChatText text={m.content} /> : m.content) : (streaming && i === messages.length - 1 ? <Loader2 className="w-4 h-4 animate-spin" /> : "")}
                {m.insights && <div className="mt-4"><SalesBriefing wsId={ws.id} expanded /></div>}
                {m.setup && <div className="mt-4 flex flex-wrap gap-3"><button onClick={() => nav(`/app/w/${ws.id}/brain`)} className="rounded-lg border px-3 py-2 font-semibold hover:bg-accent">Train Brain</button><button onClick={() => nav(`/app/w/${ws.id}/brain?tab=sales`)} className="rounded-lg bg-primary text-primary-foreground px-3 py-2 font-semibold">Build sales strategy</button></div>}
              </div>
            </div>
          ))}
        </div>
        <div className="px-4 py-2 border-t border-border"><button type="button" onClick={checkInsights} data-update="check-insights" disabled={checkingInsights || streaming} className="rounded-full border px-4 py-2 text-sm font-semibold hover:bg-accent disabled:opacity-60">{checkingInsights ? "Checking insights..." : "Check Insights"}</button></div>
        <form onSubmit={send} className="p-4 flex items-center gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask AI Manager…"
            data-testid="chat-input"
            className="flex-1 h-11 px-4 rounded-full bg-background border border-border text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <button type="submit" disabled={streaming || aiStatus.state === "checking"} data-testid="chat-send" className="grid place-items-center w-11 h-11 rounded-full bg-primary text-primary-foreground disabled:opacity-60 shrink-0">
            {streaming ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </form>
      </div>
    </div>
  );
}
