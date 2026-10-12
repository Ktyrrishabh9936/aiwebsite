import { useState } from "react";
import { Check, Code2, Copy, Globe, KeyRound, Link2, Plus, RotateCw, ShieldCheck, Terminal, X } from "lucide-react";
import { toast } from "sonner";
import { API } from "../../lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";

export function apiBase() {
  return API.startsWith("http") ? API : `${window.location.origin}${API}`;
}

function CodeBlock({ code, label }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(code); setCopied(true); toast.success("Copied to clipboard"); setTimeout(() => setCopied(false), 1500); }
    catch { toast.error("Copy failed — select the code and copy it manually"); }
  };
  return (
    <div className="relative overflow-hidden rounded-xl border bg-zinc-950 text-zinc-100">
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-2 text-[11px] uppercase tracking-wider text-zinc-400"><span>{label}</span>
        <button type="button" onClick={copy} className="inline-flex items-center gap-1.5 rounded-md bg-white/10 px-2.5 py-1 text-[11px] font-semibold normal-case tracking-normal text-white hover:bg-white/20">{copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}{copied ? "Copied" : "Copy"}</button>
      </div>
      <pre className="overflow-x-auto p-4 font-mono text-xs leading-relaxed"><code>{code}</code></pre>
    </div>
  );
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
  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {domains.map((d) => <span key={d} className="inline-flex items-center gap-1.5 rounded-full border bg-background py-1 pl-3 pr-1.5 text-xs font-medium"><Globe className="h-3 w-3 text-muted-foreground" />{d}<button type="button" aria-label={`Remove ${d}`} onClick={() => onChange(domains.filter((x) => x !== d))} className="rounded-full p-0.5 hover:bg-accent"><X className="h-3 w-3" /></button></span>)}
        {domains.length === 0 && <span className="text-xs text-muted-foreground">Any website can submit. Add your domains to lock it down.</span>}
      </div>
      <div className="mt-3 flex gap-2">
        <input value={value} onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} placeholder="villas.example.com" aria-label="Add allowed domain" className="h-10 flex-1 rounded-lg border bg-background px-3 text-sm" />
        <button type="button" onClick={add} className="inline-flex h-10 items-center gap-1.5 rounded-lg border px-3 text-sm font-medium hover:bg-accent"><Plus className="h-4 w-4" />Add</button>
      </div>
    </div>
  );
}

