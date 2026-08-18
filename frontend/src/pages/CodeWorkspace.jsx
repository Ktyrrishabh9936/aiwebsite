import { useEffect, useRef, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import api, { API } from "../lib/api";
import { useTheme } from "../context/ThemeContext";
import { AgentChat, CenterBlock, FilesPanel, TopBar } from "../components/code/CodeParts";

export default function CodeWorkspace() {
  const { pid } = useParams();
  const nav = useNavigate();
  const { theme } = useTheme();
  const [project, setProject] = useState(null);
  const [models, setModels] = useState([]);
  const [tree, setTree] = useState([]);
  const [activeFile, setActiveFile] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState("code");
  const [showFiles, setShowFiles] = useState(true);
  const [previewUrl, setPreviewUrl] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [termLines, setTermLines] = useState(["Welcome to the sandbox terminal. Type a command below."]);
  const [termInput, setTermInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const chatRef = useRef(null);

  const loadFiles = useCallback(async () => {
    try { const r = await api.get(`/code/projects/${pid}/files`); setTree(r.data.tree); return r.data.tree; }
    catch { return []; }
  }, [pid]);

  const firstFile = (nodes) => {
    for (const n of nodes || []) {
      if (n.type === "file") return n.path;
      const c = firstFile(n.children);
      if (c) return c;
    }
    return null;
  };

  const loadProject = useCallback(async () => {
    const r = await api.get(`/code/projects/${pid}`); setProject(r.data); return r.data;
  }, [pid]);

  const openFile = useCallback(async (path) => {
    try {
      const r = await api.get(`/code/projects/${pid}/file`, { params: { path } });
      setActiveFile({ path, content: r.data.content }); setDirty(false); setTab("code");
    } catch { toast.error("Could not open file"); }
  }, [pid]);

  useEffect(() => {
    (async () => {
      const p = await loadProject();
      api.get("/code/models").then((r) => setModels(r.data.models));
      api.get(`/code/projects/${pid}/messages`).then((r) => setMessages(r.data)).catch(() => {});
      let status = p.sandbox_status;
      while (status === "provisioning") {
        await new Promise((res) => setTimeout(res, 3500));
        const np = await loadProject(); status = np.sandbox_status;
      }
      if (status === "ready") { const t = await loadFiles(); const f = firstFile(t) || "src/App.jsx"; openFile(f); }
    })();
    // eslint-disable-next-line
  }, [pid]);

  useEffect(() => { chatRef.current?.scrollTo(0, chatRef.current.scrollHeight); }, [messages]);

  const saveFile = async () => {
    if (!activeFile) return;
    try { await api.put(`/code/projects/${pid}/file`, { path: activeFile.path, content: activeFile.content }); setDirty(false); toast.success("Saved"); }
    catch { toast.error("Save failed"); }
  };

  const runDev = async () => {
    setPreviewLoading(true); setTab("preview");
    try {
      await api.post(`/code/projects/${pid}/run`);
      toast.info("Starting dev server…");
      for (let i = 0; i < 25; i++) {
        await new Promise((r) => setTimeout(r, 4000));
        const s = await api.get(`/code/projects/${pid}/preview`);
        setPreviewUrl(s.data.url);
        if (s.data.ready) { setPreviewLoading(false); toast.success("Preview ready"); return; }
      }
      setPreviewLoading(false);
    } catch { setPreviewLoading(false); toast.error("Preview failed"); }
  };

  const runTerminal = async (e) => {
    e?.preventDefault();
    const cmd = termInput.trim(); if (!cmd) return;
    setTermLines((l) => [...l, `$ ${cmd}`]); setTermInput("");
    try {
      const r = await api.post(`/code/projects/${pid}/terminal`, { command: cmd });
      setTermLines((l) => [...l, r.data.output || "", `[exit ${r.data.exit_code}]`]);
    } catch { setTermLines((l) => [...l, "command failed"]); }
  };

  const send = async () => {
    const msg = input.trim(); if (!msg || streaming) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: msg }, { role: "assistant", content: "", steps: [], working: true }]);
    setStreaming(true);
    const updateLast = (fn) => setMessages((m) => { const c = [...m]; c[c.length - 1] = fn(c[c.length - 1]); return c; });
    try {
      const res = await fetch(`${API}/code/projects/${pid}/chat`, {
        method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("arevei_token")}` },
        body: JSON.stringify({ message: msg, model_id: project?.model_id }),
      });
      const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split("\n\n"); buf = parts.pop();
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data: ")); if (!line) continue;
          let ev; try { ev = JSON.parse(line.slice(6)); } catch { continue; }
          if (ev.type === "text_delta") updateLast((a) => ({ ...a, content: (a.content || "") + ev.text, working: true }));
          else if (ev.type === "summary") updateLast((a) => ({ ...a, content: ev.text }));
          else if (ev.type === "done") updateLast((a) => ({ ...a, steps: ev.steps, working: false }));
          else if (ev.type === "end") { /* persisted */ }
          else if (ev.type === "error") updateLast((a) => ({ ...a, content: `⚠️ ${ev.message}`, working: false }));
          else {
            updateLast((a) => ({ ...a, steps: [...(a.steps || []), ev] }));
            if (ev.type === "file") { loadFiles(); if (activeFile?.path === ev.path) openFile(ev.path); }
            if (ev.type === "terminal") setTermLines((l) => [...l, `$ ${ev.command}`, ev.output || ""]);
          }
        }
      }
    } catch { updateLast((a) => ({ ...a, content: "⚠️ Agent connection failed", working: false })); }
    finally { setStreaming(false); loadFiles(); if (activeFile) openFile(activeFile.path); }
  };

  const changeModel = async (id) => { const r = await api.patch(`/code/projects/${pid}`, { model_id: id }); setProject(r.data); };
  const sync = () => { loadFiles(); loadProject(); toast.success("Sandbox synced"); };

  if (!project) return <div className="min-h-screen grid place-items-center"><Loader2 className="w-6 h-6 animate-spin text-primary" /></div>;
  if (project.sandbox_status === "provisioning")
    return <div className="min-h-screen grid place-items-center text-center"><div><Loader2 className="w-8 h-8 animate-spin text-primary mx-auto mb-4" /><div className="font-display text-xl font-bold">Provisioning cloud sandbox…</div><p className="text-muted-foreground mt-1">Setting up your Daytona workspace.</p></div></div>;

  const currentModel = models.find((m) => m.id === project.model_id);
  const turns = messages.filter((m) => m.role === "user").length;

  return (
    <div className="h-screen flex flex-col bg-background">
      <TopBar project={project} onBack={() => nav("/app/code")} onSync={sync} onRun={runDev} />
      <div className="flex-1 flex min-h-0">
        <AgentChat chatRef={chatRef} messages={messages} input={input} setInput={setInput} streaming={streaming}
          onSend={send} models={models} currentModel={currentModel} onModel={changeModel} turns={turns} />
        <CenterBlock tab={tab} setTab={setTab} showFiles={showFiles} setShowFiles={setShowFiles}
          activeFile={activeFile} dirty={dirty} onSave={saveFile} theme={theme}
          onEditorChange={(v) => { setActiveFile((f) => ({ ...f, content: v ?? "" })); setDirty(true); }}
          previewLoading={previewLoading} previewUrl={previewUrl}
          termLines={termLines} termInput={termInput} setTermInput={setTermInput} onRunTerminal={runTerminal} />
        {showFiles && <FilesPanel tree={tree} activePath={activeFile?.path} onOpen={openFile} onRefresh={loadFiles} />}
      </div>
    </div>
  );
}
