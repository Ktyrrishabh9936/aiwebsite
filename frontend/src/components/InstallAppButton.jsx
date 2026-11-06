import { useState } from "react";
import { Loader2, Smartphone } from "lucide-react";
import { toast } from "sonner";
import { useInstallApp } from "../lib/installApp";

// One-tap "add to home screen". Opens the browser's native install dialog when it is
// available; otherwise explains the manual steps. Hidden once the app is installed.
export default function InstallAppButton({ className = "" }) {
  const { installed, canPrompt, promptInstall, instructions } = useInstallApp();
  const [busy, setBusy] = useState(false);
  if (installed) return null;

  const install = async () => {
    if (!canPrompt) {
      toast.info("Add Arevei to your home screen", { description: instructions });
      return;
    }
    setBusy(true);
    const outcome = await promptInstall();
    setBusy(false);
    if (outcome === "accepted") toast.success("Arevei is being added to your home screen.");
    else if (outcome === "dismissed") toast.info("Install cancelled", { description: "You can add Arevei to your home screen any time from Overview or Settings." });
    else toast.info("Add Arevei to your home screen", { description: instructions });
  };

  return (
    <button type="button" onClick={install} disabled={busy} title="Add Arevei to your home screen" data-testid="install-app-button" className={`inline-flex items-center justify-center gap-2 h-11 px-5 rounded-lg border border-border bg-card hover:bg-accent text-sm font-semibold disabled:opacity-60 ${className}`}>
      {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Smartphone className="w-4 h-4" />} Install app
    </button>
  );
}
