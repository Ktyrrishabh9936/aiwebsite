import { useState } from "react";
import { Check, Code2, Copy, ExternalLink, Globe, KeyRound, Link2, Plus, RotateCw, Share2, ShieldAlert, ShieldCheck, Terminal, X } from "lucide-react";
import { toast } from "sonner";
import { API } from "../../lib/api";

export function apiBase() {
  const configured = (process.env.REACT_APP_PUBLIC_FORM_BASE_URL || "").replace(/\/+$/, "");
  if (configured) return configured;
  return API.startsWith("http") ? API : `${window.location.origin}${API}`;
}

function CopyButton({ value, label = "Copy" }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(value); setCopied(true); toast.success("Copied to clipboard"); setTimeout(() => setCopied(false), 1500); }
    catch { toast.error("Copy failed — select the text and copy it manually"); }
  };
  return <button type="button" onClick={copy} className="inline-flex h-9 items-center gap-1.5 rounded-lg border bg-background px-3 text-xs font-semibold hover:bg-accent">{copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}{copied ? "Copied" : label}</button>;
}

function CodeBlock({ code, label }) {
  return <div className="relative overflow-hidden rounded-xl border bg-zinc-950 text-zinc-100"><div className="flex items-center justify-between border-b border-white/10 px-4 py-2 text-[11px] uppercase tracking-wider text-zinc-400"><span>{label}</span><CopyButton value={code} /></div><pre className="max-h-72 overflow-auto p-4 font-mono text-xs leading-relaxed"><code>{code}</code></pre></div>;
}

function DomainInput({ domains, onChange }) {
  const [value, setValue] = useState("");
  const add = () => {
    const clean = value.trim().replace(/^https?:\/\//i, "").replace(/\/.*$/, "").toLowerCase();
    if (!clean) return;
    if (!/^[a-z0-9.-]+(:\d+)?$/.test(clean)) { toast.error("Enter a domain like example.com"); return; }
    if (!domains.includes(clean)) onChange([...domains, clean]);
    setValue("");
  };
  return <div><div className="flex flex-wrap gap-2">{domains.map((domain) => <span key={domain} className="inline-flex items-center gap-1.5 rounded-full border bg-background py-1 pl-3 pr-1.5 text-xs font-medium"><Globe className="h-3 w-3 text-muted-foreground" />{domain}<button type="button" aria-label={`Remove ${domain}`} onClick={() => onChange(domains.filter((item) => item !== domain))} className="rounded-full p-0.5 hover:bg-accent"><X className="h-3 w-3" /></button></span>)}{!domains.length && <span className="text-xs text-muted-foreground">Any website can frame or submit this form. Add domains to restrict it.</span>}</div><div className="mt-3 flex gap-2"><input value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); add(); } }} placeholder="example.com" aria-label="Add allowed domain" className="h-10 flex-1 rounded-lg border bg-background px-3 text-sm" /><button type="button" onClick={add} className="inline-flex h-10 items-center gap-1.5 rounded-lg border px-3 text-sm font-medium hover:bg-accent"><Plus className="h-4 w-4" />Add</button></div></div>;
}

