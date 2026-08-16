import { useEffect, useRef, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { motion } from "framer-motion";
import { Send, Sparkles, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import api, { API } from "../../lib/api";

export default function Manager() {
  const { ws, refresh } = useOutletContext();
  const [messages, setMessages] = useState([
    { role: "assistant", content: `I'm your growth manager for ${ws.name}. Ask me about strategy, or say "draft a blog about ..." to direct the content agent.` },
  ]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [genning, setGenning] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => { scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight); }, [messages]);

  const send = async (e) => {
    e?.preventDefault();
    const msg = input.trim();
    if (!msg || streaming) return;
    const history = messages.slice(-6);
    setMessages((m) => [...m, { role: "user", content: msg }, { role: "assistant", content: "" }]);
    setInput("");
    setStreaming(true);
    try {
      const res = await fetch(`${API}/workspaces/${ws.id}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("arevei_token")}` },
        body: JSON.stringify({ message: msg, history, model_id: ws.model_id }),
      });
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        setMessages((m) => {
          const copy = [...m];
          copy[copy.length - 1] = { role: "assistant", content: copy[copy.length - 1].content + chunk };
          return copy;
        });
      }
    } catch (err) {
      toast.error("Chat failed");
    } finally {
      setStreaming(false);
    }
  };

  const genRoadmap = async () => {
    setGenning(true);
    try { await api.post(`/workspaces/${ws.id}/roadmap`); await refresh(); toast.success("Roadmap regenerated"); }
    catch { toast.error("Failed"); }
    finally { setGenning(false); }
  };

  const roadmap = ws.roadmap || [];

  return (
    <div className="grid lg:grid-cols-[1fr_380px] h-[calc(100vh-4rem)]">
      {/* Roadmap */}
      <div className="overflow-y-auto p-6 sm:p-10 border-r border-border">
        <div className="flex items-end justify-between mb-6 flex-wrap gap-3">
          <div>
            <h1 className="font-display text-3xl font-black tracking-tight">Growth Roadmap</h1>
            <p className="text-muted-foreground mt-1">12-month plan owned by the AI manager.</p>
          </div>
          {ws.brain_status === "ready" && (
            <button onClick={genRoadmap} disabled={genning} data-testid="regen-roadmap-btn" className="inline-flex items-center gap-2 px-4 h-10 rounded-full border border-border hover:bg-accent text-sm font-medium disabled:opacity-60">
              {genning ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />} {roadmap.length ? "Regenerate" : "Generate"}
            </button>
          )}
        </div>

        {ws.strategy_summary && (
          <div className="border border-primary/30 bg-primary/5 rounded-md p-5 mb-6">
            <div className="text-xs uppercase tracking-[0.2em] font-bold text-primary mb-2">Strategy thesis</div>
            <p className="leading-relaxed">{ws.strategy_summary}</p>
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
      </div>

      {/* Chat */}
      <div className="flex flex-col h-[calc(100vh-4rem)] bg-card/40">
        <div className="px-5 py-4 border-b border-border flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-primary" />
          <span className="font-display font-bold">Manager chat</span>
        </div>
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-5 space-y-4" data-testid="chat-messages">
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[85%] rounded-md px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${m.role === "user" ? "bg-primary text-primary-foreground" : "bg-secondary"}`}>
                {m.content || (streaming && i === messages.length - 1 ? <Loader2 className="w-4 h-4 animate-spin" /> : "")}
              </div>
            </div>
          ))}
        </div>
        <form onSubmit={send} className="p-4 border-t border-border flex items-center gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask the manager…"
            data-testid="chat-input"
            className="flex-1 h-11 px-4 rounded-full bg-background border border-border text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <button type="submit" disabled={streaming} data-testid="chat-send" className="grid place-items-center w-11 h-11 rounded-full bg-primary text-primary-foreground disabled:opacity-60 shrink-0">
            {streaming ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </form>
      </div>
    </div>
  );
}
