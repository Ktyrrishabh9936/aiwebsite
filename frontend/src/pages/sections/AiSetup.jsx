import { useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { ArrowRight, CheckCircle2, Sparkles } from "lucide-react";
import InterviewChat from "../../components/onboarding/InterviewChat";
import ChannelsStep from "../../components/onboarding/ChannelsStep";
import SetupChecklist from "../../components/onboarding/SetupChecklist";
import SetupHelpCard from "../../components/onboarding/SetupHelpCard";

/** In-workspace AI Manager setup for owners who skipped or want to redo onboarding. */
export default function AiSetup() {
  const { ws, refresh } = useOutletContext();
  const [stage, setStage] = useState("interview");
  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-8">
      <div>
        <p className="inline-flex items-center gap-1.5 text-sm font-medium text-primary"><Sparkles className="h-4 w-4" />AI Manager setup</p>
        <h1 className="mt-1.5 text-3xl font-bold tracking-tight">{stage === "interview" ? "Teach your AI Manager about your business" : stage === "channels" ? "Connect your voice agent and SMS" : "You're all set"}</h1>
        <p className="mt-1.5 max-w-2xl text-muted-foreground">{stage === "interview" ? "A short guided chat. Your answers become your sales strategy and daily briefings." : stage === "channels" ? "Optional — let your AI call every new lead within minutes." : "Your AI Manager will use this in every answer, briefing and call."}</p>
      </div>
      {stage === "interview" && <InterviewChat wsId={ws.id} currency={ws.currency} onFinished={() => { refresh?.(); setStage("channels"); }} onSkip={() => setStage("channels")} skipLabel="Skip to voice & SMS" />}
      {stage === "channels" && <ChannelsStep wsId={ws.id} onContinue={() => setStage("done")} onSkip={() => setStage("done")} />}
      {stage === "done" && (
        <div className="space-y-5">
          <div className="flex items-center gap-3 rounded-2xl border border-emerald-500/30 bg-emerald-500/5 p-5"><CheckCircle2 className="h-6 w-6 text-emerald-500" /><p className="text-sm">Saved. Your strategy appears on the Overview and in Brain → Sales strategy once it's ready.</p></div>
          <SetupChecklist wsId={ws.id} dismissible={false} title="Your setup checklist" />
          <Link to={`/app/w/${ws.id}`} className="inline-flex h-11 items-center gap-2 rounded-xl bg-primary px-5 text-sm font-semibold text-primary-foreground">Back to overview<ArrowRight className="h-4 w-4" /></Link>
        </div>
      )}
      <SetupHelpCard />
    </div>
  );
}
