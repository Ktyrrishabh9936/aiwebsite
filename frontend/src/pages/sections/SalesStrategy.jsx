import { useEffect, useRef, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { toast } from "sonner";
import { Sparkles, Pencil, ArrowUp } from "lucide-react";
import api, { formatError } from "../../lib/api";

const topics = {
  organisation: "What is your organisation called?",
  offerings: "What do you sell, what does it cost, and why do customers choose it?",
  ideal_customer: "Who is your ideal customer, and what do they need?",
  lead_sources: "Where do leads come from, and how many arrive each month?",
  team_capacity: "Who handles sales, and how many conversations can they manage daily?",
  monthly_revenue_target: "What monthly revenue target should we plan for?",
  monthly_sales_budget: "How much can you spend on sales and marketing each month?",
  business_stage: "Are you starting from scratch or already selling?",
  offer_confidence: "Are customers buying consistently, are you testing, or are you unsure?",
  customer_feedback: "What do customers like, and why do some not buy?",
  constraints: "What challenges, resource limits or sales-cycle delays should we account for?",
};
const label = key => key.replaceAll("_", " ");
export default function SalesStrategy() {
  const { ws, refresh } = useOutletContext();
  const [conversation, setConversation] = useState(null), [answer, setAnswer] = useState("");
  const [editing, setEditing] = useState(null), [busy, setBusy] = useState("");
  const [error, setError] = useState(""), [retry, setRetry] = useState(0);
  const input = useRef(null), bottom = useRef(null);
  const generation = useRef(0);
  const base = `/workspaces/${ws.id}/sales`;
  useEffect(() => {
    let live = true;
    generation.current += 1;
    setConversation(null); setAnswer(""); setEditing(null); setError(""); setBusy("");
    api.get(`${base}/conversation`).then(({ data }) => { if (live) setConversation(data); })
      .catch(err => { if (live) setError(err.response?.status === 404 ? "Deploy the updated backend to enable the sales conversation, then reload." : formatError(err.response?.data?.detail || "Could not load the conversation.")); });
    return () => { live = false; generation.current += 1; };
  }, [base, retry]);
  useEffect(() => { bottom.current?.scrollIntoView?.({ behavior: "smooth", block: "nearest" }); }, [conversation?.revision, editing]);
  const question = editing ? { field: editing, text: topics[editing], optional: ["lead_sources", "customer_feedback", "constraints"].includes(editing) } : conversation?.question;
  const send = async (event, value = answer) => {
    event?.preventDefault(); if (!value.trim() || !question || busy) return;
    const version = generation.current;
    setBusy("answer"); setError("");
    try {
      const { data } = await api.post(`${base}/conversation`, { answer: value.trim(), field: question.field, revision: conversation.revision });
      if (version === generation.current) { setConversation(data); setAnswer(""); setEditing(null); }
    } catch (err) { if (version === generation.current) setError(formatError(err.response?.data?.detail || "Your answer could not be saved. Please try again.")); }
    finally { if (version === generation.current) setBusy(""); }
  };
  const finish = async () => {
    setBusy("strategy"); setError("");
    try {
      await api.put(`${base}/profile`, { timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC", ...conversation.draft });
      await refresh();
      if (ws.brain_status === "ready") { await api.post(`${base}/strategy`); await refresh(); toast.success("Your sales strategy is ready"); }
      else toast.success("Sales context saved. Finish Brain training to prepare your strategy.");
    } catch (err) { setError(formatError(err.response?.data?.detail || "Strategy generation failed. Your conversation is saved.")); }
    finally { setBusy(""); }
  };
  return <div className="max-w-6xl mx-auto p-4 sm:p-8 space-y-6">
    <div><p className="app-eyebrow">Your sales leadership team</p><h1 className="text-3xl font-bold">Sales strategy</h1><p className="text-sm text-muted-foreground mt-2">Talk through your business. Your agent will shape your answers into a practical sales strategy.</p></div>
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(280px,1fr)] items-start">
      <section className="rounded-2xl border bg-card overflow-hidden" aria-label="Sales strategy conversation">
        <div className="border-b p-5 flex items-center gap-3"><Sparkles size={22} className="text-primary"/><div><h2 className="font-semibold">Meet your sales strategist</h2><p className="text-xs text-muted-foreground mt-1">One question at a time. Short answers are welcome.</p></div>{conversation && <span className="ml-auto text-xs whitespace-nowrap">{conversation.answered} / {conversation.total}</span>}</div>
        <div className="p-5 space-y-4 max-h-[55dvh] overflow-y-auto" role="log" aria-label="Sales conversation messages" aria-live="polite">
          <div className="rounded-xl bg-secondary/50 p-4 text-sm leading-6">I'll help you plan around your customers, capacity and goals. I'll polish your answers as we go. You can revise the draft at any time.</div>
          {conversation?.messages?.map((message,index) => <div key={index} className={`rounded-xl p-4 text-sm leading-6 whitespace-pre-wrap break-words max-w-[95%] ${message.role === "user" ? "ml-auto bg-primary text-primary-foreground" : "bg-secondary/50"}`}><p className="text-[10px] font-semibold mb-1 opacity-70">{message.role === "user" ? "You" : "Sales strategist"}</p>{message.content}</div>)}
          {!conversation && !error && <p role="status" className="text-sm text-muted-foreground">Opening your saved conversation...</p>}
          {question && <div className="rounded-xl bg-primary/10 border border-primary/20 p-4 text-sm leading-6"><p className="font-semibold">{question.text}</p>{question.field.includes("monthly") && <p className="text-xs text-muted-foreground mt-1">Currency: {ws.currency || "INR"}. You can say “2 lakh” or “50,000”.</p>}{conversation.draft[question.field] != null && <p className="mt-2 text-xs text-muted-foreground">Current draft: {String(conversation.draft[question.field])}</p>}</div>}
          {conversation?.ready && !editing && <p className="rounded-xl bg-emerald-500/10 p-4 text-sm">Your context is ready. Review the polished brief, then complete your sales strategy.</p>}<div ref={bottom}/>
        </div>
        {error && <div role="alert" className="px-5 pb-3 text-sm text-destructive">{error}<button type="button" onClick={() => setRetry(v => v+1)} className="underline ml-2">Reload conversation</button></div>}
        {question && <form onSubmit={send} className="border-t p-4 space-y-3"><label htmlFor="sales-answer" className="sr-only">Your answer</label><textarea id="sales-answer" ref={input} value={answer} onChange={e => setAnswer(e.target.value)} disabled={!!busy} rows={3} maxLength={5000} placeholder="Tell me in your own words..." className="w-full resize-none rounded-xl border bg-background p-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary"/><div className="flex gap-2 justify-between items-center"><div>{question.optional && <button type="button" disabled={!!busy} onClick={() => send(null,"skip")} className="text-xs text-muted-foreground">I'm not sure yet — skip</button>}{editing && <button type="button" disabled={!!busy} onClick={() => { setEditing(null); setAnswer(""); }} className="text-xs underline ml-3">Cancel revision</button>}</div><button disabled={!!busy || !answer.trim()} className="inline-flex gap-2 items-center rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"><ArrowUp size={16}/>{busy === "answer" ? "Polishing..." : "Send answer"}</button></div></form>}
      </section>
      <section className="rounded-2xl border bg-card p-5 space-y-4" aria-label="Polished sales context"><h2 className="font-semibold">Your strategy brief</h2><p className="text-xs text-muted-foreground">Your answers, organised and polished as we talk.</p>
        {Object.keys(topics).filter(key => conversation?.draft[key] != null).map(key => <div key={key} className="border-b pb-3"><div className="flex justify-between gap-2"><h3 className="text-xs font-medium capitalize text-muted-foreground">{label(key)}</h3><button type="button" disabled={!!busy} aria-label={`Revise ${label(key)}`} onClick={() => { setEditing(key); setAnswer(""); setError(""); }} className="text-muted-foreground hover:text-primary"><Pencil size={13}/></button></div><p className="text-sm mt-1 whitespace-pre-wrap break-words">{String(conversation.draft[key]) || "Not provided yet"}</p></div>)}
        {conversation?.ready && <><button type="button" disabled={!!busy || !!editing} onClick={finish} className="w-full rounded-xl bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground disabled:opacity-50">{busy === "strategy" ? "Completing your strategy..." : ws.brain_status === "ready" ? "Complete sales strategy" : "Save sales context"}</button>{ws.brain_status !== "ready" && <p className="text-xs text-muted-foreground">Finish Brain training to generate the strategy. You can save your answers now.</p>}</>}
      </section>
    </div>
    <section className="rounded-xl border bg-card p-5 space-y-4"><h2 className="font-semibold">Your sales strategy</h2>{ws.sales_strategy ? <><p className="text-sm leading-7">{ws.strategy_summary}</p><div className="grid sm:grid-cols-2 gap-3">{(ws.roadmap || []).map((month,index) => <article key={index} className="rounded-lg border p-4"><p className="text-xs text-primary">Month {month.month_number || index+1}</p><h3 className="text-sm font-semibold mt-1">{month.theme}</h3><p className="text-xs text-muted-foreground mt-2">{month.goal}</p><p className="text-xs text-muted-foreground mt-2">{(month.kpis || []).join(" · ")}</p></article>)}</div></> : <p className="text-sm text-muted-foreground">Answer the strategist's questions to build your first sales plan.</p>}</section>
  </div>;
}
