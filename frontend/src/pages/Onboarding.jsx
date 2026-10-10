import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Brain, ArrowRight, Loader2 } from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../lib/api";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";

export default function Onboarding() {
  const nav = useNavigate();
  const [url,setUrl] = useState("");
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const submit = async event => {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const { data } = await api.post("/workspaces", { website_url: url });
      localStorage.setItem("arevei_onboarded", "1");
      toast.success("Workspace created. Your business Brain is training.");
      nav(`/app/w/${data.id}/sales-strategy`);
    } catch (err) { setError(formatError(err.response?.data?.detail) || "Workspace could not be created"); }
    finally { setBusy(false); }
  };
  return <div className="min-h-screen flex flex-col app-shell"><header className="h-20 px-6 flex items-center justify-between border-b bg-card"><Logo/><ThemeToggle/></header><main className="flex-1 grid place-items-center p-6"><div className="w-full max-w-xl"><span className="w-14 h-14 rounded-xl bg-primary/10 text-primary grid place-items-center mb-6"><Brain size={27}/></span><p className="app-eyebrow">Meet your sales leadership team</p><h1 className="text-3xl sm:text-4xl font-bold">Let's understand your business.</h1><p className="text-sm text-muted-foreground mt-4 leading-7">Start with your website to train the Brain. Next, configure voice qualification or skip it, then tell your manager about your offer, team, budget and revenue goals.</p><ol className="grid sm:grid-cols-3 gap-3 mt-6 text-xs">{["1. Business Brain","2. Optional voice setup","3. Sales context & strategy"].map(t => <li className="border rounded-lg p-3 bg-card" key={t}>{t}</li>)}</ol><form onSubmit={submit} className="rounded-xl border bg-card p-6 mt-6 space-y-4"><label className="block text-xs font-semibold">Company website<input type="url" required autoComplete="url" placeholder="https://yourcompany.com" value={url} onChange={e => setUrl(e.target.value)} className="block w-full border rounded-lg bg-background p-3 mt-2 text-sm"/></label>{error && <p role="alert" className="text-xs text-destructive">{error}</p>}<button disabled={busy} className="w-full rounded-lg bg-primary text-primary-foreground px-5 py-3 text-sm font-semibold flex justify-center items-center gap-2">{busy ? <Loader2 size={16} className="animate-spin"/> : <ArrowRight size={16}/>} {busy ? "Creating workspace..." : "Train Brain & continue"}</button></form><button onClick={() => nav("/app")} className="text-xs text-muted-foreground mt-5">Open an existing workspace</button></div></main></div>;
}
