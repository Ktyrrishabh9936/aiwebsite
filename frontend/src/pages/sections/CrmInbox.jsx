import MetaAttribution from "../../components/MetaAttribution";
import CrmPipeline from "../../components/CrmPipeline";
import CrmReminders from "../../components/CrmReminders";
import OpportunitySelector from "../../components/OpportunitySelector";
import LeadQualificationPanel from "../../components/LeadQualificationPanel";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import {
  Users, Calendar, Info, Search, XCircle, Save, BadgeIndianRupee,
  Plus, CheckCircle2, Settings, Trash2, Columns3, Palette, Building2,
  ReceiptText, FileText, ExternalLink, RefreshCw, FileCode2, MessageSquare, Send,
  Download, RotateCcw, PhoneCall, Ban, Bot, Power, Star, KeyRound
} from "lucide-react";
import { toast } from "sonner";
import api, { API, formatError } from "../../lib/api";

const CrmPerformance = lazy(() => import("./CrmPerformance"));

const FIELD_TYPES = ["text", "long_text", "email", "phone", "number", "currency", "date", "datetime", "boolean", "select", "multi_select", "url", "json"];
const DEFAULT_STAGES = [];
const PAYMENT_METHODS = ["Cash", "Bank Transfer", "UPI", "Cheque", "Card", "Other"];
const PAYMENT_STATUSES = ["Paid", "Pending"];
const ORG_FIELDS = ["company_name", "logo_url", "address", "phone", "email", "website", "tax_number", "bank_details", "authorized_signatory", "receipt_prefix", "invoice_prefix"];
const DETAIL_TABS = ["Details", "Qualification", "Reminders", "Payments", "Receipts", "Invoice", "Notes"];
const DEFAULT_AGENT_MAPPINGS_TEXT = JSON.stringify({
  workspace_id: "workspace_id",
  lead_id: "lead_id",
  session_id: "session.id",
  call_session_id: "session.id",
  to_number: "lead.phone",
  from_number: "agent.from_number",
  customer_name: "lead.full_name",
  lead_source: "lead.source",
  result_url: "callbacks.result_url",
  status_url: "callbacks.status_url",
  recording_url: "callbacks.recording_url"
}, null, 2);
const EMPTY_AGENT_DRAFT = {
  display_name: "",
  flow_id: "",
  trigger_url: "",
  auth_type: "basic",
  auth_username: "",
  auth_password: "",
  bearer_token: "",
  from_number: "",
  qualification_config_id: "indian_real_estate_v1",
  enabled: true,
  is_default: false,
  input_variable_mappings_text: DEFAULT_AGENT_MAPPINGS_TEXT,
  extra_payload_text: "{}"
};
function selectableAgentIds(agentState) {
  return [
    ...(agentState?.agents || []),
    agentState?.legacy_environment_agent
  ].filter((agent) => agent && agent.enabled !== false && agent.readiness?.ready !== false).map((agent) => agent.id);
}

function nextSelectedAgentId(current, agentState) {
  const ids = selectableAgentIds(agentState);
  const preferred = agentState?.selected_agent_config_id || "";
  if (ids.includes(current)) return current;
  if (ids.includes(preferred)) return preferred;
  return ids[0] || "";
}

const today = () => new Date().toISOString().slice(0, 10);
const stateClasses = {
  blue: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  amber: "bg-amber-500/10 text-amber-500 border-amber-500/20",
  emerald: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
  red: "bg-destructive/10 text-destructive border-destructive/20",
  slate: "bg-muted text-muted-foreground border-border"
};

function valuesFrom(lead, fields) {
  const values = { ...(lead?.field_values || {}) };
  fields.forEach((field) => {
    if (values[field.key] == null && lead?.[field.key] != null) values[field.key] = lead[field.key];
  });
  return values;
}

function emptyValues(fields) {
  return fields.reduce((acc, field) => ({ ...acc, [field.key]: field.type === "boolean" ? false : "" }), {});
}

function planFrom(lead) {
  const plan = lead?.payment_plan || {};
  const stages = (plan.stages?.length ? plan.stages : DEFAULT_STAGES).map((stage, index) => ({
    id: stage.id || `stage-${index}`,
    name: stage.name || "",
    amount: stage.amount || "",
    paid_amount: stage.paid_amount || (stage.due_amount ? String(Math.max(0, numericAmount(stage.amount) - numericAmount(stage.due_amount))) : stage.status === "paid" ? stage.amount || "" : ""),
    due_timing: stage.due_timing || "",
    status: stage.status || "pending",
    receipt_note: stage.receipt_note || "",
    transaction_id: stage.transaction_id || "",
    payment_date: stage.payment_date || today(),
    payment_method: stage.payment_method || "Bank Transfer",
    due_amount: stage.due_amount || "",
    description: stage.description || "",
    payment_amount: "",
    source: stage.source || "system"
  }));
  return deriveStageDues({
    status: plan.status || "active",
    total_amount: plan.total_amount || "",
    final_invoice_note: plan.final_invoice_note || "",
    stages
  });
}

function numericAmount(value) {
  const n = Number(String(value || "0").replace(/,/g, ""));
  return Number.isFinite(n) ? n : 0;
}

function autoDueForStages(stages, totalAmount) {
  let runningPaid = 0;
  return stages.map((stage) => {
    const paid = numericAmount(stage.paid_amount);
    const stageAmount = numericAmount(stage.amount);
    runningPaid += paid;
    const status = paid <= 0 ? "pending" : stageAmount > 0 && paid < stageAmount ? "partially_paid" : "paid";
    const stageDue = status === "paid" ? 0 : Math.max(0, numericAmount(totalAmount) - runningPaid);
    return { ...stage, status, due_amount: String(stageDue) };
  });
}

function deriveStageDues(plan) {
  const stages = autoDueForStages(plan.stages || [], plan.total_amount);
  const totalPaid = stages.reduce((sum, stage) => sum + numericAmount(stage.paid_amount), 0);
  return {
    ...plan,
    stages,
    total_paid: String(totalPaid),
    due_amount: String(Math.max(0, numericAmount(plan.total_amount) - totalPaid)),
  };
}

function totalDueForLead(lead, plan) {
  if (lead?.conversion_type === "single_payment") {
    return numericAmount(lead?.payment_summary?.due_amount);
  }
  return numericAmount(plan?.due_amount);
}

function singleReceiptDraft(form, patch) {
  const next = { ...form, ...patch };
  const existingPaid = numericAmount(next.existing_paid);
  const paid = numericAmount(next.paid_amount);
  const due = Math.max(0, numericAmount(next.total_amount) - existingPaid - paid);
  return {
    ...next,
    amount: String(paid || ""),
    due_amount: String(due),
    status: paid <= 0 ? "Pending" : "Paid",
  };
}

function statusForPayment(amount, balance) {
  const paid = numericAmount(amount);
  if (paid <= 0) return "Pending";
  return "Paid";
}

function stageRemainingAmount(stage) {
  const stageAmount = numericAmount(stage?.amount);
  if (stageAmount <= 0) return numericAmount(stage?.due_amount);
  return Math.max(0, stageAmount - numericAmount(stage?.paid_amount));
}

function titleStatus(status) {
  return String(status || "pending").toLowerCase() === "paid" ? "Paid" : "Pending";
}

function receiptDownloadUrl(wsId, leadId, receiptId) {
  return `${API}/workspaces/${wsId}/crm/leads/${leadId}/receipts/${receiptId}/pdf`;
}

function finalInvoiceDownloadUrl(wsId, leadId) {
  return `${API}/workspaces/${wsId}/crm/leads/${leadId}/final-invoice/pdf`;
}

