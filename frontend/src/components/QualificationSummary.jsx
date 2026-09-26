import { PhoneCall, ExternalLink, RefreshCw, Ban } from "lucide-react";

export default function QualificationSummary({ communication, qualification, saving, onCancel }) {
  const hasSummary = communication.latest_summary || qualification.summary || qualification.status || qualification.scheduled_for;
  if (!hasSummary) return null;
  const status = communication.last_call_status || qualification.status || "updated";
  const recording = communication.last_recording_url || qualification.recording_url;
  const callTimestamp = qualification.call_timestamp;
  const category = communication.qualification_category || qualification.qualification_category;
  const qualificationStatus = communication.qualification_status || qualification.qualification_status;
  const score = communication.qualification_score ?? qualification.qualification_score;
  const scheduledFor = qualification.status === "scheduled" && qualification.scheduled_for;
  const categoryClass = category === "hot" ? "border-red-500/30 text-red-500 bg-red-500/10" : category === "warm" ? "border-amber-500/30 text-amber-500 bg-amber-500/10" : category === "cold" ? "border-blue-500/30 text-blue-500 bg-blue-500/10" : category === "junk" ? "border-destructive/30 text-destructive bg-destructive/10" : "border-border text-muted-foreground bg-muted";
  return (
    <section className="rounded-lg border bg-background p-4 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h4 className="font-bold flex items-center gap-2"><PhoneCall className="w-4 h-4 text-primary" /> Qualification</h4>
        <div className="flex flex-wrap justify-end gap-2">
          {category && <span className={`px-2 py-1 rounded-md border text-[11px] font-semibold uppercase ${categoryClass}`}>{category}</span>}
          {qualificationStatus && <span className={`px-2 py-1 rounded-md border text-[11px] font-semibold uppercase ${qualificationStatus === "qualified" ? "border-emerald-500/30 text-emerald-500 bg-emerald-500/10" : qualificationStatus === "not_qualified" ? "border-destructive/30 text-destructive bg-destructive/10" : "border-border text-muted-foreground bg-muted"}`}>{qualificationStatus.replace("_", " ")}</span>}
          {score != null && score !== "" && <span className="px-2 py-1 rounded-md border bg-card text-[11px] font-semibold">{score}%</span>}
          <span className="px-2 py-1 rounded-md border bg-muted text-[11px] font-semibold uppercase text-muted-foreground">{status}</span>
        </div>
      </div>
      {scheduledFor && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-primary/20 bg-primary/5 p-3 text-xs">
          <span className="font-semibold text-primary">Scheduled for {new Date(scheduledFor).toLocaleString([], { dateStyle: "medium", timeStyle: "short", hour12: true })}</span>
          {onCancel && <button onClick={onCancel} disabled={saving} className="inline-flex items-center gap-1.5 px-2.5 h-8 rounded-lg border bg-background hover:bg-accent font-semibold disabled:opacity-50" title="Cancel scheduled call">
            {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Ban className="w-3.5 h-3.5" />}
            Cancel Call
          </button>}
        </div>
      )}
      {(communication.latest_summary || qualification.summary) && <p className="text-sm leading-relaxed">{communication.latest_summary || qualification.summary}</p>}
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {communication.total_call_count ? <span>{communication.total_call_count} call{communication.total_call_count === 1 ? "" : "s"} tracked</span> : null}
        {(communication.disconnection_reason || qualification.disconnection_reason) && <span>Reason: {communication.disconnection_reason || qualification.disconnection_reason}</span>}
        {(communication.last_duration || qualification.duration) && <span>{communication.last_duration || qualification.duration}s</span>}
        {callTimestamp && <span>{new Date(callTimestamp).toLocaleString([], { dateStyle: "medium", timeStyle: "short", hour12: true })}</span>}
        {recording && <a href={recording} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 px-2.5 h-8 rounded-lg border bg-card hover:bg-accent text-foreground font-semibold"><ExternalLink className="w-3.5 h-3.5" /> Open recording</a>}
      </div>
    </section>
  );
}
