import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { 
  ArrowLeft, Check, RefreshCw, FileSpreadsheet, KeyRound, 
  MapPin, HelpCircle, Power, Ban, Trash2, ArrowRightLeft, Database
} from "lucide-react";
import { toast } from "sonner";
import api, { API, formatError } from "../../lib/api";

export default function AdsToCrmWorkflow() {
  const { wsId } = useParams();
  
  // Connection states
  const [loading, setLoading] = useState(true);
  const [connStatus, setConnStatus] = useState({ connected: false });
  const [spreadsheets, setSpreadsheets] = useState([]);
  const [fetchingSheets, setFetchingSheets] = useState(false);
  const [binding, setBinding] = useState(false);
  const [savingMap, setSavingMap] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [workflow, setWorkflow] = useState({ status: "draft" });

  // Input states for binding
  const [selectedSpreadsheetId, setSelectedSpreadsheetId] = useState("");
  const [sheetTabName, setSheetTabName] = useState("Sheet1");

  // Column map state
  const [columnMap, setColumnMap] = useState({
    email: "",
    full_name: "",
    phone: "",
    meta_lead_id: ""
  });

  const loadWorkflow = useCallback(() => {
    api.get(`/workspaces/${wsId}/workflows`)
      .then((r) => {
        const ads = r.data.find((w) => w.kind === "ads_to_crm");
        if (ads) setWorkflow(ads);
      })
      .catch(() => {});
  }, [wsId]);

  const loadStatus = useCallback(async () => {
    try {
      setLoading(true);
      const r = await api.get(`/google/workspaces/${wsId}`);
      setConnStatus(r.data);
      if (r.data.connected) {
        if (r.data.column_map) {
          setColumnMap({
            email: r.data.column_map.email || "",
            full_name: r.data.column_map.full_name || "",
            phone: r.data.column_map.phone || "",
            meta_lead_id: r.data.column_map.meta_lead_id || ""
          });
        }
        if (r.data.spreadsheet_id) {
          setSelectedSpreadsheetId(r.data.spreadsheet_id);
        }
        if (r.data.sheet_name) {
          setSheetTabName(r.data.sheet_name);
        }
        // Fetch spreadsheets list
        setFetchingSheets(true);
        const sheetsRes = await api.get(`/google/workspaces/${wsId}/spreadsheets`);
        setSpreadsheets(sheetsRes.data);
      }
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setFetchingSheets(false);
      setLoading(false);
    }
  }, [wsId]);

  useEffect(() => {
    loadStatus();
    loadWorkflow();
  }, [loadStatus, loadWorkflow]);

  const handleGoogleConnect = () => {
    const width = 550;
    const height = 650;
    const left = window.screen.width / 2 - width / 2;
    const top = window.screen.height / 2 - height / 2;
    const popup = window.open(
      `${API}/google/connect?workspace_id=${wsId}`,
      "Google Connect",
      `width=${width},height=${height},left=${left},top=${top}`
    );

    const listener = (event) => {
      if (event.data?.type === "GOOGLE_CONNECTED") {
        toast.success("Google Account connected!");
        loadStatus();
        window.removeEventListener("message", listener);
      }
    };
    window.addEventListener("message", listener);
  };

  const handleDisconnect = async () => {
    if (!confirm("Are you sure you want to disconnect Google Sheets? This will unpublish the workflow.")) return;
    try {
      await api.delete(`/google/workspaces/${wsId}`);
      toast.success("Disconnected from Google");
      setConnStatus({ connected: false });
      setSpreadsheets([]);
      setSelectedSpreadsheetId("");
      setSheetTabName("Sheet1");
      setWorkflow({ status: "draft" });
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    }
  };

  const handleBindSheet = async () => {
    if (!selectedSpreadsheetId) {
      toast.error("Please select a spreadsheet");
      return;
    }
    const sheetObj = spreadsheets.find(s => s.id === selectedSpreadsheetId);
    try {
      setBinding(true);
      const r = await api.post(`/google/workspaces/${wsId}/bind`, {
        spreadsheet_id: selectedSpreadsheetId,
        spreadsheet_name: sheetObj?.name || "Spreadsheet",
        sheet_name: sheetTabName
      });
      toast.success("Spreadsheet bound successfully! Mapping columns is ready.");
      setConnStatus(prev => ({
        ...prev,
        spreadsheet_id: selectedSpreadsheetId,
        spreadsheet_name: sheetObj?.name,
        sheet_name: sheetTabName,
        header_row: r.data.headers
      }));
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setBinding(false);
    }
  };

  const handleSaveMapping = async () => {
    try {
      setSavingMap(true);
      await api.patch(`/google/workspaces/${wsId}/column_map`, { column_map: columnMap });
      toast.success("Column mappings saved successfully!");
      setConnStatus(prev => ({ ...prev, column_map: columnMap }));
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setSavingMap(false);
    }
  };

  const handleTogglePublish = async () => {
    try {
      setPublishing(true);
      if (workflow.status === "published") {
        const r = await api.post(`/workspaces/${wsId}/workflows/ads-to-crm/unpublish`);
        setWorkflow(r.data);
        toast.info("Workflow paused (unpublished).");
      } else {
        const r = await api.post(`/workspaces/${wsId}/workflows/ads-to-crm/publish`);
        setWorkflow(r.data);
        toast.success("Workflow active! Google Sheet is now being polled for CRM leads.");
      }
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setPublishing(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-[50vh] grid place-items-center">
        <div className="flex flex-col items-center gap-3">
          <RefreshCw className="w-8 h-8 animate-spin text-primary" />
          <span className="text-sm text-muted-foreground">Loading workspace credentials...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <Link to={`/app/w/${wsId}/workflows`} className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="w-4 h-4" /> Back to Workspaces
      </Link>

      <div className="flex items-center justify-between border-b pb-4">
        <div>
          <h1 className="text-2xl font-bold">Ads to CRM</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Map columns from your Google Sheet (connected to Meta/FB Lead Ads) into your Arevei CRM inbox.
          </p>
        </div>
        
        {connStatus.connected && connStatus.spreadsheet_id && (
          <button
            onClick={handleTogglePublish}
            disabled={publishing}
            className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg font-medium text-sm transition-all shadow ${
              workflow.status === "published"
                ? "bg-destructive text-destructive-foreground hover:bg-destructive/95"
                : "bg-primary text-primary-foreground hover:bg-primary/95"
            }`}
          >
            {workflow.status === "published" ? (
              <>
                <Ban className="w-4 h-4" /> Pause Sync
              </>
            ) : (
              <>
                <Power className="w-4 h-4" /> Activate Poller
              </>
            )}
          </button>
        )}
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        {/* Source Card */}
        <div className="md:col-span-2 space-y-6">
          {/* Step 1: Connect Google */}
          <div className="p-6 rounded-xl border bg-card space-y-4">
            <h3 className="text-base font-bold flex items-center gap-2">
              <span className="flex items-center justify-center w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-semibold">1</span>
              Google Authentication
            </h3>
            
            {!connStatus.connected ? (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  Connect the Google Account which owns or has permission to edit the target Google Sheet.
                </p>
                <button
                  onClick={handleGoogleConnect}
                  className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg border bg-accent hover:bg-accent/80 font-medium text-sm transition"
                >
                  <KeyRound className="w-4 h-4" /> Connect Google Account
                </button>
              </div>
            ) : (
              <div className="flex items-center justify-between p-3 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
                <div className="text-sm">
                  <div className="font-semibold text-emerald-500 flex items-center gap-1.5">
                    <Check className="w-4 h-4" /> Connected
                  </div>
                  <div className="text-muted-foreground mt-0.5">{connStatus.google_email}</div>
                </div>
                <button
                  onClick={handleDisconnect}
                  className="p-2 text-muted-foreground hover:text-destructive transition rounded-lg hover:bg-destructive/5"
                  title="Disconnect account"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            )}
          </div>

          {/* Step 2: Bind Sheet */}
          {connStatus.connected && (
            <div className="p-6 rounded-xl border bg-card space-y-4">
              <h3 className="text-base font-bold flex items-center gap-2">
                <span className="flex items-center justify-center w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-semibold">2</span>
                Spreadsheet Configuration
              </h3>
              
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-muted-foreground">Spreadsheet File</label>
                  {fetchingSheets ? (
                    <div className="h-10 flex items-center text-sm text-muted-foreground gap-2">
                      <RefreshCw className="w-4 h-4 animate-spin" /> Loading files...
                    </div>
                  ) : (
                    <select
                      value={selectedSpreadsheetId}
                      onChange={(e) => setSelectedSpreadsheetId(e.target.value)}
                      className="w-full h-10 px-3 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                    >
                      <option value="">-- Choose Sheet --</option>
                      {spreadsheets.map((s) => (
                        <option key={s.id} value={s.id}>{s.name}</option>
                      ))}
                    </select>
                  )}
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-muted-foreground">Tab (Worksheet) Name</label>
                  <input
                    type="text"
                    value={sheetTabName}
                    onChange={(e) => setSheetTabName(e.target.value)}
                    placeholder="e.g. Sheet1"
                    className="w-full h-10 px-3 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
              </div>

              <button
                onClick={handleBindSheet}
                disabled={binding || !selectedSpreadsheetId}
                className="w-full inline-flex items-center justify-center gap-2 h-10 rounded-lg bg-primary text-primary-foreground font-semibold text-sm hover:bg-primary/95 transition shadow disabled:opacity-50"
              >
                {binding ? <RefreshCw className="w-4 h-4 animate-spin" /> : <FileSpreadsheet className="w-4 h-4" />}
                Bind & Fetch Sheet Columns
              </button>
            </div>
          )}

          {/* Step 3: Column Mapping */}
          {connStatus.connected && connStatus.spreadsheet_id && connStatus.header_row && (
            <div className="p-6 rounded-xl border bg-card space-y-4">
              <h3 className="text-base font-bold flex items-center gap-2">
                <span className="flex items-center justify-center w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-semibold">3</span>
                CRM Column Mapping
              </h3>

              <p className="text-xs text-muted-foreground">
                Match columns in your Google Sheet to standard CRM field names. Custom questions are stored in fields data.
              </p>

              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-4 items-center border-b pb-2">
                  <span className="text-xs font-bold uppercase text-muted-foreground">CRM Lead Attribute</span>
                  <span className="text-xs font-bold uppercase text-muted-foreground">Google Sheet Header</span>
                </div>

                <div className="grid grid-cols-2 gap-4 items-center">
                  <span className="text-sm font-medium flex items-center gap-1">Email <span className="text-destructive">*</span></span>
                  <select
                    value={columnMap.email}
                    onChange={(e) => setColumnMap(prev => ({ ...prev, email: e.target.value }))}
                    className="h-9 px-2 rounded-lg border bg-background text-sm focus:outline-none"
                  >
                    <option value="">-- Ignore --</option>
                    {connStatus.header_row.map((h) => (
                      <option key={h} value={h}>{h}</option>
                    ))}
                  </select>
                </div>

                <div className="grid grid-cols-2 gap-4 items-center">
                  <span className="text-sm font-medium">Full Name</span>
                  <select
                    value={columnMap.full_name}
                    onChange={(e) => setColumnMap(prev => ({ ...prev, full_name: e.target.value }))}
                    className="h-9 px-2 rounded-lg border bg-background text-sm focus:outline-none"
                  >
                    <option value="">-- Ignore --</option>
                    {connStatus.header_row.map((h) => (
                      <option key={h} value={h}>{h}</option>
                    ))}
                  </select>
                </div>

                <div className="grid grid-cols-2 gap-4 items-center">
                  <span className="text-sm font-medium">Phone Number</span>
                  <select
                    value={columnMap.phone}
                    onChange={(e) => setColumnMap(prev => ({ ...prev, phone: e.target.value }))}
                    className="h-9 px-2 rounded-lg border bg-background text-sm focus:outline-none"
                  >
                    <option value="">-- Ignore --</option>
                    {connStatus.header_row.map((h) => (
                      <option key={h} value={h}>{h}</option>
                    ))}
                  </select>
                </div>

                <div className="grid grid-cols-2 gap-4 items-center">
                  <span className="text-sm font-medium flex items-center gap-1">
                    Meta Lead ID
                    <HelpCircle className="w-3.5 h-3.5 text-muted-foreground cursor-help" title="Used to uniquely identify rows. If not provided, rows are deduped by sheet row index." />
                  </span>
                  <select
                    value={columnMap.meta_lead_id}
                    onChange={(e) => setColumnMap(prev => ({ ...prev, meta_lead_id: e.target.value }))}
                    className="h-9 px-2 rounded-lg border bg-background text-sm focus:outline-none"
                  >
                    <option value="">-- Ignore (row-index dedupe) --</option>
                    {connStatus.header_row.map((h) => (
                      <option key={h} value={h}>{h}</option>
                    ))}
                  </select>
                </div>
              </div>

              <button
                onClick={handleSaveMapping}
                disabled={savingMap}
                className="w-full mt-4 inline-flex items-center justify-center gap-2 h-10 rounded-lg bg-accent text-accent-foreground font-semibold text-sm hover:bg-accent/80 transition"
              >
                {savingMap && <RefreshCw className="w-4 h-4 animate-spin" />}
                Save Column Mapping
              </button>
            </div>
          )}
        </div>

        {/* Visual Connector Map Sidebar */}
        <div className="space-y-6">
          <div className="p-6 rounded-xl border bg-card space-y-6">
            <h3 className="text-sm font-bold uppercase tracking-wider text-muted-foreground">Workflow Nodes</h3>

            {/* Source */}
            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase text-muted-foreground flex items-center gap-1.5">
                <MapPin className="w-3.5 h-3.5" /> Source
              </div>
              <div className="p-4 rounded-xl bg-accent border flex items-center gap-3">
                <FileSpreadsheet className="w-5 h-5 text-primary shrink-0" />
                <div className="min-w-0">
                  <div className="font-semibold text-sm truncate">Google Sheets</div>
                  <div className="text-xs text-muted-foreground truncate">
                    {connStatus.spreadsheet_name ? `${connStatus.spreadsheet_name} › ${connStatus.sheet_name}` : "Not selected"}
                  </div>
                </div>
              </div>
            </div>

            {/* Connector Arrow */}
            <div className="flex justify-center text-muted-foreground py-1.5">
              <ArrowRightLeft className="w-5 h-5 rotate-95" />
            </div>

            {/* Destination */}
            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase text-muted-foreground flex items-center gap-1.5">
                <Database className="w-3.5 h-3.5" /> Destination
              </div>
              <div className="p-4 rounded-xl bg-accent border flex items-center gap-3">
                <div className="w-5 h-5 flex items-center justify-center font-bold text-sm text-primary shrink-0 bg-primary/10 rounded">A</div>
                <div className="min-w-0">
                  <div className="font-semibold text-sm">Arevei CRM</div>
                  <div className="text-xs text-emerald-500 flex items-center gap-1">
                    <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" /> Ready
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
