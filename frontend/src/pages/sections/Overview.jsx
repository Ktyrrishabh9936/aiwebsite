import { useCallback, useEffect, useState } from "react";
import { useOutletContext, useNavigate } from "react-router-dom";
import { motion, useReducedMotion } from "framer-motion";
import {
  Brain,
  FileText,
  ListChecks,
  Sparkles,
  Loader2,
  ArrowRight,
  RefreshCw,
  Users,
  BadgeIndianRupee,
  CalendarDays,
  WalletCards,
  PhoneCall,
  Ban,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";
import api from "../../lib/api";

const zeroAnalytics = {
  totals: { leads: 0, customers: 0, active_leads: 0, new_leads: 0, payments_collected: "0", due_amount: "0", receipts: 0 },
  this_month_totals: { leads: 0, customers: 0, payments_collected: "0", receipts: 0 },
  today_totals: { leads: 0, payments_collected: "0", receipts: 0 },
  status_counts: {},
  day_buckets: [],
  month_buckets: [],
  recent_receipts: [],
  scheduled_calls: [],
};

function Stat({ icon: Icon, label, value, testid, detail }) {
  return (
    <div className="min-w-0 rounded-xl border bg-card p-4 sm:p-5" data-testid={testid}>
      <div className="flex items-center justify-between gap-2 text-sm text-muted-foreground"><span>{label}</span><Icon aria-hidden="true" className="w-4 h-4 shrink-0" /></div>
      <div className="mt-3 text-2xl sm:text-3xl font-semibold tracking-tight tabular-nums break-words">{value}</div>
      {detail && <div className="mt-2 text-xs text-muted-foreground leading-relaxed">{detail}</div>}
    </div>
  );
}

function money(value) {
  const n = Number(String(value || "0").replace(/,/g, ""));
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(Number.isFinite(n) ? n : 0);
}

function chartData(rows, keyName) {
  return (rows || []).map((row) => ({
    label: row[keyName],
    leads: Number(row.leads || 0),
    payments: Number(String(row.payments_collected || "0").replace(/,/g, "")) || 0,
  }));
}

function AnalyticsChart({ title, data, empty }) {
  const [metric, setMetric] = useState("leads");
  const reduceMotion = useReducedMotion();
  return (
    <section className="min-w-0 border border-border rounded-xl bg-card p-4 sm:p-6" aria-label={title}>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <h2 className="font-semibold">{title}</h2>
        <div role="group" aria-label={`${title} measure`} className="inline-flex rounded-lg bg-muted p-1">
          {["leads", "payments"].map((value) => <button key={value} type="button" aria-pressed={metric === value} onClick={() => setMetric(value)} className={`min-h-9 rounded-md px-3 text-xs font-medium ${metric === value ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>{value === "leads" ? "Leads" : "Collected"}</button>)}
        </div>
      </div>
      {data.length === 0 ? (
        <div className="h-56 grid place-items-center text-sm text-muted-foreground">{empty}</div>
      ) : (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
              <YAxis width={70} allowDecimals={metric === "payments"} tickFormatter={metric === "payments" ? (value) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", notation: "compact", maximumFractionDigits: 1 }).format(value) : undefined} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ background: "hsl(var(--card))", borderColor: "hsl(var(--border))", color: "hsl(var(--foreground))", borderRadius: 8 }} formatter={(value) => [metric === "payments" ? money(value) : value, metric === "payments" ? "Collected" : "Leads"]} />
              <Bar dataKey={metric} fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} isAnimationActive={!reduceMotion} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

export default function Overview() {
  const { ws, refresh } = useOutletContext();
  const nav = useNavigate();
  const [tasks, setTasks] = useState([]);
  const [blogs, setBlogs] = useState([]);
  const [crmAnalytics, setCrmAnalytics] = useState(zeroAnalytics);
  const [genning, setGenning] = useState(false);
  const [cancellingCallId, setCancellingCallId] = useState("");
  const [analyticsStatus, setAnalyticsStatus] = useState("loading");
  const reduceMotion = useReducedMotion();

  const load = useCallback(() => {
    api.get(`/workspaces/${ws.id}/tasks`).then((r) => setTasks(r.data)).catch(() => {});
    api.get(`/workspaces/${ws.id}/blogs`).then((r) => setBlogs(r.data)).catch(() => {});
    api.get(`/workspaces/${ws.id}/crm/analytics/overview`).then((r) => { setCrmAnalytics({ ...zeroAnalytics, ...r.data }); setAnalyticsStatus("ready"); }).catch(() => setAnalyticsStatus("error"));
  }, [ws.id]);

  useEffect(() => {
    load();
    const t = setInterval(load, 6000);
    return () => clearInterval(t);
  }, [load]);

  const genRoadmap = async () => {
    setGenning(true);
    try {
      await api.post(`/workspaces/${ws.id}/roadmap`);
      await refresh();
      toast.success("Roadmap generated & tasks scheduled");
      nav("manager");
    } catch (e) {
      toast.error("Could not generate roadmap");
    } finally {
      setGenning(false);
    }
  };

  const cancelScheduledCall = async (leadId) => {
    try {
      setCancellingCallId(leadId);
      await api.post(`/workspaces/${ws.id}/crm/leads/${leadId}/calls/qualification/cancel`, {});
      toast.success("Scheduled call cancelled");
      load();
    } catch (e) {
      toast.error("Could not cancel scheduled call");
    } finally {
      setCancellingCallId("");
    }
  };

  const building = ws.brain_status === "building" || ws.brain_status === "pending";
  const published = blogs.filter((b) => b.status === "published").length;
  const totals = crmAnalytics.totals || zeroAnalytics.totals;
  const monthTotals = crmAnalytics.this_month_totals || zeroAnalytics.this_month_totals;
  const todayTotals = crmAnalytics.today_totals || zeroAnalytics.today_totals;
  const days = chartData(crmAnalytics.day_buckets, "date");
  const months = chartData(crmAnalytics.month_buckets, "month");
  const scheduledCalls = crmAnalytics.scheduled_calls || [];
  const metricValue = (value) => analyticsStatus === "ready" ? value : "—";

  return (
    <div className="workspace-overview p-4 sm:p-8 max-w-7xl mx-auto space-y-7">
      {building && (
        <div className="border border-border rounded-md bg-card p-6 flex items-center gap-4">
          <Loader2 className="w-6 h-6 text-primary animate-spin" />
          <div>
            <div className="font-display font-bold">Training the business brain...</div>
            <div className="text-sm text-muted-foreground">Crawling {ws.website_url} and structuring knowledge. This takes 20-40s.</div>
          </div>
        </div>
      )}

      {ws.brain_status === "error" && (
        <div className="border border-destructive/40 rounded-md bg-destructive/5 p-6 flex items-center justify-between">
          <div>
            <div className="font-display font-bold text-destructive">Brain training failed</div>
            <div className="text-sm text-muted-foreground">We couldn't crawl that site. Try again.</div>
          </div>
          <button onClick={() => api.post(`/workspaces/${ws.id}/rebrain`).then(refresh)} className="inline-flex items-center gap-2 px-4 h-10 rounded-full border border-border hover:bg-accent text-sm font-medium">
            <RefreshCw className="w-4 h-4" /> Retry
          </button>
        </div>
      )}

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><h1 className="font-display text-3xl sm:text-4xl font-bold tracking-tight">Business overview</h1>
        <p className="text-sm text-muted-foreground mt-2">Track your leads, collections, and next steps.</p></div>
        <button onClick={() => nav("crm")} className="inline-flex items-center justify-center gap-2 h-11 px-5 rounded-lg bg-primary text-primary-foreground text-sm font-semibold">Open CRM <ArrowRight className="w-4 h-4" /></button>
      </div>

      {analyticsStatus === "error" && <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-card p-4 text-sm"><p>CRM data couldn’t be refreshed. Your records are still available in CRM.</p><button onClick={load} className="inline-flex min-h-10 items-center gap-2 px-3 rounded-lg border font-medium"><RefreshCw size={14} /> Try again</button></div>}
      {analyticsStatus === "loading" && <p role="status" className="text-sm text-muted-foreground">Loading your CRM overview…</p>}

      <section aria-label="Sales snapshot" className="space-y-4">
        <div className="grid grid-cols-1 min-[400px]:grid-cols-2 xl:grid-cols-4 gap-3">
          <Stat icon={Users} label="Total leads" value={metricValue(totals.leads)} detail={analyticsStatus === "ready" ? `${todayTotals.leads} today · ${monthTotals.leads} this month` : "All time"} testid="stat-crm-total-leads" />
          <Stat icon={BadgeIndianRupee} label="Total collected" value={metricValue(money(totals.payments_collected))} detail={analyticsStatus === "ready" ? `${money(monthTotals.payments_collected)} this month` : "All time"} testid="stat-crm-total-collected" />
          <Stat icon={WalletCards} label="Outstanding amount" value={metricValue(money(totals.due_amount))} detail="Payments still to be collected" testid="stat-crm-due" />
          <Stat icon={Users} label="Customers" value={metricValue(totals.customers)} detail={analyticsStatus === "ready" ? `${totals.new_leads || 0} new leads · ${totals.active_leads || 0} active` : "Converted leads"} testid="stat-crm-customers" />
        </div>
      </section>

      {analyticsStatus === "ready" && <>
      <div className="grid lg:grid-cols-2 gap-4">
        <AnalyticsChart title="Daily activity" data={days} empty="Add a lead or record a payment to see daily activity." />
        <AnalyticsChart title="Monthly activity" data={months} empty="Your monthly trends will appear as you add leads and payments." />
      </div>

      <div className="border border-border rounded-md bg-card p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-display font-bold flex items-center gap-2"><PhoneCall className="w-4 h-4 text-primary" /> Scheduled qualification calls</h3>
          <button onClick={() => nav("crm")} className="text-sm text-primary inline-flex items-center gap-1">View CRM <ArrowRight className="w-3.5 h-3.5" /></button>
        </div>
        <div className="space-y-3">
          {scheduledCalls.slice(0, 5).map((call) => (
            <div key={call.lead_id} className="grid sm:grid-cols-[1fr_auto] gap-3 rounded-md border bg-background p-3 text-sm">
              <div className="min-w-0">
                <div className="font-medium truncate">{call.lead_name || call.phone || "Unnamed Lead"}</div>
                <div className="text-xs text-muted-foreground">{call.phone || "No phone"} - {call.scheduled_for ? new Date(call.scheduled_for).toLocaleString() : "No time"}</div>
              </div>
              <button onClick={() => cancelScheduledCall(call.lead_id)} disabled={cancellingCallId === call.lead_id} className="inline-flex items-center justify-center gap-1.5 px-3 h-9 rounded-md border bg-card hover:bg-accent text-xs font-semibold disabled:opacity-50">
                {cancellingCallId === call.lead_id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Ban className="w-3.5 h-3.5" />}
                Cancel Call
              </button>
            </div>
          ))}
          {scheduledCalls.length === 0 && <div className="text-sm text-muted-foreground">No qualification calls scheduled.</div>}
        </div>
      </div>

      <div className="border border-border rounded-md bg-card p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-display font-bold">Recent payments</h3>
          <button onClick={() => nav("crm")} className="text-sm text-primary inline-flex items-center gap-1">View CRM <ArrowRight className="w-3.5 h-3.5" /></button>
        </div>
        <div className="space-y-3">
          {(crmAnalytics.recent_receipts || []).slice(0, 5).map((receipt) => (
            <div key={receipt.id} className="grid grid-cols-[1fr_auto] gap-3 text-sm">
              <div className="min-w-0">
                <div className="truncate font-medium">{receipt.lead_name || "Customer"} - {receipt.receipt_number || "Receipt"}</div>
                <div className="text-xs text-muted-foreground">{receipt.payment_date || "No date"} {receipt.payment_method ? `- ${receipt.payment_method}` : ""}</div>
              </div>
              <div className="font-semibold">{money(receipt.amount)}</div>
            </div>
          ))}
          {(crmAnalytics.recent_receipts || []).length === 0 && <div className="text-sm text-muted-foreground">No payments collected yet.</div>}
        </div>
      </div>

      </>}

      <section aria-labelledby="workspace-activity" className="space-y-4">
        <h2 id="workspace-activity" className="text-lg font-semibold">Workspace activity</h2>
        <div className="grid grid-cols-1 min-[400px]:grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat icon={Brain} label="Business brain" value={({ ready: "Ready", building: "Training", pending: "Queued", error: "Needs attention" })[ws.brain_status] || "Not started"} testid="stat-brain" />
          <Stat icon={ListChecks} label="Scheduled tasks" value={tasks.length} testid="stat-tasks" />
          <Stat icon={FileText} label="Published blogs" value={published} testid="stat-blogs" />
          <Stat icon={CalendarDays} label="Roadmap months" value={(ws.roadmap || []).length} testid="stat-roadmap" />
        </div>
      </section>

      {ws.brain_status === "ready" && (ws.roadmap || []).length === 0 && (
        <motion.div initial={reduceMotion ? false : { opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="border border-primary/30 rounded-xl bg-primary/5 p-6 sm:p-8 text-center">
          <Sparkles className="w-8 h-8 text-primary mx-auto mb-3" />
          <h3 className="font-display text-xl font-bold">Brain is ready. Generate your growth plan.</h3>
          <p className="text-muted-foreground mt-1 mb-5">The manager will draft a 12-month roadmap and auto-schedule daily tasks.</p>
          <button onClick={genRoadmap} disabled={genning} data-testid="generate-roadmap-btn" className="inline-flex items-center gap-2 px-6 h-11 rounded-full bg-primary text-primary-foreground font-semibold disabled:opacity-60">
            {genning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            {genning ? "Generating..." : "Generate roadmap"}
          </button>
        </motion.div>
      )}

      {ws.strategy_summary && (
        <div className="border border-border rounded-md bg-card p-6">
          <div className="text-xs uppercase tracking-[0.2em] font-bold text-primary mb-2">Strategy</div>
          <p className="text-lg leading-relaxed">{ws.strategy_summary}</p>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="border border-border rounded-md bg-card p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-display font-bold">Upcoming tasks</h3>
            <button onClick={() => nav("tasks")} className="text-sm text-primary inline-flex items-center gap-1">View all <ArrowRight className="w-3.5 h-3.5" /></button>
          </div>
          <div className="space-y-3">
            {tasks.slice(0, 4).map((t) => (
              <div key={t.id} className="flex items-center gap-3">
                <span className="text-[10px] uppercase font-bold px-2 py-0.5 rounded-full bg-secondary">{t.agent}</span>
                <span className="text-sm truncate flex-1">{t.title}</span>
                <span className="text-xs text-muted-foreground">{t.status}</span>
              </div>
            ))}
            {tasks.length === 0 && <div className="text-sm text-muted-foreground">No tasks yet.</div>}
          </div>
        </div>
        <div className="border border-border rounded-md bg-card p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-display font-bold">Recent blogs</h3>
            <button onClick={() => nav("blogs")} className="text-sm text-primary inline-flex items-center gap-1">View all <ArrowRight className="w-3.5 h-3.5" /></button>
          </div>
          <div className="space-y-3">
            {blogs.slice(0, 4).map((b) => (
              <div key={b.id} className="flex items-center gap-3">
                <span className={`w-2 h-2 rounded-full ${b.status === "published" ? "bg-primary" : "bg-muted-foreground"}`} />
                <span className="text-sm truncate flex-1">{b.title}</span>
                <span className="text-xs text-muted-foreground">{b.status}</span>
              </div>
            ))}
            {blogs.length === 0 && <div className="text-sm text-muted-foreground">No blogs yet.</div>}
          </div>
        </div>
      </div>
    </div>
  );
}
