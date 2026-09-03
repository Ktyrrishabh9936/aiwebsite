import { useCallback, useEffect, useState } from "react";
import { useOutletContext, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
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
};

function Stat({ icon: Icon, label, value, testid }) {
  return (
    <div className="border border-border rounded-md bg-card p-5" data-testid={testid}>
      <Icon className="w-5 h-5 text-primary mb-3" />
      <div className="font-display text-3xl font-black break-words">{value}</div>
      <div className="text-sm text-muted-foreground">{label}</div>
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
  return (
    <div className="border border-border rounded-md bg-card p-6">
      <h3 className="font-display font-bold mb-4">{title}</h3>
      {data.length === 0 ? (
        <div className="h-56 grid place-items-center text-sm text-muted-foreground">{empty}</div>
      ) : (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
              <Tooltip formatter={(value, name) => (name === "payments" ? money(value) : value)} />
              <Bar dataKey="leads" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
              <Bar dataKey="payments" fill="hsl(var(--muted-foreground))" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export default function Overview() {
  const { ws, refresh } = useOutletContext();
  const nav = useNavigate();
  const [tasks, setTasks] = useState([]);
  const [blogs, setBlogs] = useState([]);
  const [crmAnalytics, setCrmAnalytics] = useState(zeroAnalytics);
  const [genning, setGenning] = useState(false);

  const load = useCallback(() => {
    api.get(`/workspaces/${ws.id}/tasks`).then((r) => setTasks(r.data)).catch(() => {});
    api.get(`/workspaces/${ws.id}/blogs`).then((r) => setBlogs(r.data)).catch(() => {});
    api.get(`/workspaces/${ws.id}/crm/analytics/overview`).then((r) => setCrmAnalytics({ ...zeroAnalytics, ...r.data })).catch(() => setCrmAnalytics(zeroAnalytics));
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

  const building = ws.brain_status === "building" || ws.brain_status === "pending";
  const published = blogs.filter((b) => b.status === "published").length;
  const totals = crmAnalytics.totals || zeroAnalytics.totals;
  const monthTotals = crmAnalytics.this_month_totals || zeroAnalytics.this_month_totals;
  const todayTotals = crmAnalytics.today_totals || zeroAnalytics.today_totals;
  const days = chartData(crmAnalytics.day_buckets, "date");
  const months = chartData(crmAnalytics.month_buckets, "month");

  return (
    <div className="p-6 sm:p-10 max-w-6xl mx-auto space-y-8">
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

      <div>
        <h1 className="font-display text-3xl font-black tracking-tight">Overview</h1>
        <p className="text-muted-foreground mt-1">Your AI manager's command center.</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Stat icon={Brain} label="Brain status" value={ws.brain_status === "ready" ? "Ready" : "..."} testid="stat-brain" />
        <Stat icon={ListChecks} label="Scheduled tasks" value={tasks.length} testid="stat-tasks" />
        <Stat icon={FileText} label="Published blogs" value={published} testid="stat-blogs" />
        <Stat icon={Sparkles} label="Roadmap months" value={(ws.roadmap || []).length} testid="stat-roadmap" />
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Stat icon={Users} label="Total leads" value={totals.leads} testid="stat-crm-total-leads" />
        <Stat icon={CalendarDays} label="Leads this month" value={monthTotals.leads} testid="stat-crm-month-leads" />
        <Stat icon={Users} label="Leads today" value={todayTotals.leads} testid="stat-crm-today-leads" />
        <Stat icon={Users} label="Customers" value={totals.customers} testid="stat-crm-customers" />
        <Stat icon={BadgeIndianRupee} label="Total collected" value={money(totals.payments_collected)} testid="stat-crm-total-collected" />
        <Stat icon={BadgeIndianRupee} label="Collected this month" value={money(monthTotals.payments_collected)} testid="stat-crm-month-collected" />
        <Stat icon={WalletCards} label="Due amount" value={money(totals.due_amount)} testid="stat-crm-due" />
        <Stat icon={Users} label="New / active leads" value={`${totals.new_leads || 0} / ${totals.active_leads || 0}`} testid="stat-crm-active" />
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <AnalyticsChart title="Day-wise CRM" data={days} empty="No daily CRM activity yet." />
        <AnalyticsChart title="Month-wise CRM" data={months} empty="No monthly CRM activity yet." />
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

      {ws.brain_status === "ready" && (ws.roadmap || []).length === 0 && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="border border-primary/30 rounded-md bg-primary/5 p-8 text-center">
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

      <div className="grid grid-cols-1 gap-4">
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
