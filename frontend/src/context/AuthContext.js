import { createContext, useContext, useEffect, useState } from "react";
import api from "../lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null = loading, false = logged out
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("arevei_token");
    if (!token) {
      setUser(false);
      setReady(true);
      return;
    }
    api
      .get("/auth/me")
      .then((r) => setUser(r.data))
      .catch(() => {
        localStorage.removeItem("arevei_token");
        setUser(false);
      })
      .finally(() => setReady(true));
  }, []);

  const persist = (data) => {
    localStorage.setItem("arevei_token", data.token);
    setUser(data.user);
  };

  const login = async (email, password) => {
    const r = await api.post("/auth/login", { email, password });
    persist(r.data);
  };
  const register = async (name, email, password) => {
    const r = await api.post("/auth/register", { name, email, password });
    persist(r.data);
  };
  const logout = () => {
    localStorage.removeItem("arevei_token");
    setUser(false);
  };

  return (
    <AuthContext.Provider value={{ user, ready, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
