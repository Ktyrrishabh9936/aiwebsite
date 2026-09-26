import { useState } from "react";
import { MessageSquare, PhoneCall, Bot, Trash2, Send } from "lucide-react";

export default function LeadNotes({ notes = [], saving, onAdd, onDelete }) {
  const [draft, setDraft] = useState("");
  const send = async () => { if (await onAdd(draft.trim())) setDraft(""); };
  return (
<section className="space-y-3">
            <h4 className="font-bold flex items-center gap-2"><MessageSquare className="w-4 h-4 text-primary" /> Lead Notes</h4>
            <div className="h-[360px] overflow-y-auto rounded-lg border bg-background p-3 space-y-3">
              {(notes || []).length === 0 ? (
                <div className="h-full grid place-items-center text-center text-xs text-muted-foreground">No notes yet.</div>
              ) : (notes || []).map((note) => (
                <div key={note.id} className="flex justify-end">
                  <div className="max-w-[86%] rounded-2xl rounded-br-md bg-primary text-primary-foreground px-3 py-2 shadow-sm">
                    {note.source === "call_agent" && (
                      <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[10px] font-semibold uppercase opacity-80">
                        <PhoneCall className="w-3 h-3" />
                        <span>{note.call_provider === "plivo" ? "AI call" : note.call_provider || "call"}</span>
                        {note.call_direction && <span>{note.call_direction}</span>}
                        {note.status && <span>{note.status}</span>}
                        {note.duration && <span>{note.duration}s</span>}
                      </div>
                    )}
                    {note.source === "lead_context_agent" && (
                      <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[10px] font-semibold uppercase opacity-80">
                        <Bot className="w-3 h-3" /><span>Lead Context Agent</span>
                        {note.context_source && <span>{note.context_source.replaceAll("_", " ")}</span>}
                      </div>
                    )}
                    {note.source === "manual_whatsapp" && <div className="mb-1 text-[10px] font-semibold uppercase opacity-80">WhatsApp · marked sent manually</div>}
                    <div className="text-sm whitespace-pre-wrap leading-relaxed">{note.body}</div>
                    <StructuredCallDetails note={note} />
                    {note.recording_url && <a href={note.recording_url} target="_blank" rel="noreferrer" className="mt-1 block text-[10px] underline underline-offset-2 opacity-90">Open recording</a>}
                    <div className="mt-1 flex items-center justify-end gap-2 text-[10px] opacity-80">
                      <span>{note.author}</span>
                      <span>{new Date(note.created_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short", hour12: true })}</span>
                      {onDelete && <button onClick={() => onDelete(note.id)} disabled={saving} className="opacity-80 hover:opacity-100 disabled:opacity-40" title="Remove note"><Trash2 className="w-3 h-3" /></button>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <div className="flex items-end gap-2">
              <textarea value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Add an internal lead note" rows={3} className="flex-1 px-3 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
              <button onClick={send} disabled={saving || !draft.trim()} className="grid place-items-center w-11 h-11 rounded-full bg-primary text-primary-foreground disabled:opacity-50" title="Send note"><Send className="w-4 h-4" /></button>
            </div>
          </section>
  );
}

function listItems(value) {
  if (Array.isArray(value)) return value.filter(Boolean).map(String);
  if (value && typeof value === "object") return Object.entries(value).filter(([, v]) => v != null && String(v).trim()).map(([k, v]) => `${k}: ${v}`);
  if (typeof value === "string" && value.trim()) return value.split(/\r?\n/).map((v) => v.trim()).filter(Boolean);
  return [];
}


function StructuredCallDetails({ note }) {
  const answers = listItems(note.answers);
  const collected = listItems(note.collected_information);
  const pending = listItems(note.pending_discussion);
  const steps = listItems(note.recommended_next_steps);
  const hasDetails = answers.length || collected.length || pending.length || steps.length || note.transcript;
  if (!hasDetails) return null;
  return (
    <div className="mt-2 space-y-2 rounded-lg bg-primary-foreground/10 p-2 text-[11px] leading-relaxed">
      <InlineDetails label="Answers" items={answers} />
      <InlineDetails label="Collected" items={collected} />
      <InlineDetails label="Pending" items={pending} />
      <InlineDetails label="Next" items={steps} />
      {note.transcript && <details><summary className="cursor-pointer font-semibold">Transcript</summary><div className="mt-1 whitespace-pre-wrap opacity-90">{note.transcript}</div></details>}
    </div>
  );
}

function InlineDetails({ label, items }) {
  if (!items.length) return null;
  return <div><span className="font-semibold">{label}: </span>{items.slice(0, 6).join("; ")}</div>;
}
