import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, Sparkles, CheckCircle2, AlertCircle, FileSpreadsheet, PlusCircle } from "lucide-react";
import api from "../../lib/api";

export default function Workflows() {
  const { wsId } = useParams();
  const [workflows, setWorkflows] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get(`/workspaces/${wsId}/workflows`)
      .then((r) => setWorkflows(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [wsId]);

  const adsWorkflow = workflows.find((w) => w.kind === "ads_to_crm") || { status: "draft" };

  const availableWorkflows = [
    {
      id: "ads-to-crm",
      title: "Ads to CRM",
      description: "Sync Meta / Facebook Lead Ads automatically using our Google Sheet connector.",
      kind: "ads_to_crm",
      status: adsWorkflow.status,
      icon: FileSpreadsheet,
      active: true,
    }
    // {
    //   id: "forms-to-crm",
    //   title: "Google Forms to CRM",
    //   description: "Instantly create CRM leads when a client submits a response on Google Forms.",
    //   kind: "forms_to_crm",
    //   status: "coming_soon",
    //   icon: PlusCircle,
    //   active: false,
    // }
  ];

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-8">
      <div>
        <div className="flex items-center gap-2 text-primary font-medium text-sm mb-1.5">
          <Sparkles className="w-4 h-4" /> Workflows & Connectors
        </div>
        <h1 className="text-3xl font-display font-bold tracking-tight">Automations</h1>
        <p className="text-muted-foreground mt-1.5 max-w-2xl">
          Connect your marketing channels directly to Arevei CRM. No developer keys required.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {availableWorkflows.map((w) => {
          const Icon = w.icon;
          return (
            <div
              key={w.id}
              className={`relative flex flex-col justify-between p-6 rounded-xl border bg-card transition-all ${
                w.active
                  ? "hover:shadow-md hover:border-primary/40 cursor-pointer"
                  : "opacity-65"
              }`}
            >
              <div>
                <div className="flex items-center justify-between mb-4">
                  <div className="p-2.5 bg-primary/10 text-primary rounded-lg">
                    <Icon className="w-5 h-5" />
                  </div>
                  {w.status === "published" ? (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-500">
                      <CheckCircle2 className="w-3 h-3" /> Active
                    </span>
                  ) : w.status === "draft" ? (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-muted text-muted-foreground">
                      <AlertCircle className="w-3 h-3" /> Inactive
                    </span>
                  ) : (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-primary/5 text-primary border border-primary/20">
                      Coming Soon
                    </span>
                  )}
                </div>

                <h3 className="text-lg font-bold">{w.title}</h3>
                <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
                  {w.description}
                </p>
              </div>

              <div className="mt-6 pt-4 border-t border-border/60 flex items-center justify-between">
                {w.active ? (
                  <Link
                    to={`/app/w/${wsId}/workflows/${w.id}`}
                    className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline"
                  >
                    Configure connector <ArrowRight className="w-4 h-4" />
                  </Link>
                ) : (
                  <span className="text-xs text-muted-foreground">Disabled in beta</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
