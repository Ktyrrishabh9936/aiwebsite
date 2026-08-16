import { useEffect, useState } from "react";
import { useOutletContext, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Plus, Loader2, Sparkles, Eye, Trash2, Globe, PenLine } from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";

export default function Blogs() {
  const { ws } = useOutletContext();
  const nav = useNavigate();
  const [blogs, setBlogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [topic, setTopic] = useState("");
  const [genning, setGenning] = useState(false);

  const load = () => api.get(`/workspaces/${ws.id}/blogs`).then((r) => setBlogs(r.data)).finally(() => setLoading(false));
  useEffect(() => { load(); }, [ws.id]);

  const generate = async (e) => {
    e.preventDefault();
    setGenning(true);
    try {
      const r = await api.post(`/workspaces/${ws.id}/blogs/generate`, { topic, model_id: ws.model_id });
      toast.success("Draft generated");
      setOpen(false); setTopic("");
      nav(`${r.data.id}`);
    } catch (err) {
      toast.error(formatError(err.response?.data?.detail));
    } finally { setGenning(false); }
  };

  const togglePublish = async (b) => {
    await api.post(`/blogs/${b.id}/publish`);
    load();
  };
  const del = async (id) => { await api.delete(`/blogs/${id}`); load(); toast.success("Deleted"); };

  return (
    <div className="p-6 sm:p-10 max-w-5xl mx-auto space-y-6">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <h1 className="font-display text-3xl font-black tracking-tight">Blogs</h1>
          <p className="text-muted-foreground mt-1">AI-written, advanced editor, full public previews.</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <button data-testid="generate-blog-btn" disabled={ws.brain_status !== "ready"} className="inline-flex items-center gap-2 px-5 h-11 rounded-full bg-primary text-primary-foreground font-semibold hover:-translate-y-0.5 transition-transform disabled:opacity-50">
              <Sparkles className="w-4 h-4" /> Generate blog
            </button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader><DialogTitle className="font-display">Generate a blog</DialogTitle></DialogHeader>
            <form onSubmit={generate} className="space-y-5 pt-2" data-testid="generate-blog-form">
              <div className="space-y-2">
                <Label htmlFor="topic">Topic or title</Label>
                <Input id="topic" data-testid="blog-topic-input" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="e.g. How AI website management drives organic growth" required />
                <p className="text-xs text-muted-foreground">The content agent writes on-brand using your brain.</p>
              </div>
              <button type="submit" disabled={genning} data-testid="generate-blog-submit" className="w-full h-11 rounded-full bg-primary text-primary-foreground font-semibold disabled:opacity-60 inline-flex items-center justify-center gap-2">
                {genning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />} {genning ? "Writing…" : "Write draft"}
              </button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {loading ? <div className="text-muted-foreground">Loading…</div> : blogs.length === 0 ? (
        <div className="border border-dashed border-border rounded-md py-16 text-center text-muted-foreground">No blogs yet. Generate one or let the scheduler auto-create them.</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {blogs.map((b, i) => (
            <motion.div key={b.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i * 0.04, 0.3) }} className="border border-border rounded-md bg-card overflow-hidden group" data-testid={`blog-card-${b.id}`}>
              {b.hero_image && <img src={b.hero_image} alt="" className="w-full h-40 object-cover" />}
              <div className="p-5">
                <div className="flex items-center gap-2 mb-2">
                  <span className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded-full ${b.status === "published" ? "bg-primary/10 text-primary" : "bg-secondary text-muted-foreground"}`}>{b.status}</span>
                  <span className="text-xs text-muted-foreground">{b.read_time}</span>
                </div>
                <h3 className="font-display font-bold leading-snug line-clamp-2">{b.title}</h3>
                <p className="text-sm text-muted-foreground mt-1 line-clamp-2">{b.excerpt}</p>
                <div className="mt-4 flex items-center gap-1.5">
                  <button onClick={() => nav(`${b.id}`)} data-testid={`blog-edit-${b.id}`} className="inline-flex items-center gap-1.5 px-3 h-9 rounded-full bg-primary text-primary-foreground text-sm font-medium"><PenLine className="w-3.5 h-3.5" /> Edit</button>
                  <button onClick={() => togglePublish(b)} data-testid={`blog-publish-${b.id}`} className="inline-flex items-center gap-1.5 px-3 h-9 rounded-full border border-border hover:bg-accent text-sm font-medium"><Globe className="w-3.5 h-3.5" /> {b.status === "published" ? "Unpublish" : "Publish"}</button>
                  {b.status === "published" && (
                    <a href={`/blog/${b.slug}`} target="_blank" rel="noreferrer" data-testid={`blog-preview-${b.id}`} className="grid place-items-center w-9 h-9 rounded-full border border-border hover:bg-accent" title="Preview"><Eye className="w-4 h-4" /></a>
                  )}
                  <button onClick={() => del(b.id)} className="grid place-items-center w-9 h-9 rounded-full border border-border hover:bg-accent text-muted-foreground hover:text-destructive ml-auto"><Trash2 className="w-4 h-4" /></button>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
