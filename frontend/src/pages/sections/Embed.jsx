import { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { Copy, Check, Code2, Globe, Terminal } from "lucide-react";
import { toast } from "sonner";
import api from "../../lib/api";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../../components/ui/tabs";

function CodeBlock({ code, testid }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    toast.success("Copied");
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="relative border border-border rounded-md bg-secondary/50 overflow-hidden">
      <button onClick={copy} data-testid={testid} className="absolute top-3 right-3 inline-flex items-center gap-1.5 px-3 h-8 rounded-full bg-primary text-primary-foreground text-xs font-medium">
        {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />} {copied ? "Copied" : "Copy"}
      </button>
      <pre className="font-mono text-xs p-4 pr-24 overflow-x-auto whitespace-pre-wrap">{code}</pre>
    </div>
  );
}

export default function Embed() {
  const { ws } = useOutletContext();
  const [count, setCount] = useState(0);
  const [previewPosts, setPreviewPosts] = useState([]);
  const [previewLoading, setPreviewLoading] = useState(true);
  const [previewError, setPreviewError] = useState("");
  const backend = process.env.REACT_APP_BACKEND_URL || window.location.origin;
  const origin = window.location.origin;
  const key = ws.public_key;

  useEffect(() => {
    setPreviewLoading(true);
    setPreviewError("");
    api.get(`/workspaces/${ws.id}/blogs`)
      .then((r) => {
        const published = (r.data || []).filter((post) => post.status === "published");
        setPreviewPosts(published);
        setCount(published.length);
      })
      .catch((e) => setPreviewError(e.response?.data?.detail || "Could not load blog preview"))
      .finally(() => setPreviewLoading(false));
  }, [ws.id]);

  const scriptSnippet = `<!-- Arevei Blog System - uses a publishable read-only blog key -->
<div id="arevei-blog"></div>
<script src="${backend}/api/embed/widget.js?key=${key}" defer></script>`;

  const reactSnippet = `import { useEffect, useState } from "react";

const AREVEI_PUBLISHABLE_BLOG_KEY = "${key}";
const AREVEI_API = "${backend}";

export function AreveiBlog() {
  const [posts, setPosts] = useState([]);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch(\`\${AREVEI_API}/api/public/blogs?key=\${AREVEI_PUBLISHABLE_BLOG_KEY}\`)
      .then(async r => {
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(data.detail || \`HTTP \${r.status}\`);
        if (!Array.isArray(data)) throw new Error("Unexpected blog response");
        return data;
      })
      .then(setPosts)
      .catch(e => setError(e.message || "Unable to load blogs"));
  }, []);
  if (error) return <p>Unable to load blogs: {error}.</p>;
  if (posts.length === 0) return <p>No published blogs yet.</p>;
  return (
    <div style={{display:"grid",gap:20,gridTemplateColumns:"repeat(auto-fill,minmax(280px,1fr))"}}>
      {posts.map(p => (
        <a key={p.slug} href={\`${origin}/blog/\${p.slug}\`} target="_blank" rel="noreferrer">
          <img src={p.hero_image} alt="" style={{width:"100%",height:160,objectFit:"cover",borderRadius:10}} />
          <h3>{p.title}</h3>
          <p>{p.excerpt}</p>
        </a>
      ))}
    </div>
  );
}`;

  const apiSnippet = `# List published blogs with a publishable read-only key
GET ${backend}/api/public/blogs?key=${key}

# Fetch a single published blog by slug
GET ${backend}/api/public/blog/{slug}`;

  return (
    <div className="p-6 sm:p-10 max-w-4xl mx-auto space-y-8">
      <div>
        <h1 className="font-display text-3xl font-black tracking-tight">Add Blog System</h1>
        <p className="text-muted-foreground mt-1">
          Drop your Arevei-managed blog into any codebase. This app stays the control panel - you write and publish here,
          it appears there automatically through a frontend-safe read-only key. {count} published post{count === 1 ? "" : "s"} live.
        </p>
      </div>

      <div className="border border-border rounded-md bg-card p-5 flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] font-bold text-primary mb-1">Publishable Blog Key</div>
          <div className="font-mono text-sm">{key}</div>
        </div>
        <button onClick={() => { navigator.clipboard.writeText(key); toast.success("Publishable key copied"); }} data-testid="copy-key-btn" className="inline-flex items-center gap-2 px-4 h-10 rounded-full border border-border hover:bg-accent text-sm font-medium">
          <Copy className="w-4 h-4" /> Copy key
        </button>
      </div>

      <div className="rounded-md border border-border bg-secondary/30 p-4 text-sm leading-6 text-muted-foreground">
        This key is safe to place in frontend code because it can only read published blog content. Private Arevei auth tokens, admin keys, and model provider keys should never be added to customer codebases.
      </div>

      <Tabs defaultValue="script">
        <TabsList>
          <TabsTrigger value="script" data-testid="tab-script"><Globe className="w-4 h-4 mr-1.5" /> Script</TabsTrigger>
          <TabsTrigger value="react" data-testid="tab-react"><Code2 className="w-4 h-4 mr-1.5" /> React</TabsTrigger>
          <TabsTrigger value="api" data-testid="tab-api"><Terminal className="w-4 h-4 mr-1.5" /> API</TabsTrigger>
        </TabsList>
        <TabsContent value="script" className="space-y-3 pt-4">
          <p className="text-sm text-muted-foreground">Works in any HTML site. Paste this snippet; it renders a responsive blog grid linking to full article pages.</p>
          <CodeBlock code={scriptSnippet} testid="copy-script" />
        </TabsContent>
        <TabsContent value="react" className="space-y-3 pt-4">
          <p className="text-sm text-muted-foreground">Drop this component into a React app.</p>
          <CodeBlock code={reactSnippet} testid="copy-react" />
        </TabsContent>
        <TabsContent value="api" className="space-y-3 pt-4">
          <p className="text-sm text-muted-foreground">Build a fully custom UI on top of the public JSON API.</p>
          <CodeBlock code={apiSnippet} testid="copy-api" />
        </TabsContent>
      </Tabs>

      <div className="border border-border rounded-md bg-card p-6">
        <div className="text-xs uppercase tracking-[0.2em] font-bold text-primary mb-3">Live preview</div>
        <div data-testid="embed-preview" className="min-h-72 rounded-md border border-border bg-background p-4">
          {previewLoading ? (
            <div className="text-sm text-muted-foreground">Loading preview...</div>
          ) : previewError ? (
            <div className="text-sm text-destructive">{previewError}</div>
          ) : previewPosts.length === 0 ? (
            <div className="text-sm text-muted-foreground">No published blogs yet.</div>
          ) : (
            <div className="grid gap-5 sm:grid-cols-2">
              {previewPosts.map((post) => (
                <a key={post.id} href={`/blog/${post.slug}`} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-md border border-border transition hover:-translate-y-0.5">
                  {post.hero_image && <img src={post.hero_image} alt="" className="h-36 w-full object-cover" />}
                  <div className="p-4">
                    <h3 className="font-display font-bold leading-snug">{post.title}</h3>
                    <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{post.excerpt}</p>
                  </div>
                </a>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
