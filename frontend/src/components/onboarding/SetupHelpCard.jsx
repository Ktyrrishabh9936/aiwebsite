import { LifeBuoy, Mail } from "lucide-react";

export const AREVEI_CONTACT = { name: "arevei", email: "admin@arevei.com" };

/** Contact details for hands-on setup help, shown on every onboarding step. */
export default function SetupHelpCard({ compact = false, className = "" }) {
  if (compact) {
    return (
      <p className={`flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-xs text-muted-foreground ${className}`}>
        <LifeBuoy className="h-3.5 w-3.5" aria-hidden="true" />
        Need a hand? Contact <span className="font-semibold text-foreground">{AREVEI_CONTACT.name}</span>
        <span aria-hidden="true">·</span>
        <a href={`mailto:${AREVEI_CONTACT.email}`} className="font-semibold text-primary hover:underline">{AREVEI_CONTACT.email}</a>
      </p>
    );
  }
  return (
    <div className={`flex items-start gap-3 rounded-xl border bg-card p-4 ${className}`}>
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary"><LifeBuoy className="h-5 w-5" /></span>
      <div className="min-w-0 text-sm">
        <p className="font-semibold">Prefer we set it up for you?</p>
        <p className="mt-0.5 text-muted-foreground">Our team can configure your AI Manager, voice agent and lead sources.</p>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-semibold">{AREVEI_CONTACT.name}</span>
          <a href={`mailto:${AREVEI_CONTACT.email}`} className="inline-flex items-center gap-1 font-semibold text-primary hover:underline"><Mail className="h-3.5 w-3.5" />{AREVEI_CONTACT.email}</a>
        </div>
      </div>
    </div>
  );
}
