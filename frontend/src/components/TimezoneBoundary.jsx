import { useEffect, useState } from "react";
import { getAppTimezone } from "../lib/timezone";

export default function TimezoneBoundary({ children }) {
  const [zone, setZone] = useState(getAppTimezone);
  useEffect(() => {
    const update = () => setZone(getAppTimezone());
    window.addEventListener("arevei:timezone-changed", update);
    window.addEventListener("storage", update);
    window.addEventListener("focus", update);
    return () => { window.removeEventListener("arevei:timezone-changed", update); window.removeEventListener("storage", update); window.removeEventListener("focus", update); };
  }, []);
  return <div key={zone} className="contents">{children}</div>;
}
