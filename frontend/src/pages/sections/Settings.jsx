import VoiceProviders from "../../components/VoiceProviders";
import AIUsageDashboard from "../../components/AIUsageDashboard";
import { useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { Building2, Check, Copy, KeyRound, Loader2, PackageOpen, Phone, PhoneOff, RotateCw, Save, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../context/AuthContext";
import api from "../../lib/api";

export default function Settings() {
  const { user } = useAuth();
  const { ws, setWs, refresh } = useOutletContext();
  const [originsText, setOriginsText] = useState("");
  const [savingOrigins, setSavingOrigins] = useState(false);
  const [rotatingKey, setRotatingKey] = useState(false);
  const [copied, setCopied] = useState(false);
  const [voice, setVoice] = useState({ connected: false, caller_phone: "", service_enabled: false });
  const [voicePhone, setVoicePhone] = useState("");
  const [savingVoice, setSavingVoice] = useState(false);
  const [modules, setModules] = useState(ws.modules || { real_estate: true, agency: false });
  const [currency, setCurrency] = useState(ws.currency || "INR");
  const [savingModules, setSavingModules] = useState(false);
  useEffect(() => {
    setOriginsText((ws.allowed_blog_origins || []).join("\n"));
  }, [ws.allowed_blog_origins]);
  useEffect(() => {
    setModules(ws.modules || { real_estate: true, agency: false });
    setCurrency(ws.currency || "INR");
  }, [ws.modules, ws.currency]);
  useEffect(() => {
    let active = true;
    api.get(`/ai-manager/voice/workspaces/${ws.id}/connection`).then(({ data }) => {
      if (active) { setVoice(data); setVoicePhone(data.caller_phone || ""); }
    }).catch(() => {});
    return () => { active = false; };
  }, [ws.id]);

  const connectVoice = async () => {
    setSavingVoice(true);
    try {
      const { data } = await api.put(`/ai-manager/voice/workspaces/${ws.id}/connection`, { caller_phone: voicePhone.trim() });
      setVoice(data);
      setVoicePhone(data.caller_phone);
      toast.success("Phone connected to this workspace");
    } catch (error) {
      toast.error(error?.response?.data?.detail || "Could not connect this phone");
    } finally { setSavingVoice(false); }
  };

  const disconnectVoice = async () => {
    setSavingVoice(true);
    try {
      const { data } = await api.delete(`/ai-manager/voice/workspaces/${ws.id}/connection`);
      setVoice(data);
      setVoicePhone("");
      toast.success("Phone disconnected from this workspace");
    } catch { toast.error("Could not disconnect this phone"); }
    finally { setSavingVoice(false); }
  };

  const copyKey = async () => {
    await navigator.clipboard.writeText(ws.public_key || "");
    setCopied(true);
    toast.success("Publishable blog key copied");
    setTimeout(() => setCopied(false), 1500);
  };

  const saveOrigins = async () => {
    setSavingOrigins(true);
    try {
      const allowed_blog_origins = originsText.split(/\r?\n|,/).map((origin) => origin.trim()).filter(Boolean);
      const { data } = await api.patch(`/workspaces/${ws.id}`, { allowed_blog_origins });
      setWs?.(data);
      await refresh?.();
      toast.success("Blog origin allowlist saved");
    } catch {
      toast.error("Could not save allowed origins");
    } finally {
      setSavingOrigins(false);
    }
  };

  const rotateKey = async () => {
    if (!window.confirm("Rotate the publishable blog key? Existing external integrations using the old key will stop loading blog lists.")) return;
    setRotatingKey(true);
    try {
      const { data } = await api.post(`/workspaces/${ws.id}/public-key/rotate`);
      setWs?.(data);
      await refresh?.();
      toast.success("Publishable blog key rotated");
    } catch {
      toast.error("Could not rotate publishable blog key");
    } finally {
      setRotatingKey(false);
    }
  };

  const toggleWorkspaceModule = async (key) => {
    if (savingModules) return;
    const previous = modules;
    const next = { ...modules, [key]: !modules[key] };
    setModules(next);
    setSavingModules(true);
    try {
      const { data } = await api.patch(`/workspaces/${ws.id}`, { modules: next });
      setModules(data.modules || next);
      setWs?.(data);
      await refresh?.();
      toast.success(`${key === "real_estate" ? "Real Estate" : "Agency"} module ${next[key] ? "activated" : "deactivated"}`);
    } catch (error) {
      setModules(previous);
      toast.error(error?.response?.data?.detail || "Could not save workspace modules");
    } finally { setSavingModules(false); }
  };

  const saveWorkspaceCurrency = async () => {
    setSavingModules(true);
    try {
      const { data } = await api.patch(`/workspaces/${ws.id}`, { currency });
      setCurrency(data.currency || currency);
      setWs?.(data);
      await refresh?.();
      toast.success("Workspace currency saved");
    } catch (error) {
      toast.error(error?.response?.data?.detail || "Could not save workspace currency");
    } finally { setSavingModules(false); }
  };

  return (
    <div className="p-6 sm:p-10 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="font-display text-3xl font-black tracking-tight">Settings</h1>
        <p className="text-muted-foreground mt-1">Manage your account and workspace preferences.</p>
      </div>

      <section className="border border-border rounded-md bg-card p-6 space-y-5">
        <div>
          <h2 className="font-display text-xl font-bold">Workspace modules</h2>
          <p className="text-sm text-muted-foreground mt-1">Install the sales tools this workspace needs. Deactivating a module hides it and keeps its existing data.</p>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <ModuleCard icon={Building2} title="Real Estate" description="Property inventory linked to CRM opportunities and completed sales." active={modules.real_estate === true} busy={savingModules} onToggle={() => toggleWorkspaceModule("real_estate")} />
          <ModuleCard icon={PackageOpen} title="Agency" description="Products and services linked to CRM opportunities and product stock." active={modules.agency === true} busy={savingModules} onToggle={() => toggleWorkspaceModule("agency")} />
        </div>
        <label className="block max-w-xs space-y-2"><span className="text-sm font-semibold">Workspace currency</span><select value={currency} onChange={(event) => setCurrency(event.target.value)} className="w-full h-10 rounded-md border bg-background px-3 text-sm">{["INR", "USD", "EUR", "GBP", "AED", "CAD", "AUD", "SGD", "JPY"].map((code) => <option key={code} value={code}>{code}</option>)}</select></label>
        <p className="text-xs text-muted-foreground">This currency is used across property, catalog, opportunity, and pipeline values. Changing it updates the currency label; it does not convert existing amounts.</p>
        <button onClick={saveWorkspaceCurrency} disabled={savingModules} className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-60">{savingModules ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save currency</button>
      </section>

      <AIUsageDashboard wsId={ws.id} />

      <section className="border border-border rounded-md bg-card p-6 space-y-5">
        <div className="flex items-start gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-md bg-primary/10 text-primary"><Phone className="h-5 w-5" /></div>
          <div>
            <h2 className="font-display text-xl font-bold">Call your AI Manager</h2>
            <p className="text-sm text-muted-foreground mt-1">Connect the phone you will call from. Incoming Sarvam calls from this number will use this workspace's AI Manager and business context.</p>
          </div>
        </div>
        <div className="space-y-2">
          <label className="text-sm font-semibold" htmlFor="voice-phone">Your calling phone number</label>
          <div className="flex flex-col sm:flex-row gap-2">
            <input id="voice-phone" value={voicePhone} onChange={(e) => setVoicePhone(e.target.value)} placeholder="+919876543210" className="h-10 flex-1 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring" />
            <button onClick={connectVoice} disabled={savingVoice || !voicePhone.trim()} className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-60">
              {savingVoice ? <Loader2 className="h-4 w-4 animate-spin" /> : <Phone className="h-4 w-4" />} {voice.connected ? "Update connection" : "Connect phone"}
            </button>
            {voice.connected && <button onClick={disconnectVoice} disabled={savingVoice} className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-border px-4 text-sm font-medium hover:bg-accent disabled:opacity-60"><PhoneOff className="h-4 w-4" /> Disconnect</button>}
          </div>
          <p className="text-xs leading-5 text-muted-foreground">Use international E.164 format with country code. Connecting the same phone from another workspace moves your calls to that workspace.</p>
          {voice.connected && <p className="text-sm text-primary">Connected to {ws.name}</p>}
          {!voice.service_enabled && <p className="text-xs text-amber-600">The connection can be saved, but the Sarvam voice service is currently disabled by the server administrator.</p>}
        </div>
      </section>

      <section className="border border-border rounded-md bg-card p-6 space-y-5">
        <div>
          <h2 className="font-display text-xl font-bold">Account</h2>
          <p className="text-sm text-muted-foreground mt-1">Your signed-in profile for Arevei.</p>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <InfoItem label="Name" value={user?.name || "Not set"} />
          <InfoItem label="Email" value={user?.email || "Not available"} />
          <InfoItem label="Role" value={user?.role || "User"} />
        </div>
      </section>

      <section className="border border-border rounded-md bg-card p-6 space-y-5">
        <div className="flex items-start gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-md bg-primary/10 text-primary">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <h2 className="font-display text-xl font-bold">Publishable Blog Key</h2>
            <p className="text-sm text-muted-foreground mt-1">
              Frontend-safe key for reading published blog posts only. It cannot create, edit, publish, or delete Arevei content.
            </p>
          </div>
        </div>

        <div className="rounded-md border border-border bg-background p-4">
          <div className="text-xs uppercase text-muted-foreground font-semibold">Current key</div>
          <div className="mt-2 flex items-center gap-3">
            <code className="min-w-0 flex-1 truncate rounded bg-secondary px-3 py-2 text-sm">{ws.public_key}</code>
            <button onClick={copyKey} className="inline-flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm font-medium hover:bg-accent">
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />} {copied ? "Copied" : "Copy"}
            </button>
            <button onClick={rotateKey} disabled={rotatingKey} className="inline-flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm font-medium hover:bg-accent disabled:opacity-60">
              {rotatingKey ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />} Rotate
            </button>
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-sm font-semibold" htmlFor="allowed-origins">Allowed blog origins</label>
          <textarea
            id="allowed-origins"
            value={originsText}
            onChange={(e) => setOriginsText(e.target.value)}
            rows={5}
            placeholder={"https://example.com\nhttps://www.example.com"}
            className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          />
          <p className="text-xs leading-5 text-muted-foreground">
            Optional. Leave empty to allow any website to read published blogs with this key. Add one origin per line to restrict browser requests.
          </p>
          <button onClick={saveOrigins} disabled={savingOrigins} className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-60">
            {savingOrigins ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />} Save Blog Security
          </button>
        </div>
      </section>

      <section className="border border-border rounded-md bg-card p-6 space-y-3">
        <h2 className="font-display text-xl font-bold">Lead Qualification</h2>
        <p className="text-sm text-muted-foreground">Manage product and campaign rules, scoring, retries and next actions.</p>
        <Link className="text-sm text-primary" to={`/app/w/${ws.id}/qualification`}>Open qualification profiles</Link>
      </section>

      <section className="border border-border rounded-md bg-card p-6">
        <h2 className="font-display text-xl font-bold">Workspace</h2>
        <p className="text-sm text-muted-foreground mt-1">Use the account menu in the top bar to switch website workspaces or create a new one.</p>
      </section>
      <VoiceProviders workspaceId={ws.id} />
    </div>
  );
}

function InfoItem({ label, value }) {
  return (
    <div className="rounded-md border border-border bg-background p-4">
      <div className="text-xs uppercase text-muted-foreground font-semibold">{label}</div>
      <div className="mt-1 font-medium capitalize">{value}</div>
    </div>
  );
}

function ModuleCard({ icon: Icon, title, description, active, busy, onToggle }) {
  return <div className={`rounded-lg border p-4 ${active ? "border-primary/40 bg-primary/5" : "bg-background"}`}><div className="flex items-start gap-3"><div className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-primary/10 text-primary"><Icon className="h-4 w-4" /></div><div className="min-w-0 flex-1"><div className="flex items-center justify-between gap-3"><h3 className="font-semibold">{title}</h3><span className={`text-[10px] uppercase font-bold ${active ? "text-primary" : "text-muted-foreground"}`}>{active ? "Active" : "Not installed"}</span></div><p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p><button type="button" disabled={busy} onClick={onToggle} className={`mt-3 inline-flex h-8 items-center gap-2 rounded-md px-3 text-xs font-semibold disabled:opacity-60 ${active ? "border hover:bg-accent" : "bg-primary text-primary-foreground"}`}>{busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}{active ? "Deactivate" : "Install & activate"}</button></div></div></div>;
}
