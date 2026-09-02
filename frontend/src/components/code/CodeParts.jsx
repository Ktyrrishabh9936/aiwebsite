import { useState } from "react";
import {
  Folder, FolderOpen, File as FileIcon, RefreshCw, TerminalSquare, Search,
  FileEdit, Loader2, CheckCircle2, ChevronDown, Send, Sparkles, History,
  Code2, Monitor, Save, PanelRight, Play, ArrowLeft, Square, Wrench, PlugZap,
  X, Image as ImageIcon, ExternalLink, RotateCcw,
} from "lucide-react";
import Editor from "@monaco-editor/react";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import { Logo } from "../Logo";

export const langOf = (path = "") => {
  const e = path.split(".").pop();
  return { js: "javascript", jsx: "javascript", ts: "typescript", tsx: "typescript", json: "json", css: "css", html: "html", md: "markdown" }[e] || "plaintext";
};

function FileNode({ node, depth, activePath, onOpen }) {
  const [open, setOpen] = useState(depth < 1);
  const pad = { paddingLeft: 8 + depth * 12 };
  const isDir = node.type === "dir";
  const active = activePath === node.path;
  const cls = active
    ? "flex items-center gap-1.5 w-full px-2 py-1 rounded text-sm bg-primary/15 text-primary"
    : "flex items-center gap-1.5 w-full px-2 py-1 rounded text-sm hover:bg-accent";
  return (
    <div>
      <button
        data-testid={isDir ? undefined : `file-${node.path}`}
        onClick={() => (isDir ? setOpen((o) => !o) : onOpen(node.path))}
        className={cls}
        style={pad}
      >
        {isDir
          ? (open ? <FolderOpen className="w-3.5 h-3.5 text-primary" /> : <Folder className="w-3.5 h-3.5 text-primary" />)
          : <FileIcon className="w-3.5 h-3.5 opacity-60" />}
        <span className="truncate">{node.name}</span>
      </button>
      {isDir && open && (node.children || []).map((c) => (
        <FileNodeChild key={c.path} node={c} depth={depth + 1} activePath={activePath} onOpen={onOpen} />
      ))}
    </div>
  );
}

const FileNodeChild = FileNode;

export function FilesPanel({ tree, activePath, onOpen, onRefresh }) {
  return (
    <aside className="w-64 shrink-0 border-l border-border flex flex-col min-h-0" data-testid="files-panel">
      <div className="h-11 px-4 flex items-center justify-between border-b border-border">
        <span className="text-xs uppercase tracking-wider font-bold text-muted-foreground">Files</span>
        <button onClick={onRefresh} className="grid place-items-center w-7 h-7 rounded hover:bg-accent"><RefreshCw className="w-3.5 h-3.5" /></button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {tree.map((n) => <FileNodeChild key={n.path} node={n} depth={0} activePath={activePath} onOpen={onOpen} />)}
      </div>
    </aside>
  );
}

function stepLabel(s) {
  if (s.type === "file" || s.type === "file_changed") return { icon: FileEdit, text: s.label || `Edited ${s.path}` };
  if (s.type === "terminal" || s.type === "terminal_result") return { icon: TerminalSquare, text: s.label || `Ran ${s.command}` };
  if (s.type === "activity_finished") return { icon: s.kind === "read" ? Search : CheckCircle2, text: s.label || "Completed" };
  if (s.type === "tool" && s.name === "read_file") return { icon: Search, text: `Read ${s.args?.path || ""}` };
  if (s.type === "tool" && s.name === "list_files") return { icon: Search, text: "Scanned project" };
  if (s.type === "tool" && s.name === "write_file") return null;
  if (s.type === "tool" && s.name === "run_command") return { icon: TerminalSquare, text: `Run ${s.args?.command || ""}` };
  return null;
}

