import { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { Check, Copy, KeyRound, Loader2, RotateCw, ShieldCheck } from "lucide-react";
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

  useEffect(() => {
    setOriginsText((ws.allowed_blog_origins || []).join("\n"));
  }, [ws.allowed_blog_origins]);

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

  return (
    <div className="p-6 sm:p-10 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="font-display text-3xl font-black tracking-tight">Settings</h1>
        <p className="text-muted-foreground mt-1">Manage your account and workspace preferences.</p>
      </div>

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

      <section className="border border-border rounded-md bg-card p-6">
        <h2 className="font-display text-xl font-bold">Workspace</h2>
        <p className="text-sm text-muted-foreground mt-1">Use the account menu in the top bar to switch website workspaces or create a new one.</p>
      </section>
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
