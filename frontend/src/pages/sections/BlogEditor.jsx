import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft, Bold, Italic, Heading2, Heading3, List, Quote, Link2,
  Save, Globe, Eye, Loader2, Settings2, X,
} from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";

const ToolBtn = ({ onClick, children, label }) => (
  <button
    type="button"
    title={label}
    data-testid={`fmt-${label}`}
    onMouseDown={(e) => {
      e.preventDefault();
      onClick();
    }}
    className="grid h-8 w-8 place-items-center rounded-md text-zinc-500 transition-colors hover:bg-white/[0.08] hover:text-white"
  >
    {children}
  </button>
);

const escapeHtml = (value = "") =>
  String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

const blocksToHtml = (blocks = []) => {
  if (!blocks.length) return "<p></p>";

  return blocks
    .map((block) => {
      if (block.type === "heading") return `<h2>${escapeHtml(block.text)}</h2>`;
      if (block.type === "subheading") return `<h3>${escapeHtml(block.text)}</h3>`;
      if (block.type === "quote") return `<blockquote>${escapeHtml(block.text)}</blockquote>`;
      if (block.type === "list") {
        const items = (block.items || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
        return `<ul>${items}</ul>`;
      }
      return `<p>${escapeHtml(block.text)}</p>`;
    })
    .join("");
};

const htmlToBlocks = (html = "") => {
  const template = document.createElement("template");
  template.innerHTML = html;
  const blocks = [];

  template.content.childNodes.forEach((node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.textContent.trim();
      if (text) blocks.push({ type: "paragraph", text });
      return;
    }

    if (node.nodeType !== Node.ELEMENT_NODE) return;

    const tag = node.tagName.toLowerCase();
    const text = node.textContent.trim();
    if (!text && tag !== "ul" && tag !== "ol") return;

    if (tag === "h1" || tag === "h2") blocks.push({ type: "heading", text });
    else if (tag === "h3") blocks.push({ type: "subheading", text });
    else if (tag === "blockquote") blocks.push({ type: "quote", text });
    else if (tag === "ul" || tag === "ol") {
      blocks.push({
        type: "list",
        items: Array.from(node.querySelectorAll("li")).map((li) => li.textContent.trim()).filter(Boolean),
      });
    } else blocks.push({ type: "paragraph", text });
  });

  return blocks.length ? blocks : [{ type: "paragraph", text: "" }];
};

