import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Users, Calendar, Info, Search, XCircle, Save, BadgeIndianRupee,
  Plus, CheckCircle2, Settings, Trash2, Columns3, Palette, Building2,
  ReceiptText, FileText, ExternalLink, RefreshCw, FileCode2, MessageSquare, Send,
  Download, RotateCcw
} from "lucide-react";
import { toast } from "sonner";
import api, { API, formatError } from "../../lib/api";

const FIELD_TYPES = ["text", "long_text", "email", "phone", "number", "currency", "date", "datetime", "boolean", "select", "multi_select", "url", "json"];
const DEFAULT_STAGES = [];
const PAYMENT_METHODS = ["Cash", "Bank Transfer", "UPI", "Cheque", "Card", "Other"];
const PAYMENT_STATUSES = ["Paid", "Pending"];
const ORG_FIELDS = ["company_name", "logo_url", "address", "phone", "email", "website", "tax_number", "bank_details", "authorized_signatory", "receipt_prefix", "invoice_prefix"];
const DETAIL_TABS = ["Details", "Payments", "Receipts", "Invoice", "Notes"];
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
  const [activeTab, setActiveTab] = useState("records");
  const [recordView, setRecordView] = useState("active");
  const [leads, setLeads] = useState([]);
  const [settings, setSettings] = useState({ fields: [], states: [], templates: [], organization: {} });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState({ total: 0, page: 1, limit: 10 });
  const [selectedLead, setSelectedLead] = useState(null);
  const [fieldValues, setFieldValues] = useState({});
  const [showCreateLead, setShowCreateLead] = useState(false);
  const [createValues, setCreateValues] = useState({});
  const [paymentPlan, setPaymentPlan] = useState(planFrom(null));
  const [conversionType, setConversionType] = useState("single_payment");
  const [receiptForm, setReceiptForm] = useState({ payment_stage: "Single Payment", total_amount: "", existing_paid: "", paid_amount: "", amount: "", transaction_id: "", payment_date: today(), payment_method: "Bank Transfer", status: "Pending", due_amount: "0", description: "" });
  const [newField, setNewField] = useState({ label: "", key: "", type: "text", required: false, options: [] });
  const [newState, setNewState] = useState({ label: "", key: "", color: "blue" });
  const [templateDraft, setTemplateDraft] = useState({ name: "Receipt", type: "receipt", button_label: "Download Receipt", active: true, html: "<h1>Receipt</h1><p>{{full_name}}</p><p>{{email}}</p><table>{{payment_plan.stages}}</table>" });

  const activeFields = useMemo(() => (settings.fields || []).filter((field) => field.active !== false), [settings.fields]);
  const states = settings.states?.length ? settings.states : [{ key: "new", label: "New", color: "blue" }];
  const totalPages = Math.max(1, Math.ceil((pagination.total || 0) / pagination.limit));

  const selectLead = (lead) => {
    setSelectedLead(lead);
    setFieldValues(valuesFrom(lead, activeFields));
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

  const openCreateLead = () => {
    setCreateValues(emptyValues(activeFields));
    setShowCreateLead(true);
  };

  const loadAll = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams({ page: String(page), limit: "10" });
      if (statusFilter !== "all") params.set("status", statusFilter);
      if (searchQuery.trim()) params.set("search", searchQuery.trim());
      if (recordView === "trash") params.set("trashed", "true");
      const [settingsRes, leadsRes] = await Promise.all([
        api.get(`/workspaces/${wsId}/crm/settings`),
        api.get(`/workspaces/${wsId}/crm/leads?${params.toString()}`)
      ]);
      setSettings(settingsRes.data);
      setLeads(leadsRes.data.items || []);
      setPagination({ total: leadsRes.data.total || 0, page: leadsRes.data.page || page, limit: leadsRes.data.limit || 10 });
      if (selectedLead && !(leadsRes.data.items || []).some((lead) => lead.id === selectedLead.id)) setSelectedLead(null);
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const t = setTimeout(loadAll, 200);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId, statusFilter, page, searchQuery, recordView]);

  const mergeLead = (updated) => {
    setLeads((prev) => prev.map((lead) => lead.id === updated.id ? updated : lead));
    selectLead(updated);
  };

  const createLead = async () => {
    try {
      setSaving(true);
      const r = await api.post(`/workspaces/${wsId}/crm/leads`, { field_values: createValues });
      toast.success("Lead created");
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

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2"><Users className="w-6 h-6 text-primary" /> CRM Leads</h1>
          <p className="text-sm text-muted-foreground mt-1">Manage records, states, organization details, receipts, and invoices.</p>
        </div>
        <div className="flex rounded-lg border bg-card p-1 w-fit">
          <TabButton active={activeTab === "records"} onClick={() => setActiveTab("records")} icon={Users} label="Records" />
          <TabButton active={activeTab === "settings"} onClick={() => setActiveTab("settings")} icon={Settings} label="Settings" />
        </div>
      </div>

      {activeTab === "settings" ? (
        <SettingsPanel
          fields={settings.fields || []}
          states={states}
          organization={settings.organization || {}}
          templates={settings.templates || []}
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
        />
      ) : (
        <>
          <div className="flex flex-col sm:flex-row gap-3 items-center justify-between">
            <div className="flex flex-wrap gap-1.5 w-full sm:w-auto">
              <FilterButton active={recordView === "active" && statusFilter === "all"} onClick={() => { setRecordView("active"); setStatusFilter("all"); setPage(1); }}>All Leads</FilterButton>
              {states.map((state) => <FilterButton key={state.key} active={recordView === "active" && statusFilter === state.key} onClick={() => { setRecordView("active"); setStatusFilter(state.key); setPage(1); }}>{state.label}</FilterButton>)}
              <FilterButton active={recordView === "trash"} onClick={() => { setRecordView("trash"); setStatusFilter("all"); setPage(1); }}><Trash2 className="w-3.5 h-3.5" /> Trash</FilterButton>
            </div>
            <div className="flex gap-2 w-full sm:w-auto">
              <button onClick={openCreateLead} className="inline-flex items-center gap-2 px-3 h-10 rounded-lg bg-primary text-primary-foreground text-sm font-semibold whitespace-nowrap"><Plus className="w-4 h-4" /> New Lead</button>
              <div className="relative flex-1 sm:w-72">
                <Search className="absolute left-3 top-3 w-4 h-4 text-muted-foreground" />
                <input value={searchQuery} onChange={(e) => { setSearchQuery(e.target.value); setPage(1); }} placeholder={recordView === "trash" ? "Search trash..." : "Search leads..."} className="w-full pl-9 pr-4 h-10 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
              </div>
            </div>
          </div>

          <div className={`grid gap-6 items-start ${selectedLead ? "xl:grid-cols-[minmax(0,1fr)_560px]" : "grid-cols-1"}`}>
            <div className="space-y-3">
              <LeadTable leads={leads} fields={activeFields} states={states} selectedLead={selectedLead} loading={loading} trashed={recordView === "trash"} onSelect={selectLead} onStatus={changeStatus} onTrash={trashLead} onRestore={restoreLead} />
              <Pagination page={page} totalPages={totalPages} total={pagination.total} onPage={setPage} />
            </div>
            {selectedLead && (
              <LeadDetail
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
                trashLead={trashLead}
                restoreLead={restoreLead}
                close={() => setSelectedLead(null)}
                wsId={wsId}
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

function LeadTable({ leads, fields, states, selectedLead, loading, trashed, onSelect, onStatus, onTrash, onRestore }) {
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
              return (
                <tr key={lead.id} onClick={() => onSelect(lead)} className={`hover:bg-accent/40 cursor-pointer transition-colors ${selectedLead?.id === lead.id ? "bg-accent/50" : ""}`}>
                  <td className="p-4">
                    <div className="font-semibold text-foreground flex items-center gap-2">{values.full_name || values.phone || values.email || "Unnamed Lead"}{lead.customer_status === "customer" && <span className="text-[10px] uppercase px-1.5 py-0.5 rounded border border-emerald-500/30 text-emerald-500">Customer</span>}</div>
                    <div className="grid sm:grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground mt-2">{primaryFields.map((field) => values[field.key] ? <span key={field.key}>{field.label}: {String(values[field.key])}</span> : null)}</div>
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
                      <button onClick={() => onTrash(lead)} className="grid place-items-center w-8 h-8 rounded-lg border bg-background hover:bg-destructive/10 text-muted-foreground hover:text-destructive" title="Move lead to trash"><Trash2 className="w-4 h-4" /></button>
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
  const { lead, fields, states, values, setValues, setLead, saving, saveLead, conversionType, setConversionType, convertLead, paymentPlan, setPaymentPlan, savePlan, receiptForm, setReceiptForm, createReceipt, createInvoice, addLeadNote, deleteLeadNote, trashLead, restoreLead, close, wsId } = props;
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
    <aside className="fixed inset-0 z-50 overflow-y-auto bg-background p-4 xl:static xl:z-auto xl:bg-transparent xl:p-0">
      <div className="p-5 rounded-xl border bg-card space-y-5 max-w-3xl mx-auto xl:max-w-none">
        <div className="flex items-start justify-between border-b pb-4">
          <div className="min-w-0"><h3 className="font-bold text-lg truncate">{values.full_name || values.phone || values.email || "Unnamed Lead"}</h3><span className="text-xs text-muted-foreground flex items-center gap-1 mt-1"><Calendar className="w-3.5 h-3.5" /> Captured on {new Date(lead.created_at).toLocaleString()}</span></div>
          <div className="flex items-center gap-2">
            {isTrashed ? (
              <button onClick={() => restoreLead(lead)} disabled={saving} className="grid place-items-center w-9 h-9 rounded-lg border bg-background hover:bg-accent text-muted-foreground disabled:opacity-50" title="Restore lead"><RotateCcw className="w-4 h-4" /></button>
            ) : (
              <button onClick={() => trashLead(lead)} disabled={saving} className="grid place-items-center w-9 h-9 rounded-lg border bg-background hover:bg-destructive/10 text-muted-foreground hover:text-destructive disabled:opacity-50" title="Move lead to trash"><Trash2 className="w-4 h-4" /></button>
            )}
            <button onClick={close} className="p-1 rounded-lg hover:bg-accent text-muted-foreground" title="Close details"><XCircle className="w-5 h-5" /></button>
          </div>
        </div>
        {isTrashed && <div className="rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-xs text-destructive">This lead is in trash and can be restored until {new Date(lead.delete_after).toLocaleDateString()}.</div>}
        <div className="flex rounded-lg border bg-background p-1 overflow-x-auto">
          {DETAIL_TABS.map((tab) => <button key={tab} onClick={() => setDetailTab(tab)} className={`px-3 h-9 rounded-md text-sm font-semibold whitespace-nowrap ${detailTab === tab ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent"}`}>{tab}</button>)}
        </div>

        {detailTab === "Details" && (
          <section className="space-y-4">
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
                    <div className="text-sm whitespace-pre-wrap leading-relaxed">{note.body}</div>
                    <div className="mt-1 flex items-center justify-end gap-2 text-[10px] opacity-80">
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

function SettingsPanel({ fields, states, organization, templates, newField, setNewField, newState, setNewState, templateDraft, setTemplateDraft, addField, updateField, removeField, addState, saveStates, saveOrganization, saveTemplate }) {
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
