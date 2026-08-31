import { useAuth } from "../../context/AuthContext";

export default function Settings() {
  const { user } = useAuth();

  return (
    <div className="p-6 sm:p-10 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="font-display text-3xl font-black tracking-tight">Settings</h1>
        <p className="text-muted-foreground mt-1">Manage your account and workspace preferences.</p>
      </div>

      <section className="border border-border rounded-md bg-card p-6 space-y-5">
        <div>
          <h2 className="font-display text-xl font-bold">Account</h2>
          <p className="text-sm text-muted-foreground mt-1">Your signed-in profile for Arevei.</p>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <InfoItem label="Name" value={user?.name || "Not set"} />
          <InfoItem label="Email" value={user?.email || "Not available"} />
          <InfoItem label="Role" value={user?.role || "User"} />
        </div>
      </section>

      <section className="border border-border rounded-md bg-card p-6">
        <h2 className="font-display text-xl font-bold">Workspace</h2>
        <p className="text-sm text-muted-foreground mt-1">Use the account menu in the top bar to switch website workspaces or create a new one.</p>
      </section>
    </div>
  );
}

function InfoItem({ label, value }) {
  return (
    <div className="rounded-md border border-border bg-background p-4">
      <div className="text-xs uppercase text-muted-foreground font-semibold">{label}</div>
      <div className="mt-1 font-medium capitalize">{value}</div>
    </div>
  );
}
