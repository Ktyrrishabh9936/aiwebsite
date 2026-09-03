import { useEffect, useRef, useState } from "react";
import { Loader2, MessageSquare, Send, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { API } from "../lib/api";

export function ManagerChatWidget({ ws }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([
    { role: "assistant", content: `I'm your AI manager for ${ws.name}. Ask me about CRM, payments, leads, strategy, or tasks.` },
  ]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [unread, setUnread] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    setMessages([{ role: "assistant", content: `I'm your AI manager for ${ws.name}. Ask me about CRM, payments, leads, strategy, or tasks.` }]);
    setUnread(false);
  }, [ws.id, ws.name]);

  useEffect(() => {
    if (open) {
      setUnread(false);
      scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
    }
  }, [messages, open]);

  const send = async (e) => {
    e?.preventDefault();
    const msg = input.trim();
    if (!msg || streaming) return;
    const history = messages.slice(-6);
    setMessages((current) => [...current, { role: "user", content: msg }, { role: "assistant", content: "" }]);
    setInput("");
    setStreaming(true);
    try {
      const res = await fetch(`${API}/workspaces/${ws.id}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("arevei_token")}` },
        body: JSON.stringify({ message: msg, history, model_id: ws.model_id }),
      });
      if (!res.ok || !res.body) throw new Error("Chat failed");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        setMessages((current) => {
          const copy = [...current];
          copy[copy.length - 1] = { role: "assistant", content: copy[copy.length - 1].content + chunk };
          return copy;
        });
      }
      if (!open) setUnread(true);
    } catch (err) {
      toast.error("Manager chat failed");
      setMessages((current) => current.filter((_, index) => index !== current.length - 1));
    } finally {
      setStreaming(false);
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
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
            {messages.map((message, index) => (
              <div key={index} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[86%] rounded-md px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap ${message.role === "user" ? "bg-primary text-primary-foreground" : "bg-secondary"}`}>
                  {message.content || (streaming && index === messages.length - 1 ? <Loader2 className="w-4 h-4 animate-spin" /> : "")}
                </div>
              </div>
            ))}
          </div>
          <form onSubmit={send} className="p-3 border-t flex items-center gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask anything..."
              className="flex-1 h-10 px-3 rounded-full bg-background border border-border text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
            <button type="submit" disabled={streaming || !input.trim()} className="grid place-items-center w-10 h-10 rounded-full bg-primary text-primary-foreground disabled:opacity-50" title="Send">
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
