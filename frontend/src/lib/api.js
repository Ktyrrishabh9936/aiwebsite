import axios from "axios";
import { getAppTimezone } from "./timezone";

const backendUrl = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "");
const API = `${backendUrl}/api`;

const api = axios.create({ baseURL: API });

api.interceptors.request.use((cfg) => {
  const token = localStorage.getItem("arevei_token");
  if (token) cfg.headers.Authorization = `Bearer ${token}`;
  cfg.headers["X-App-Timezone"] = getAppTimezone();
  return cfg;
});

export function formatError(detail) {
  if (detail == null) return "Something went wrong.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail.map((e) => (e?.msg ? e.msg : JSON.stringify(e))).join(" ");
  if (detail?.msg) return detail.msg;
  return String(detail);
}

export { API };
export default api;