export default function InstallPanel({ form, onOriginsChange, onRotate, dirty = false }) {
  const base = apiBase();
  const key = form.form_key;
  const shareUrl = `${base}/public/forms/${key}/view`;
  const submitUrl = `${base}/public/forms/${key}/submit`;
  const rawLambda = /\.lambda-url\.[^.]+\.on\.aws/i.test(base);
  const iframe = `<!-- Responsive Arevei form; UTMs are forwarded automatically -->\n<iframe data-arevei-frame\n  data-src="${shareUrl}"\n  src="${shareUrl}"\n  title="${form.name.replaceAll('"', '&quot;')}"\n  loading="lazy"\n  referrerpolicy="strict-origin-when-cross-origin"\n  style="width:100%;min-height:640px;border:0"></iframe>\n<script src="${base}/embed/form-frame.js" async></script>`;
  const embed = `<!-- Arevei landing page form: ${form.name} -->\n<div data-arevei-form="${key}"></div>\n<script src="${base}/embed/form.js" async></script>`;
  const connect = `<!-- Keep your existing design and send a copy to Arevei -->\n<form data-arevei>\n  <input name="name" required>\n  <input name="email" type="email">\n  <input name="country_code" value="+91" type="hidden">\n  <input name="phone" required>\n  <textarea name="message"></textarea>\n  <button type="submit">Send</button>\n</form>\n<script src="${base}/embed/form-connect.js"\n  data-form-key="${key}"\n  data-map='{"full_name":"name","requirement":"message"}'></script>`;
  const curl = `curl -X POST "${submitUrl}" \\\n+  -H "Content-Type: application/json" \\\n+  -d '{"full_name":"Priya Sharma","phone":"9876543210","country_code":"IN","utm_source":"facebook","utm_campaign":"launch"}'`;

  return <div className="space-y-5">
    {dirty && <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-200">Save your changes before sharing so visitors see the latest fields and design.</div>}
    {rawLambda && <div className="flex gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4"><ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" /><div><p className="text-sm font-semibold">A raw AWS Lambda URL is currently used</p><p className="mt-1 text-xs leading-5 text-muted-foreground">It works, and the URL is not a secret, but a branded API domain is safer to operate and easier to trust. Set <code className="rounded bg-background px-1">PUBLIC_BASE_URL</code> on the backend and <code className="rounded bg-background px-1">REACT_APP_PUBLIC_FORM_BASE_URL</code> on the frontend after putting API Gateway or CloudFront/WAF in front.</p></div></div>}
    <section className="rounded-2xl border bg-gradient-to-br from-primary/10 via-card to-card p-5"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="flex items-center gap-2 font-semibold"><Share2 className="h-4 w-4 text-primary" />Share this form as a page</p><p className="mt-1 text-sm text-muted-foreground">Send this link in email, WhatsApp, ads or social posts. UTM parameters in the shared link are captured automatically.</p></div><div className="flex gap-2"><CopyButton value={shareUrl} label="Copy link" /><a href={shareUrl} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-primary px-3 text-xs font-semibold text-primary-foreground"><ExternalLink className="h-3.5 w-3.5" />Open</a></div></div><div className="mt-4 break-all rounded-xl border bg-background p-3 font-mono text-xs">{shareUrl}</div></section>
    <section className="space-y-3 rounded-2xl border bg-card p-5"><div><h3 className="flex items-center gap-2 font-semibold"><Code2 className="h-4 w-4 text-primary" />Embed with an iframe</h3><p className="mt-1 text-sm text-muted-foreground">Paste once on WordPress, Webflow, Framer, Wix, Squarespace or custom HTML. The helper forwards campaign UTMs and automatically adjusts the frame height.</p></div><CodeBlock label="Responsive iframe" code={iframe} /></section>
    <details className="rounded-2xl border bg-card p-5"><summary className="flex cursor-pointer list-none items-center gap-2 font-semibold [&::-webkit-details-marker]:hidden"><Link2 className="h-4 w-4 text-primary" />Other integration options <span className="ml-auto text-xs font-normal text-muted-foreground">Advanced</span></summary><div className="mt-5 space-y-5"><div><p className="mb-2 text-sm font-semibold">JavaScript-rendered form</p><p className="mb-3 text-xs text-muted-foreground">Use this when you want the form rendered directly into the page instead of an iframe.</p><CodeBlock label="HTML" code={embed} /></div><div><p className="mb-2 text-sm font-semibold">Connect your existing form</p><p className="mb-3 text-xs text-muted-foreground">Keep your design and send a copy of each submission to Arevei.</p><CodeBlock label="HTML" code={connect} /></div><div><p className="mb-2 flex items-center gap-2 text-sm font-semibold"><Terminal className="h-4 w-4" />API / webhook</p><p className="mb-3 break-all rounded-lg border bg-background p-3 font-mono text-xs"><span className="mr-2 font-bold text-emerald-600">POST</span>{submitUrl}</p><CodeBlock label="cURL" code={curl} /></div></div></details>
    <details className="rounded-2xl border bg-card p-5"><summary className="flex cursor-pointer list-none items-center gap-2 font-semibold [&::-webkit-details-marker]:hidden"><ShieldCheck className="h-4 w-4 text-primary" />Security and access <span className="ml-auto text-xs font-normal text-muted-foreground">Domains & key</span></summary><div className="mt-5 space-y-5"><div><p className="text-sm font-semibold">Allowed websites</p><p className="mb-3 mt-1 text-xs text-muted-foreground">These domains may frame and submit the form. Server tools such as Zapier and Make can still post directly.</p><DomainInput domains={form.allowed_origins || []} onChange={onOriginsChange} /></div><div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4"><div><p className="flex items-center gap-2 text-sm font-semibold"><KeyRound className="h-4 w-4 text-primary" />Public form key</p><p className="mt-1 font-mono text-xs">{key}</p></div><button type="button" onClick={onRotate} className="inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-xs font-medium hover:bg-accent"><RotateCw className="h-3.5 w-3.5" />Rotate key</button></div></div></details>
  </div>;
}