export default function InstallPanel({ form, onOriginsChange, onRotate }) {
  const base = apiBase();
  const key = form.form_key;
  const submitUrl = `${base}/public/forms/${key}/submit`;
  const embed = `<!-- Arevei landing page form: ${form.name} -->\n<div data-arevei-form="${key}"></div>\n<script src="${base}/embed/form.js" async></script>`;
  const connect = `<!-- 1. Add data-arevei to your existing form -->\n<form data-arevei>\n  <input name="name" required>\n  <input name="email" type="email">\n  <input name="country_code" value="+91" type="hidden">\n  <input name="phone" required>\n  <textarea name="message"></textarea>\n  <button type="submit">Send</button>\n</form>\n\n<!-- 2. Paste before </body>. UTM fields are added automatically. -->\n<script src="${base}/embed/form-connect.js"\n  data-form-key="${key}"\n  data-map='{"full_name":"name","requirement":"message"}'></script>`;
  const htmlOnly = `<form action="${submitUrl}" method="POST">\n  <input name="full_name" placeholder="Name" required>\n  <input name="email" type="email" placeholder="Email">\n  <select name="country_code"><option value="IN">+91</option><option value="AE">+971</option></select>\n  <input name="phone" placeholder="Phone" required>\n  <textarea name="requirement" placeholder="Your requirement"></textarea>\n  <input name="utm_source" type="hidden"><input name="utm_campaign" type="hidden">\n  <input name="_hp" style="display:none" tabindex="-1" autocomplete="off">\n  <button type="submit">Submit</button>\n</form>`;
  const curl = `curl -X POST "${submitUrl}" \\\n  -H "Content-Type: application/json" \\\n  -d '{\n    "full_name": "Priya Sharma",\n    "email": "priya@example.com",\n    "country_code": "+91",\n    "phone": "9876543210",\n    "requirement": "3BHK under 1.2 Cr",\n    "utm_source": "facebook",\n    "utm_medium": "paid_social",\n    "utm_campaign": "diwali_launch",\n    "page_url": "https://villas.example.com/launch"\n  }'`;

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border bg-card p-5">
        <h3 className="flex items-center gap-2 font-semibold"><ShieldCheck className="h-4 w-4 text-primary" />Allowed domains</h3>
        <p className="mb-4 mt-1 text-sm text-muted-foreground">Only these websites (and their subdomains) can submit from a browser. Server tools like Zapier still work.</p>
        <DomainInput domains={form.allowed_origins || []} onChange={onOriginsChange} />
      </section>

      <section className="rounded-2xl border bg-card p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="flex items-center gap-2 font-semibold"><KeyRound className="h-4 w-4 text-primary" />Form key</h3>
            <p className="mt-1 font-mono text-sm">{key}</p>
          </div>
          <button type="button" onClick={onRotate} className="inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-xs font-medium hover:bg-accent"><RotateCw className="h-3.5 w-3.5" />Rotate key</button>
        </div>
      </section>

      <Tabs defaultValue="embed">
        <TabsList className="grid h-auto w-full grid-cols-3">
          <TabsTrigger value="embed" className="gap-1.5 py-2"><Code2 className="h-4 w-4" /><span className="hidden sm:inline">Embed script</span><span className="sm:hidden">Embed</span></TabsTrigger>
          <TabsTrigger value="connect" className="gap-1.5 py-2"><Link2 className="h-4 w-4" /><span className="hidden sm:inline">Connect existing form</span><span className="sm:hidden">Connect</span></TabsTrigger>
          <TabsTrigger value="api" className="gap-1.5 py-2"><Terminal className="h-4 w-4" /><span className="hidden sm:inline">API / Webhook</span><span className="sm:hidden">API</span></TabsTrigger>
        </TabsList>
        <TabsContent value="embed" className="mt-4 space-y-3">
          <p className="text-sm text-muted-foreground">Paste where the form should appear. It renders your design with a country-code picker and captures UTM parameters automatically.</p>
          <CodeBlock label="HTML" code={embed} />
          <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
            {[["WordPress / Elementor", "Add an HTML widget and paste the code."], ["Webflow", "Add an Embed element and paste the code."], ["Framer", "Insert → Embed → HTML, then paste."], ["Wix / Squarespace", "Add a Custom Code / Embed block."]].map(([t, d]) => <div key={t} className="rounded-lg border bg-background p-3"><p className="font-semibold text-foreground">{t}</p><p className="mt-0.5">{d}</p></div>)}
          </div>
        </TabsContent>
        <TabsContent value="connect" className="mt-4 space-y-3">
          <p className="text-sm text-muted-foreground">Keep your own form design. The script sends a copy of each submission to Arevei, with UTM data. Map your input names with <code className="rounded bg-muted px-1">data-map</code> if they differ from name / email / phone / message.</p>
          <CodeBlock label="HTML" code={connect} />
          <details className="rounded-xl border bg-background p-4 text-sm">
            <summary className="cursor-pointer font-semibold">No JavaScript allowed? Post the form directly</summary>
            <p className="my-3 text-muted-foreground">A plain HTML form works too. Visitors see your thank-you message or are redirected to your page. Hidden UTM inputs are only filled if your page sets them, so prefer the script above for campaign tracking.</p>
            <CodeBlock label="HTML" code={htmlOnly} />
          </details>
        </TabsContent>
        <TabsContent value="api" className="mt-4 space-y-3">
          <p className="text-sm text-muted-foreground">Send leads from Zapier, Make, n8n or your backend. Accepts JSON or form-encoded data.</p>
          <div className="rounded-xl border bg-background p-3 text-sm"><span className="mr-2 rounded bg-emerald-500/15 px-1.5 py-0.5 font-mono text-xs font-bold text-emerald-600">POST</span><span className="break-all font-mono text-xs">{submitUrl}</span></div>
          <CodeBlock label="cURL" code={curl} />
          <div className="overflow-hidden rounded-xl border text-xs">
            <table className="w-full">
              <thead className="bg-muted/50 text-left"><tr><th className="p-2.5">Field</th><th className="p-2.5">Description</th></tr></thead>
              <tbody className="divide-y">
                {[["full_name", "Visitor name"], ["email", "Email address"], ["phone", "Phone number (local or with +code)"], ["country_code", "ISO (IN) or dial code (+91). Defaults to the form's country"], ["requirement", "Requirement or query"], ["utm_source … utm_content", "Campaign tracking (hidden)"], ["page_url, referrer", "Where the lead came from"], ["submission_id", "Optional idempotency key — retries won't duplicate"]].map(([k, d]) => <tr key={k}><td className="p-2.5 font-mono">{k}</td><td className="p-2.5 text-muted-foreground">{d}</td></tr>)}
              </tbody>
            </table>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
