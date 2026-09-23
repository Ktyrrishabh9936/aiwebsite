import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import {
  ArrowLeft, Check, RefreshCw, FileSpreadsheet, KeyRound,
  MapPin, Power, Ban, Trash2, ArrowRightLeft, Database
} from "lucide-react";
import { toast } from "sonner";
import api, { API, formatError } from "../../lib/api";
import { SHEET_MAPPING_FIELDS } from "../../lib/metaFields";

export default function AdsToCrmWorkflow() {
  const { wsId } = useParams();
  const [loading, setLoading] = useState(true);
  const [connStatus, setConnStatus] = useState({ connected: false });
  const [settings, setSettings] = useState({ fields: [] });
  const [spreadsheets, setSpreadsheets] = useState([]);
  const [sheetTabs, setSheetTabs] = useState([]);
  const [fetchingSheets, setFetchingSheets] = useState(false);
  const [fetchingTabs, setFetchingTabs] = useState(false);
  const [tabError, setTabError] = useState("");
  const [binding, setBinding] = useState(false);
  const [aiMatching, setAiMatching] = useState(false);
  const [mappingNotice, setMappingNotice] = useState("");
  const [savingMap, setSavingMap] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [workflow, setWorkflow] = useState({ status: "draft" });
  const [selectedSpreadsheetId, setSelectedSpreadsheetId] = useState("");
  const [sheetTabName, setSheetTabName] = useState("");
  const [columnMap, setColumnMap] = useState({});

  const mappingFields = connStatus.mapping_fields || SHEET_MAPPING_FIELDS;
  const mappingKeys = new Set(mappingFields.map((field) => field.key));
  const crmFields = [...(settings.fields || []).filter((field) => field.active !== false && !mappingKeys.has(field.key)), ...mappingFields];
  const canMap = Boolean(connStatus.connected && connStatus.spreadsheet_id && connStatus.header_row?.length);

  const loadWorkflow = useCallback(() => {
    api.get(`/workspaces/${wsId}/workflows`)
      .then((r) => {
        const ads = r.data.find((w) => w.kind === "ads_to_crm");
        if (ads) setWorkflow(ads);
      })
      .catch(() => {});
  }, [wsId]);

  const loadTabs = useCallback(async (spreadsheetId, preferredTab = "") => {
    if (!spreadsheetId) {
      setSheetTabs([]);
      setSheetTabName("");
      setTabError("");
      return;
    }
    try {
      setFetchingTabs(true);
      setTabError("");
      const r = await api.get(`/google/workspaces/${wsId}/spreadsheets/${spreadsheetId}/tabs`);
      const tabs = r.data || [];
      setSheetTabs(tabs);
      const names = tabs.map((tab) => tab.name);
      setSheetTabName((preferredTab && names.includes(preferredTab)) ? preferredTab : (names[0] || ""));
      if (!tabs.length) setTabError("No tabs were found in this spreadsheet.");
    } catch (e) {
      const message = formatError(e.response?.data?.detail);
      setTabError(message);
      toast.error(message);
      setSheetTabs([]);
    } finally {
      setFetchingTabs(false);
    }
  }, [wsId]);

  const loadStatus = useCallback(async () => {
    try {
      setLoading(true);
      const [statusRes, settingsRes] = await Promise.all([
        api.get(`/google/workspaces/${wsId}`),
        api.get(`/workspaces/${wsId}/crm/settings`)
      ]);
      setConnStatus(statusRes.data);
      setSettings(settingsRes.data);
      setColumnMap(statusRes.data.column_map || {});
      if (statusRes.data.connected) {
        setFetchingSheets(true);
        const sheetsRes = await api.get(`/google/workspaces/${wsId}/spreadsheets`);
        setSpreadsheets(sheetsRes.data);
        if (statusRes.data.spreadsheet_id) {
          setSelectedSpreadsheetId(statusRes.data.spreadsheet_id);
          await loadTabs(statusRes.data.spreadsheet_id, statusRes.data.sheet_name);
        }
      }
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setFetchingSheets(false);
      setLoading(false);
    }
  }, [wsId, loadTabs]);

  useEffect(() => {
    loadStatus();
    loadWorkflow();
  }, [loadStatus, loadWorkflow]);

  const handleGoogleConnect = () => {
    const width = 550;
    const height = 650;
    const left = window.screen.width / 2 - width / 2;
    const top = window.screen.height / 2 - height / 2;
    window.open(
      `${API}/google/connect?workspace_id=${wsId}`,
      "Google Connect",
      `width=${width},height=${height},left=${left},top=${top}`
    );
    const listener = (event) => {
      if (event.data?.type === "GOOGLE_CONNECTED") {
        toast.success("Google Account connected");
        loadStatus();
        window.removeEventListener("message", listener);
      }
    };
    window.addEventListener("message", listener);
  };

  const handleDisconnect = async () => {
    if (!confirm("Disconnect Google Sheets and pause this workflow?")) return;
    try {
      await api.delete(`/google/workspaces/${wsId}`);
      toast.success("Disconnected from Google");
      setConnStatus({ connected: false });
      setSpreadsheets([]);
      setSheetTabs([]);
      setSelectedSpreadsheetId("");
      setSheetTabName("");
      setWorkflow({ status: "draft" });
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    }
  };

  const handleSheetChange = async (spreadsheetId) => {
    setSelectedSpreadsheetId(spreadsheetId);
    await loadTabs(spreadsheetId);
  };

  const handleBindSheet = async () => {
    if (!selectedSpreadsheetId || !sheetTabName) {
      toast.error("Please select a spreadsheet and tab");
      return;
    }
    const sheetObj = spreadsheets.find((s) => s.id === selectedSpreadsheetId);
    try {
      setBinding(true);
      setMappingNotice("");
      const r = await api.post(`/google/workspaces/${wsId}/bind`, {
        spreadsheet_id: selectedSpreadsheetId,
        spreadsheet_name: sheetObj?.name || "Spreadsheet",
        sheet_name: sheetTabName
      });
      toast.success("Spreadsheet bound. Map CRM fields now.");
      setConnStatus((prev) => ({
        ...prev,
        spreadsheet_id: selectedSpreadsheetId,
        spreadsheet_name: sheetObj?.name,
        sheet_name: sheetTabName,
        header_row: r.data.headers
      }));
      setAiMatching(true);
      const suggested = await api.post(`/google/workspaces/${wsId}/suggest-column-map`);
      setColumnMap(suggested.data.column_map || {});
      setMappingNotice(suggested.data.warning || `AI matched ${suggested.data.matched} of ${suggested.data.total} CRM fields. Review the suggestions, then save.`);
      toast.success(suggested.data.warning ? "Sheet bound with high-confidence matches" : "Sheet bound and AI mapping completed");
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setAiMatching(false);
      setBinding(false);
    }
  };

  const handleAiMatch = async () => {
    try {
      setAiMatching(true);
      setMappingNotice("");
      const suggested = await api.post(`/google/workspaces/${wsId}/suggest-column-map`);
      setColumnMap(suggested.data.column_map || {});
      setMappingNotice(suggested.data.warning || `AI matched ${suggested.data.matched} of ${suggested.data.total} CRM fields. Review the suggestions, then save.`);
      toast.success(suggested.data.warning ? "High-confidence matches applied" : "AI mapping completed");
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setAiMatching(false);
    }
  };

  const handleSaveMapping = async () => {
    try {
      setSavingMap(true);
      await api.patch(`/google/workspaces/${wsId}/column_map`, { column_map: columnMap });
      toast.success("Column mapping saved");
      setConnStatus((prev) => ({ ...prev, column_map: columnMap }));
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
        toast.info("Workflow paused");
      } else {
        const r = await api.post(`/workspaces/${wsId}/workflows/ads-to-crm/publish`);
        setWorkflow(r.data);
        toast.success("Workflow active");
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
          <span className="text-sm text-muted-foreground">Loading connector...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <Link to={`/app/w/${wsId}/workflows`} className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="w-4 h-4" /> Back to Workflows
      </Link>

      <div className="flex items-center justify-between border-b pb-4">
        <div>
          <h1 className="text-2xl font-bold">Ads to CRM</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Map Google Sheet columns into your CRM. Active workflows receive Google change webhooks and import new rows automatically.
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
            {workflow.status === "published" ? <><Ban className="w-4 h-4" /> Pause Webhook</> : <><Power className="w-4 h-4" /> Activate Webhook</>}
          </button>
        )}
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <div className="md:col-span-2 space-y-6">
          <div className="p-6 rounded-xl border bg-card space-y-4">
            <h3 className="text-base font-bold flex items-center gap-2">
              <span className="flex items-center justify-center w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-semibold">1</span>
              Google Authentication
            </h3>
            {!connStatus.connected ? (
              <button onClick={handleGoogleConnect} className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg border bg-accent hover:bg-accent/80 font-medium text-sm transition">
                <KeyRound className="w-4 h-4" /> Connect Google Account
              </button>
            ) : (
              <div className="flex items-center justify-between p-3 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
                <div className="text-sm">
                  <div className="font-semibold text-emerald-500 flex items-center gap-1.5"><Check className="w-4 h-4" /> Connected</div>
                  <div className="text-muted-foreground mt-0.5">{connStatus.google_email}</div>
                  {!connStatus.write_access && <button onClick={handleGoogleConnect} className="mt-2 underline">Reconnect Google to allow status updates</button>}
                </div>
                <button onClick={handleDisconnect} className="p-2 text-muted-foreground hover:text-destructive transition rounded-lg hover:bg-destructive/5" title="Disconnect account">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            )}
          </div>

          {connStatus.connected && (
            <div className="p-6 rounded-xl border bg-card space-y-4">
              <h3 className="text-base font-bold flex items-center gap-2">
                <span className="flex items-center justify-center w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-semibold">2</span>
                Spreadsheet Configuration
              </h3>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="space-y-1.5">
                  <span className="text-xs font-semibold text-muted-foreground">Spreadsheet File</span>
                  <select
                    value={selectedSpreadsheetId}
                    onChange={(e) => handleSheetChange(e.target.value)}
                    disabled={fetchingSheets}
                    className="w-full h-10 px-3 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                  >
                    <option value="">Choose Sheet</option>
                    {spreadsheets.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                </label>
                <label className="space-y-1.5">
                  <span className="text-xs font-semibold text-muted-foreground">Tab</span>
                  <select
                    value={sheetTabName}
                    onChange={(e) => setSheetTabName(e.target.value)}
                    disabled={!selectedSpreadsheetId || fetchingTabs}
                    className="w-full h-10 px-3 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                  >
                    <option value="">{fetchingTabs ? "Loading tabs..." : "Choose Tab"}</option>
                    {sheetTabs.map((tab) => <option key={tab.name} value={tab.name}>{tab.name}</option>)}
                  </select>
                </label>
              </div>
              {tabError && selectedSpreadsheetId && (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm">
                  <span className="text-amber-600 dark:text-amber-400">{tabError}</span>
                  <button type="button" onClick={() => loadTabs(selectedSpreadsheetId, sheetTabName || connStatus.sheet_name)} disabled={fetchingTabs} className="inline-flex items-center gap-1.5 font-semibold text-primary underline disabled:opacity-50">
                    <RefreshCw className={`w-3.5 h-3.5 ${fetchingTabs ? "animate-spin" : ""}`} /> Retry tabs
                  </button>
                </div>
              )}
              <button
                onClick={handleBindSheet}
                disabled={binding || aiMatching || !selectedSpreadsheetId || !sheetTabName}
                className="w-full inline-flex items-center justify-center gap-2 h-10 rounded-lg bg-primary text-primary-foreground font-semibold text-sm hover:bg-primary/95 transition shadow disabled:opacity-50"
              >
                {(binding || aiMatching) ? <RefreshCw className="w-4 h-4 animate-spin" /> : <FileSpreadsheet className="w-4 h-4" />}
                {aiMatching ? "AI Matching Columns..." : "Bind & AI Match Columns"}
              </button>
            </div>
          )}

          {(
            <div className="p-6 rounded-xl border bg-card space-y-4">
              <h3 className="text-base font-bold flex items-center gap-2">
                <span className="flex items-center justify-center w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-semibold">3</span>
                CRM Column Mapping
              </h3>
              <p className="text-sm text-muted-foreground">Map Meta lead and attribution columns below. For custom form questions, create a field in <Link className="underline text-primary" to={`/app/w/${wsId}/crm`}>CRM Settings</Link>, then return here to map its Sheet column.</p>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-muted-foreground">AI suggestions are drafts. Review them before saving the mapping.</p>
                <button type="button" onClick={handleAiMatch} disabled={!canMap || aiMatching} className="inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold hover:bg-accent disabled:opacity-50">
                  <RefreshCw className={`w-4 h-4 ${aiMatching ? "animate-spin" : ""}`} /> AI Match Columns
                </button>
              </div>
              {mappingNotice && <p className="rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm text-primary">{mappingNotice}</p>}
              {!canMap && <p className="text-sm text-muted-foreground">Connect Google and bind a Sheet to choose headers for these fields.</p>}
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-4 items-center border-b pb-2">
                  <span className="text-xs font-bold uppercase text-muted-foreground">CRM Field</span>
                  <span className="text-xs font-bold uppercase text-muted-foreground">Google Sheet Header</span>
                </div>
                {crmFields.map((field) => (
                  <div key={field.key} className="grid grid-cols-2 gap-4 items-center">
                    <span className="text-sm font-medium">
                      {field.label} {field.required && <span className="text-destructive">*</span>}
                    </span>
                    <select
                      aria-label={`Sheet column for ${field.label}`}
                      disabled={!canMap}
                      value={columnMap[field.key] || ""}
                      onChange={(e) => setColumnMap((prev) => ({ ...prev, [field.key]: e.target.value }))}
                      className="h-9 px-2 rounded-lg border bg-background text-sm focus:outline-none"
                    >
                      <option value="">Ignore</option>
                      {(connStatus.header_row || []).map((h) => <option key={h} value={h}>{h}</option>)}
                    </select>
                  </div>
                ))}
              </div>
              <button
                onClick={handleSaveMapping}
                disabled={!canMap || savingMap || !columnMap.phone}
                className="w-full mt-4 inline-flex items-center justify-center gap-2 h-10 rounded-lg bg-accent text-accent-foreground font-semibold text-sm hover:bg-accent/80 transition disabled:opacity-50"
              >
                {savingMap && <RefreshCw className="w-4 h-4 animate-spin" />}
                Save Column Mapping
              </button>
            </div>
          )}
        </div>

        <div className="space-y-6">
          <div className="p-6 rounded-xl border bg-card space-y-6">
            <h3 className="text-sm font-bold uppercase tracking-wider text-muted-foreground">Workflow Nodes</h3>
            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase text-muted-foreground flex items-center gap-1.5"><MapPin className="w-3.5 h-3.5" /> Source</div>
              <div className="p-4 rounded-xl bg-accent border flex items-center gap-3">
                <FileSpreadsheet className="w-5 h-5 text-primary shrink-0" />
                <div className="min-w-0">
                  <div className="font-semibold text-sm truncate">Google Sheets</div>
                  <div className="text-xs text-muted-foreground truncate">{connStatus.spreadsheet_name ? `${connStatus.spreadsheet_name} > ${connStatus.sheet_name}` : "Not selected"}</div>
                </div>
              </div>
            </div>
            <div className="flex justify-center text-muted-foreground py-1.5"><ArrowRightLeft className="w-5 h-5 rotate-95" /></div>
            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase text-muted-foreground flex items-center gap-1.5"><Database className="w-3.5 h-3.5" /> Destination</div>
              <div className="p-4 rounded-xl bg-accent border flex items-center gap-3">
                <div className="w-5 h-5 flex items-center justify-center font-bold text-sm text-primary shrink-0 bg-primary/10 rounded">A</div>
                <div className="min-w-0">
                  <div className="font-semibold text-sm">Arevei CRM</div>
                  <div className="text-xs text-emerald-500 flex items-center gap-1"><span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" /> Ready</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
