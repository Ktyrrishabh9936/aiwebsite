import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import api, { formatError } from "../lib/api";

export default function JoinWorkspace() {
  const { token } = useParams();
  const { user, ready, login, register, logout } = useAuth();
  const navigate = useNavigate();
  const [invite, setInvite] = useState(null);
  const [error, setError] = useState("");
  const [newAccount, setNewAccount] = useState(false);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.get(`/membership-invitations/${token}`).then(({ data }) => { setInvite(data); setName(data.name); }).catch((err) => setError(formatError(err.response?.data?.detail))); }, [token]);
  const accept = async (event) => {
    event.preventDefault(); setBusy(true); setError("");
    try {
      if (!user) { if (newAccount) await register(name, invite.email, password); else await login(invite.email, password); }
      const { data } = await api.post(`/membership-invitations/${token}/accept`, {});
      localStorage.setItem("arevei_onboarded", "true");
      navigate(`/app/w/${data.workspace_id}/crm`, { replace: true });
    } catch (err) { setError(formatError(err.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  return <main className="min-h-screen grid place-items-center p-6"><div className="w-full max-w-md rounded-xl border bg-card p-6 space-y-4"><h1 className="text-2xl font-semibold">Join workspace</h1>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}{!invite ? <p className="text-sm text-muted-foreground">{error ? "Request a new invitation from the owner." : "Loading invitation..."}</p> : <><p className="text-sm">You are invited to <strong>{invite.workspace_name}</strong> as a {invite.role.replaceAll("_", " ")}.</p><p className="text-sm text-muted-foreground">Invited email: {invite.email}</p>{user && user.email?.toLowerCase() !== invite.email ? <><p className="text-sm">Sign out and use the invited email to continue.</p><button onClick={logout} className="rounded-lg border px-3 py-2 text-sm">Sign out</button></> : <form onSubmit={accept} className="space-y-4">{!user && <>{newAccount && <label className="block text-sm">Name<input required value={name} onChange={(event) => setName(event.target.value)} className="mt-1 h-10 w-full rounded-lg border bg-background px-3" /></label>}<label className="block text-sm">{newAccount ? "Create password" : "Password"}<input required minLength={6} type="password" autoComplete={newAccount ? "new-password" : "current-password"} value={password} onChange={(event) => setPassword(event.target.value)} className="mt-1 h-10 w-full rounded-lg border bg-background px-3" /></label><button type="button" onClick={() => setNewAccount(!newAccount)} className="text-sm text-primary underline">{newAccount ? "I already have an account" : "Create an account"}</button></>}<button disabled={busy || !ready} className="h-10 w-full rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50">{busy ? "Joining..." : "Accept invitation"}</button></form>}</>}</div></main>;
}
