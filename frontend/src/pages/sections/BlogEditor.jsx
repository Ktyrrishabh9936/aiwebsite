import { useEffect, useState } from "react";
import { useOutletContext, useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft, Save, Globe, Eye, Loader2, Plus, Trash2, ChevronUp, ChevronDown,
  Type, Heading, Quote, List as ListIcon,
} from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import { Label } from "../../components/ui/label";
import { BlockRenderer } from "../../components/BlockRenderer";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "../../components/ui/dropdown-menu";

const BLOCK_TYPES = [
  { type: "paragraph", label: "Paragraph", icon: Type },
  { type: "heading", label: "Heading", icon: Heading },
  { type: "quote", label: "Quote", icon: Quote },
  { type: "list", label: "List", icon: ListIcon },
];

export default function BlogEditor() {
  const { ws } = useOutletContext();
  const { blogId } = useParams();
  const nav = useNavigate();
  const [blog, setBlog] = useState(null);
  const [saving, setSaving] = useState(false);
  const [preview, setPreview] = useState(false);

  useEffect(() => { api.get(`/blogs/${blogId}`).then((r) => setBlog(r.data)); }, [blogId]);

  if (!blog) return <div className="p-10 grid place-items-center text-muted-foreground"><Loader2 className="w-5 h-5 animate-spin" /></div>;

  const set = (patch) => setBlog((b) => ({ ...b, ...patch }));
  const setBlock = (i, patch) => setBlog((b) => { const blocks = [...b.blocks]; blocks[i] = { ...blocks[i], ...patch }; return { ...b, blocks }; });
  const addBlock = (type) => setBlog((b) => ({ ...b, blocks: [...b.blocks, type === "list" ? { type, items: ["New item"] } : { type, text: "" }] }));
  const removeBlock = (i) => setBlog((b) => ({ ...b, blocks: b.blocks.filter((_, j) => j !== i) }));
  const move = (i, dir) => setBlog((b) => {
    const blocks = [...b.blocks]; const j = i + dir;
    if (j < 0 || j >= blocks.length) return b;
    [blocks[i], blocks[j]] = [blocks[j], blocks[i]];
    return { ...b, blocks };
  });

  const save = async (publish) => {
    setSaving(true);
    try {
      await api.put(`/blogs/${blogId}`, {
        title: blog.title, excerpt: blog.excerpt, hero_image: blog.hero_image, author: blog.author,
        read_time: blog.read_time, tags: blog.tags, blocks: blog.blocks,
        meta_title: blog.meta_title, meta_description: blog.meta_description, keywords: blog.keywords,
      });
      if (publish !== undefined) {
        const r = await api.post(`/blogs/${blogId}/publish`);
        set({ status: r.data.status, slug: r.data.slug });
      }
      toast.success("Saved");
    } catch { toast.error("Save failed"); }
    finally { setSaving(false); }
  };

  return (
    <div className="min-h-full">
      <div className="sticky top-0 z-10 glass border-b border-border px-5 h-14 flex items-center justify-between gap-3">
        <button onClick={() => nav("../blogs")} data-testid="editor-back" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="w-4 h-4" /> Blogs
        </button>
        <div className="flex items-center gap-2">
          <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded-full ${blog.status === "published" ? "bg-primary/10 text-primary" : "bg-secondary text-muted-foreground"}`}>{blog.status}</span>
          <button onClick={() => setPreview((p) => !p)} data-testid="editor-toggle-preview" className="inline-flex items-center gap-1.5 px-3 h-9 rounded-full border border-border hover:bg-accent text-sm font-medium">
            <Eye className="w-4 h-4" /> {preview ? "Edit" : "Preview"}
          </button>
          <button onClick={() => save(undefined)} disabled={saving} data-testid="editor-save" className="inline-flex items-center gap-1.5 px-4 h-9 rounded-full border border-border hover:bg-accent text-sm font-medium disabled:opacity-60">
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />} Save
          </button>
          <button onClick={() => save(true)} disabled={saving} data-testid="editor-publish" className="inline-flex items-center gap-1.5 px-4 h-9 rounded-full bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-60">
            <Globe className="w-4 h-4" /> {blog.status === "published" ? "Update / Unpublish" : "Publish"}
          </button>
        </div>
      </div>

      {preview ? (
        <article className="max-w-3xl mx-auto px-6 py-10">
          {blog.hero_image && <img src={blog.hero_image} alt="" className="w-full h-72 object-cover rounded-md mb-8" />}
          <h1 className="font-display text-4xl font-black tracking-tight mb-4">{blog.title}</h1>
          <p className="text-lg text-muted-foreground mb-8">{blog.excerpt}</p>
          <BlockRenderer blocks={blog.blocks} />
        </article>
      ) : (
        <div className="grid lg:grid-cols-[1fr_320px] gap-0">
          {/* Main editor */}
          <div className="px-6 py-8 max-w-3xl mx-auto w-full space-y-5">
            <input
              value={blog.title}
              onChange={(e) => set({ title: e.target.value })}
              data-testid="editor-title"
              className="w-full font-display text-3xl sm:text-4xl font-black tracking-tight bg-transparent focus:outline-none"
              placeholder="Blog title"
            />
            <Textarea value={blog.excerpt} onChange={(e) => set({ excerpt: e.target.value })} data-testid="editor-excerpt" rows={2} placeholder="Short excerpt…" className="text-base" />

            <div className="space-y-3 pt-2">
              {blog.blocks.map((blk, i) => (
                <div key={i} className="group relative border border-border rounded-md p-3 bg-card" data-testid={`editor-block-${i}`}>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-[10px] uppercase tracking-wider font-bold text-muted-foreground">{blk.type}</span>
                    <div className="ml-auto flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button onClick={() => move(i, -1)} className="grid place-items-center w-7 h-7 rounded hover:bg-accent"><ChevronUp className="w-3.5 h-3.5" /></button>
                      <button onClick={() => move(i, 1)} className="grid place-items-center w-7 h-7 rounded hover:bg-accent"><ChevronDown className="w-3.5 h-3.5" /></button>
                      <button onClick={() => removeBlock(i)} data-testid={`block-delete-${i}`} className="grid place-items-center w-7 h-7 rounded hover:bg-accent text-muted-foreground hover:text-destructive"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  </div>
                  {blk.type === "list" ? (
                    <Textarea
                      value={(blk.items || []).join("\n")}
                      onChange={(e) => setBlock(i, { items: e.target.value.split("\n") })}
                      rows={Math.max(2, (blk.items || []).length)}
                      className="text-sm"
                      placeholder="One item per line"
                    />
                  ) : (
                    <Textarea
                      value={blk.text || ""}
                      onChange={(e) => setBlock(i, { text: e.target.value })}
                      rows={blk.type === "heading" ? 1 : 3}
                      className={blk.type === "heading" ? "font-display font-bold text-lg" : "text-sm"}
                      placeholder={blk.type}
                    />
                  )}
                </div>
              ))}
            </div>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button data-testid="add-block-btn" className="inline-flex items-center gap-2 px-4 h-10 rounded-full border border-dashed border-border hover:bg-accent text-sm font-medium">
                  <Plus className="w-4 h-4" /> Add block
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                {BLOCK_TYPES.map((bt) => (
                  <DropdownMenuItem key={bt.type} onClick={() => addBlock(bt.type)} data-testid={`add-block-${bt.type}`} className="gap-2 cursor-pointer">
                    <bt.icon className="w-4 h-4" /> {bt.label}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          {/* Meta sidebar */}
          <aside className="border-l border-border p-6 space-y-5 bg-card/40">
            <div className="font-display font-bold">Settings</div>
            <div className="space-y-2">
              <Label>Hero image URL</Label>
              <Input value={blog.hero_image} onChange={(e) => set({ hero_image: e.target.value })} data-testid="editor-hero" className="text-xs" />
              {blog.hero_image && <img src={blog.hero_image} alt="" className="w-full h-24 object-cover rounded" />}
            </div>
            <div className="space-y-2">
              <Label>Read time</Label>
              <Input value={blog.read_time} onChange={(e) => set({ read_time: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>Tags (comma separated)</Label>
              <Input value={(blog.tags || []).join(", ")} onChange={(e) => set({ tags: e.target.value.split(",").map((t) => t.trim()).filter(Boolean) })} data-testid="editor-tags" />
            </div>
            <div className="pt-2 border-t border-border space-y-2">
              <Label>SEO title</Label>
              <Input value={blog.meta_title} onChange={(e) => set({ meta_title: e.target.value })} />
              <Label>SEO description</Label>
              <Textarea value={blog.meta_description} onChange={(e) => set({ meta_description: e.target.value })} rows={3} />
            </div>
            {blog.status === "published" && (
              <a href={`/blog/${blog.slug}`} target="_blank" rel="noreferrer" className="block text-sm text-primary hover:underline break-all">/blog/{blog.slug}</a>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
