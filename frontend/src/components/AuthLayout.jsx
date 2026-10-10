import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, PhoneCall, MessageSquare, ChartNoAxesCombined, Eye, EyeOff, ShieldCheck } from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";
import "../pages/Landing.css";
import "./AuthLayout.css";

export function PasswordField({ id = "password", ...props }) {
  const [visible, setVisible] = useState(false);
  return <div className="auth-password"><input id={id} type={visible ? "text" : "password"} {...props}/><button type="button" onClick={() => setVisible(!visible)} aria-label={visible ? "Hide password" : "Show password"} aria-pressed={visible} aria-controls={id}>{visible ? <EyeOff size={18}/> : <Eye size={18}/>}</button></div>;
}
export default function AuthLayout({ children, signup = false }) {
  return <div className="am-landing auth-page">
    <header className="auth-header"><Link className="am-logo" to="/" aria-label="Arevei AI Manager home"><span>AI</span> Manager<small>by Arevei</small></Link><div><Link className="auth-back" to="/"><ArrowLeft size={15}/><span>Back to home</span></Link><ThemeToggle/></div></header>
    <main className="auth-main">
      <section className="auth-showcase" aria-label="AI Manager sales workspace">
        <div className="auth-showcase-copy"><p className="am-eyebrow">Your AI Native sales workspace</p><h2>{signup ? <>Your next chapter.<br/><span className="am-gradient">More possibilities.</span></> : <>Less busy work.<br/><span className="am-gradient">More closed deals.</span></>}</h2><p>Qualify leads, manage your pipeline, and find your next best action. All in one connected workspace.</p></div>
        <div className="auth-art" aria-hidden="true"><div className="auth-art-dots"/><div className="auth-art-orbit"/><div className="auth-art-orbit auth-art-orbit-two"/><div className="auth-art-orb">AI</div><div className="auth-float auth-float-one"><PhoneCall/><div><strong>AI Voice Agents</strong><span>Every lead gets attention</span></div></div><div className="auth-float auth-float-two"><MessageSquare/><div><strong>Chat-driven CRM</strong><span>Your pipeline, in plain language</span></div></div><div className="auth-float auth-float-three"><ChartNoAxesCombined/><div><strong>Pipeline intelligence</strong><span>A clearer next move</span></div></div></div>
        <div className="auth-showcase-footer"><span className="auth-status-dot"/><p>You focus on relationships.<br/><strong>AI helps with the rest.</strong></p></div>
        <svg className="auth-waves" viewBox="0 0 700 180" preserveAspectRatio="none" aria-hidden="true">{Array.from({length:18},(_,i)=><path key={i} d={`M-20 ${100+i*4} C150 ${20+i*3},260 ${220-i*4},410 ${100+i*2} S600 ${20+i*5},740 ${100+i*2}`} stroke={i%2 ? "#844fff" : "#4a8eff"} strokeWidth=".8" fill="none" opacity=".2"/>)}</svg>
      </section>
      <section className="auth-form-panel" aria-label={signup ? "Create your account" : "Sign in to your account"}><div className="auth-form-card">{children}</div><p className="auth-reassurance"><ShieldCheck size={14}/>Your workspace. Your team. Your control.</p></section>
    </main><footer className="auth-footer"><span>© {new Date().getFullYear()} Arevei</span><span>More conversations. Better opportunities.</span></footer>
  </div>;
}
