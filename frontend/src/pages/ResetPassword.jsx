import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, KeyRound, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";
import api, { formatError } from "../lib/api";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export default function ResetPassword() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const token = useMemo(() => params.get("token") || "", [params]);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  const canSubmit = token && password.length >= 6 && password === confirmPassword;

  const submit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setLoading(true);
    try {
      await api.post("/auth/reset-password", { token, password });
      setDone(true);
      toast.success("Password reset successfully");
      setTimeout(() => nav("/login"), 1200);
    } catch (err) {
      toast.error(formatError(err.response?.data?.detail) || "Could not reset password");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2">
      <div className="hidden lg:flex flex-col justify-between p-10 bg-primary text-primary-foreground grain">
        <Logo className="text-lg text-primary-foreground" />
        <div>
          <h2 className="font-display text-4xl font-black leading-tight">
            Set a fresh password.
          </h2>
          <p className="mt-4 text-primary-foreground/80 max-w-md">
            Secure your account with a new password and return to your Arevei workspace.
          </p>
        </div>
        <span className="text-sm text-primary-foreground/60">One-time reset link</span>
      </div>

      <div className="flex flex-col p-6 sm:p-10">
        <div className="flex justify-between items-center">
          <Logo className="lg:hidden" />
          <div className="ml-auto"><ThemeToggle /></div>
        </div>
        <div className="flex-1 grid place-items-center">
          <div className="w-full max-w-sm space-y-5">
            <Link to="/login" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
              <ArrowLeft className="w-4 h-4" /> Back to login
            </Link>
            {done ? (
              <div className="rounded-2xl border bg-card p-6 shadow-sm">
                <div className="grid h-12 w-12 place-items-center rounded-full bg-primary/10 text-primary mb-4">
                  <CheckCircle2 className="h-6 w-6" />
                </div>
                <h1 className="font-display text-2xl font-black">Password updated</h1>
                <p className="text-sm text-muted-foreground mt-2 leading-6">Redirecting you to login.</p>
              </div>
            ) : (
              <form onSubmit={submit} className="rounded-2xl border bg-card p-6 shadow-sm space-y-5" data-testid="reset-password-form">
                <div className="grid h-12 w-12 place-items-center rounded-full bg-primary/10 text-primary">
                  <KeyRound className="h-6 w-6" />
                </div>
                <div>
                  <h1 className="font-display text-3xl font-black">Reset password</h1>
                  <p className="text-muted-foreground mt-1 text-sm">Choose a new password for your Arevei account.</p>
                </div>
                {!token && (
                  <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                    This reset link is missing a token. Request a new link from the forgot password page.
                  </div>
                )}
                <div className="space-y-2">
                  <Label htmlFor="password">New password</Label>
                  <Input id="password" type="password" data-testid="reset-password-new" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} placeholder="At least 6 characters" />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="confirmPassword">Confirm password</Label>
                  <Input id="confirmPassword" type="password" data-testid="reset-password-confirm" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required minLength={6} placeholder="Repeat password" />
                  {confirmPassword && password !== confirmPassword && <p className="text-xs text-destructive">Passwords do not match.</p>}
                </div>
                <button
                  type="submit"
                  disabled={loading || !canSubmit}
                  data-testid="reset-password-submit"
                  className="w-full h-11 rounded-full bg-primary text-primary-foreground font-semibold hover:-translate-y-0.5 transition-transform disabled:opacity-60 inline-flex items-center justify-center gap-2"
                >
                  {loading && <Loader2 className="w-4 h-4 animate-spin" />}
                  {loading ? "Updating..." : "Update password"}
                </button>
              </form>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