export default function CrmInbox() {
  const { wsId } = useParams();
  const location = useLocation();
  const [activeTab, setActiveTab] = useState(() => new URLSearchParams(window.location.search).get("tab") === "reminders" ? "reminders" : "records");
  useEffect(() => { if (new URLSearchParams(location.search).get("tab") === "reminders") setActiveTab("reminders"); }, [location.search]);
  const [recordsLayout, setRecordsLayout] = useState("list");
  const [pipelineRevision, setPipelineRevision] = useState(0);
  const openLead = async (leadOrId) => {
    const id = typeof leadOrId === "object" ? leadOrId?.id : leadOrId;
    if (!id) return;
    try { const { data } = await api.get(`/workspaces/${wsId}/crm/leads/${encodeURIComponent(id)}`); selectLead(data); }
    catch (e) { toast.error(formatError(e.response?.data?.detail)); }
  };
  const [recordView, setRecordView] = useState("active");
  const [leads, setLeads] = useState([]);
  const [settings, setSettings] = useState({ fields: [], states: [], templates: [], organization: {} });
  const [plivoAgentState, setPlivoAgentState] = useState({ agents: [], selected_agent_config_id: "", legacy_environment_agent: null });
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [callingLeadId, setCallingLeadId] = useState("");
  const [cancellingCallId, setCancellingCallId] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [campaignQuery, setCampaignQuery] = useState("");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdBefore, setCreatedBefore] = useState("");
  const [debouncedLeadFilters, setDebouncedLeadFilters] = useState({});
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState({ total: 0, page: 1, limit: 10 });
  const [selectedLead, setSelectedLead] = useState(null);
  const [fieldValues, setFieldValues] = useState({});
  const lastServerValues = useRef({});
  const [showCreateLead, setShowCreateLead] = useState(false);
  const [createValues, setCreateValues] = useState({});
  const [paymentPlan, setPaymentPlan] = useState(planFrom(null));
  const [conversionType, setConversionType] = useState("single_payment");
  const [receiptForm, setReceiptForm] = useState({ payment_stage: "Single Payment", total_amount: "", existing_paid: "", paid_amount: "", amount: "", transaction_id: "", payment_date: today(), payment_method: "Bank Transfer", status: "Pending", due_amount: "0", description: "" });
  const [newField, setNewField] = useState({ label: "", key: "", type: "text", required: false, options: [] });
  const [newState, setNewState] = useState({ label: "", key: "", color: "blue" });
  const [templateDraft, setTemplateDraft] = useState({ name: "Receipt", type: "receipt", button_label: "Download Receipt", active: true, html: "<h1>Receipt</h1><p>{{full_name}}</p><p>{{email}}</p><table>{{payment_plan.stages}}</table>" });
  const listRefreshInFlight = useRef(false);

  const activeFields = useMemo(() => (settings.fields || []).filter((field) => field.active !== false), [settings.fields]);
  const leadFilters = useMemo(() => ({
    ...(debouncedSearch.trim() ? { search: debouncedSearch.trim() } : {}),
    ...(campaignQuery.trim() ? { campaign: campaignQuery.trim() } : {}),
    ...(createdFrom ? { created_from: new Date(createdFrom).toISOString() } : {}),
    ...(createdBefore ? { created_before: new Date(new Date(createdBefore).getTime() + 60_000).toISOString() } : {}),
  }), [debouncedSearch, campaignQuery, createdFrom, createdBefore]);
  const states = useMemo(() => {
    const base = settings.states?.length ? settings.states : [{ key: "new", label: "New", color: "blue" }];
    const hasAiQualified = base.some((state) => state.key === "ai_qualified");
    return hasAiQualified ? base : [...base, { key: "ai_qualified", label: "AI Qualified", color: "emerald", order: (base.length || 1) + 1 }];
  }, [settings.states]);
  const plivoAgents = useMemo(() => {
    const stored = plivoAgentState.agents || [];
    return plivoAgentState.legacy_environment_agent ? [...stored, plivoAgentState.legacy_environment_agent] : stored;
  }, [plivoAgentState]);
  const enabledPlivoAgents = useMemo(() => plivoAgents.filter((agent) => agent.enabled !== false && agent.readiness?.ready !== false), [plivoAgents]);
  const hasCallableAgent = true; // Backend resolves the lead profile and validates its workspace provider.
  const totalPages = Math.max(1, Math.ceil((pagination.total || 0) / pagination.limit));

  const selectLead = (lead) => {
    setSelectedLead(lead);
    const values = valuesFrom(lead, activeFields);
    lastServerValues.current = values;
    setFieldValues(values);
    setPaymentPlan(planFrom(lead));
    setConversionType(lead?.conversion_type || "single_payment");
    const summary = lead?.payment_summary || {};
    setReceiptForm((current) => ({
      ...current,
      total_amount: summary.total_amount || current.total_amount || "",
      existing_paid: summary.total_paid || "",
      paid_amount: "",
      amount: "",
      due_amount: summary.due_amount || "0",
      status: summary.status === "completed" ? "Paid" : "Pending",
    }));
  };

  const refreshSelectedLead = (lead, fields = activeFields) => {
    const previous = lastServerValues.current;
    const incoming = valuesFrom(lead, fields);
    setFieldValues((current) => {
      const merged = { ...incoming };
      for (const [key, value] of Object.entries(current)) {
        if (value !== previous[key]) merged[key] = value;
      }
      return merged;
    });
    lastServerValues.current = incoming;
    setSelectedLead(lead);
  };

  const openCreateLead = () => {
    setCreateValues(emptyValues(activeFields));
    setShowCreateLead(true);
  };

  const leadListParams = () => {
    const params = new URLSearchParams({ page: String(page), limit: "10" });
    if (statusFilter !== "all") params.set("status", statusFilter);
    Object.entries(debouncedLeadFilters).forEach(([key, value]) => params.set(key, value));
    if (recordView === "trash") params.set("trashed", "true");
    return params;
  };

  const applyLeadPage = (leadPage) => {
    const items = leadPage?.items || [];
    setLeads(items);
    setPagination({ total: leadPage?.total || 0, page: leadPage?.page || page, limit: leadPage?.limit || 10 });
  };

  const refreshLeadList = async (signal) => {
    if (listRefreshInFlight.current) return;
    listRefreshInFlight.current = true;
    try {
      const { data } = await api.get(`/workspaces/${wsId}/crm/leads?${leadListParams().toString()}`, { signal });
      applyLeadPage(data);
    } catch (e) {
      if (e.code !== "ERR_CANCELED") toast.error(formatError(e.response?.data?.detail));
    } finally {
      listRefreshInFlight.current = false;
    }
  };

  const loadAll = async (signal) => {
    try {
      setLoading(true);
      const params = leadListParams();
      const { data } = await api.get(`/workspaces/${wsId}/crm/bootstrap?${params.toString()}`, { signal });
      setSettings(data.settings);
      const nextPlivoAgents = data.agents || { agents: [], selected_agent_config_id: "", legacy_environment_agent: null };
      setPlivoAgentState(nextPlivoAgents);
      setSelectedAgentId((current) => nextSelectedAgentId(current, nextPlivoAgents));
      applyLeadPage(data.leads);
      if (selectedLead) {
        const refreshed = (data.leads?.items || []).find((lead) => lead.id === selectedLead.id);
        if (refreshed) {
          refreshSelectedLead(refreshed, (data.settings?.fields || []).filter((field) => field.active !== false));
        } else {
          setSelectedLead(null);
        }
      }
    } catch (e) {
      if (e.code === "ERR_CANCELED") return;
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchQuery), 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedLeadFilters(leadFilters), 300);
    return () => clearTimeout(timer);
  }, [leadFilters]);

  useEffect(() => {
    const controller = new AbortController();
    const t = setTimeout(() => loadAll(controller.signal), 50);
    return () => { clearTimeout(t); controller.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId, statusFilter, page, debouncedLeadFilters, recordView]);

  useEffect(() => {
    const refreshImportedLeads = () => refreshLeadList();
    window.addEventListener("arevei:sheet-synced", refreshImportedLeads);
    return () => window.removeEventListener("arevei:sheet-synced", refreshImportedLeads);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId, statusFilter, page, debouncedLeadFilters, recordView]);

  // A Sheet webhook runs on the server, so an already-open browser cannot
  // receive its new rows directly. Refresh only the lightweight lead page
  // while CRM records are visible; bootstrap/settings/agents are not repeated.
  useEffect(() => {
    if (activeTab !== "records") return undefined;
    const refreshWhenVisible = () => { if (!document.hidden) refreshLeadList(); };
    const interval = setInterval(refreshWhenVisible, 15000);
    window.addEventListener("focus", refreshWhenVisible);
    return () => { clearInterval(interval); window.removeEventListener("focus", refreshWhenVisible); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, wsId, statusFilter, page, debouncedLeadFilters, recordView]);

  const mergeLead = (updated) => {
    setLeads((prev) => prev.map((lead) => lead.id === updated.id ? updated : lead));
    selectLead(updated);
  };

  useEffect(() => {
    if (!selectedLead?.id) return undefined;
    let cancelled = false;
    const interval = setInterval(async () => {
      if (document.hidden) return;
      try {
        const r = await api.get(`/workspaces/${wsId}/crm/leads/${selectedLead.id}`);
        if (!cancelled) {
          setLeads((prev) => prev.map((lead) => lead.id === r.data.id ? r.data : lead));
          refreshSelectedLead(r.data);
        }
      } catch {
        clearInterval(interval);
      }
    }, 6000);
    return () => { cancelled = true; clearInterval(interval); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId, selectedLead?.id, selectedLead?.qualification_call?.status]);

  const createLead = async () => {
    try {
      setSaving(true);
      const r = await api.post(`/workspaces/${wsId}/crm/leads`, { field_values: createValues });
      const call = r.data?.qualification_call || {};
      if (call.status === "failed") {
        toast.error(`Lead created, but the call failed: ${call.last_error || "Check the lead's call status"}`);
      } else if (call.status === "reconcile_required") {
        toast.warning("Lead created, but the call outcome needs review before retrying");
      } else if (call.status === "scheduled") {
        toast.success(call.scheduled_for
          ? `Lead created. Call scheduled for ${new Date(call.scheduled_for).toLocaleString()}`
          : "Lead created. Qualification call scheduled");
      } else if (call.status === "started") {
        toast.success("Lead created. Qualification call started");
      } else {
        toast.success("Lead created");
      }
      setShowCreateLead(false);
      setRecordView("active");
      setStatusFilter("all");
      setPage(1);
      await loadAll();
      selectLead(r.data);
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const trashLead = async (lead) => {
    try {
      setSaving(true);
      await api.delete(`/workspaces/${wsId}/crm/leads/${lead.id}`);
      toast.success("Lead moved to trash");
      if (selectedLead?.id === lead.id) setSelectedLead(null);
      await loadAll();
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const restoreLead = async (lead) => {
    try {
      setSaving(true);
      const r = await api.post(`/workspaces/${wsId}/crm/leads/${lead.id}/restore`, {});
      toast.success("Lead restored");
      setRecordView("active");
      setStatusFilter("all");
      setPage(1);
      await loadAll();
      selectLead(r.data);
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const saveLead = async () => {
    if (!selectedLead) return;
    try {
      setSaving(true);
      const r = await api.patch(`/workspaces/${wsId}/crm/leads/${selectedLead.id}`, { status: selectedLead.status, field_values: fieldValues });
      toast.success("CRM record saved");
      mergeLead(r.data);
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const changeStatus = async (lead, status) => {
    try {
      const r = await api.patch(`/workspaces/${wsId}/crm/leads/${lead.id}`, { status });
      mergeLead(r.data);
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    }
  };

  const convertLead = async () => {
    if (!selectedLead) return;
    try {
      setSaving(true);
      const r = await api.post(`/workspaces/${wsId}/crm/leads/${selectedLead.id}/convert`, { conversion_type: conversionType, payment_plan: paymentPlan });
      toast.success(conversionType === "single_payment" ? "Customer ready for final invoice" : "Payment plan created");
      mergeLead(r.data);
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const savePlan = async () => {
    if (!selectedLead) return;
    try {
      setSaving(true);
      const r = await api.patch(`/workspaces/${wsId}/crm/leads/${selectedLead.id}/payment-plan`, paymentPlan);
      toast.success("Payment plan saved");
      mergeLead(r.data);
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const refreshSelected = async () => {
    if (!selectedLead) return;
    const r = await api.get(`/workspaces/${wsId}/crm/leads/${selectedLead.id}`);
    mergeLead(r.data);
  };

  const createReceipt = async (receiptPayload = null) => {
    if (!selectedLead) return;
    try {
      setSaving(true);
      const payload = receiptPayload && !receiptPayload.preventDefault ? receiptPayload : receiptForm;
      const r = await api.post(`/workspaces/${wsId}/crm/leads/${selectedLead.id}/receipts`, payload);
      toast.success("Receipt generated");
      mergeLead(r.data);
      return r.data;
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
    return null;
  };

  const createInvoice = async () => {
    if (!selectedLead) return;
    try {
      setSaving(true);
      await api.post(`/workspaces/${wsId}/crm/leads/${selectedLead.id}/final-invoice`, {});
      toast.success("Final invoice generated");
      await refreshSelected();
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const addLeadNote = async (body) => {
    if (!selectedLead) return;
    try {
      setSaving(true);
      const r = await api.post(`/workspaces/${wsId}/crm/leads/${selectedLead.id}/notes`, { body });
      toast.success("Note added");
      mergeLead(r.data);
      return r.data;
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
    return null;
  };

  const deleteLeadNote = async (noteId) => {
    if (!selectedLead) return;
    try {
      setSaving(true);
      const r = await api.delete(`/workspaces/${wsId}/crm/leads/${selectedLead.id}/notes/${noteId}`);
      toast.success("Note removed");
      mergeLead(r.data);
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const addField = async () => {
    try {
      const r = await api.post(`/workspaces/${wsId}/crm/settings/fields`, newField);
      setSettings(r.data);
      setNewField({ label: "", key: "", type: "text", required: false, options: [] });
      toast.success("Field added");
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    }
  };
  const updateField = async (field, patch) => {
    const r = await api.patch(`/workspaces/${wsId}/crm/settings/fields/${field.key}`, patch);
    setSettings(r.data);
  };
  const removeField = async (field) => {
    try {
      const r = await api.delete(`/workspaces/${wsId}/crm/settings/fields/${field.key}`);
      setSettings(r.data);
      toast.success("Field removed");
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    }
  };
  const saveStates = async (nextStates) => {
    const r = await api.put(`/workspaces/${wsId}/crm/settings/states`, { states: nextStates });
    setSettings(r.data);
  };
  const addState = async () => {
    if (!newState.label.trim()) return;
    await saveStates([...(settings.states || []), { ...newState, order: (settings.states || []).length + 1 }]);
    setNewState({ label: "", key: "", color: "blue" });
  };
  const saveOrganization = async (org) => {
    const r = await api.patch(`/workspaces/${wsId}/crm/settings/organization`, org);
    setSettings(r.data);
    toast.success("Organization saved");
  };
  const saveTemplate = async () => {
    const r = await api.post(`/workspaces/${wsId}/crm/settings/templates`, templateDraft);
    setSettings(r.data);
    toast.success("Template saved");
  };

  const refreshPlivoAgents = async () => {
    const { data } = await api.get(`/workspaces/${wsId}/crm/plivo/agents`);
    const nextState = data || { agents: [], selected_agent_config_id: "", legacy_environment_agent: null };
    setPlivoAgentState(nextState);
    setSelectedAgentId((current) => nextSelectedAgentId(current, nextState));
    return nextState;
  };

  const agentPayloadFromDraft = (draft) => {
    const inputMappings = JSON.parse(draft.input_variable_mappings_text || "{}");
    const extraPayload = JSON.parse(draft.extra_payload_text || "{}");
    const payload = {
      display_name: draft.display_name,
      flow_id: draft.flow_id,
      trigger_url: draft.trigger_url,
      auth_type: draft.auth_type,
      from_number: draft.from_number,
      qualification_config_id: draft.qualification_config_id,
      enabled: draft.enabled,
      is_default: draft.is_default,
      input_variable_mappings: inputMappings,
      extra_payload: extraPayload
    };
    if (draft.auth_type === "basic") {
      if (draft.auth_username?.trim()) payload.auth_username = draft.auth_username.trim();
      if (draft.auth_password?.trim()) payload.auth_password = draft.auth_password.trim();
    }
    if (draft.auth_type === "bearer" && draft.bearer_token?.trim()) {
      payload.bearer_token = draft.bearer_token.trim();
    }
    return payload;
  };

  const savePlivoAgent = async (draft) => {
    try {
      setSaving(true);
      const payload = agentPayloadFromDraft(draft);
      if (draft.id && draft.id !== "environment") {
        await api.patch(`/workspaces/${wsId}/crm/plivo/agents/${draft.id}`, payload);
        toast.success("AI agent saved");
      } else {
        const { data } = await api.post(`/workspaces/${wsId}/crm/plivo/agents`, payload);
        setSelectedAgentId(data.id);
        toast.success("AI agent connected");
      }
      await refreshPlivoAgents();
      return true;
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail || e.message));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const selectPlivoAgent = async (agent) => {
    if (!agent?.id || agent.id === "environment") {
      setSelectedAgentId(agent?.id || "");
      return;
    }
    try {
      setSaving(true);
      const { data } = await api.post(`/workspaces/${wsId}/crm/plivo/agents/${agent.id}/select`, {});
      setSelectedAgentId(data.id);
      await refreshPlivoAgents();
      toast.success("Default AI agent selected");
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const togglePlivoAgent = async (agent) => {
    if (!agent?.id || agent.id === "environment") return;
    try {
      setSaving(true);
      await api.patch(`/workspaces/${wsId}/crm/plivo/agents/${agent.id}`, { ...agent, enabled: agent.enabled === false });
      await refreshPlivoAgents();
      toast.success(agent.enabled === false ? "AI agent enabled" : "AI agent disabled");
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const callLead = async (lead) => {
    if (!lead?.id) return;
    try {
      setCallingLeadId(lead.id);
      const payload = {}; // Qualification profile selects the provider.
      const r = await api.post(`/workspaces/${wsId}/crm/leads/${lead.id}/calls/outbound`, payload);
      if (r.data?.status === "already_active") {
        toast.info(r.data.reason || "AI qualification call is already in progress");
        if (r.data?.lead) mergeLead(r.data.lead);
        return;
      }
      const leadPhone = r.data?.lead_phone;
      const agentName = r.data?.agent_display_name;
      toast.success(leadPhone ? `Qualification call started to ${leadPhone}${agentName ? ` via ${agentName}` : ""}` : "Qualification call started");
      if (r.data?.lead) mergeLead(r.data.lead);
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setCallingLeadId("");
    }
  };

  const cancelScheduledCall = async (lead) => {
    if (!lead?.id) return;
    try {
      setCancellingCallId(lead.id);
      const r = await api.post(`/workspaces/${wsId}/crm/leads/${lead.id}/calls/qualification/cancel`, {});
      toast.success("Scheduled call cancelled");
      if (r.data?.lead) mergeLead(r.data.lead);
      await loadAll();
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setCancellingCallId("");
    }
  };

  return (
    <div className="crm-workspace p-4 sm:p-8 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="font-display text-3xl sm:text-4xl font-bold tracking-tight">CRM</h1>
          <p className="text-sm text-muted-foreground mt-2">Move leads forward. Keep every follow-up and payment in view.</p>
        </div>
        <div className="flex rounded-lg border bg-card p-1 w-fit max-w-full overflow-x-auto" role="group" aria-label="CRM sections">
          <TabButton active={activeTab === "records"} onClick={() => setActiveTab("records")} icon={Users} label="Records" />
          <TabButton active={activeTab === "reminders"} onClick={() => { setActiveTab("reminders"); setSelectedLead(null); }} icon={Calendar} label="Reminders" />
          <TabButton active={activeTab === "settings"} onClick={() => setActiveTab("settings")} icon={Settings} label="Settings" />
          <TabButton active={activeTab === "performance"} onClick={() => setActiveTab("performance")} icon={CheckCircle2} label="Performance" />
        </div>
      </div>

      {activeTab === "reminders" ? <CrmReminders wsId={wsId} onOpenLead={async (id) => { await openLead(id); setActiveTab("records"); }} /> : activeTab === "performance" ? <Suspense fallback={<div className="rounded-xl border bg-card p-8 text-sm text-muted-foreground">Loading performance…</div>}><CrmPerformance wsId={wsId} states={states} /></Suspense> : activeTab === "settings" ? (
        <SettingsPanel
          fields={settings.fields || []}
          states={states}
          organization={settings.organization || {}}
          templates={settings.templates || []}
          plivoAgents={plivoAgents}
          selectedAgentId={selectedAgentId}
          newField={newField}
          setNewField={setNewField}
          newState={newState}
          setNewState={setNewState}
          templateDraft={templateDraft}
          setTemplateDraft={setTemplateDraft}
          addField={addField}
          updateField={updateField}
          removeField={removeField}
          addState={addState}
          saveStates={saveStates}
          saveOrganization={saveOrganization}
          saveTemplate={saveTemplate}
          savePlivoAgent={savePlivoAgent}
          selectPlivoAgent={selectPlivoAgent}
          togglePlivoAgent={togglePlivoAgent}
          saving={saving}
        />
      ) : (
        <>
          <div className="flex flex-col-reverse lg:flex-row gap-4 lg:items-start justify-between">
            <div className="flex flex-wrap gap-1.5 w-full sm:w-auto">
              <FilterButton active={recordView === "active" && statusFilter === "all"} onClick={() => { setRecordView("active"); setStatusFilter("all"); setPage(1); }}>All Leads</FilterButton>
              {states.map((state) => <FilterButton key={state.key} active={recordView === "active" && statusFilter === state.key} onClick={() => { setRecordView("active"); setStatusFilter(state.key); setPage(1); }}>{state.label}</FilterButton>)}
              <FilterButton active={recordView === "trash"} onClick={() => { setRecordView("trash"); setStatusFilter("all"); setPage(1); }}><Trash2 className="w-3.5 h-3.5" /> Trash</FilterButton>
            </div>
            <div className="flex shrink-0 lg:justify-end">
              <button onClick={openCreateLead} className="inline-flex items-center justify-center gap-2 px-5 h-11 rounded-lg bg-primary text-primary-foreground text-sm font-semibold whitespace-nowrap"><Plus className="w-4 h-4" /> New Lead</button>
            </div>
          </div>

          <div className="grid gap-3 rounded-xl border bg-card p-3 sm:grid-cols-2 xl:grid-cols-[minmax(220px,2fr)_minmax(160px,1fr)_minmax(160px,1fr)_minmax(160px,1fr)_auto] xl:items-end" role="search" aria-label="Filter CRM leads">
            <label className="text-xs font-medium text-muted-foreground">Search leads
              <div className="relative mt-1"><Search className="absolute left-3 top-3 w-4 h-4" /><input value={searchQuery} maxLength={200} onChange={(e) => { setSearchQuery(e.target.value); setPage(1); }} placeholder="Name, phone, or campaign" className="w-full h-10 pl-9 pr-3 rounded-lg border bg-background text-sm text-foreground" /></div>
            </label>
            <label className="text-xs font-medium text-muted-foreground">Campaign
              <input value={campaignQuery} maxLength={200} onChange={(e) => { setCampaignQuery(e.target.value); setPage(1); }} placeholder="Filter campaign" className="mt-1 w-full h-10 px-3 rounded-lg border bg-background text-sm text-foreground" />
            </label>
            <label className="text-xs font-medium text-muted-foreground">Created from
              <input type="datetime-local" value={createdFrom} onChange={(e) => { setCreatedFrom(e.target.value); setPage(1); }} className="mt-1 w-full h-10 px-2 rounded-lg border bg-background text-sm text-foreground" />
            </label>
            <label className="text-xs font-medium text-muted-foreground">Created through
              <input type="datetime-local" min={createdFrom || undefined} value={createdBefore} onChange={(e) => { setCreatedBefore(e.target.value); setPage(1); }} className="mt-1 w-full h-10 px-2 rounded-lg border bg-background text-sm text-foreground" />
            </label>
            <button type="button" disabled={!searchQuery && !campaignQuery && !createdFrom && !createdBefore} onClick={() => { setSearchQuery(""); setCampaignQuery(""); setCreatedFrom(""); setCreatedBefore(""); setPage(1); }} className="h-10 px-3 rounded-lg border bg-background text-sm font-medium hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed">Clear filters</button>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-1 rounded-lg bg-muted p-1" role="group" aria-label="Record views">{["list", "kanban"].map((view) => <button key={view} aria-pressed={recordsLayout === view} onClick={() => { setRecordsLayout(view); if (view === "kanban") setRecordView("active"); }} className={`min-h-9 px-4 rounded-md text-sm font-medium ${recordsLayout === view ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>{view === "list" ? "List" : "Pipeline"}</button>)}</div>
            <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs text-muted-foreground">
              <Link to={`/app/w/${wsId}/workflows/ads-to-crm`} className="inline-flex items-center min-h-9 underline underline-offset-4 hover:text-foreground">Lead source mapping</Link>
              <Link to={`/app/w/${wsId}/qualification`} className="inline-flex items-center min-h-9 underline underline-offset-4 hover:text-foreground">Voice qualification settings</Link>
            </div>
          </div>
          <div className={`grid gap-6 items-start ${selectedLead ? "xl:grid-cols-[minmax(0,1fr)_560px]" : "grid-cols-1"}`}>
            <div className="space-y-3 min-w-0">
              {recordsLayout === "kanban" && recordView !== "trash" ? <CrmPipeline wsId={wsId} states={states} filters={debouncedLeadFilters} statusFilter={statusFilter} onSelect={openLead} revision={pipelineRevision} onChanged={(lead) => { setPipelineRevision((v) => v + 1); setSelectedLead((old) => old?.id === lead.id ? lead : old); loadAll(); }} /> : <>
              <LeadTable leads={leads} fields={activeFields} states={states} selectedLead={selectedLead} loading={loading} trashed={recordView === "trash"} callingLeadId={callingLeadId} canCallWithAI={hasCallableAgent} onSelect={openLead} onStatus={changeStatus} onTrash={trashLead} onRestore={restoreLead} onCall={callLead} />
              <Pagination page={page} totalPages={totalPages} total={pagination.total} onPage={setPage} />
              </>}
            </div>
            {selectedLead && (
              <LeadDetail
                key={selectedLead.id}
                lead={selectedLead}
                fields={activeFields}
                states={states}
                values={fieldValues}
                setValues={setFieldValues}
                setLead={setSelectedLead}
                saving={saving}
                saveLead={saveLead}
                conversionType={conversionType}
                setConversionType={setConversionType}
                convertLead={convertLead}
                paymentPlan={paymentPlan}
                setPaymentPlan={setPaymentPlan}
                savePlan={savePlan}
                receiptForm={receiptForm}
                setReceiptForm={setReceiptForm}
                createReceipt={createReceipt}
                createInvoice={createInvoice}
                addLeadNote={addLeadNote}
                deleteLeadNote={deleteLeadNote}
                callingLeadId={callingLeadId}
                canCallWithAI={hasCallableAgent}
                cancellingCallId={cancellingCallId}
                callLead={callLead}
                cancelScheduledCall={cancelScheduledCall}
                trashLead={trashLead}
                restoreLead={restoreLead}
                close={() => setSelectedLead(null)}
                wsId={wsId}
                onOpportunityUpdated={(lead) => { mergeLead(lead); setPipelineRevision((value) => value + 1); }}
              />
            )}
          </div>
          {showCreateLead && (
            <CreateLeadDialog
              fields={activeFields}
              values={createValues}
              setValues={setCreateValues}
              saving={saving}
              onCreate={createLead}
              onClose={() => setShowCreateLead(false)}
            />
          )}
        </>
      )}
    </div>
  );
}

function TabButton({ active, onClick, icon: Icon, label }) {
  return <button onClick={onClick} className={`inline-flex items-center gap-2 px-3 h-9 rounded-md text-sm font-semibold ${active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent"}`}><Icon className="w-4 h-4" /> {label}</button>;
}
function FilterButton({ active, onClick, children }) {
  return <button onClick={onClick} className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition ${active ? "bg-primary text-primary-foreground border-primary" : "bg-card text-muted-foreground hover:bg-accent"}`}>{children}</button>;
}
function Pagination({ page, totalPages, total, onPage }) {
  return <div className="flex items-center justify-between text-sm text-muted-foreground"><span>{total} leads</span><div className="flex items-center gap-2"><button disabled={page <= 1} onClick={() => onPage(page - 1)} className="px-3 h-8 rounded-lg border bg-card disabled:opacity-40">Previous</button><span>Page {page} of {totalPages}</span><button disabled={page >= totalPages} onClick={() => onPage(page + 1)} className="px-3 h-8 rounded-lg border bg-card disabled:opacity-40">Next</button></div></div>;
}

function normalizeAgentDisplayName(name) {
  const cleaned = String(name || "")
    .replace(/\bPlivo\b/gi, "")
    .replace(/\s{2,}/g, " ")
    .replace(/\s+AI\s+agent/gi, " AI agent")
    .trim();
  return cleaned || "AI agent";
}

function AgentCallSelector({ agents, selectedAgentId, setSelectedAgentId }) {
  if (!agents.length) {
    return (
      <div className="hidden md:flex h-10 items-center gap-2 rounded-lg border bg-muted px-3 text-xs font-semibold text-muted-foreground">
        <Bot className="w-4 h-4" />
        No AI agent
      </div>
    );
  }
  return (
    <label className="relative min-w-0 flex-1 sm:flex-none sm:w-56">
      <Bot className="absolute left-3 top-3 w-4 h-4 text-muted-foreground" />
      <select value={selectedAgentId} onChange={(e) => setSelectedAgentId(e.target.value)} className="w-full h-10 pl-9 pr-3 rounded-lg border bg-background text-sm font-semibold focus:outline-none focus:ring-1 focus:ring-primary">
        {agents.map((agent) => (
          <option key={agent.id} value={agent.id}>{normalizeAgentDisplayName(agent.display_name)}</option>
        ))}
      </select>
    </label>
  );
}

function LeadTable({ leads, fields, states, selectedLead, loading, trashed, callingLeadId, canCallWithAI, onSelect, onStatus, onTrash, onRestore, onCall }) {
  const primaryFields = fields.slice(0, 4);
  return (
    <div className={`rounded-xl border bg-card overflow-hidden ${loading ? "opacity-60" : ""}`}>
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse text-sm">
          <thead><tr className="border-b bg-muted/30"><th className="p-4 font-semibold text-muted-foreground">Lead Details</th><th className="p-4 font-semibold text-muted-foreground">Status</th><th className="p-4 font-semibold text-muted-foreground hidden lg:table-cell">{trashed ? "Trash Expiry" : "Created"}</th><th className="p-4 w-10"></th></tr></thead>
          <tbody className="divide-y">
            {leads.length === 0 ? <tr><td colSpan="4" className="p-8 text-center text-muted-foreground">{loading ? "Loading leads..." : "No leads found."}</td></tr> : leads.map((lead) => {
              const values = valuesFrom(lead, fields);
              const state = states.find((s) => s.key === lead.status) || states[0];
              const qualification = lead.qualification_call || {};
              const qualificationStatus = lead.qualification_status || qualification.qualification_status;
              const isJunk = qualification.qualification_category === "junk";
              const scheduledFor = qualification.status === "scheduled" && qualification.scheduled_for;
              return (
                <tr key={lead.id} onClick={() => onSelect(lead)} className={`hover:bg-accent/40 cursor-pointer transition-colors ${selectedLead?.id === lead.id ? "bg-accent/50" : ""}`}>
                  <td className="p-4">
                    <div className="font-semibold text-foreground flex items-center gap-2">{values.full_name || values.phone || values.email || "Unnamed Lead"}{lead.customer_status === "customer" && <span className="text-[10px] uppercase px-1.5 py-0.5 rounded border border-emerald-500/30 text-emerald-500">Customer</span>}{isJunk && <span className="text-[10px] uppercase px-1.5 py-0.5 rounded border border-destructive/30 text-destructive">Junk</span>}{qualificationStatus && <span className={`text-[10px] uppercase px-1.5 py-0.5 rounded border ${qualificationStatus === "qualified" ? "border-emerald-500/30 text-emerald-500" : qualificationStatus === "not_qualified" ? "border-destructive/30 text-destructive" : "border-border text-muted-foreground"}`}>{qualificationStatus.replace("_", " ")}</span>}</div>
                    <div className="grid sm:grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground mt-2">{primaryFields.map((field) => values[field.key] ? <span key={field.key}>{field.label}: {String(values[field.key])}</span> : null)}</div>
                    {scheduledFor && <div className="mt-2 inline-flex items-center gap-1.5 text-[11px] text-primary"><PhoneCall className="w-3 h-3" /> Scheduled {new Date(scheduledFor).toLocaleString()}</div>}
                  </td>
                  <td className="p-4" onClick={(e) => e.stopPropagation()}>
                    {trashed ? (
                      <span className={`px-2.5 py-1 rounded-md border text-xs font-semibold ${stateClasses[state.color] || stateClasses.slate}`}>{state.label}</span>
                    ) : (
                      <select value={lead.status} onChange={(e) => onStatus(lead, e.target.value)} className={`px-2.5 py-1 rounded-md border text-xs font-semibold focus:outline-none ${stateClasses[state.color] || stateClasses.slate}`}>{states.map((s) => <option key={s.key} value={s.key} className="bg-background text-foreground">{s.label}</option>)}</select>
                    )}
                  </td>
                  <td className="p-4 text-xs text-muted-foreground hidden lg:table-cell">{new Date(trashed ? lead.delete_after : lead.created_at).toLocaleDateString()}</td>
                  <td className="p-4 text-right" onClick={(e) => e.stopPropagation()}>
                    {trashed ? (
                      <button onClick={() => onRestore(lead)} className="grid place-items-center w-8 h-8 rounded-lg border bg-background hover:bg-accent text-muted-foreground" title="Restore lead"><RotateCcw className="w-4 h-4" /></button>
                    ) : (
                      <div className="flex items-center justify-end gap-2">
                        <button onClick={() => onCall(lead)} disabled={!values.phone || callingLeadId === lead.id || isJunk || !canCallWithAI} className="grid place-items-center w-8 h-8 rounded-lg border bg-background hover:bg-accent text-muted-foreground disabled:opacity-40" title={isJunk ? "Junk leads cannot be called" : !canCallWithAI ? "Connect an AI agent first" : values.phone ? "Call with AI" : "Phone number required"}>
                          {callingLeadId === lead.id ? <RefreshCw className="w-4 h-4 animate-spin" /> : <PhoneCall className="w-4 h-4" />}
                        </button>
                        <button onClick={() => onTrash(lead)} className="grid place-items-center w-8 h-8 rounded-lg border bg-background hover:bg-destructive/10 text-muted-foreground hover:text-destructive" title="Move lead to trash"><Trash2 className="w-4 h-4" /></button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LeadDetail(props) {
  const { lead, fields, states, values, setValues, setLead, saving, saveLead, conversionType, setConversionType, convertLead, paymentPlan, setPaymentPlan, savePlan, receiptForm, setReceiptForm, createReceipt, createInvoice, addLeadNote, deleteLeadNote, callingLeadId, canCallWithAI, cancellingCallId, callLead, cancelScheduledCall, trashLead, restoreLead, close, wsId, onOpportunityUpdated } = props;
  const [detailTab, setDetailTab] = useState("Details");
  const [activeStageId, setActiveStageId] = useState("");
  const [noteDraft, setNoteDraft] = useState("");
  const isCustomer = lead.customer_status === "customer" || lead.status === "won";
  const isTrashed = Boolean(lead.deleted_at);
  useEffect(() => {
    if (paymentPlan.stages?.[0]?.id && !paymentPlan.stages.some((stage) => stage.id === activeStageId)) setActiveStageId(paymentPlan.stages[0].id);
  }, [activeStageId, paymentPlan.stages]);
  const setField = (key, value) => setValues({ ...values, [key]: value });
  const setStatus = (status) => setLead({ ...lead, status });
  const setTotalAmount = (value) => {
    const stages = (paymentPlan.stages || []).length ? paymentPlan.stages : [{
      id: `new-${Date.now()}`,
      name: "Payment 1",
      amount: "",
      paid_amount: "",
      due_timing: "",
      status: "pending",
      receipt_note: "",
      transaction_id: "",
      payment_date: today(),
      payment_method: "Bank Transfer",
      due_amount: value,
      description: "",
      payment_amount: "",
      source: "system",
    }];
    setPaymentPlan(deriveStageDues({ ...paymentPlan, total_amount: value, stages }));
  };
  const updateStage = (index, key, value) => {
    const stages = paymentPlan.stages.map((stage, i) => i === index ? { ...stage, [key]: value } : stage);
    setPaymentPlan(deriveStageDues({ ...paymentPlan, stages }));
  };
  const updateStagePatch = (index, patch) => {
    const stages = paymentPlan.stages.map((stage, i) => i === index ? { ...stage, ...patch } : stage);
    setPaymentPlan(deriveStageDues({ ...paymentPlan, stages }));
  };
  const addStage = () => {
    const count = (paymentPlan.stages || []).length + 1;
    const remaining = numericAmount(paymentPlan.due_amount || paymentPlan.total_amount);
    const nextStage = { id: `new-${Date.now()}`, name: `Payment ${count}`, amount: "", paid_amount: "", due_timing: "", status: "pending", receipt_note: "", transaction_id: "", payment_date: today(), payment_method: "Bank Transfer", due_amount: String(remaining || ""), description: "", payment_amount: "", source: "manual" };
    const stages = [...paymentPlan.stages, nextStage];
    setActiveStageId(nextStage.id);
    setPaymentPlan(deriveStageDues({ ...paymentPlan, stages }));
  };
  const stageReceipt = (stage) => [...(lead.receipts || [])].reverse().find((receipt) => receipt.stage_id === stage?.id);
  const stageHasReceipt = (stage) => Boolean(stageReceipt(stage));
  const removeStage = (stage, index) => {
    if (stage.source !== "manual" || stageHasReceipt(stage)) return;
    const stages = paymentPlan.stages.filter((_, i) => i !== index);
    const nextActive = stages[Math.min(index, stages.length - 1)] || stages[index - 1] || stages[0];
    setActiveStageId(nextActive?.id || "");
    setPaymentPlan(deriveStageDues({ ...paymentPlan, stages }));
  };
  const currentPlan = lead.payment_plan?.stages ? lead.payment_plan : paymentPlan;
  const planDue = totalDueForLead(lead, currentPlan);
  const planStages = currentPlan.stages || [];
  const allPlanStagesPaid = planStages.length > 0 && planStages.every((stage) => stage.status === "paid");
  const canInvoice = (lead.receipts || []).length > 0 && planDue === 0 && (lead.conversion_type === "single_payment" || allPlanStagesPaid);
  const communication = lead.communication_summary || {};
  const qualification = lead.qualification_call || {};
  const isJunkLead = qualification.qualification_category === "junk";
  const activeStageIndex = Math.max(0, (paymentPlan.stages || []).findIndex((stage) => stage.id === (activeStageId || paymentPlan.stages?.[0]?.id)));
  const activeStage = (paymentPlan.stages || [])[activeStageIndex];
  const stageCount = (paymentPlan.stages || []).length;
  const canAddStage = isCustomer && lead.conversion_type !== "single_payment";
  const activeBalance = stageRemainingAmount(activeStage);
  const activeDueAmount = Math.max(0, planDue - numericAmount(activeStage?.amount));
  const activeStageReceipt = stageReceipt(activeStage);
  const singlePaymentReceipt = [...(lead.receipts || [])].reverse().find((receipt) => !receipt.stage_id);
  const invoiceReceipts = lead.final_invoice?.receipts?.length ? lead.final_invoice.receipts : (lead.receipts || []);
  const updateActiveAmount = (value) => {
    updateStagePatch(activeStageIndex, { amount: value, status: statusForPayment(value, activeBalance).toLowerCase().replaceAll(" ", "_") });
  };
  const makeStageReceipt = async (stage) => {
    const updated = await createReceipt({
      stage_id: stage.id,
      payment_stage: stage.name,
      amount: stage.amount,
      balance_amount: String(activeBalance),
      transaction_id: stage.transaction_id,
      payment_date: stage.payment_date || today(),
      payment_method: stage.payment_method,
      status: titleStatus(stage.status),
      due_amount: String(activeDueAmount),
      description: stage.description || stage.receipt_note,
      payment_plan: paymentPlan,
    });
    const nextStage = updated?.payment_plan?.stages?.find((s) => numericAmount(s.due_amount) > 0);
    if (nextStage?.id) setActiveStageId(nextStage.id);
  };
  const sendNote = async () => {
    const body = noteDraft.trim();
    if (!body) return;
    const updated = await addLeadNote(body);
    if (updated) setNoteDraft("");
  };

  return (
    <aside aria-label="Lead details" className="fixed inset-0 z-50 overflow-y-auto overscroll-contain bg-background p-4 xl:sticky xl:top-4 xl:z-auto xl:max-h-[calc(100dvh-130px)] xl:bg-transparent xl:p-0">
      <div className="p-5 rounded-xl border bg-card space-y-5 max-w-3xl mx-auto xl:max-w-none">
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b pb-4 pt-2 bg-card">
          <div className="min-w-0"><h3 className="font-bold text-lg truncate">{values.full_name || values.phone || values.email || "Unnamed Lead"}</h3><span className="text-xs text-muted-foreground flex items-center gap-1 mt-1"><Calendar className="w-3.5 h-3.5" /> Captured on {new Date(lead.created_at).toLocaleString()}</span></div>
          <div className="flex items-center gap-2">
            {isTrashed ? (
              <button onClick={() => restoreLead(lead)} disabled={saving} className="grid place-items-center w-9 h-9 rounded-lg border bg-background hover:bg-accent text-muted-foreground disabled:opacity-50" title="Restore lead"><RotateCcw className="w-4 h-4" /></button>
            ) : (
              <>
                <button onClick={() => callLead(lead)} disabled={saving || !values.phone || callingLeadId === lead.id || isJunkLead || !canCallWithAI} className="grid place-items-center w-9 h-9 rounded-lg border bg-background hover:bg-accent text-muted-foreground disabled:opacity-50" title={isJunkLead ? "Junk leads cannot be called" : !canCallWithAI ? "Connect an AI agent first" : values.phone ? "Call with AI" : "Phone number required"}>
                  {callingLeadId === lead.id ? <RefreshCw className="w-4 h-4 animate-spin" /> : <PhoneCall className="w-4 h-4" />}
                </button>
                <button onClick={() => trashLead(lead)} disabled={saving} className="grid place-items-center w-9 h-9 rounded-lg border bg-background hover:bg-destructive/10 text-muted-foreground hover:text-destructive disabled:opacity-50" title="Move lead to trash"><Trash2 className="w-4 h-4" /></button>
              </>
            )}
            <button onClick={close} className="p-1 rounded-lg hover:bg-accent text-muted-foreground" title="Close details"><XCircle className="w-5 h-5" /></button>
          </div>
        </div>
        {isTrashed && <div className="rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-xs text-destructive">This lead is in trash and can be restored until {new Date(lead.delete_after).toLocaleDateString()}.</div>}
        <div className="sticky top-[76px] z-10 flex flex-wrap gap-1 rounded-lg border bg-card p-1" role="group" aria-label="Lead sections">
          {DETAIL_TABS.map((tab) => <button key={tab} aria-pressed={detailTab === tab} onClick={() => setDetailTab(tab)} className={`px-3 h-9 rounded-md text-xs font-semibold whitespace-nowrap ${detailTab === tab ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent"}`}>{tab}</button>)}
        </div>
        {detailTab === "Qualification" && <><LeadQualificationPanel key={lead.id} lead={lead} /><QualificationSummary communication={communication} qualification={qualification} saving={saving || cancellingCallId === lead.id} onCancel={() => cancelScheduledCall(lead)} /></>}
        {detailTab === "Reminders" && (isTrashed ? <p className="text-sm text-muted-foreground">Restore this lead to set reminders.</p> : <CrmReminders wsId={wsId} leadId={lead.id} />)}
        {detailTab === "Payments" && !isCustomer && <p className="text-sm text-muted-foreground">Convert this lead to a customer in Details to manage payments.</p>}

        {detailTab === "Details" && (
          <section className="space-y-4">
            <MetaAttribution lead={lead} wsId={wsId} onUpdate={setLead} />
            {!isTrashed && <OpportunitySelector wsId={wsId} lead={lead} onUpdated={onOpportunityUpdated} />}
            <div className="grid sm:grid-cols-2 gap-3">
              {fields.map((field) => <DynamicField key={field.key} field={field} value={values[field.key] || ""} onChange={(v) => setField(field.key, v)} />)}
              <label className="space-y-1.5"><span className="text-xs font-semibold text-muted-foreground uppercase">State</span><select value={lead.status} onChange={(e) => setStatus(e.target.value)} className="w-full h-10 px-3 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary">{states.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</select></label>
            </div>
            <div className="flex flex-wrap gap-2">
              <button onClick={saveLead} disabled={saving} className="inline-flex items-center gap-2 px-3 h-9 rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50"><Save className="w-4 h-4" /> Save CRM</button>
              {!isCustomer && <><select value={conversionType} onChange={(e) => setConversionType(e.target.value)} className="h-9 px-3 rounded-lg border bg-background text-sm"><option value="single_payment">Single Payment</option><option value="payment_plan">Payment Plan</option></select><button onClick={convertLead} disabled={saving} className="inline-flex items-center gap-2 px-3 h-9 rounded-lg border bg-accent hover:bg-accent/80 text-sm font-semibold disabled:opacity-50"><CheckCircle2 className="w-4 h-4" /> Convert Lead</button></>}
            </div>
          </section>
        )}

        {detailTab === "Payments" && isCustomer && lead.conversion_type !== "single_payment" && (
          <section className="space-y-3">
            <div className="flex items-center justify-between gap-3"><h4 className="font-bold flex items-center gap-2"><BadgeIndianRupee className="w-4 h-4 text-primary" /> Payment Stages</h4><button onClick={addStage} disabled={!canAddStage} className="inline-flex items-center gap-1.5 px-2.5 h-8 rounded-lg border bg-background hover:bg-accent text-xs font-semibold disabled:opacity-50"><Plus className="w-3.5 h-3.5" /> Stage</button></div>
            <div className="grid sm:grid-cols-2 gap-2">
              <SmallInput label="Total" value={paymentPlan.total_amount || ""} onChange={setTotalAmount} />
              <ReadOnlyValue label="Balance" value={paymentPlan.due_amount || "0"} />
            </div>
            {(paymentPlan.stages || []).length === 0 ? (
              <div className="text-xs text-muted-foreground p-3 rounded-lg border border-dashed">Enter total amount to start Payment 1.</div>
            ) : (
              <>
                <div className="flex rounded-lg border bg-background p-1 overflow-x-auto">
                  {paymentPlan.stages.map((stage, index) => {
                    const locked = index > 0 && paymentPlan.stages[index - 1]?.status !== "paid";
                    const canRemove = stage.source === "manual" && !stageHasReceipt(stage);
                    return (
                      <div key={stage.id || index} className={`flex items-center rounded-md ${activeStageIndex === index ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent"}`}>
                        <button disabled={locked} onClick={() => setActiveStageId(stage.id)} className="px-3 h-9 text-xs font-semibold whitespace-nowrap disabled:opacity-40">{stage.name || `Stage ${index + 1}`}</button>
                        {stage.source === "manual" && (
                          <button onClick={(e) => { e.stopPropagation(); removeStage(stage, index); }} disabled={!canRemove} title={canRemove ? "Remove stage" : "Stage has receipt history"} className="h-9 w-8 grid place-items-center rounded-md hover:bg-destructive/10 disabled:opacity-40">
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
                {activeStage && (
                  <div className="p-4 rounded-lg border bg-background space-y-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-semibold text-sm">{activeStage.name || `Stage ${activeStageIndex + 1}`}</div>
                      <span className={`px-2 py-1 rounded-md text-[11px] font-semibold uppercase ${activeStage.status === "paid" ? "bg-emerald-500/10 text-emerald-500" : activeStage.status === "partially_paid" ? "bg-amber-500/10 text-amber-500" : "bg-muted text-muted-foreground"}`}>{activeStage.status.replace("_", " ")}</span>
                    </div>
                    <div className="grid sm:grid-cols-2 gap-2">
                      <SmallInput label="Payment Stage" value={activeStage.name} onChange={(v) => updateStage(activeStageIndex, "name", v)} />
                      <SmallInput label="Amount" value={activeStage.amount} onChange={updateActiveAmount} />
                      <DateInput label="Payment Date" value={activeStage.payment_date || ""} onChange={(v) => updateStage(activeStageIndex, "payment_date", v)} />
                      <MethodSelect value={activeStage.payment_method || "Bank Transfer"} onChange={(v) => updateStage(activeStageIndex, "payment_method", v)} />
                      <StatusSelect value={titleStatus(activeStage.status)} onChange={(v) => updateStage(activeStageIndex, "status", v.toLowerCase())} />
                      <ReadOnlyValue label="Due Amount" value={String(activeDueAmount)} />
                      <SmallInput label="Transaction ID" value={activeStage.transaction_id || ""} onChange={(v) => updateStage(activeStageIndex, "transaction_id", v)} />
                    </div>
                    <textarea value={activeStage.description || ""} onChange={(e) => updateStage(activeStageIndex, "description", e.target.value)} placeholder="Transaction description" rows={2} className="w-full px-3 py-2 rounded-lg border bg-background text-sm" />
                    <div className="flex flex-wrap gap-2">
                      <button onClick={() => makeStageReceipt(activeStage)} disabled={saving || activeStage.status === "paid" || (activeStageIndex > 0 && paymentPlan.stages[activeStageIndex - 1]?.status !== "paid") || !numericAmount(activeStage.amount) || numericAmount(activeStage.amount) > activeBalance} className="inline-flex items-center gap-2 px-3 h-9 rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50"><ReceiptText className="w-4 h-4" /> Generate Receipt & Continue</button>
                      {activeStageReceipt && <a href={`${API}/workspaces/${wsId}/crm/leads/${lead.id}/receipts/${activeStageReceipt.id}/html`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 px-3 h-9 rounded-lg border bg-background hover:bg-accent text-sm font-semibold"><ExternalLink className="w-4 h-4" /> Open Receipt</a>}
                      {activeStageReceipt && <a href={receiptDownloadUrl(wsId, lead.id, activeStageReceipt.id)} className="inline-flex items-center gap-2 px-3 h-9 rounded-lg border bg-background hover:bg-accent text-sm font-semibold"><Download className="w-4 h-4" /> Download Receipt</a>}
                    </div>
                  </div>
                )}
              </>
            )}
            <button onClick={savePlan} disabled={saving} className="w-full inline-flex items-center justify-center gap-2 h-9 rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50"><Save className="w-4 h-4" /> Save Payment Plan</button>
          </section>
        )}

        {detailTab === "Payments" && isCustomer && lead.conversion_type === "single_payment" && (
          <section className="space-y-4">
            <h4 className="font-bold flex items-center gap-2"><ReceiptText className="w-4 h-4 text-primary" /> Single Payment Transaction</h4>
            <div className="grid sm:grid-cols-2 gap-2">
              <SmallInput label="Total" value={receiptForm.total_amount} onChange={(v) => setReceiptForm(singleReceiptDraft(receiptForm, { total_amount: v }))} />
              <ReadOnlyValue label="Balance" value={String(Math.max(0, numericAmount(receiptForm.total_amount) - numericAmount(receiptForm.existing_paid)))} />
              <SmallInput label="Payment Stage" value={receiptForm.payment_stage} onChange={(v) => setReceiptForm({ ...receiptForm, payment_stage: v })} />
              <SmallInput label="Amount" value={receiptForm.paid_amount} onChange={(v) => setReceiptForm(singleReceiptDraft(receiptForm, { paid_amount: v }))} />
              <DateInput label="Payment Date" value={receiptForm.payment_date} onChange={(v) => setReceiptForm({ ...receiptForm, payment_date: v })} />
              <MethodSelect value={receiptForm.payment_method} onChange={(v) => setReceiptForm({ ...receiptForm, payment_method: v })} />
              <StatusSelect value={receiptForm.status} onChange={(v) => setReceiptForm({ ...receiptForm, status: v })} />
              <ReadOnlyValue label="Due Amount" value={receiptForm.due_amount || "0"} />
              <SmallInput label="Transaction ID" value={receiptForm.transaction_id} onChange={(v) => setReceiptForm({ ...receiptForm, transaction_id: v })} />
            </div>
            <textarea value={receiptForm.description} onChange={(e) => setReceiptForm({ ...receiptForm, description: e.target.value })} placeholder="Payment description" rows={2} className="w-full px-3 py-2 rounded-lg border bg-background text-sm" />
            <div className="flex flex-wrap gap-2">
              <button onClick={() => createReceipt({ ...receiptForm, amount: receiptForm.paid_amount, payment_stage: "Single Payment" })} disabled={saving || !numericAmount(receiptForm.total_amount) || !numericAmount(receiptForm.paid_amount) || numericAmount(receiptForm.paid_amount) > numericAmount(receiptForm.total_amount) - numericAmount(receiptForm.existing_paid)} className="inline-flex items-center gap-2 px-3 h-9 rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50"><ReceiptText className="w-4 h-4" /> Generate Receipt</button>
              {singlePaymentReceipt && <a href={`${API}/workspaces/${wsId}/crm/leads/${lead.id}/receipts/${singlePaymentReceipt.id}/html`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 px-3 h-9 rounded-lg border bg-background hover:bg-accent text-sm font-semibold"><ExternalLink className="w-4 h-4" /> Open Receipt</a>}
              {singlePaymentReceipt && <a href={receiptDownloadUrl(wsId, lead.id, singlePaymentReceipt.id)} className="inline-flex items-center gap-2 px-3 h-9 rounded-lg border bg-background hover:bg-accent text-sm font-semibold"><Download className="w-4 h-4" /> Download Receipt</a>}
            </div>
          </section>
        )}

        {detailTab === "Receipts" && isCustomer && (
          <section className="space-y-3">
            <h4 className="font-bold flex items-center gap-2"><ReceiptText className="w-4 h-4 text-primary" /> Receipt History</h4>
            <div className="grid gap-2">{(lead.receipts || []).length === 0 ? <div className="text-xs text-muted-foreground p-3 rounded-lg border border-dashed">No payment transactions yet.</div> : (lead.receipts || []).map((receipt) => <div key={receipt.id} className="flex items-center justify-between gap-3 p-3 rounded-lg border bg-background hover:bg-accent text-sm"><a href={`${API}/workspaces/${wsId}/crm/leads/${lead.id}/receipts/${receipt.id}/html`} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate"><span>{receipt.receipt_number} - {receipt.transaction_id || "No transaction ID"} - {receipt.payment_stage}</span></a><div className="flex items-center gap-2"><a href={`${API}/workspaces/${wsId}/crm/leads/${lead.id}/receipts/${receipt.id}/html`} target="_blank" rel="noreferrer" className="grid place-items-center w-8 h-8 rounded-lg border bg-background hover:bg-accent text-muted-foreground" title="Open receipt"><ExternalLink className="w-4 h-4" /></a><a href={receiptDownloadUrl(wsId, lead.id, receipt.id)} className="grid place-items-center w-8 h-8 rounded-lg border bg-background hover:bg-accent text-muted-foreground" title="Download receipt"><Download className="w-4 h-4" /></a></div></div>)}</div>
          </section>
        )}

        {detailTab === "Notes" && (
          <section className="space-y-3">
            <h4 className="font-bold flex items-center gap-2"><MessageSquare className="w-4 h-4 text-primary" /> Lead Notes</h4>
            <div className="h-[360px] overflow-y-auto rounded-lg border bg-background p-3 space-y-3">
              {(lead.lead_notes || []).length === 0 ? (
                <div className="h-full grid place-items-center text-center text-xs text-muted-foreground">No notes yet.</div>
              ) : (lead.lead_notes || []).map((note) => (
                <div key={note.id} className="flex justify-end">
                  <div className="max-w-[86%] rounded-2xl rounded-br-md bg-primary text-primary-foreground px-3 py-2 shadow-sm">
                    {note.source === "call_agent" && (
                      <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[10px] font-semibold uppercase opacity-80">
                        <PhoneCall className="w-3 h-3" />
                        <span>{note.call_provider === "plivo" ? "AI call" : note.call_provider || "call"}</span>
                        {note.call_direction && <span>{note.call_direction}</span>}
                        {note.status && <span>{note.status}</span>}
                        {note.duration && <span>{note.duration}s</span>}
                      </div>
                    )}
                    {note.source === "lead_context_agent" && (
                      <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[10px] font-semibold uppercase opacity-80">
                        <Bot className="w-3 h-3" /><span>Lead Context Agent</span>
                        {note.context_source && <span>{note.context_source.replaceAll("_", " ")}</span>}
                      </div>
                    )}
                    <div className="text-sm whitespace-pre-wrap leading-relaxed">{note.body}</div>
                    <StructuredCallDetails note={note} />
                    {note.recording_url && <a href={note.recording_url} target="_blank" rel="noreferrer" className="mt-1 block text-[10px] underline underline-offset-2 opacity-90">Open recording</a>}
                    <div className="mt-1 flex items-center justify-end gap-2 text-[10px] opacity-80">
                      <span>{note.author}</span>
                      <span>{new Date(note.created_at).toLocaleString()}</span>
                      <button onClick={() => deleteLeadNote(note.id)} disabled={saving} className="opacity-80 hover:opacity-100 disabled:opacity-40" title="Remove note"><Trash2 className="w-3 h-3" /></button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <div className="flex items-end gap-2">
              <textarea value={noteDraft} onChange={(e) => setNoteDraft(e.target.value)} placeholder="Add an internal lead note" rows={3} className="flex-1 px-3 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
              <button onClick={sendNote} disabled={saving || !noteDraft.trim()} className="grid place-items-center w-11 h-11 rounded-full bg-primary text-primary-foreground disabled:opacity-50" title="Send note"><Send className="w-4 h-4" /></button>
            </div>
          </section>
        )}

        {detailTab === "Invoice" && isCustomer && (
          <section className="space-y-3">
            <h4 className="font-bold flex items-center gap-2"><FileText className="w-4 h-4 text-primary" /> Final Invoice</h4>
            <div className="text-xs text-muted-foreground rounded-lg border bg-background p-3">{canInvoice ? "All payment stages are paid. Final invoice can be generated." : "Generate receipts and mark every payment stage paid to enable final invoice."}</div>
            <div className="flex flex-wrap gap-2"><button onClick={createInvoice} disabled={saving || !canInvoice} className="inline-flex items-center gap-2 px-3 h-9 rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50"><FileText className="w-4 h-4" /> Generate Final Invoice</button>{lead.final_invoice?.id && <a href={`${API}/workspaces/${wsId}/crm/leads/${lead.id}/final-invoice/html`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 px-3 h-9 rounded-lg border bg-background hover:bg-accent text-sm font-semibold"><ExternalLink className="w-4 h-4" /> Open Invoice</a>}{lead.final_invoice?.id && <a href={finalInvoiceDownloadUrl(wsId, lead.id)} className="inline-flex items-center gap-2 px-3 h-9 rounded-lg border bg-background hover:bg-accent text-sm font-semibold"><Download className="w-4 h-4" /> Download PDF</a>}</div>
            {lead.final_invoice?.id && (
              <div className="grid gap-2">
                {invoiceReceipts.map((receipt) => (
                  <div key={receipt.id} className="flex items-center justify-between gap-3 p-3 rounded-lg border bg-background text-sm">
                    <span className="min-w-0 flex-1 truncate">{receipt.receipt_number} - {receipt.payment_stage}</span>
                    <a href={receiptDownloadUrl(wsId, lead.id, receipt.id)} className="inline-flex items-center gap-2 px-3 h-8 rounded-lg border bg-background hover:bg-accent text-xs font-semibold"><Download className="w-4 h-4" /> Download Receipt</a>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {detailTab !== "Details" && detailTab !== "Notes" && !isCustomer && <div className="text-xs text-muted-foreground rounded-lg border border-dashed p-4">Convert this lead first to use payments and documents.</div>}
      </div>
    </aside>
  );
}

function listItems(value) {
  if (Array.isArray(value)) return value.filter(Boolean).map(String);
  if (value && typeof value === "object") return Object.entries(value).filter(([, v]) => v != null && String(v).trim()).map(([k, v]) => `${k}: ${v}`);
  if (typeof value === "string" && value.trim()) return value.split(/\r?\n/).map((v) => v.trim()).filter(Boolean);
  return [];
}

function QualificationSummary({ communication, qualification, saving, onCancel }) {
  const hasSummary = communication.latest_summary || qualification.summary || qualification.status || qualification.scheduled_for;
  if (!hasSummary) return null;
  const status = communication.last_call_status || qualification.status || "updated";
  const recording = communication.last_recording_url || qualification.recording_url;
  const callTimestamp = qualification.call_timestamp;
  const category = communication.qualification_category || qualification.qualification_category;
  const qualificationStatus = communication.qualification_status || qualification.qualification_status;
  const score = communication.qualification_score ?? qualification.qualification_score;
  const scheduledFor = qualification.status === "scheduled" && qualification.scheduled_for;
  const categoryClass = category === "hot" ? "border-red-500/30 text-red-500 bg-red-500/10" : category === "warm" ? "border-amber-500/30 text-amber-500 bg-amber-500/10" : category === "cold" ? "border-blue-500/30 text-blue-500 bg-blue-500/10" : category === "junk" ? "border-destructive/30 text-destructive bg-destructive/10" : "border-border text-muted-foreground bg-muted";
  return (
    <section className="rounded-lg border bg-background p-4 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h4 className="font-bold flex items-center gap-2"><PhoneCall className="w-4 h-4 text-primary" /> Qualification</h4>
        <div className="flex flex-wrap justify-end gap-2">
          {category && <span className={`px-2 py-1 rounded-md border text-[11px] font-semibold uppercase ${categoryClass}`}>{category}</span>}
          {qualificationStatus && <span className={`px-2 py-1 rounded-md border text-[11px] font-semibold uppercase ${qualificationStatus === "qualified" ? "border-emerald-500/30 text-emerald-500 bg-emerald-500/10" : qualificationStatus === "not_qualified" ? "border-destructive/30 text-destructive bg-destructive/10" : "border-border text-muted-foreground bg-muted"}`}>{qualificationStatus.replace("_", " ")}</span>}
          {score != null && score !== "" && <span className="px-2 py-1 rounded-md border bg-card text-[11px] font-semibold">{score}%</span>}
          <span className="px-2 py-1 rounded-md border bg-muted text-[11px] font-semibold uppercase text-muted-foreground">{status}</span>
        </div>
      </div>
      {scheduledFor && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-primary/20 bg-primary/5 p-3 text-xs">
          <span className="font-semibold text-primary">Scheduled for {new Date(scheduledFor).toLocaleString()}</span>
          <button onClick={onCancel} disabled={saving} className="inline-flex items-center gap-1.5 px-2.5 h-8 rounded-lg border bg-background hover:bg-accent font-semibold disabled:opacity-50" title="Cancel scheduled call">
            {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Ban className="w-3.5 h-3.5" />}
            Cancel Call
          </button>
        </div>
      )}
      {(communication.latest_summary || qualification.summary) && <p className="text-sm leading-relaxed">{communication.latest_summary || qualification.summary}</p>}
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {communication.total_call_count ? <span>{communication.total_call_count} call{communication.total_call_count === 1 ? "" : "s"} tracked</span> : null}
        {(communication.disconnection_reason || qualification.disconnection_reason) && <span>Reason: {communication.disconnection_reason || qualification.disconnection_reason}</span>}
        {(communication.last_duration || qualification.duration) && <span>{communication.last_duration || qualification.duration}s</span>}
        {callTimestamp && <span>{new Date(callTimestamp).toLocaleString()}</span>}
        {recording && <a href={recording} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 px-2.5 h-8 rounded-lg border bg-card hover:bg-accent text-foreground font-semibold"><ExternalLink className="w-3.5 h-3.5" /> Open recording</a>}
      </div>
    </section>
  );
}

function StructuredCallDetails({ note }) {
  const answers = listItems(note.answers);
  const collected = listItems(note.collected_information);
  const pending = listItems(note.pending_discussion);
  const steps = listItems(note.recommended_next_steps);
  const hasDetails = answers.length || collected.length || pending.length || steps.length || note.transcript;
  if (!hasDetails) return null;
  return (
    <div className="mt-2 space-y-2 rounded-lg bg-primary-foreground/10 p-2 text-[11px] leading-relaxed">
      <InlineDetails label="Answers" items={answers} />
      <InlineDetails label="Collected" items={collected} />
      <InlineDetails label="Pending" items={pending} />
      <InlineDetails label="Next" items={steps} />
      {note.transcript && <details><summary className="cursor-pointer font-semibold">Transcript</summary><div className="mt-1 whitespace-pre-wrap opacity-90">{note.transcript}</div></details>}
    </div>
  );
}

function InlineDetails({ label, items }) {
  if (!items.length) return null;
  return <div><span className="font-semibold">{label}: </span>{items.slice(0, 6).join("; ")}</div>;
}

function CreateLeadDialog({ fields, values, setValues, saving, onCreate, onClose }) {
  const requiredMissing = fields.some((field) => field.required && !String(values[field.key] || "").trim());
  const setField = (key, value) => setValues({ ...values, [key]: value });
  return (
    <div className="fixed inset-0 z-[60] bg-background/80 backdrop-blur-sm p-4 grid place-items-center">
      <div className="w-full max-w-2xl rounded-xl border bg-card shadow-xl">
        <div className="flex items-start justify-between gap-4 p-5 border-b">
          <div>
            <h3 className="font-bold text-lg">Create Lead</h3>
            <p className="text-xs text-muted-foreground mt-1">Add a CRM lead manually using your active field setup.</p>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-accent text-muted-foreground" title="Close"><XCircle className="w-5 h-5" /></button>
        </div>
        <div className="p-5 grid sm:grid-cols-2 gap-3 max-h-[70vh] overflow-y-auto">
          {fields.map((field) => <DynamicField key={field.key} field={field} value={values[field.key] || ""} onChange={(v) => setField(field.key, v)} />)}
        </div>
        <div className="p-5 border-t flex flex-wrap items-center justify-end gap-2">
          <button onClick={onClose} className="px-3 h-9 rounded-lg border bg-background hover:bg-accent text-sm font-semibold">Cancel</button>
          <button onClick={onCreate} disabled={saving || requiredMissing} className="inline-flex items-center gap-2 px-3 h-9 rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50"><Plus className="w-4 h-4" /> Add Lead</button>
        </div>
      </div>
    </div>
  );
}

function DynamicField({ field, value, onChange }) {
  const common = "w-full h-10 px-3 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary";
  const label = <span className="text-xs font-semibold text-muted-foreground uppercase">{field.label}{field.required && <span className="text-destructive"> *</span>}</span>;
  if (field.type === "long_text" || field.type === "json") return <label className="space-y-1.5 sm:col-span-2">{label}<textarea value={value} onChange={(e) => onChange(e.target.value)} rows={3} className="w-full px-3 py-2 rounded-lg border bg-background text-sm" /></label>;
  if (field.type === "boolean") return <label className="space-y-1.5">{label}<select value={value ? "true" : "false"} onChange={(e) => onChange(e.target.value === "true")} className={common}><option value="false">No</option><option value="true">Yes</option></select></label>;
  if (field.type === "select") return <label className="space-y-1.5">{label}<select value={value} onChange={(e) => onChange(e.target.value)} className={common}><option value="">Select</option>{(field.options || []).map((o) => <option key={o} value={o}>{o}</option>)}</select></label>;
  const type = field.type === "email" ? "email" : field.type === "phone" ? "tel" : field.type === "number" || field.type === "currency" ? "number" : field.type === "date" ? "date" : field.type === "datetime" ? "datetime-local" : field.type === "url" ? "url" : "text";
  return <label className="space-y-1.5">{label}<input type={type} value={value} onChange={(e) => onChange(e.target.value)} className={common} /></label>;
}
function SmallInput({ label, value, onChange }) {
  return <label className="space-y-1 block"><span className="text-[11px] font-semibold text-muted-foreground uppercase">{label}</span><input value={value} onChange={(e) => onChange(e.target.value)} className="h-9 px-2 text-xs w-full rounded-lg border bg-background focus:outline-none focus:ring-1 focus:ring-primary" /></label>;
}
function SecretInput({ label, value, onChange }) {
  return <label className="space-y-1 block"><span className="text-[11px] font-semibold text-muted-foreground uppercase">{label}</span><input type="password" value={value} onChange={(e) => onChange(e.target.value)} className="h-9 px-2 text-xs w-full rounded-lg border bg-background focus:outline-none focus:ring-1 focus:ring-primary" autoComplete="new-password" /></label>;
}
function ReadOnlyValue({ label, value }) {
  return <label className="space-y-1 block"><span className="text-[11px] font-semibold text-muted-foreground uppercase">{label}</span><div className="h-9 px-2 rounded-lg border bg-muted/40 text-xs flex items-center">{value}</div></label>;
}
function DateInput({ label, value, onChange }) {
  return <label className="space-y-1 block"><span className="text-[11px] font-semibold text-muted-foreground uppercase">{label}</span><input type="date" value={value} onChange={(e) => onChange(e.target.value)} className="h-9 px-2 text-xs w-full rounded-lg border bg-background focus:outline-none focus:ring-1 focus:ring-primary" /></label>;
}
function MethodSelect({ value, onChange }) {
  return (
    <label className="space-y-1 block">
      <span className="text-[11px] font-semibold text-muted-foreground uppercase">Payment Method</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="h-9 px-2 text-xs w-full rounded-lg border bg-background focus:outline-none focus:ring-1 focus:ring-primary">
        {PAYMENT_METHODS.map((method) => <option key={method} value={method}>{method}</option>)}
      </select>
    </label>
  );
}
function StatusSelect({ value, onChange }) {
  return (
    <label className="space-y-1 block">
      <span className="text-[11px] font-semibold text-muted-foreground uppercase">Status</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="h-9 px-2 text-xs w-full rounded-lg border bg-background focus:outline-none focus:ring-1 focus:ring-primary">
        {PAYMENT_STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
      </select>
    </label>
  );
}

function agentDraftFrom(agent) {
  if (!agent) return { ...EMPTY_AGENT_DRAFT };
  return {
    ...EMPTY_AGENT_DRAFT,
    id: agent.id,
    display_name: agent.display_name || "",
    flow_id: agent.flow_id || agent.provider_agent_id || "",
    trigger_url: agent.trigger_url || "",
    auth_type: agent.auth_type || "basic",
    from_number: agent.from_number || agent.authorized_calling_number || "",
    qualification_config_id: agent.qualification_config_id || "indian_real_estate_v1",
    enabled: agent.enabled !== false,
    is_default: Boolean(agent.is_default),
    input_variable_mappings_text: JSON.stringify(agent.input_variable_mappings || JSON.parse(DEFAULT_AGENT_MAPPINGS_TEXT), null, 2),
    extra_payload_text: JSON.stringify(agent.extra_payload || {}, null, 2)
  };
}

function PlivoAgentsPanel({ agents, selectedAgentId, onSave, onSelect, onToggle, saving }) {
  const [draft, setDraft] = useState({ ...EMPTY_AGENT_DRAFT });
  const editingStored = draft.id && draft.id !== "environment";
  const setField = (key, value) => setDraft((current) => ({ ...current, [key]: value }));
  const editAgent = (agent) => setDraft(agentDraftFrom(agent));
  const newAgent = () => setDraft({ ...EMPTY_AGENT_DRAFT });
  const submit = async () => {
    const saved = await onSave(draft);
    if (saved && !editingStored) newAgent();
  };
  return (
    <section className="rounded-xl border bg-card p-5 space-y-4 xl:col-span-2">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <h3 className="font-bold flex items-center gap-2"><Bot className="w-4 h-4 text-primary" /> AI Voice Agents</h3>
        <button onClick={newAgent} className="inline-flex items-center gap-2 px-3 h-9 rounded-lg border bg-background hover:bg-accent text-sm font-semibold"><Plus className="w-4 h-4" /> New Agent</button>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(340px,0.9fr)]">
        <div className="space-y-2">
          {agents.length === 0 ? (
            <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">No AI agents connected.</div>
          ) : agents.map((agent) => {
            const ready = agent.readiness?.ready !== false;
            const missing = agent.readiness?.missing || [];
            const active = selectedAgentId === agent.id || agent.is_default;
            return (
              <div key={agent.id} className="rounded-lg border bg-background p-3 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold truncate">{normalizeAgentDisplayName(agent.display_name)}</span>
                      {active && <span className="inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase text-primary"><Star className="w-3 h-3" /> Default</span>}
                      {agent.legacy_environment && <span className="rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase text-muted-foreground">Env</span>}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground truncate">{agent.flow_id || "No flow ID"} - {agent.from_number || "No number"}</div>
                  </div>
                  <span className={`rounded-md border px-2 py-1 text-[10px] font-semibold uppercase ${agent.enabled === false ? "bg-muted text-muted-foreground" : ready ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-500" : "border-destructive/30 bg-destructive/10 text-destructive"}`}>
                    {agent.enabled === false ? "Disabled" : ready ? "Ready" : "Missing"}
                  </span>
                </div>
                {!ready && missing.length > 0 && <div className="text-xs text-destructive">Missing: {missing.join(", ")}</div>}
                <div className="flex flex-wrap gap-2">
                  <button onClick={() => onSelect(agent)} disabled={!ready || agent.enabled === false || saving} className="inline-flex items-center gap-1.5 px-2.5 h-8 rounded-lg border bg-card hover:bg-accent text-xs font-semibold disabled:opacity-40"><Star className="w-3.5 h-3.5" /> Select</button>
                  {!agent.legacy_environment && <button onClick={() => editAgent(agent)} className="inline-flex items-center gap-1.5 px-2.5 h-8 rounded-lg border bg-card hover:bg-accent text-xs font-semibold"><Settings className="w-3.5 h-3.5" /> Edit</button>}
                  {!agent.legacy_environment && <button onClick={() => onToggle(agent)} disabled={saving} className="inline-flex items-center gap-1.5 px-2.5 h-8 rounded-lg border bg-card hover:bg-accent text-xs font-semibold disabled:opacity-40"><Power className="w-3.5 h-3.5" /> {agent.enabled === false ? "Enable" : "Disable"}</button>}
                </div>
              </div>
            );
          })}
        </div>
        <div className="rounded-lg border bg-background p-4 space-y-3">
          <div className="grid sm:grid-cols-2 gap-3">
            <SmallInput label="Display Name" value={draft.display_name} onChange={(v) => setField("display_name", v)} />
            <SmallInput label="Flow ID" value={draft.flow_id} onChange={(v) => setField("flow_id", v)} />
            <label className="space-y-1 block sm:col-span-2">
              <span className="text-[11px] font-semibold text-muted-foreground uppercase">Trigger URL</span>
              <input value={draft.trigger_url} onChange={(e) => setField("trigger_url", e.target.value)} className="h-9 px-2 text-xs w-full rounded-lg border bg-background focus:outline-none focus:ring-1 focus:ring-primary" />
            </label>
            <SmallInput label="From Number" value={draft.from_number} onChange={(v) => setField("from_number", v)} />
            <SmallInput label="Qualification Config" value={draft.qualification_config_id} onChange={(v) => setField("qualification_config_id", v)} />
            <label className="space-y-1 block">
              <span className="text-[11px] font-semibold text-muted-foreground uppercase">Auth</span>
              <select value={draft.auth_type} onChange={(e) => setField("auth_type", e.target.value)} className="h-9 px-2 text-xs w-full rounded-lg border bg-background focus:outline-none focus:ring-1 focus:ring-primary">
                <option value="basic">Basic</option>
                <option value="bearer">Bearer</option>
                <option value="none">None</option>
              </select>
            </label>
            <label className="flex items-center gap-2 pt-6 text-xs font-semibold text-muted-foreground"><input type="checkbox" checked={draft.enabled} onChange={(e) => setField("enabled", e.target.checked)} /> Enabled</label>
            {draft.auth_type === "basic" && (
              <>
                <SmallInput label="Auth ID" value={draft.auth_username} onChange={(v) => setField("auth_username", v)} />
                <SecretInput label={editingStored ? "New Auth Token" : "Auth Token"} value={draft.auth_password} onChange={(v) => setField("auth_password", v)} />
              </>
            )}
            {draft.auth_type === "bearer" && <SecretInput label={editingStored ? "New Bearer Token" : "Bearer Token"} value={draft.bearer_token} onChange={(v) => setField("bearer_token", v)} />}
            <label className="flex items-center gap-2 text-xs font-semibold text-muted-foreground"><input type="checkbox" checked={draft.is_default} onChange={(e) => setField("is_default", e.target.checked)} /> Default agent</label>
          </div>
          <label className="space-y-1 block">
            <span className="text-[11px] font-semibold text-muted-foreground uppercase">Input Variable Mappings</span>
            <textarea value={draft.input_variable_mappings_text} onChange={(e) => setField("input_variable_mappings_text", e.target.value)} rows={9} className="w-full px-3 py-2 rounded-lg border bg-background text-xs font-mono focus:outline-none focus:ring-1 focus:ring-primary" />
          </label>
          <label className="space-y-1 block">
            <span className="text-[11px] font-semibold text-muted-foreground uppercase">Extra Payload</span>
            <textarea value={draft.extra_payload_text} onChange={(e) => setField("extra_payload_text", e.target.value)} rows={3} className="w-full px-3 py-2 rounded-lg border bg-background text-xs font-mono focus:outline-none focus:ring-1 focus:ring-primary" />
          </label>
          <div className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"><KeyRound className="w-3.5 h-3.5" /> Legacy agent credentials must be migrated to workspace Voice Provider settings.</div>
          <button onClick={submit} disabled={saving || !draft.display_name.trim() || !draft.trigger_url.trim() || !draft.from_number.trim()} className="inline-flex items-center gap-2 px-3 h-9 rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50"><Save className="w-4 h-4" /> {editingStored ? "Save Agent" : "Connect Agent"}</button>
        </div>
      </div>
    </section>
  );
}

function SettingsPanel({ fields, states, organization, templates, plivoAgents, selectedAgentId, newField, setNewField, newState, setNewState, templateDraft, setTemplateDraft, addField, updateField, removeField, addState, saveStates, saveOrganization, saveTemplate, savePlivoAgent, selectPlivoAgent, togglePlivoAgent, saving }) {
  const [org, setOrg] = useState(organization);
  const [fieldDrafts, setFieldDrafts] = useState({});
  const [stateDrafts, setStateDrafts] = useState({});
  const [savingFieldKey, setSavingFieldKey] = useState("");
  const [savingStateKey, setSavingStateKey] = useState("");

  useEffect(() => setOrg(organization), [organization]);

  useEffect(() => {
    setFieldDrafts(fields.reduce((acc, field) => ({
      ...acc,
      [field.key]: {
        label: field.label || "",
        type: field.type || "text",
        required: Boolean(field.required),
      },
    }), {}));
  }, [fields]);

  useEffect(() => {
    setStateDrafts(states.reduce((acc, state) => ({
      ...acc,
      [state.key]: {
        label: state.label || "",
        color: state.color || "blue",
      },
    }), {}));
  }, [states]);

  const fieldDraft = (field) => fieldDrafts[field.key] || {
    label: field.label || "",
    type: field.type || "text",
    required: Boolean(field.required),
  };

  const setFieldDraft = (field, patch) => {
    setFieldDrafts((current) => ({
      ...current,
      [field.key]: { ...fieldDraft(field), ...patch },
    }));
  };

  const fieldHasChanges = (field) => {
    const draft = fieldDraft(field);
    return draft.label !== (field.label || "") || draft.type !== (field.type || "text") || draft.required !== Boolean(field.required);
  };

  const stateDraft = (state) => stateDrafts[state.key] || {
    label: state.label || "",
    color: state.color || "blue",
  };

  const setStateDraft = (state, patch) => {
    setStateDrafts((current) => ({
      ...current,
      [state.key]: { ...stateDraft(state), ...patch },
    }));
  };

  const stateHasChanges = (state) => {
    const draft = stateDraft(state);
    return draft.label !== (state.label || "") || draft.color !== (state.color || "blue");
  };

  const saveFieldDraft = async (field) => {
    const draft = fieldDraft(field);
    try {
      setSavingFieldKey(field.key);
      await updateField(field, draft);
      toast.success("Field saved");
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setSavingFieldKey("");
    }
  };

  const saveStateDraft = async (state) => {
    const draft = stateDraft(state);
    try {
      setSavingStateKey(state.key);
      await saveStates(states.map((s) => s.key === state.key ? { ...s, ...draft } : s));
      toast.success("State saved");
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setSavingStateKey("");
    }
  };

  return (
    <div className="grid gap-6 xl:grid-cols-2 items-start">
      <QualificationSettingsLink />

      <section className="rounded-xl border bg-card p-5 space-y-4">
        <h3 className="font-bold flex items-center gap-2"><Columns3 className="w-4 h-4 text-primary" /> Field Columns</h3>
        <div className="space-y-2">{fields.map((field) => {
          const draft = fieldDraft(field);
          const dirty = fieldHasChanges(field);
          return (
            <div key={field.key} className="grid grid-cols-[1fr_130px_70px_84px_36px] gap-2 items-center p-2 rounded-lg border bg-background">
              <input value={draft.label} onChange={(e) => setFieldDraft(field, { label: e.target.value })} className="h-9 px-2 rounded border bg-background text-sm" />
              <select value={draft.type} disabled={field.key === "phone"} onChange={(e) => setFieldDraft(field, { type: e.target.value })} className="h-9 px-2 rounded border bg-background text-xs">{FIELD_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}</select>
              <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={draft.required} disabled={field.key === "phone"} onChange={(e) => setFieldDraft(field, { required: e.target.checked })} /> Req</label>
              <button onClick={() => saveFieldDraft(field)} disabled={!dirty || savingFieldKey === field.key || !draft.label.trim()} className="inline-flex items-center justify-center gap-1 h-9 rounded border hover:bg-accent text-xs font-semibold disabled:opacity-40" title="Save field"><Save className="w-3.5 h-3.5" /> Save</button>
              <button onClick={() => removeField(field)} disabled={field.key === "phone"} className="h-9 rounded border hover:bg-accent disabled:opacity-40" title="Remove field"><Trash2 className="w-4 h-4 mx-auto" /></button>
            </div>
          );
        })}</div>
        <div className="grid grid-cols-[1fr_130px_80px] gap-2 border-t pt-4"><input placeholder="Field label" value={newField.label} onChange={(e) => setNewField({ ...newField, label: e.target.value })} className="h-10 px-3 rounded-lg border bg-background text-sm" /><select value={newField.type} onChange={(e) => setNewField({ ...newField, type: e.target.value })} className="h-10 px-2 rounded-lg border bg-background text-xs">{FIELD_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}</select><button onClick={addField} disabled={!newField.label.trim()} className="inline-flex items-center justify-center gap-1 h-10 rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50"><Plus className="w-4 h-4" /> Add</button></div>
      </section>
      <section className="rounded-xl border bg-card p-5 space-y-4">
        <h3 className="font-bold flex items-center gap-2"><Palette className="w-4 h-4 text-primary" /> Lead States</h3>
        <div className="space-y-2">{states.map((state, index) => {
          const draft = stateDraft(state);
          const dirty = stateHasChanges(state);
          return (
            <div key={state.key} className="grid grid-cols-[1fr_110px_84px_36px] gap-2 items-center p-2 rounded-lg border bg-background">
              <input value={draft.label} onChange={(e) => setStateDraft(state, { label: e.target.value })} className="h-9 px-2 rounded border bg-background text-sm" />
              <select value={draft.color} onChange={(e) => setStateDraft(state, { color: e.target.value })} className="h-9 px-2 rounded border bg-background text-xs">{Object.keys(stateClasses).map((color) => <option key={color} value={color}>{color}</option>)}</select>
              <button onClick={() => saveStateDraft(state)} disabled={!dirty || savingStateKey === state.key || !draft.label.trim()} className="inline-flex items-center justify-center gap-1 h-9 rounded border hover:bg-accent text-xs font-semibold disabled:opacity-40" title="Save state"><Save className="w-3.5 h-3.5" /> Save</button>
              <span className="text-xs text-muted-foreground text-center">{index + 1}</span>
            </div>
          );
        })}</div>
        <div className="grid grid-cols-[1fr_110px_80px] gap-2 border-t pt-4"><input placeholder="State label" value={newState.label} onChange={(e) => setNewState({ ...newState, label: e.target.value })} className="h-10 px-3 rounded-lg border bg-background text-sm" /><select value={newState.color} onChange={(e) => setNewState({ ...newState, color: e.target.value })} className="h-10 px-2 rounded-lg border bg-background text-xs">{Object.keys(stateClasses).map((color) => <option key={color} value={color}>{color}</option>)}</select><button onClick={addState} disabled={!newState.label.trim()} className="inline-flex items-center justify-center gap-1 h-10 rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50"><Plus className="w-4 h-4" /> Add</button></div>
      </section>
      <section className="rounded-xl border bg-card p-5 space-y-4 xl:col-span-2">
        <h3 className="font-bold flex items-center gap-2"><Building2 className="w-4 h-4 text-primary" /> Organization Details</h3>
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-3">{ORG_FIELDS.map((key) => <SmallInput key={key} label={key.replaceAll("_", " ")} value={org[key] || ""} onChange={(v) => setOrg({ ...org, [key]: v })} />)}</div>
        <button onClick={() => saveOrganization(org)} className="inline-flex items-center gap-2 px-3 h-9 rounded-lg bg-primary text-primary-foreground text-sm font-semibold"><Save className="w-4 h-4" /> Save Organization</button>
      </section>
      <section className="rounded-xl border bg-card p-5 space-y-4 xl:col-span-2">
        <h3 className="font-bold flex items-center gap-2"><FileCode2 className="w-4 h-4 text-primary" /> HTML Templates</h3>
        <div className="grid lg:grid-cols-3 gap-3"><input value={templateDraft.name} onChange={(e) => setTemplateDraft({ ...templateDraft, name: e.target.value })} className="h-10 px-3 rounded-lg border bg-background text-sm" /><input value={templateDraft.button_label} onChange={(e) => setTemplateDraft({ ...templateDraft, button_label: e.target.value })} className="h-10 px-3 rounded-lg border bg-background text-sm" /><button onClick={saveTemplate} className="h-10 rounded-lg bg-primary text-primary-foreground text-sm font-semibold">Save Template</button></div>
        <textarea value={templateDraft.html} onChange={(e) => setTemplateDraft({ ...templateDraft, html: e.target.value })} rows={8} className="w-full px-3 py-2 rounded-lg border bg-background text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary" />
        <div className="text-xs text-muted-foreground">Placeholders: {fields.filter((f) => f.active !== false).slice(0, 8).map((f) => `{{${f.key}}}`).join(" ")} {"{{payment_plan.stages}}"}</div>
        <div className="flex flex-wrap gap-2">{templates.map((template) => <button key={template.id} onClick={() => setTemplateDraft(template)} className="px-3 h-8 rounded-lg border bg-background hover:bg-accent text-xs font-semibold">{template.button_label}</button>)}</div>
      </section>
    </div>
  );
}

function QualificationSettingsLink() {
  const { wsId } = useParams();
  return <section className="rounded-xl border bg-card p-5 space-y-3"><h3 className="font-bold">Lead qualification</h3><p className="text-sm text-muted-foreground">Configure product rules, scoring, next actions and retries. Results appear inside each lead.</p><Link className="inline-block text-sm text-primary" to={`/app/w/${wsId}/qualification`}>Open qualification profiles</Link><Link className="block text-sm text-primary" to={`/app/w/${wsId}/settings`}>Configure voice providers</Link></section>;
}
