import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowRight, Users, ListChecks, MessageSquare, Activity, PhoneCall, Brain } from "lucide-react";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";
import { useAuth } from "../context/AuthContext";

const features = [
  { icon: PhoneCall, title: "EVERY NEW LEAD GETS A FIRST CONVERSATION.", body: "Your AI agent calls new leads, asks qualification questions, and saves the answers. Your sales team gets the context before picking up the phone." },
  { icon: Users, title: "YOUR MANAGER COORDINATES. YOUR TEAM CLOSES.", body: "Know which leads need attention. Schedule the next conversation. Assign the right salesperson. AI handles initial qualification and coordination. Your people handle the relationship." },
  { icon: Activity, title: "WATCH YOUR TEAM AT WORK.", body: "See your manager retrieve information, update the CRM, and delegate to AI agents. Every action has a status. Know what's completed, what's pending, and what needs your attention." },
  { icon: Brain, title: "THE CONTEXT STAYS WITH THE LEAD.", body: "Qualification answers, call summaries, notes, assignments, and follow-ups stay together. Your team starts each conversation knowing what happened before." },
];

export default function Landing() {
  const { user } = useAuth();
  const nav = useNavigate();
  const cta = user ? "/app" : "/register";
  return (
    <div className="min-h-screen grain relative overflow-hidden">
      <header className="sticky top-0 z-30 glass border-b border-border">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <Logo className="text-lg" />
          <nav className="flex items-center gap-3" aria-label="Main navigation">
            <ThemeToggle />
            <Link to="/login" data-testid="nav-login" className="text-sm font-medium px-3 py-2 hover:text-primary transition-colors">Log in</Link>
            <Link to={cta} data-testid="nav-get-started" className="inline-flex items-center gap-1.5 text-sm font-semibold px-4 py-2 rounded-full bg-primary text-primary-foreground hover:-translate-y-0.5 transition-transform">Get early access <ArrowRight className="w-4 h-4" /></Link>
          </nav>
        </div>
      </header>

      <main>
        <section className="max-w-6xl mx-auto px-6 pt-20 pb-20 sm:pt-28 sm:pb-24">
          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }} className="max-w-4xl mx-auto text-center">
            <p className="text-xs tracking-[0.2em] uppercase font-bold text-primary mb-6">Your AI-native sales manager</p>
            <h1 className="font-display text-4xl sm:text-5xl lg:text-6xl font-black tracking-tight leading-[1.05]">YOUR SALES RUNS ITSELF.<br /><span className="text-primary">YOU JUST APPROVE.</span></h1>
            <p className="mt-6 text-lg text-muted-foreground max-w-2xl mx-auto leading-relaxed">Your AI manager qualifies leads, schedules follow-ups, and assigns your sales team. Give direction through chat. See every action as it happens.</p>
            <div className="mt-9 flex flex-wrap justify-center items-center gap-4">
              <button onClick={() => nav(cta)} data-testid="hero-cta" className="inline-flex items-center gap-2 px-6 h-12 rounded-full bg-primary text-primary-foreground font-semibold hover:-translate-y-0.5 transition-transform">Get early access <ArrowRight className="w-4 h-4" /></button>
              <button onClick={() => nav("/check-demo")} data-testid="check-demo-cta" className="inline-flex items-center gap-2 px-6 h-12 rounded-full border border-primary text-primary font-semibold hover:bg-primary/10 transition-colors"><PhoneCall className="w-4 h-4" /> See it in action</button>
            </div>
          </motion.div>
        </section>

        <section className="max-w-6xl mx-auto px-6 pb-20" aria-label="How your AI manager works">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {features.map((feature, i) => (
              <motion.article key={feature.title} initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: i * 0.08, duration: 0.5 }} className="border border-border rounded-md bg-card p-6 sm:p-8" data-testid={`pillar-${i}`}>
                <div className="w-10 h-10 rounded-md bg-primary/10 text-primary grid place-items-center mb-4"><feature.icon className="w-5 h-5" /></div>
                <h2 className="font-display text-lg font-bold mb-3">{feature.title}</h2>
                <p className="text-sm text-muted-foreground leading-relaxed">{feature.body}</p>
              </motion.article>
            ))}
          </div>
        </section>

        <section className="max-w-6xl mx-auto px-6 pb-20">
          <div className="border border-border rounded-md bg-card p-6 sm:p-10 grid md:grid-cols-2 gap-8 items-center">
            <div><MessageSquare className="w-8 h-8 text-primary mb-4" /><h2 className="font-display text-2xl sm:text-3xl font-bold">SAY IT. GET IT DONE.</h2><p className="mt-4 text-muted-foreground leading-relaxed">Your manager reads the records, makes the changes, and confirms what's saved.</p></div>
            <div className="space-y-3" aria-label="Example requests">{["Add this lead.", "Schedule Rishabh's demo for tomorrow at 11.", "Save this note and assign him to Priya."].map((request) => <p key={request} className="rounded-xl border border-border bg-background px-5 py-4 text-sm font-medium">{request}</p>)}</div>
          </div>
        </section>

        <section className="max-w-6xl mx-auto px-6 pb-20">
          <h2 className="font-display text-2xl sm:text-3xl font-bold mb-6">ONE WORKSPACE. TWO WAYS TO WORK.</h2>
          <div className="grid md:grid-cols-2 gap-6">
            <div className="border border-border rounded-md p-6"><MessageSquare className="w-6 h-6 text-primary mb-3" /><h3 className="text-lg font-bold">Agent Mode</h3><p className="mt-2 text-muted-foreground">Manage sales through chat.</p></div>
            <div className="border border-border rounded-md p-6"><ListChecks className="w-6 h-6 text-primary mb-3" /><h3 className="text-lg font-bold">Human Mode</h3><p className="mt-2 text-muted-foreground">Open records and make changes yourself.</p></div>
          </div>
          <p className="mt-5 text-muted-foreground">Switch whenever you need.</p>
        </section>

        <section className="border-t border-border py-20 text-center px-6">
          <h2 className="font-display text-2xl sm:text-4xl font-bold">PUT YOUR AI MANAGER TO WORK.</h2>
          <p className="mt-5 mb-8 max-w-2xl mx-auto text-muted-foreground leading-relaxed">From the first qualification call to the next human conversation, keep your sales work moving.</p>
          <Link to={cta} className="inline-flex items-center gap-2 px-6 h-12 rounded-full bg-primary text-primary-foreground font-semibold">Get early access <ArrowRight className="w-4 h-4" /></Link>
        </section>
      </main>
      <footer className="border-t border-border"><div className="max-w-6xl mx-auto px-6 py-8 flex flex-wrap gap-4 items-center justify-between text-sm text-muted-foreground"><Logo /><span>Your sales, managed by AI.</span></div></footer>
    </div>
  );
}
