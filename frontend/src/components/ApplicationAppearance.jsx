import { useLayoutEffect } from "react";
import { useLocation } from "react-router-dom";
import "./ApplicationAppearance.css";

export default function ApplicationAppearance({ children }) {
  const { pathname } = useLocation();
  const enabled = pathname === "/app" || pathname.startsWith("/app/") || pathname === "/welcome";
  useLayoutEffect(() => {
    if (enabled) document.documentElement.setAttribute("data-app-ui", "true");
    else document.documentElement.removeAttribute("data-app-ui");
    return () => document.documentElement.removeAttribute("data-app-ui");
  }, [enabled]);
  return <div className={enabled ? "application-ui" : undefined} style={{ display: "contents" }}>{children}</div>;
}
