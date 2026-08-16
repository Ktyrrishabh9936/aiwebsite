import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";
import { useAuth } from "../context/AuthContext";
import { formatError } from "../lib/api";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(email, password);
      toast.success("Welcome back");
      nav("/app");
    } catch (err) {
      toast.error(formatError(err.response?.data?.detail) || "Login failed");
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
            Your website, run by an AI manager.
          </h2>
          <p className="mt-4 text-primary-foreground/80 max-w-md">
            Log in to your control panel — brains, roadmaps, agents, and auto-published content.
          </p>
        </div>
        <span className="text-sm text-primary-foreground/60">AI-native website growth OS</span>
      </div>

      <div className="flex flex-col p-6 sm:p-10">
        <div className="flex justify-between items-center">
          <Logo className="lg:hidden" />
          <div className="ml-auto"><ThemeToggle /></div>
        </div>
        <div className="flex-1 grid place-items-center">
          <form onSubmit={submit} className="w-full max-w-sm space-y-5" data-testid="login-form">
            <div>
              <h1 className="font-display text-3xl font-black">Log in</h1>
              <p className="text-muted-foreground mt-1 text-sm">Welcome back to Arevei.</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" data-testid="login-email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="admin@arevei.ai" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" data-testid="login-password" value={password} onChange={(e) => setPassword(e.target.value)} required placeholder="••••••••" />
            </div>
            <button
              type="submit"
              disabled={loading}
              data-testid="login-submit"
              className="w-full h-11 rounded-full bg-primary text-primary-foreground font-semibold hover:-translate-y-0.5 transition-transform disabled:opacity-60"
            >
              {loading ? "Logging in…" : "Log in"}
            </button>
            <p className="text-sm text-muted-foreground text-center">
              No account?{" "}
              <Link to="/register" data-testid="to-register" className="text-primary font-medium hover:underline">Sign up</Link>
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
