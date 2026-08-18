import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  Rocket, Wand2, ArrowRight, ArrowLeft, Import, LayoutDashboard, Check,
  Loader2, ExternalLink, Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import api from "../lib/api";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";

const DEMO_MSG = "This is demo website content. Kindly contact the Arevei team for the website manager — vinay@arevei.com";
const demoAlert = () => toast.info(DEMO_MSG, { duration: 6000 });

function PilotScreen({ onBuild, onSkip }) {
  return (
    <motion.div key="pilot" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }} transition={{ duration: 0.5 }} className="max-w-2xl mx-auto text-center">
      <motion.div initial={{ scale: 0.8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ delay: 0.1, type: "spring" }} className="w-20 h-20 rounded-2xl bg-primary/10 text-primary grid place-items-center mx-auto mb-8">
        <Rocket className="w-9 h-9" />
      </motion.div>
      <h1 className="font-display text-4xl sm:text-5xl font-black tracking-tight">Hey, I'm Arevei.</h1>
      <p className="mt-3 text-xl text-primary font-display font-bold">I'm your Pilot.</p>
      <p className="mt-4 text-muted-foreground max-w-lg mx-auto leading-relaxed">I build, manage and grow your website end-to-end. Let's get you set up — choose how you'd like to start.</p>
      <div className="mt-10 grid sm:grid-cols-3 gap-3">
        <button onClick={onBuild} data-testid="pilot-build" className="group border border-border rounded-xl p-5 text-left hover:border-primary hover:-translate-y-1 transition-all bg-card">
          <Wand2 className="w-6 h-6 text-primary mb-3" />
          <div className="font-display font-bold">Build a website</div>
          <div className="text-sm text-muted-foreground mt-1">Start from a smart template</div>
        </button>
        <button onClick={demoAlert} data-testid="pilot-migrate" className="group border border-border rounded-xl p-5 text-left hover:border-primary hover:-translate-y-1 transition-all bg-card">
          <Import className="w-6 h-6 text-primary mb-3" />
          <div className="font-display font-bold">Migrate existing</div>
          <div className="text-sm text-muted-foreground mt-1">Bring your current site</div>
        </button>
        <button onClick={onSkip} data-testid="pilot-skip" className="group border border-border rounded-xl p-5 text-left hover:border-primary hover:-translate-y-1 transition-all bg-card">
          <LayoutDashboard className="w-6 h-6 text-primary mb-3" />
          <div className="font-display font-bold">Skip to dashboard</div>
          <div className="text-sm text-muted-foreground mt-1">Explore first</div>
        </button>
      </div>
    </motion.div>
  );
}

function WelcomeScreen({ onFillDemo, onBack }) {
  return (
    <motion.div key="welcome" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }} transition={{ duration: 0.5 }} className="max-w-xl mx-auto text-center">
      <div className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.2em] font-bold text-primary mb-4"><Sparkles className="w-4 h-4" /> Setup</div>
      <h1 className="font-display text-4xl font-black tracking-tight">Let's set up your business brain</h1>
      <p className="mt-4 text-muted-foreground leading-relaxed">Fill demo data to see Arevei in action instantly, or connect your own details.</p>
      <div className="mt-8 space-y-3">
        <button onClick={onFillDemo} data-testid="welcome-fill-demo" className="w-full inline-flex items-center justify-center gap-2 h-12 rounded-full bg-primary text-primary-foreground font-semibold hover:-translate-y-0.5 transition-transform">
          <Wand2 className="w-4 h-4" /> Fill demo data & build
        </button>
        <div className="grid grid-cols-2 gap-3">
          <button onClick={demoAlert} className="h-11 rounded-full border border-border hover:bg-accent text-sm font-medium">Connect your site</button>
          <button onClick={demoAlert} className="h-11 rounded-full border border-border hover:bg-accent text-sm font-medium">Import content</button>
        </div>
      </div>
      <button onClick={onBack} className="mt-8 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="w-4 h-4" /> Back</button>
    </motion.div>
  );
}

const BUILD_STEPS = ["Loading starter template", "Wiring components", "Booting live preview", "Finalizing workspace"];

