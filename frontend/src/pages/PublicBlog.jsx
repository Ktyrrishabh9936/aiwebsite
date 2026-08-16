import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, Loader2, Clock } from "lucide-react";
import api from "../lib/api";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";
import { BlockRenderer } from "../components/BlockRenderer";

export default function PublicBlog() {
  const { slug } = useParams();
  const [blog, setBlog] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    api.get(`/public/blog/${slug}`).then((r) => setBlog(r.data)).catch(() => setError(true));
  }, [slug]);

  if (error) return (
    <div className="min-h-screen grid place-items-center text-center px-6">
      <div>
        <h1 className="font-display text-3xl font-black mb-2">Article not found</h1>
        <p className="text-muted-foreground">This blog may be unpublished or removed.</p>
        <Link to="/" className="inline-block mt-6 text-primary font-medium">← Back to Arevei</Link>
      </div>
    </div>
  );

  if (!blog) return <div className="min-h-screen grid place-items-center"><Loader2 className="w-6 h-6 animate-spin text-primary" /></div>;

  const date = blog.published_at ? new Date(blog.published_at).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" }) : "";

  return (
    <div className="min-h-screen grain">
      <header className="sticky top-0 z-30 glass border-b border-border">
        <div className="max-w-3xl mx-auto px-6 h-16 flex items-center justify-between">
          <Logo className="text-base" />
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground hidden sm:block">{blog.workspace_name}</span>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <article className="max-w-3xl mx-auto px-6 py-12">
        <div className="flex flex-wrap gap-1.5 mb-5">
          {(blog.tags || []).map((t, i) => (
            <span key={i} className="text-[11px] uppercase tracking-wider font-bold px-2.5 py-1 rounded-full bg-primary/10 text-primary">{t}</span>
          ))}
        </div>
        <motion.h1 initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="font-display text-4xl sm:text-5xl font-black tracking-tight leading-[1.05]">
          {blog.title}
        </motion.h1>
        <p className="mt-5 text-lg sm:text-xl text-muted-foreground leading-relaxed">{blog.excerpt}</p>
        <div className="mt-6 flex items-center gap-4 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">{blog.author}</span>
          {date && <span>{date}</span>}
          <span className="inline-flex items-center gap-1"><Clock className="w-3.5 h-3.5" /> {blog.read_time}</span>
        </div>

        {blog.hero_image && (
          <motion.img
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.5 }}
            src={blog.hero_image}
            alt=""
            className="w-full h-64 sm:h-96 object-cover rounded-md mt-10"
          />
        )}

        <div className="mt-10">
          <BlockRenderer blocks={blog.blocks} />
        </div>

        <div className="mt-16 pt-8 border-t border-border flex items-center justify-between">
          <Link to="/" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
            <ArrowLeft className="w-4 h-4" /> Powered by Arevei
          </Link>
          {blog.workspace_url && <a href={blog.workspace_url} className="text-sm text-primary font-medium">Visit site →</a>}
        </div>
      </article>
    </div>
  );
}
