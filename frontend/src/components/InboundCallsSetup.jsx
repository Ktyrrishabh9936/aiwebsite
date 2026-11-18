import { useEffect, useState } from "react";
import api, { formatError } from "../lib/api";

const detail = (error) => { const d = error?.response?.data?.detail; return d && typeof d === "object" && !Array.isArray(d) ? d : null; };
const errorMessage = (error, fallback) => detail(error)?.message || (error?.response?.data?.detail != null ? formatError(error.response.data.detail) : fallback);
const when = (value) => { try { return value ? new Date(value).toLocaleString() : ""; } catch { return ""; } };

// The lookup runs when a call starts, so it is always a little older than the call. Much older means it did not run.
const lookupMissed = (route) => Boolean(route.caller_lookup !== "off" && route.last_call_at
  && (!route.last_context_at || new Date(route.last_call_at) - new Date(route.last_context_at) > 30 * 60 * 1000));

function lookupText(route) {
  if (route.caller_lookup === "off") return "Callers are matched to leads after the call. Recognising them during the call is not available for this agent.";
  if (lookupMissed(route)) return "The caller lookup did not run on the latest call, so the caller was not recognised by name. Callers are still matched to leads after each call.";
  if (route.last_context_at && route.last_context_caller_seen) return "Returning callers are recognised by name during the call.";
  if (route.last_context_at && !route.last_context_caller_seen) return "Sarvam is not sending the caller's number to the lookup yet. In your Sarvam console, open the agent's \"arevei_caller_lookup\" tool and map caller_phone to User Identifier. Callers are still matched to leads after each call.";
  return "Returning callers will be recognised once the first inbound call comes in.";
}

/** Inbound calls for the workspace's own Sarvam agent: answered 24/7 on the agent's calling number. */
export default function InboundCallsSetup({ workspaceId }) {
  const base = `/workspaces/${workspaceId}/voice-providers/sarvam/inbound`;
  const [route, setRoute] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const load = async () => {
    try { const { data } = await api.get(base); setRoute(data || { enabled: false }); }
    catch (error) { setRoute({ enabled: false, status: "unavailable" }); setMessage(errorMessage(error, "Could not load inbound call settings.")); }
  };
  useEffect(() => { load(); }, [base]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = async (enable) => {
    setBusy(true); setMessage(enable ? "Setting up inbound calls in Sarvam… this can take a minute." : "Turning off inbound calls…");
    try {
      const { data } = await api.post(`${base}/${enable ? "enable" : "disable"}`, {});
      setRoute(data);
      setMessage(enable ? `Inbound calls are on. Calls to ${data.agent_phone_number} are answered by your agent 24/7.` : "Inbound calls are off. Your number keeps making outbound calls.");
    } catch (error) {
      const code = detail(error)?.code;
      setMessage(code === "account_not_connected" || code === "account_reconnect_required"
        ? "Reconnect your Sarvam account above, then try again."
        : `Could not ${enable ? "turn on" : "turn off"} inbound calls: ${errorMessage(error, "Could not reach the server.")}`);
      await load();
    } finally { setBusy(false); }
  };

  if (!route) return <p className="text-sm text-muted-foreground">Loading inbound calls…</p>;
  const on = route.enabled && route.status === "active";
  return (
    <section className="rounded-lg border p-3 space-y-2" aria-label="Inbound calls">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold">Inbound calls{on ? ` · on${route.agent_phone_number ? ` (${route.agent_phone_number})` : ""}` : route.enabled ? "" : " · off"}</p>
        {route.enabled
          ? <button type="button" disabled={busy} onClick={() => toggle(false)} className="rounded-lg border px-3 py-1.5 text-sm disabled:opacity-50">{busy ? "Working…" : "Turn off"}</button>
          : <button type="button" disabled={busy} onClick={() => toggle(true)} className="rounded-lg bg-primary text-primary-foreground px-3 py-1.5 text-sm font-semibold disabled:opacity-50">{busy ? "Working…" : "Turn on inbound calls"}</button>}
      </div>
      {!route.enabled && <p className="text-xs text-muted-foreground">Your agent answers calls to its number 24/7. Known leads are recognised by their number, new callers become leads, and every answered call is qualified like an outbound call.</p>}
      {route.status === "needs_attention" && <div role="alert" className="rounded border border-destructive/30 bg-destructive/5 p-2 text-sm">
        Inbound calls need attention: {route.error || "the Sarvam setup is out of date."}
        <button type="button" disabled={busy} onClick={() => toggle(true)} className="ml-2 underline disabled:opacity-50">Fix now</button>
      </div>}
      {on && <>
        <p className="text-xs text-muted-foreground">{lookupText(route)}{lookupMissed(route)
          && <button type="button" disabled={busy} onClick={() => toggle(true)} className="ml-2 underline disabled:opacity-50">Fix now</button>}</p>
        <p className="text-xs text-muted-foreground">{route.last_call_at ? `Last inbound call: ${when(route.last_call_at)}` : "No inbound calls yet."}</p>
      </>}
      {message && <p role="status" className="text-sm">{message}</p>}
    </section>
  );
}
