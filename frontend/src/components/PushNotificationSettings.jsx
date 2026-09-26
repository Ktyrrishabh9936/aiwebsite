import { useEffect, useState } from "react";
import { Bell, Loader2 } from "lucide-react";
import { currentDevice, enablePush, disablePush } from "../lib/pushNotifications";
import { formatError } from "../lib/api";

export default function PushNotificationSettings({ wsId }) {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setStatus(null);
    setError("");
    const refresh = () => currentDevice(wsId).then((data) => { if (active) setStatus(data); })
      .catch(() => { if (active) setError("Could not check notifications. Try again."); });
    refresh();
    window.addEventListener("focus", refresh);
    window.addEventListener("arevei:push-changed", refresh);
    return () => { active = false; window.removeEventListener("focus", refresh); window.removeEventListener("arevei:push-changed", refresh); };
  }, [wsId]);

  async function toggle() {
    setBusy(true);
    setError("");
    try {
      if (status?.enabled) await disablePush(wsId);
      else await enablePush(wsId);
      setStatus(await currentDevice(wsId));
    } catch (failure) {
      setError(formatError(failure.response?.data?.detail || failure.message));
    } finally { setBusy(false); }
  }

  return <section aria-labelledby="follow-up-notifications" className="border border-border rounded-md bg-card p-6 space-y-4">
    <div className="flex items-start gap-3"><Bell className="h-5 w-5 mt-1 text-primary shrink-0" /><div>
      <h2 id="follow-up-notifications" className="font-display text-xl font-bold">Follow-up notifications</h2>
      <p className="text-sm text-muted-foreground mt-1">Get alerts for follow-ups you create in this workspace, even when the app is closed. Tap an alert to open the lead.</p>
    </div></div>
    <p className="text-sm" role="status">{!status ? "Checking notification settings…" : !status.supported ? "Install the app on iPhone, or use a supported browser over HTTPS." : !status.configured ? "Server notification setup is pending." : status.enabled ? "Enabled on this device for this workspace." : "Off on this device for this workspace."}</p>
    <button type="button" onClick={toggle} disabled={busy || status?.supported === false || status?.configured === false} className="inline-flex min-h-10 items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50">{busy && <Loader2 className="h-4 w-4 animate-spin" />}{status?.enabled ? "Turn off notifications" : "Enable notifications"}</button>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <p className="text-xs leading-5 text-muted-foreground">On iPhone, first add Arevei to your home screen, launch it from there, and enable notifications here. Delivery requires an internet connection and may be delayed by your phone’s notification settings.</p>
  </section>;
}