function BuildScreen({ projectId, ready, onOpen, onDashboard }) {
  const [active, setActive] = useState(0);
  useEffect(() => {
    if (ready) { setActive(BUILD_STEPS.length); return; }
    const t = setInterval(() => setActive((a) => Math.min(a + 1, BUILD_STEPS.length - 1)), 1600);
    return () => clearInterval(t);
  }, [ready]);
  const done = ready && projectId;
  return (
    <motion.div key="build" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }} transition={{ duration: 0.5 }} className="max-w-xl mx-auto text-center">
      <div className="w-16 h-16 rounded-2xl bg-primary/10 text-primary grid place-items-center mx-auto mb-6">
        {done ? <Check className="w-8 h-8" /> : <Loader2 className="w-8 h-8 animate-spin" />}
      </div>
      <h1 className="font-display text-3xl font-black tracking-tight">{done ? "Your starter website is ready" : "Building your website…"}</h1>
      <div className="mt-8 space-y-2 text-left max-w-sm mx-auto">
        {BUILD_STEPS.map((s, i) => {
          const state = done || i < active ? "done" : i === active ? "active" : "pending";
          return (
            <div key={s} className="flex items-center gap-3">
              <span className={state === "done" ? "grid place-items-center w-6 h-6 rounded-full bg-primary text-primary-foreground" : state === "active" ? "grid place-items-center w-6 h-6 rounded-full border-2 border-primary text-primary" : "grid place-items-center w-6 h-6 rounded-full border border-border text-muted-foreground"}>
                {state === "done" ? <Check className="w-3.5 h-3.5" /> : state === "active" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <span className="text-xs">{i + 1}</span>}
              </span>
              <span className={state === "pending" ? "text-sm text-muted-foreground" : "text-sm"}>{s}</span>
            </div>
          );
        })}
      </div>
      <div className="mt-10 flex items-center justify-center gap-3">
        <button onClick={onOpen} disabled={!done} data-testid="build-open" className="inline-flex items-center gap-2 px-6 h-12 rounded-full bg-primary text-primary-foreground font-semibold disabled:opacity-50">
          <ExternalLink className="w-4 h-4" /> Open in Workspace
        </button>
        <button onClick={onDashboard} data-testid="build-dashboard" className="inline-flex items-center gap-2 px-5 h-12 rounded-full border border-border hover:bg-accent font-medium">
          Go to Dashboard <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    </motion.div>
  );
}

export default function Onboarding() {
  const nav = useNavigate();
  const [step, setStep] = useState(0);
  const [projectId, setProjectId] = useState(null);
  const [ready, setReady] = useState(false);

  const finish = () => { localStorage.setItem("arevei_onboarded", "1"); nav("/app"); };

  const startBuild = async () => {
    setStep(2);
    try {
      const r = await api.post("/code/projects", { name: "My Website", template: "react-vite" });
      setProjectId(r.data.id);
      const poll = setInterval(async () => {
        const p = await api.get(`/code/projects/${r.data.id}`);
        if (p.data.sandbox_status === "ready") { setReady(true); clearInterval(poll); }
        if (p.data.sandbox_status === "error") { clearInterval(poll); toast.error("Sandbox failed — you can retry from Workspace"); setReady(true); }
      }, 3500);
    } catch { toast.error("Could not start build"); }
  };

  return (
    <div className="min-h-screen grain flex flex-col">
      <header className="h-16 px-6 flex items-center justify-between border-b border-border glass">
        <Logo className="text-lg" />
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <button onClick={finish} className="text-sm text-muted-foreground hover:text-foreground">Skip</button>
        </div>
      </header>
      <div className="flex-1 grid place-items-center px-6 py-12">
        <AnimatePresence mode="wait">
          {step === 0 && <PilotScreen onBuild={() => setStep(1)} onSkip={finish} />}
          {step === 1 && <WelcomeScreen onFillDemo={startBuild} onBack={() => setStep(0)} />}
          {step === 2 && <BuildScreen projectId={projectId} ready={ready} onOpen={() => { localStorage.setItem("arevei_onboarded", "1"); nav(`/app/code/${projectId}`); }} onDashboard={finish} />}
        </AnimatePresence>
      </div>
    </div>
  );
}
