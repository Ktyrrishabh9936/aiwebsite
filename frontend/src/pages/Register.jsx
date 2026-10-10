import { useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { toast } from "sonner";
import AuthLayout, { PasswordField } from "../components/AuthLayout";
import { ArrowRight, Loader2, Sparkles } from "lucide-react";

import { useAuth } from "../context/AuthContext";
import { formatError } from "../lib/api";



export default function Register() {
  const { register } = useAuth();
  const nav = useNavigate();
  const { state } = useLocation();
  const [name, setName] = useState(state?.name || "");
  const [email, setEmail] = useState(state?.email || "");
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

  return <AuthLayout signup>
    <form onSubmit={submit} data-testid="register-form">
      <div className="auth-form-heading"><span className="auth-heading-icon"><Sparkles size={22}/></span><p className="am-eyebrow">Your AI journey starts here</p><h1>Create your account.</h1><p>A smarter sales pipeline starts with you.</p></div>
      <div className="auth-field"><label htmlFor="name">Full name</label><input id="name" autoComplete="name" data-testid="register-name" value={name} onChange={e => setName(e.target.value)} required placeholder="Sarah Mitchell"/></div>
      <div className="auth-field"><label htmlFor="email">Email address</label><input id="email" type="email" autoComplete="email" data-testid="register-email" value={email} onChange={e => setEmail(e.target.value)} required placeholder="you@company.com"/></div>
      <div className="auth-field"><label htmlFor="password">Password</label><PasswordField autoComplete="new-password" data-testid="register-password" value={password} onChange={e => setPassword(e.target.value)} required minLength={6} aria-describedby="password-hint" placeholder="Create a password"/><p className="auth-hint" id="password-hint">Use at least 6 characters.</p></div>
      <button type="submit" disabled={loading} data-testid="register-submit" className="am-button auth-submit">{loading ? <><Loader2 size={16} className="auth-spinner"/>Creating your account...</> : <>Create account<ArrowRight size={16}/></>}</button>
      <p className="auth-switch">Already have an account? <Link to="/login" data-testid="to-login">Sign in</Link></p>
    </form>
  </AuthLayout>;
}