function inlineMd(text) {
  const parts = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  for (const match of text.matchAll(re)) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("`")) parts.push(<code key={parts.length} className="px-1 py-0.5 rounded bg-secondary font-mono text-[0.9em]">{token.slice(1, -1)}</code>);
    else if (token.startsWith("**")) parts.push(<strong key={parts.length}>{token.slice(2, -2)}</strong>);
    else {
      const [, label, href] = token.match(/\[([^\]]+)\]\(([^)]+)\)/) || [];
      parts.push(<a key={parts.length} href={href} target="_blank" rel="noreferrer" className="text-primary underline underline-offset-2">{label || token}</a>);
    }
    last = match.index + token.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function MarkdownBlock({ text = "", muted = false }) {
  const lines = text.split("\n");
  const blocks = [];
  let list = [];
  let code = [];
  let inCode = false;
  const flushList = () => {
    if (!list.length) return;
    blocks.push(<ul key={`ul-${blocks.length}`} className="my-2 list-disc pl-5 space-y-1">{list.map((x, i) => <li key={i}>{inlineMd(x)}</li>)}</ul>);
    list = [];
  };
  const flushCode = () => {
    if (!code.length) return;
    blocks.push(<pre key={`code-${blocks.length}`} className="my-2 overflow-x-auto rounded-md border border-border bg-secondary p-3 text-xs"><code>{code.join("\n")}</code></pre>);
    code = [];
  };

  lines.forEach((raw) => {
    const line = raw.trimEnd();
    if (line.startsWith("```")) {
      if (inCode) { flushCode(); inCode = false; } else { flushList(); inCode = true; }
      return;
    }
    if (inCode) { code.push(raw); return; }
    if (!line.trim()) { flushList(); return; }
    if (line.startsWith("### ")) { flushList(); blocks.push(<h4 key={blocks.length} className="mt-3 mb-1 font-bold">{inlineMd(line.slice(4))}</h4>); return; }
    if (line.startsWith("## ")) { flushList(); blocks.push(<h3 key={blocks.length} className="mt-3 mb-1 font-display text-base font-bold">{inlineMd(line.slice(3))}</h3>); return; }
    if (line.startsWith("# ")) { flushList(); blocks.push(<h2 key={blocks.length} className="mt-3 mb-1 font-display text-lg font-bold">{inlineMd(line.slice(2))}</h2>); return; }
    if (/^[-*]\s+/.test(line)) { list.push(line.replace(/^[-*]\s+/, "")); return; }
    flushList();
    blocks.push(<p key={blocks.length} className="my-1.5">{inlineMd(line)}</p>);
  });
  flushList();
  flushCode();
  return <div className={`text-sm leading-relaxed ${muted ? "text-muted-foreground" : ""}`}>{blocks}</div>;
}

function StepRow({ step, label }) {
  const Icon = label.icon;
  const [open, setOpen] = useState(false);
  const output = step.output || step.message;
  return (
    <div className="rounded-md border border-border bg-background/70">
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-xs text-muted-foreground">
        <Icon className="w-3.5 h-3.5 shrink-0 text-primary" />
        <span className="truncate font-mono">{label.text}</span>
        {(step.added != null || step.removed != null) && <span className="ml-auto font-mono text-[11px] text-muted-foreground">+{step.added || 0} -{step.removed || 0}</span>}
        {step.exit_code != null && <span className={step.exit_code === 0 ? "ml-auto text-primary" : "ml-auto text-destructive"}>exit {step.exit_code}</span>}
      </button>
      {open && output && <pre className="max-h-52 overflow-auto border-t border-border p-2 text-[11px] font-mono whitespace-pre-wrap">{output}</pre>}
    </div>
  );
}

