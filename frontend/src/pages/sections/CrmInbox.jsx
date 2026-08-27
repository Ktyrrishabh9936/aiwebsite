import { useEffect, useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import { 
  Users, Mail, Phone, Calendar, Info, RefreshCw, 
  Search, ShieldAlert, CheckCircle2, ChevronRight, XCircle
} from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../../lib/api";

const STATUS_OPTIONS = [
  { value: "new", label: "New", color: "bg-blue-500/10 text-blue-500 border-blue-500/20" },
  { value: "contacted", label: "Contacted", color: "bg-amber-500/10 text-amber-500 border-amber-500/20" },
  { value: "won", label: "Won", color: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20" },
  { value: "lost", label: "Lost", color: "bg-destructive/10 text-destructive border-destructive/20" }
];

export default function CrmInbox() {
  const { wsId } = useParams();
  const [leads, setLeads] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedLead, setSelectedLead] = useState(null);

  const fetchLeads = useCallback(async () => {
    try {
      setLoading(true);
      const url = statusFilter === "all" 
        ? `/workspaces/${wsId}/crm/leads` 
        : `/workspaces/${wsId}/crm/leads?status=${statusFilter}`;
      const r = await api.get(url);
      setLeads(r.data);
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  }, [wsId, statusFilter]);

  useEffect(() => {
    fetchLeads();
  }, [fetchLeads]);

  const handleStatusChange = async (leadId, newStatus) => {
    try {
      await api.patch(`/workspaces/${wsId}/crm/leads/${leadId}`, { status: newStatus });
      toast.success("Lead status updated");
      setLeads(prev => prev.map(l => l.id === leadId ? { ...l, status: newStatus } : l));
      if (selectedLead && selectedLead.id === leadId) {
        setSelectedLead(prev => ({ ...prev, status: newStatus }));
      }
    } catch (e) {
      toast.error(formatError(e.response?.data?.detail));
    }
  };

  const filteredLeads = leads.filter(lead => {
    const term = searchQuery.toLowerCase();
    const nameMatch = (lead.full_name || "").toLowerCase().includes(term);
    const emailMatch = (lead.email || "").toLowerCase().includes(term);
    const phoneMatch = (lead.phone || "").toLowerCase().includes(term);
    return nameMatch || emailMatch || phoneMatch;
  });

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Users className="w-6 h-6 text-primary" /> Lead Inbox
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Manage and nurture inbound leads collected from your spreadsheets.
          </p>
        </div>
        <button
          onClick={fetchLeads}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border bg-card hover:bg-accent text-sm font-medium transition self-start sm:self-auto"
        >
          <RefreshCw className="w-3.5 h-3.5" /> Refresh
        </button>
      </div>

      {/* Filters & Search */}
      <div className="flex flex-col sm:flex-row gap-3 items-center justify-between">
        <div className="flex flex-wrap gap-1.5 w-full sm:w-auto">
          <button
            onClick={() => setStatusFilter("all")}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition ${
              statusFilter === "all" ? "bg-primary text-primary-foreground border-primary" : "bg-card text-muted-foreground hover:bg-accent"
            }`}
          >
            All Leads
          </button>
          {STATUS_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setStatusFilter(opt.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition ${
                statusFilter === opt.value ? "bg-primary text-primary-foreground border-primary" : "bg-card text-muted-foreground hover:bg-accent"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <div className="relative w-full sm:w-64">
          <Search className="absolute left-3 top-2.5 w-4 h-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search leads..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3 items-start">
        {/* Table List */}
        <div className={`lg:col-span-2 rounded-xl border bg-card overflow-hidden ${loading ? "opacity-60" : ""}`}>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="border-b bg-muted/30">
                  <th className="p-4 font-semibold text-muted-foreground">Lead Details</th>
                  <th className="p-4 font-semibold text-muted-foreground">Status</th>
                  <th className="p-4 font-semibold text-muted-foreground hidden sm:table-cell">Created</th>
                  <th className="p-4 w-10"></th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {filteredLeads.length === 0 ? (
                  <tr>
                    <td colSpan="4" className="p-8 text-center text-muted-foreground">
                      {loading ? "Loading leads..." : "No leads found."}
                    </td>
                  </tr>
                ) : (
                  filteredLeads.map((lead) => {
                    const statusOpt = STATUS_OPTIONS.find(s => s.value === lead.status) || STATUS_OPTIONS[0];
                    return (
                      <tr 
                        key={lead.id} 
                        onClick={() => setSelectedLead(lead)}
                        className={`hover:bg-accent/40 cursor-pointer transition-colors ${
                          selectedLead?.id === lead.id ? "bg-accent/50" : ""
                        }`}
                      >
                        <td className="p-4">
                          <div className="font-semibold text-foreground">{lead.full_name || "Unnamed Lead"}</div>
                          <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-3 text-xs text-muted-foreground mt-1">
                            {lead.email && (
                              <span className="flex items-center gap-1"><Mail className="w-3.5 h-3.5" /> {lead.email}</span>
                            )}
                            {lead.phone && (
                              <span className="flex items-center gap-1"><Phone className="w-3.5 h-3.5" /> {lead.phone}</span>
                            )}
                          </div>
                        </td>
                        <td className="p-4" onClick={(e) => e.stopPropagation()}>
                          <select
                            value={lead.status}
                            onChange={(e) => handleStatusChange(lead.id, e.target.value)}
                            className={`px-2.5 py-1 rounded-md border text-xs font-semibold focus:outline-none ${statusOpt.color}`}
                          >
                            {STATUS_OPTIONS.map((opt) => (
                              <option key={opt.value} value={opt.value} className="bg-background text-foreground">
                                {opt.label}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="p-4 text-xs text-muted-foreground hidden sm:table-cell">
                          {new Date(lead.created_at).toLocaleDateString()}
                        </td>
                        <td className="p-4 text-right">
                          <ChevronRight className="w-4 h-4 text-muted-foreground" />
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Detailed Side Panel */}
        <div className="lg:col-span-1">
          {selectedLead ? (
            <div className="p-6 rounded-xl border bg-card space-y-6">
              <div className="flex items-center justify-between border-b pb-4">
                <div>
                  <h3 className="font-bold text-lg">{selectedLead.full_name || "Unnamed Lead"}</h3>
                  <span className="text-xs text-muted-foreground flex items-center gap-1 mt-1">
                    <Calendar className="w-3.5 h-3.5" /> Captured on {new Date(selectedLead.created_at).toLocaleString()}
                  </span>
                </div>
                <button
                  onClick={() => setSelectedLead(null)}
                  className="p-1 rounded-lg hover:bg-accent text-muted-foreground"
                >
                  <XCircle className="w-5 h-5" />
                </button>
              </div>

              <div className="space-y-4">
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-muted-foreground uppercase">Contact Info</label>
                  <div className="space-y-2 pt-1">
                    {selectedLead.email && (
                      <div className="flex items-center gap-2.5 text-sm">
                        <Mail className="w-4 h-4 text-muted-foreground" />
                        <a href={`mailto:${selectedLead.email}`} className="text-primary hover:underline">{selectedLead.email}</a>
                      </div>
                    )}
                    {selectedLead.phone && (
                      <div className="flex items-center gap-2.5 text-sm">
                        <Phone className="w-4 h-4 text-muted-foreground" />
                        <a href={`tel:${selectedLead.phone}`} className="text-primary hover:underline">{selectedLead.phone}</a>
                      </div>
                    )}
                  </div>
                </div>

                <div className="space-y-2 pt-2">
                  <label className="text-xs font-semibold text-muted-foreground uppercase">Captured Fields (Raw Data)</label>
                  <div className="space-y-2.5 max-h-60 overflow-y-auto p-3 rounded-lg bg-accent/30 border text-xs">
                    {Object.entries(selectedLead.fields || {}).map(([key, val]) => (
                      <div key={key} className="space-y-1">
                        <div className="font-semibold text-muted-foreground">{key}</div>
                        <div className="text-foreground break-all">{String(val || "—")}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="p-6 rounded-xl border border-dashed text-center space-y-3">
              <Info className="w-8 h-8 text-muted-foreground mx-auto" />
              <div className="text-sm font-semibold">Select a lead</div>
              <p className="text-xs text-muted-foreground">
                Click any lead row in the inbox list to inspect its captured spreadsheet fields, questions, and responses.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