export default function BlogEditor() {
  const { blogId } = useParams();
  const nav = useNavigate();
  const bodyRef = useRef(null);
  const [blog, setBlog] = useState(null);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [showSettings, setShowSettings] = useState(true);

  useEffect(() => {
    api.get(`/blogs/${blogId}`)
      .then((r) => {
        setBlog(r.data);
        requestAnimationFrame(() => {
          if (bodyRef.current) {
            bodyRef.current.innerHTML = r.data.content_html || blocksToHtml(r.data.blocks);
          }
        });
      })
      .catch(() => {
        toast.error("Blog not found");
        nav("../blogs");
      });
  }, [blogId, nav]);

  const exec = (command, value = null) => {
    document.execCommand(command, false, value);
    bodyRef.current?.focus();
  };

  const format = (tag) => exec("formatBlock", tag);

  const addLink = () => {
    const url = window.prompt("Link URL");
    if (url) exec("createLink", url);
  };

  const set = (key, value) => setBlog((current) => ({ ...current, [key]: value }));

  const payload = () => {
    const contentHtml = bodyRef.current?.innerHTML || blog.content_html || blocksToHtml(blog.blocks);
    return {
      title: blog.title,
      excerpt: blog.excerpt || "",
      hero_image: blog.hero_image || "",
      author: blog.author || "Arevei AI",
      read_time: blog.read_time || "5 min read",
      tags: blog.tags || [],
      blocks: htmlToBlocks(contentHtml),
      content_html: contentHtml,
      meta_title: blog.meta_title || "",
      meta_description: blog.meta_description || "",
      keywords: blog.keywords || [],
    };
  };

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.put(`/blogs/${blogId}`, payload());
      setBlog(data);
      toast.success("Saved");
    } catch {
      toast.error("Save failed");
    } finally {
      setSaving(false);
    }
  };

  const publish = async () => {
    setPublishing(true);
    try {
      const desiredStatus = blog.status === "published" ? "draft" : "published";
      await api.put(`/blogs/${blogId}`, { ...payload(), status: blog.status });
      const { data } = await api.post(`/blogs/${blogId}/publish`, { status: desiredStatus });
      setBlog(data);
      toast.success(data.status === "published" ? "Published live" : "Moved back to draft");
    } catch {
      toast.error("Publish failed");
    } finally {
      setPublishing(false);
    }
  };

  const openPublic = () => {
    if (blog.status !== "published") {
      toast.error("Publish first to open the live URL");
      return;
    }
    window.open(`/blog/${blog.slug}`, "_blank", "noopener,noreferrer");
  };

  if (!blog) {
    return (
      <div className="grid min-h-full place-items-center p-10 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#050506] text-zinc-100">
      <div className="sticky top-0 z-10 flex h-[72px] items-center justify-between border-b border-white/[0.07] bg-[#09090b]/95 px-6 backdrop-blur">
        <div className="flex items-center gap-4">
          <button
            onClick={() => nav("../blogs")}
            data-testid="editor-back"
            className="grid h-8 w-8 place-items-center rounded-md text-zinc-300 transition-colors hover:bg-white/[0.06] hover:text-white"
            title="Back"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold lowercase ${blog.status === "published" ? "bg-emerald-500/15 text-emerald-300" : "bg-white/[0.06] text-zinc-400"}`}>
            {blog.status}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => window.open(`/blog/${blog.slug}`, "_blank", "noopener,noreferrer")}
            data-testid="editor-preview"
            className="inline-flex h-9 items-center gap-2 rounded-md border border-white/10 px-3 text-sm font-medium text-zinc-100 transition-colors hover:bg-white/[0.05]"
          >
            <Eye className="h-4 w-4" /> Preview
          </button>
          <button
            onClick={openPublic}
            className="inline-flex h-9 items-center gap-2 rounded-md border border-white/10 px-3 text-sm font-medium text-zinc-100 transition-colors hover:bg-white/[0.05]"
          >
            <Globe className="h-4 w-4" /> Live URL
          </button>
          <button
            onClick={save}
            disabled={saving}
            data-testid="editor-save"
            className="inline-flex h-9 items-center gap-2 rounded-md border border-white/10 px-3 text-sm font-medium text-zinc-100 transition-colors hover:bg-white/[0.05] disabled:opacity-60"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save
          </button>
          <button
            onClick={publish}
            disabled={publishing}
            data-testid="editor-publish"
            className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-60"
          >
            {publishing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Globe className="h-4 w-4" />}
            {blog.status === "published" ? "Unpublish" : "Publish"}
          </button>
          <button
            onClick={() => setShowSettings((show) => !show)}
            data-testid="editor-toggle-settings"
            className="grid h-9 w-9 place-items-center rounded-md text-zinc-300 transition-colors hover:bg-white/[0.06] hover:text-white"
            title={showSettings ? "Close settings" : "Open settings"}
          >
            {showSettings ? <X className="h-4 w-4" /> : <Settings2 className="h-4 w-4" />}
          </button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-4xl px-8 py-14">
            <input
              value={blog.title}
              onChange={(e) => set("title", e.target.value)}
              data-testid="editor-title"
              className="mb-5 w-full bg-transparent font-serif text-4xl font-bold leading-tight text-white placeholder:text-zinc-700 focus:outline-none sm:text-5xl"
              placeholder="Post title"
            />
            <textarea
              value={blog.excerpt || ""}
              onChange={(e) => set("excerpt", e.target.value)}
              data-testid="editor-excerpt"
              rows={2}
              placeholder="Add a short excerpt / dek..."
              className="mb-10 w-full resize-none bg-transparent text-xl leading-relaxed text-zinc-400 placeholder:text-zinc-700 focus:outline-none"
            />

            <div className="sticky top-0 z-[5] mb-7 flex items-center gap-1 border-y border-white/[0.06] bg-[#050506]/95 py-3 backdrop-blur">
              <ToolBtn onClick={() => exec("bold")} label="bold"><Bold className="h-4 w-4" /></ToolBtn>
              <ToolBtn onClick={() => exec("italic")} label="italic"><Italic className="h-4 w-4" /></ToolBtn>
              <div className="mx-2 h-5 w-px bg-white/10" />
              <ToolBtn onClick={() => format("h2")} label="h2"><Heading2 className="h-4 w-4" /></ToolBtn>
              <ToolBtn onClick={() => format("h3")} label="h3"><Heading3 className="h-4 w-4" /></ToolBtn>
              <ToolBtn onClick={() => format("blockquote")} label="quote"><Quote className="h-4 w-4" /></ToolBtn>
              <ToolBtn onClick={() => exec("insertUnorderedList")} label="list"><List className="h-4 w-4" /></ToolBtn>
              <ToolBtn onClick={addLink} label="link"><Link2 className="h-4 w-4" /></ToolBtn>
              <ToolBtn onClick={() => format("p")} label="paragraph"><span className="text-xs font-semibold">P</span></ToolBtn>
            </div>

            <div
              ref={bodyRef}
              data-testid="editor-body"
              contentEditable
              suppressContentEditableWarning
              data-placeholder="Start writing, or generate with AI from the studio..."
              className="prose-arevei editor-body min-h-[520px] pb-24 focus:outline-none"
            />
          </div>
        </div>

        {showSettings && (
          <aside className="w-80 shrink-0 overflow-y-auto border-l border-white/[0.07] bg-[#08080a] p-6">
            <div className="space-y-8">
              <div>
                <div className="mb-3 text-xs uppercase tracking-wider text-zinc-600">Publishing</div>
                <select
                  value={blog.status}
                  onChange={(e) => set("status", e.target.value)}
                  data-testid="editor-status"
                  className="h-12 w-full rounded-lg border border-white/10 bg-black/50 px-4 text-sm font-medium text-zinc-100 focus:outline-none"
                >
                  <option value="draft">Draft</option>
                  <option value="published">Published</option>
                </select>
              </div>

              <div>
                <div className="mb-2 text-xs uppercase tracking-wider text-zinc-600">Cover Image URL</div>
                <input
                  value={blog.hero_image || ""}
                  onChange={(e) => set("hero_image", e.target.value)}
                  data-testid="editor-hero"
                  placeholder="https://..."
                  className="h-12 w-full rounded-lg border border-white/10 bg-black/50 px-4 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none"
                />
                {blog.hero_image && <img src={blog.hero_image} alt="" className="mt-3 aspect-video w-full rounded-lg object-cover" />}
              </div>

              <div>
                <div className="mb-2 text-xs uppercase tracking-wider text-zinc-600">Read Time</div>
                <input
                  value={blog.read_time || ""}
                  onChange={(e) => set("read_time", e.target.value)}
                  className="h-12 w-full rounded-lg border border-white/10 bg-black/50 px-4 text-sm text-zinc-100 focus:outline-none"
                />
              </div>

              <div>
                <div className="mb-2 text-xs uppercase tracking-wider text-zinc-600">Tags (comma separated)</div>
                <input
                  value={(blog.tags || []).join(", ")}
                  onChange={(e) => set("tags", e.target.value.split(",").map((tag) => tag.trim()).filter(Boolean))}
                  data-testid="editor-tags"
                  className="h-12 w-full rounded-lg border border-white/10 bg-black/50 px-4 text-sm font-semibold text-zinc-100 focus:outline-none"
                />
              </div>

              <div className="border-t border-white/[0.06] pt-5">
                <div className="mb-3 text-xs uppercase tracking-wider text-zinc-600">SEO</div>
                <input
                  value={blog.meta_title || ""}
                  onChange={(e) => set("meta_title", e.target.value)}
                  placeholder="SEO title"
                  data-testid="editor-seo-title"
                  className="mb-2 h-12 w-full rounded-lg border border-white/10 bg-black/50 px-4 text-sm font-semibold text-zinc-100 placeholder:text-zinc-500 focus:outline-none"
                />
                <textarea
                  value={blog.meta_description || ""}
                  onChange={(e) => set("meta_description", e.target.value)}
                  placeholder="Meta description"
                  rows={4}
                  data-testid="editor-seo-desc"
                  className="w-full resize-none rounded-lg border border-white/10 bg-black/50 px-4 py-3 text-sm leading-relaxed text-zinc-100 placeholder:text-zinc-500 focus:outline-none"
                />
              </div>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
