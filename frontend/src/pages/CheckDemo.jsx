import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Loader2, PhoneCall } from "lucide-react";
import { toast } from "sonner";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";
import api, { formatError } from "../lib/api";

export default function CheckDemo() {
  const [form, setForm] = useState({ name: "", email: "", phone: "" });
  const [loading, setLoading] = useState(false);
  const [demo, setDemo] = useState(null);

  useEffect(() => {
    if (!demo?.lead_id) return undefined;
    let active = true;
    const loadResult = async () => {
      try {
        const response = await api.get(`/public/check-demo/${demo.lead_id}`);
        if (active) setDemo((current) => ({ ...current, result: response.data }));
      } catch { /* The initial call can take a moment to create its record. */ }
    };
    loadResult();
    const interval = window.setInterval(loadResult, 5000);
    return () => { active = false; window.clearInterval(interval); };
  }, [demo?.lead_id]);

  const update = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const submit = async (event) => {
    event.preventDefault();
    try {
      setLoading(true);
      const response = await api.post("/public/check-demo", form);
      setDemo({ lead_id: response.data.lead_id });
    } catch (error) {
      toast.error(formatError(error.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen grain">
      <header className="h-16 px-6 flex items-center justify-between border-b border-border glass">
        <Logo to={null} className="text-lg" />
        <ThemeToggle />
      </header>
      <main className="max-w-xl mx-auto px-6 py-20">
        {demo ? (
          <DemoResult result={demo.result} />
        ) : (
          <section className="rounded-xl border bg-card p-7 sm:p-9">
            <div className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.2em] font-bold text-primary"><PhoneCall className="w-4 h-4" /> AI demo call</div>
            <h1 className="mt-4 font-display text-3xl sm:text-4xl font-black tracking-tight">Check if Arevei fits your business</h1>
            <p className="mt-3 text-muted-foreground leading-relaxed">Share your details and our AI agent will call to learn what you need.</p>
            <form onSubmit={submit} className="mt-8 space-y-4">
              {[['name', 'Name', 'Your name', 'text'], ['email', 'Email', 'you@company.com', 'email'], ['phone', 'Phone Number', '+91 98765 43210', 'tel']].map(([key, label, placeholder, type]) => (
                <label key={key} className="block space-y-1.5">
                  <span className="text-sm font-semibold">{label}</span>
                  <input required type={type} value={form[key]} onChange={(event) => update(key, event.target.value)} placeholder={placeholder} className="w-full h-11 px-3 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/30" />
                </label>
              ))}
              <button disabled={loading} className="w-full inline-flex items-center justify-center gap-2 h-12 rounded-lg bg-primary text-primary-foreground font-semibold disabled:opacity-60">
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <PhoneCall className="w-4 h-4" />} Call me for the demo
              </button>
            </form>
          </section>
        )}
      </main>
    </div>
  );
}

function DemoResult({ result }) {
  const finished = result?.completed;
  const qualified = result?.qualification_status === "qualified";
  return (
    <section className="rounded-xl border bg-card p-7 sm:p-9">
      <div className={`w-12 h-12 rounded-full grid place-items-center ${finished ? qualified ? "bg-emerald-500/10 text-emerald-500" : "bg-destructive/10 text-destructive" : "bg-primary/10 text-primary"}`}>
        {finished ? <CheckCircle2 className="w-6 h-6" /> : <Loader2 className="w-6 h-6 animate-spin" />}
      </div>
      <h1 className="mt-5 font-display text-3xl font-black">{finished ? "Demo call details" : "Your AI demo call is in progress"}</h1>
      <p className="mt-3 text-muted-foreground leading-relaxed">{finished ? "Your call has been analyzed." : "Our AI agent is calling you now. This page will update when the conversation is complete."}</p>
      {finished && (
        <div className="mt-7 space-y-4 text-left">
          <div className={`rounded-lg border p-4 text-center font-bold uppercase tracking-wide ${qualified ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-500" : "border-destructive/30 bg-destructive/10 text-destructive"}`}>
            {qualified ? "Qualified" : "Not Qualified"}
          </div>
          <div className="grid gap-3 text-sm">
            <Detail label="Call status" value={result.call_status} />
            <Detail label="Call time" value={result.call_timestamp ? new Date(result.call_timestamp).toLocaleString() : "Not available"} />
            <Detail label="Duration" value={result.duration ? `${result.duration}s` : "Not available"} />
            <Detail label="AI summary" value={result.summary || "Not available"} />
          </div>
        </div>
      )}
      <Link to="/" className="mt-7 inline-flex items-center gap-2 text-sm font-semibold text-primary"><ArrowLeft className="w-4 h-4" /> Back to Arevei</Link>
    </section>
  );
}

function Detail({ label, value }) {
  return <div className="rounded-lg border bg-background p-3"><div className="text-[11px] font-bold uppercase text-muted-foreground">{label}</div><div className="mt-1 font-semibold capitalize">{String(value || "-").replaceAll("_", " ")}</div></div>;
}