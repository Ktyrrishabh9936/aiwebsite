import { countryByIso } from "../../lib/countries";

/** Visual preview that mirrors the hosted embed form (backend/lead_forms.py EMBED_JS). */
export default function FormPreview({ form }) {
  const a = form.appearance || {};
  const f = form.fields || {};
  const dark = a.theme === "dark";
  const accent = a.accent_color || "#4f46e5";
  const radius = a.rounded === false ? 4 : 12;
  const palette = dark
    ? { bg: "#0f172a", fg: "#f8fafc", mute: "#94a3b8", line: "#334155", field: "#1e293b" }
    : { bg: "#ffffff", fg: "#0f172a", mute: "#64748b", line: "#e2e8f0", field: "#ffffff" };
  const input = { width: "100%", border: `1px solid ${palette.line}`, borderRadius: radius, padding: "10px 12px", fontSize: 14, background: palette.field, color: palette.mute };
  const country = countryByIso(f.phone?.default_country);
  const Field = ({ name, children }) => f[name]?.enabled ? (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 5 }}>{f[name].label}{f[name].required ? " *" : ""}</div>
      {children}
    </div>
  ) : null;
  return (
    <div aria-label="Form preview" style={{ fontFamily: "system-ui,-apple-system,'Segoe UI',Roboto,sans-serif", background: palette.bg, color: palette.fg, border: `1px solid ${palette.line}`, borderRadius: a.rounded === false ? 6 : 18, padding: 24, boxShadow: "0 10px 30px rgba(15,23,42,.08)" }}>
      {form.status !== "active" && <div style={{ fontSize: 11, fontWeight: 700, color: "#b45309", background: "#fef3c7", borderRadius: 999, display: "inline-block", padding: "2px 8px", marginBottom: 10 }}>Paused — visitors see “not accepting submissions”</div>}
      {a.title && <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>{a.title}</div>}
      {a.subtitle && <div style={{ fontSize: 13, color: palette.mute, marginBottom: 16, lineHeight: 1.5 }}>{a.subtitle}</div>}
      <Field name="full_name"><div style={input}>{f.full_name?.placeholder || " "}</div></Field>
      <Field name="email"><div style={input}>{f.email?.placeholder || " "}</div></Field>
      <Field name="phone">
        <div style={{ display: "flex", gap: 8 }}>
          <div style={{ ...input, width: 104, flex: "none", color: palette.fg }}>{country.flag} {country.dial} ▾</div>
          <div style={input}>{f.phone?.placeholder || " "}</div>
        </div>
      </Field>
      <Field name="requirement"><div style={{ ...input, minHeight: 72 }}>{f.requirement?.placeholder || " "}</div></Field>
      <div style={{ background: accent, color: "#fff", textAlign: "center", fontWeight: 700, fontSize: 14, borderRadius: radius, padding: "12px 16px", marginTop: 4 }}>{a.button_label || "Submit"}</div>
      <div style={{ textAlign: "center", fontSize: 10, color: palette.mute, marginTop: 10 }}>Secured by Arevei</div>
    </div>
  );
}