function dedupeSteps(steps = []) {
  let seenExplore = false;
  const seenReads = new Set();
  const seenTerminals = new Set();
  return steps.filter((step) => {
    if (step.type === "activity_finished" && step.kind === "explore") {
      if (seenExplore) return false;
      seenExplore = true;
      return true;
    }
    if (step.type === "activity_finished" && step.kind === "read") {
      const key = step.path || step.label;
      if (seenReads.has(key)) return false;
      seenReads.add(key);
      return true;
    }
    if (step.type === "terminal_result") {
      const key = `${step.command || ""}:${step.exit_code ?? ""}`;
      if (seenTerminals.has(key)) return false;
      seenTerminals.add(key);
      return true;
    }
    return true;
  });
}

function ChangedFilesCard({ files = [] }) {
  if (!files.length) return null;
  return (
    <div className="mt-3 overflow-hidden rounded-lg border border-border bg-muted/30">
      <div className="flex items-center gap-2 px-3 py-2 text-xs">
        <span className="font-semibold">{files.length} file{files.length === 1 ? "" : "s"} changed</span>
        <button disabled className="ml-auto inline-flex items-center gap-1 text-muted-foreground opacity-60" title="Undo will be available with project snapshots">
          Undo <RotateCcw className="w-3 h-3" />
        </button>
        <button disabled className="inline-flex items-center gap-1 text-muted-foreground opacity-60" title="Diff view coming soon">
          View changes <ExternalLink className="w-3 h-3" />
        </button>
      </div>
      <div className="space-y-1 p-2 pt-0">
        {files.map((file) => (
          <div key={file.path} className="flex items-center gap-2 rounded-md bg-background px-2.5 py-2 text-xs">
            <FileEdit className="w-3.5 h-3.5 text-primary" />
            <span className="min-w-0 flex-1 truncate font-mono">{file.path}</span>
            <span className="font-mono text-primary">+{file.added || 0}</span>
            <span className="font-mono text-destructive">-{file.removed || 0}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AgentMessage({ m }) {
  if (m.role === "user") {
    return (
      <div className="ml-8 rounded-2xl px-3.5 py-2.5 bg-primary text-primary-foreground text-sm">
        <div>{m.content}</div>
        {m.attachments?.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {m.attachments.map((a, i) => (
              a.data_url ? (
                <img key={`${a.name}-${i}`} src={a.data_url} alt={a.name} className="h-14 w-14 rounded-md object-cover ring-1 ring-primary-foreground/25" />
              ) : (
                <div key={`${a.name}-${i}`} className="flex items-center gap-1.5 rounded-md bg-primary-foreground/15 px-2 py-1 text-xs">
                  <ImageIcon className="w-3 h-3" /> <span className="max-w-[120px] truncate">{a.name}</span>
                </div>
              )
            ))}
          </div>
        )}
      </div>
    );
  }
  const steps = dedupeSteps(m.steps || []).map((s, i) => ({ s, l: stepLabel(s), i })).filter((x) => x.l);
  const lastStep = steps[steps.length - 1];
  return (
    <div className="rounded-md border border-border bg-card px-3.5 py-3">
      {steps.length > 0 && <div className="space-y-1.5">{steps.map(({ s, l, i }) => <StepRow key={i} step={s} label={l} />)}</div>}
      {m.working ? (
        <div className="mt-2">
          <div className="flex items-center gap-2 text-xs text-primary mb-1.5">
            <span className="relative flex h-2 w-2"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-60" /><span className="relative inline-flex rounded-full h-2 w-2 bg-primary" /></span>
            <span className="font-medium">{lastStep ? lastStep.l.text : "Thinking..."}</span>
          </div>
          {m.content && <div><MarkdownBlock text={m.content} muted /><span className="inline-block w-1.5 h-4 bg-primary/70 ml-0.5 align-middle animate-pulse" /></div>}
        </div>
      ) : (
        <div className="mt-2">
          <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-bold text-primary mb-1"><CheckCircle2 className="w-3 h-3" /> Summary</div>
          <MarkdownBlock text={m.content} />
          <ChangedFilesCard files={m.changed_files || []} />
        </div>
      )}
    </div>
  );
}

function attachmentWarning(attachments, currentModel) {
  if (!attachments?.length) return "";
  if (!currentModel?.vision) return "Select a vision-capable model to send image references.";
  return "";
}

export function AgentChat({ chatRef, messages, input, setInput, streaming, onSend, onStop, models, providers, currentModel, onModel, turns, attachments = [], setAttachments }) {
  const suggestions = ["Build a landing page hero", "Add a contact form", "Make it dark mode", "Add a pricing section"];
  const groups = [...new Set(models.map((m) => m.tier || "other"))];
  const warning = attachmentWarning(attachments, currentModel);

  /* const addImages = async (files) => {
    const selected = Array.from(files || []);
    const allowed = new Set(["image/png", "image/jpeg", "image/webp"]);
    const next = [];
    for (const file of selected) {
      if (!allowed.has(file.type) || file.size > 4 * 1024 * 1024) continue;
      const dataUrl = await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.readAsDataURL(file);
      });
      next.push({
        name: file.name,
        mime_type: file.type,
        size: file.size,
        data_url: dataUrl,
        data_base64: String(dataUrl).split(",")[1] || "",
      });
    }
    setAttachments((prev) => [...prev, ...next].slice(0, 3));
  }; */
  return (
    <div className="w-[380px] shrink-0 border-r border-border flex flex-col min-h-0">
      <div className="h-11 px-4 flex items-center justify-between border-b border-border">
        <div className="flex items-center gap-2"><Sparkles className="w-4 h-4 text-primary" /><span className="font-display font-bold text-sm">Coding Agent</span></div>
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground"><History className="w-3.5 h-3.5" /> {turns} turns</span>
      </div>
      <div ref={chatRef} className="flex-1 overflow-y-auto p-4 space-y-4" data-testid="agent-messages">
        {messages.length === 0 && (
          <div className="space-y-3">
            <div className="text-sm text-muted-foreground">Ask the agent to build or change anything. It edits files, runs commands, uses skills, and reports code plus terminal results.</div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-md border border-border p-2"><Wrench className="w-3.5 h-3.5 text-primary mb-1" /> Skills ready</div>
              <div className="rounded-md border border-border p-2"><PlugZap className="w-3.5 h-3.5 text-primary mb-1" /> {providers?.openai?.configured || providers?.openrouter?.configured || providers?.nvidia?.configured ? "Models connected" : "Add model keys"}</div>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {suggestions.map((s) => (
                <button key={s} onClick={() => onSend(s)} data-testid={`suggest-${s.slice(0, 6)}`} className="text-xs px-2.5 py-1.5 rounded-full border border-border hover:bg-accent hover:border-primary/40 transition-colors">{s}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => <AgentMessage key={i} m={m} />)}
      </div>
      <div className="p-3 border-t border-border space-y-2">
        <div className="rounded-xl border border-border bg-background focus-within:ring-2 focus-within:ring-ring/60 transition-shadow">
          <textarea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); } }} placeholder="Ask the agent to build...  (Enter to send)" data-testid="agent-input" rows={2} className="w-full px-3 py-2.5 bg-transparent text-sm resize-none focus:outline-none" />
          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 px-2 pb-2">
              {attachments.map((a, i) => (
                <div key={`${a.name}-${i}`} className="group relative h-14 w-14 overflow-hidden rounded-md border border-border bg-secondary">
                  <img src={a.data_url} alt={a.name} className="h-full w-full object-cover" />
                  <button type="button" onClick={() => setAttachments((prev) => prev.filter((_, idx) => idx !== i))} className="absolute right-1 top-1 grid h-5 w-5 place-items-center rounded-full bg-background/90 opacity-0 shadow group-hover:opacity-100" title="Remove image">
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
          {warning && <div className="px-3 pb-2 text-xs text-amber-500">{warning}</div>}
          <div className="flex items-center justify-end px-2 pb-2">
            {/* <label className="grid place-items-center w-8 h-8 rounded-full border border-border hover:bg-accent cursor-pointer" title="Attach reference images">
              <Plus className="w-4 h-4" />
              <input type="file" accept="image/png,image/jpeg,image/webp" multiple className="hidden" onChange={(e) => { addImages(e.target.files); e.target.value = ""; }} />
            </label> */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button data-testid="agent-model-picker" className="inline-flex items-center gap-1.5 px-2.5 h-7 rounded-full border border-border text-xs font-medium hover:bg-accent">
                  <span className="w-1.5 h-1.5 rounded-full bg-primary" />{currentModel?.label || "model"}<ChevronDown className="w-3 h-3 opacity-60" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-72">
                {groups.map((tier) => {
                  const group = models.filter((m) => m.tier === tier);
                  if (group.length === 0) return null;
                  return (
                    <div key={tier}>
                      <div className="px-2 py-1 text-[10px] uppercase tracking-wider font-bold text-muted-foreground">{tier}</div>
                      {group.map((m) => (
                        <DropdownMenuItem key={m.id} disabled={!m.configured} onClick={() => onModel(m.id)} title={m.reason || ""} className="flex items-center justify-between gap-3 cursor-pointer">
                          <span>{m.label}</span>
                          <span className={m.configured ? "text-[10px] px-1.5 rounded-full bg-emerald-500/15 text-emerald-500" : "text-[10px] px-1.5 rounded-full bg-amber-500/15 text-amber-500"}>{m.configured ? (m.vision ? "vision" : m.tier) : "setup needed"}</span>
                        </DropdownMenuItem>
                      ))}
                    </div>
                  );
                })}
              </DropdownMenuContent>
            </DropdownMenu>
            {streaming ? (
              <button onClick={onStop} data-testid="agent-stop" className="inline-flex items-center gap-1.5 px-3 h-8 rounded-full bg-destructive text-destructive-foreground text-xs font-semibold">
                <Square className="w-3 h-3 fill-current" /> Stop
              </button>
            ) : (
              <button onClick={() => onSend()} data-testid="agent-send" className="grid place-items-center w-8 h-8 rounded-full bg-primary text-primary-foreground">
                <Send className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export function TopBar({ project, onBack, onSync, onRun }) {
  return (
    <header className="h-14 border-b border-border flex items-center px-4 gap-4 shrink-0">
      <button onClick={onBack} data-testid="code-back" className="grid place-items-center w-9 h-9 rounded-full hover:bg-accent"><ArrowLeft className="w-4 h-4" /></button>
      <Logo className="text-sm" to={null} />
      <div className="h-5 w-px bg-border" />
      <div className="flex items-center gap-2 min-w-0">
        <span className="font-display font-bold truncate">{project.name}</span>
        <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded-full bg-secondary text-muted-foreground">{project.template}</span>
      </div>
      <div className="ml-auto flex items-center gap-2">
        <button onClick={onSync} data-testid="sync-btn" className="grid place-items-center w-9 h-9 rounded-full border border-border hover:bg-accent" title="Sync / wake sandbox"><RefreshCw className="w-4 h-4" /></button>
        <button onClick={onRun} data-testid="run-btn" className="inline-flex items-center gap-2 px-4 h-9 rounded-full bg-primary text-primary-foreground text-sm font-semibold hover:-translate-y-0.5 transition-transform"><Play className="w-4 h-4" /> Run</button>
      </div>
    </header>
  );
}

const TABS = [{ id: "code", label: "Code", icon: Code2 }, { id: "preview", label: "Preview", icon: Monitor }, { id: "terminal", label: "Terminal", icon: TerminalSquare }];

function CodeTab({ activeFile, theme, onChange }) {
  if (!activeFile) return <div className="h-full grid place-items-center text-muted-foreground text-sm">Select a file from the tree.</div>;
  return (
    <Editor height="100%" theme={theme === "dark" ? "vs-dark" : "light"} path={activeFile.path} language={langOf(activeFile.path)} value={activeFile.content} onChange={onChange}
      options={{ fontSize: 13, minimap: { enabled: false }, fontFamily: "JetBrains Mono, monospace", scrollBeyondLastLine: false, automaticLayout: true }} />
  );
}

function PreviewTab({ previewLoading, previewUrl }) {
  return (
    <div className="h-full bg-white relative">
      {previewLoading && <div className="absolute inset-0 grid place-items-center bg-background/80 z-10"><div className="text-center"><Loader2 className="w-6 h-6 animate-spin text-primary mx-auto mb-2" /><span className="text-sm text-muted-foreground">Booting dev server...</span></div></div>}
      {previewUrl
        ? <iframe title="preview" src={previewUrl} className="w-full h-full border-0" data-testid="preview-iframe" />
        : <div className="h-full grid place-items-center text-muted-foreground text-sm">Press Run to start the live preview.</div>}
    </div>
  );
}

function TerminalTab({ termLines, termInput, setTermInput, onRun }) {
  return (
    <div className="h-full flex flex-col bg-[#0a0a0a] text-green-400">
      <div className="flex-1 overflow-y-auto p-3 font-mono text-xs whitespace-pre-wrap" data-testid="terminal-output">{termLines.join("\n")}</div>
      <form onSubmit={onRun} className="flex items-center gap-2 border-t border-white/10 px-3 h-10">
        <span className="text-green-500 font-mono">$</span>
        <input value={termInput} onChange={(e) => setTermInput(e.target.value)} data-testid="terminal-input" className="flex-1 bg-transparent text-green-400 font-mono text-xs focus:outline-none" placeholder="npm install lodash" />
      </form>
    </div>
  );
}

export function CenterBlock(props) {
  const { tab, setTab, showFiles, setShowFiles, activeFile, dirty, onSave } = props;
  return (
    <div className="flex-1 flex flex-col min-w-0">
      <div className="h-11 border-b border-border flex items-center px-2 gap-1">
        {TABS.map((t) => {
          const on = tab === t.id;
          return (
            <button key={t.id} onClick={() => setTab(t.id)} data-testid={`tab-${t.id}`} className={on ? "inline-flex items-center gap-1.5 px-3 h-8 rounded-md text-sm font-medium bg-primary text-primary-foreground" : "inline-flex items-center gap-1.5 px-3 h-8 rounded-md text-sm font-medium text-muted-foreground hover:bg-accent"}>
              <t.icon className="w-3.5 h-3.5" /> {t.label}
            </button>
          );
        })}
        <div className="ml-auto flex items-center gap-2">
          {tab === "code" && activeFile && (
            <>
              <span className="text-xs font-mono text-muted-foreground truncate max-w-[240px]">{activeFile.path}{dirty ? " *" : ""}</span>
              <button onClick={onSave} data-testid="save-file-btn" className="inline-flex items-center gap-1 px-2.5 h-8 rounded-md border border-border hover:bg-accent text-xs"><Save className="w-3.5 h-3.5" /> Save</button>
            </>
          )}
          <button onClick={() => setShowFiles(!showFiles)} data-testid="toggle-files-btn" className={showFiles ? "grid place-items-center w-8 h-8 rounded-md border border-border hover:bg-accent text-primary" : "grid place-items-center w-8 h-8 rounded-md border border-border hover:bg-accent"} title="Toggle files"><PanelRight className="w-4 h-4" /></button>
        </div>
      </div>
      <div className="flex-1 min-h-0">
        {tab === "code" && <CodeTab activeFile={activeFile} theme={props.theme} onChange={props.onEditorChange} />}
        {tab === "preview" && <PreviewTab previewLoading={props.previewLoading} previewUrl={props.previewUrl} />}
        {tab === "terminal" && <TerminalTab termLines={props.termLines} termInput={props.termInput} setTermInput={props.setTermInput} onRun={props.onRunTerminal} />}
      </div>
    </div>
  );
}
