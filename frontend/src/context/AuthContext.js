import { createContext, useContext, useEffect, useState } from "react";
import api from "../lib/api";
import { removeDevicePush } from "../lib/pushNotifications";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null = loading, false = logged out
  const [ready, setReady] = useState(false);
  const [connectionError, setConnectionError] = useState(false);
  const [authAttempt, setAuthAttempt] = useState(0);

  useEffect(() => {
    const token = localStorage.getItem("arevei_token");
    if (!token) {
      setUser(false);
      setConnectionError(false);
      setReady(true);
      return;
    }
    setReady(false);
    api
      .get("/auth/me", { timeout: 8000 })
      .then((r) => { setUser(r.data); setConnectionError(false); })
      .catch((error) => {
        if ([401, 403].includes(error.response?.status)) {
          localStorage.removeItem("arevei_token");
          setUser(false);
          setConnectionError(false);
        } else {
          setConnectionError(true);
        }
      })
      .finally(() => setReady(true));
  }, [authAttempt]);

  const retryAuth = () => {
    setReady(false);
    setConnectionError(false);
    setAuthAttempt((attempt) => attempt + 1);
  };

  const persist = (data) => {
    localStorage.setItem("arevei_token", data.token);
    setUser(data.user);
    setConnectionError(false);
  };

  const login = async (email, password) => {
    const r = await api.post("/auth/login", { email, password });
    persist(r.data);
    return r.data;
  };
  const register = async (name, email, password) => {
    const r = await api.post("/auth/register", { name, email, password });
    persist(r.data);
  };
  const logout = async () => {
    try { await removeDevicePush(); }
    catch { /* The browser subscription is also removed when the API is unavailable. */ }
    localStorage.removeItem("arevei_token");
    setUser(false);
    setConnectionError(false);
  };

  return (
    <AuthContext.Provider value={{ user, ready, connectionError, retryAuth, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
