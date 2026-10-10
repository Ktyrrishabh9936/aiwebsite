import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import api from "../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog";

export default function SalesTaskAction({ task, wsId, onComplete }) {
  const [open,setOpen] = useState(false);
  const [outcome,setOutcome] = useState("");
  const [busy,setBusy] = useState(false);
  const complete = async event => {
    event.preventDefault(); setBusy(true);
    try { await api.post(`/workspaces/${wsId}/sales/tasks/${task.id}/complete`, { outcome }); setOpen(false); onComplete(); toast.success("Sales outcome recorded"); }
    catch { toast.error("Outcome could not be recorded"); }
    finally { setBusy(false); }
  };
  return <><Link className="text-xs text-primary" to={`/app/w/${wsId}/crm${task.lead_id ? `?lead=${task.lead_id}` : ""}`}>Open lead</Link><button onClick={() => setOpen(true)} className="rounded-lg border px-3 py-2 text-xs">Record outcome</button><Dialog open={open} onOpenChange={setOpen}><DialogContent><DialogHeader><DialogTitle>Record sales task outcome</DialogTitle></DialogHeader><p className="text-sm">{task.title}</p><p className="text-xs text-muted-foreground">{task.reason} {task.success_criteria}</p><form onSubmit={complete} className="space-y-4"><label className="text-xs block">Customer response, owner and agreed next step<textarea className="w-full rounded-lg border bg-background p-3 mt-2 text-sm" minLength={3} maxLength={2000} required rows={4} value={outcome} onChange={e => setOutcome(e.target.value)}/></label><button disabled={busy} className="rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm">{busy ? "Saving..." : "Save outcome & complete"}</button></form></DialogContent></Dialog></>;
}
