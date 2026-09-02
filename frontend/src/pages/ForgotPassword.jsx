import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Loader2, Mail } from "lucide-react";
import { toast } from "sonner";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";
import api, { formatError } from "../lib/api";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api.post("/auth/forgot-password", { email });
      setSent(true);
    } catch (err) {
      toast.error(formatError(err.response?.data?.detail) || "Could not send reset link");
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
            Get back into your command center.
          </h2>
          <p className="mt-4 text-primary-foreground/80 max-w-md">
            We will send a secure one-time reset link to your account email.
          </p>
        </div>
        <span className="text-sm text-primary-foreground/60">Password links expire in 30 minutes</span>
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
            {sent ? (
              <div className="rounded-2xl border bg-card p-6 shadow-sm">
                <div className="grid h-12 w-12 place-items-center rounded-full bg-primary/10 text-primary mb-4">
                  <CheckCircle2 className="h-6 w-6" />
                </div>
                <h1 className="font-display text-2xl font-black">Check your inbox</h1>
                <p className="text-sm text-muted-foreground mt-2 leading-6">
                  If an account exists for that email, a reset link has been sent. The link expires in 30 minutes.
                </p>
              </div>
            ) : (
              <form onSubmit={submit} className="rounded-2xl border bg-card p-6 shadow-sm space-y-5" data-testid="forgot-password-form">
                <div className="grid h-12 w-12 place-items-center rounded-full bg-primary/10 text-primary">
                  <Mail className="h-6 w-6" />
                </div>
                <div>
                  <h1 className="font-display text-3xl font-black">Forgot password</h1>
                  <p className="text-muted-foreground mt-1 text-sm">Enter your email and we will send a reset link.</p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="email">Email</Label>
                  <Input id="email" type="email" data-testid="forgot-password-email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="you@company.com" />
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  data-testid="forgot-password-submit"
                  className="w-full h-11 rounded-full bg-primary text-primary-foreground font-semibold hover:-translate-y-0.5 transition-transform disabled:opacity-60 inline-flex items-center justify-center gap-2"
                >
                  {loading && <Loader2 className="w-4 h-4 animate-spin" />}
                  {loading ? "Sending..." : "Send reset link"}
                </button>
              </form>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
