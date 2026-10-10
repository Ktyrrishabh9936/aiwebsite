import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "./ui/dialog";
import { PRODUCT_UPDATES, readSeenUpdates, unreadUpdates } from "../lib/productUpdates";

export default function ProductUpdates({ userId, wsId, onExplore }) {
  const key = `arevei:updates:seen:${userId || "session"}`;
  const [seen, setSeen] = useState(() => readSeenUpdates(key));
  const [open, setOpen] = useState(false);
  useEffect(() => { setSeen(readSeenUpdates(key)); }, [key]);
  useEffect(() => {
    const sync = event => { if (event.key === key) setSeen(readSeenUpdates(key)); };
    window.addEventListener("storage", sync); return () => window.removeEventListener("storage", sync);
  }, [key]);
  const unread = unreadUpdates(seen);
  useEffect(() => {
    if (!unread.length) return;
    const noticeKey = `${key}:notice:${unread[0].id}`;
    try { if (localStorage.getItem(noticeKey)) return; localStorage.setItem(noticeKey, "1"); } catch { return; }
    toast("New product updates are available", { description: unread[0].title, action: { label: "See updates", onClick: () => setOpen(true) } });
  }, [key, unread]);
  const markSeen = () => {
    const ids = PRODUCT_UPDATES.map(release => release.id);
    setSeen(ids); try { localStorage.setItem(key, JSON.stringify(ids)); } catch { /* In-memory dismissal remains usable. */ }
  };
  const selectors = unread.flatMap(release => release.features.flatMap(feature => feature.selectors));
  return <>
    {selectors.length > 0 && <style>{`${selectors.join(",")} { outline: 2px solid hsl(var(--primary) / .65); outline-offset: 2px; } ${selectors.map(selector => `${selector}::after`).join(",")} { content: 'New'; display: inline-block; margin-left: 6px; padding: 1px 5px; border-radius: 6px; background: hsl(var(--primary)); color: hsl(var(--primary-foreground)); font-size: 10px; font-weight: 700; }`}</style>}
    <button type="button" onClick={() => setOpen(true)} aria-label={unread.length ? "New updates, unread" : "New updates"} className="relative inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs font-semibold hover:bg-accent"><Sparkles size={15}/><span>New updates</span>{unread.length > 0 && <span aria-hidden="true" className="h-2 w-2 rounded-full bg-primary"/>}</button>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent className="max-w-2xl max-h-[85dvh] overflow-y-auto"><DialogHeader><DialogTitle>What's new in AI Manager</DialogTitle><DialogDescription>Explore updated features. Mark releases as read to clear their highlights on this browser.</DialogDescription></DialogHeader>{PRODUCT_UPDATES.map(release => <section key={release.id} className="space-y-4 border-t pt-4"><div><p className="text-xs text-muted-foreground">{release.date}{!seen.includes(release.id) && " · Unread"}</p><h3 className="text-lg font-bold mt-1">{release.title}</h3></div>{release.features.map(feature => <article key={feature.id} className="rounded-lg border p-4"><h4 className="font-semibold">{feature.title}</h4><p className="text-sm text-muted-foreground leading-relaxed mt-2">{feature.description}</p><button type="button" onClick={() => { setOpen(false); onExplore(`/app/w/${wsId}/${feature.path}`); }} className="text-sm text-primary font-semibold mt-3">Explore feature →</button></article>)}</section>)}<button type="button" onClick={markSeen} disabled={!unread.length} className="rounded-lg bg-primary text-primary-foreground px-4 py-2 font-semibold disabled:opacity-50">{unread.length ? "Mark all as read" : "All updates read"}</button></DialogContent></Dialog>
  </>;
}
