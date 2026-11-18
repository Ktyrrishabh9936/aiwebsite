import { useEffect, useRef, useState } from "react";
import api, { formatError } from "../lib/api";

const detail = (error) => { const d = error?.response?.data?.detail; return d && typeof d === "object" && !Array.isArray(d) ? d : null; };
const errorMessage = (error, fallback) => detail(error)?.message || (error?.response?.data?.detail != null ? formatError(error.response.data.detail) : fallback);

const isCallback = (text) => /^http:\/\/127\.0\.0\.1:\d+\/\S*[?&](code|error)=/.test((text || "").trim());

/**
 * Finishes a Sarvam sign-in when Sarvam cannot redirect back to this site (its https callback is not
 * allow-listed yet). Sarvam then sends the browser to a 127.0.0.1 address that shows a "can't be reached"
 * page; its address holds a single-use code, which the user pastes here.
 */
export default function SarvamPasteSignIn({ workspaceId, onConnected, onCancel }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const sent = useRef("");     // last address submitted; the automatic path never sends one twice (a code works once)
  const running = useRef(false);

  const finish = async (address = value) => {
    if (running.current) return;
    running.current = true; sent.current = address.trim();
    setBusy(true); setError("");
    try {
      await api.post(`/workspaces/${workspaceId}/voice-providers/sarvam/account/complete`, { callback_url: address.trim() });
      setValue("");
      await onConnected?.();
    } catch (err) {
      setError(errorMessage(err, "Could not finish the Sarvam sign-in."));
    } finally { running.current = false; setBusy(false); }
  };

  // One step instead of three: read the copied address when the user comes back to this tab, and finish by itself.
  const fromClipboard = async (quiet) => {
    try {
      const text = await navigator.clipboard.readText();
      if (quiet && sent.current === text.trim()) return;
      if (isCallback(text)) { setValue(text.trim()); await finish(text); }
      else if (!quiet) setError("The copied text is not the Sarvam address. Copy the whole address from the window that opened.");
    } catch { if (!quiet) setError("Your browser did not allow reading the clipboard. Paste the address into the box instead."); }
  };
  useEffect(() => {
    const onFocus = async () => {
      try { // only when the browser already allows it, so returning to the tab never triggers a permission prompt
        const permission = await navigator.permissions?.query({ name: "clipboard-read" });
        if (permission?.state === "granted") await fromClipboard(true);
      } catch { /* not supported: the button and the box still work */ }
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="rounded-lg border p-3 space-y-2" aria-label="Finish Sarvam sign-in">
      <p className="text-sm font-medium">Finish the Sarvam sign-in</p>
      <ol className="list-decimal pl-5 text-xs text-muted-foreground space-y-1">
        <li>Approve AREVEI in the Sarvam window that opened.</li>
        <li>That window then shows "This site can't be reached". This is expected.</li>
        <li>Copy the whole address from that window's address bar (it starts with http://127.0.0.1), come back here and click "Use copied address".</li>
      </ol>
      <input className="w-full border rounded px-3 py-2 bg-background text-sm" value={value} placeholder="http://127.0.0.1:53682/arevei/sarvam/callback?code=…"
             onChange={(e) => setValue(e.target.value)} aria-label="Sarvam sign-in address"
             onPaste={(e) => { const text = e.clipboardData?.getData("text") || ""; if (isCallback(text)) { e.preventDefault(); setValue(text.trim()); finish(text); } }} />
      <div className="flex flex-wrap gap-2">
        {typeof navigator !== "undefined" && navigator.clipboard?.readText && <button type="button" disabled={busy} onClick={() => fromClipboard(false)} className="rounded-lg bg-primary text-primary-foreground px-3 py-1.5 text-sm font-semibold disabled:opacity-50">
          {busy ? "Connecting…" : "Use copied address"}
        </button>}
        <button type="button" disabled={busy || !value.trim()} onClick={() => finish()} className="rounded-lg bg-primary text-primary-foreground px-3 py-1.5 text-sm font-semibold disabled:opacity-50">
          {busy ? "Connecting…" : "Finish connecting"}
        </button>
        {onCancel && <button type="button" disabled={busy} onClick={onCancel} className="rounded-lg border px-3 py-1.5 text-sm">Cancel</button>}
      </div>
      <p className="text-xs text-muted-foreground">The code works once and expires after 10 minutes. If it expired, click Connect again.</p>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
