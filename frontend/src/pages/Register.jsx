import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";
import { useAuth } from "../context/AuthContext";
import { formatError } from "../lib/api";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export default function Register() {
  const { register } = useAuth();
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await register(name, email, password);
      toast.success("Account created");
      nav("/welcome");
    } catch (err) {
      toast.error(formatError(err.response?.data?.detail) || "Sign up failed");
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
            Turn your website into a growth machine.
          </h2>
          <p className="mt-4 text-primary-foreground/80 max-w-md">
            Create an account, paste your URL, and let the AI manager take over.
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
          <form onSubmit={submit} className="w-full max-w-sm space-y-5" data-testid="register-form">
            <div>
              <h1 className="font-display text-3xl font-black">Create account</h1>
              <p className="text-muted-foreground mt-1 text-sm">Start managing your website with agents.</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="name">Name</Label>
              <Input id="name" data-testid="register-name" value={name} onChange={(e) => setName(e.target.value)} required placeholder="Jane Founder" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" data-testid="register-email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="you@company.com" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" data-testid="register-password" value={password} onChange={(e) => setPassword(e.target.value)} required placeholder="At least 6 characters" />
            </div>
            <button
              type="submit"
              disabled={loading}
              data-testid="register-submit"
              className="w-full h-11 rounded-full bg-primary text-primary-foreground font-semibold hover:-translate-y-0.5 transition-transform disabled:opacity-60"
            >
              {loading ? "Creating…" : "Create account"}
            </button>
            <p className="text-sm text-muted-foreground text-center">
              Already have an account?{" "}
              <Link to="/login" data-testid="to-login" className="text-primary font-medium hover:underline">Log in</Link>
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
