import { useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { toast } from "sonner";
import AuthLayout, { PasswordField } from "../components/AuthLayout";
import { ArrowRight, Loader2, LogIn } from "lucide-react";

import { useAuth } from "../context/AuthContext";
import { formatError } from "../lib/api";



export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const session = await login(email, password);
      toast.success("Welcome back");
      const returnTo = location.state?.from;
      // A saved return path can belong to a previous user/session (or to a
      // workspace that was deleted). The login response is authoritative, so
      // enter the current user's workspace first instead of rendering a stale
      // workspace URL as "Workspace not found".
      if (session?.default_workspace_id) nav(`/app/w/${session.default_workspace_id}`, { replace: true });
      else if (typeof returnTo === "string" && returnTo.startsWith("/app/") && !returnTo.startsWith("//")) nav(returnTo, { replace: true });
      else if (!localStorage.getItem("arevei_onboarded")) nav("/welcome");
      else nav("/app");
    } catch (err) {
      toast.error(formatError(err.response?.data?.detail) || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return <AuthLayout>
    <form onSubmit={submit} data-testid="login-form">
      <div className="auth-form-heading"><span className="auth-heading-icon"><LogIn size={22}/></span><p className="am-eyebrow">Good to have you back</p><h1>Welcome back.</h1><p>Sign in to keep your sales pipeline moving.</p></div>
      <div className="auth-field"><label htmlFor="email">Email address</label><input id="email" type="email" autoComplete="email" data-testid="login-email" value={email} onChange={e => setEmail(e.target.value)} required placeholder="you@company.com"/></div>
      <div className="auth-field"><div className="auth-field-heading"><label htmlFor="password">Password</label><Link to="/forgot-password" data-testid="login-forgot-password-link">Forgot password?</Link></div><PasswordField autoComplete="current-password" data-testid="login-password" value={password} onChange={e => setPassword(e.target.value)} required placeholder="Enter your password"/></div>
      <button type="submit" disabled={loading} data-testid="login-submit" className="am-button auth-submit">{loading ? <><Loader2 size={16} className="auth-spinner"/>Signing in...</> : <>Sign in<ArrowRight size={16}/></>}</button>
      <p className="auth-switch">New to AI Manager? <Link to="/register" data-testid="to-register">Create an account</Link></p>
    </form>
  </AuthLayout>;
}
