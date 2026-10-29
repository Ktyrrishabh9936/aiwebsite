/** Editable CRM lead field rendered from the workspace field definition. */
export default function DynamicField({ field, value, onChange, onBlur }) {
  const common = "w-full h-10 px-3 rounded-lg border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary";
  const label = <span className="text-xs font-semibold text-muted-foreground uppercase">{field.label}{field.required && <span className="text-destructive"> *</span>}</span>;
  if (field.type === "long_text" || field.type === "json") return <label onBlur={onBlur} className="space-y-1.5 sm:col-span-2">{label}<textarea aria-label={field.label} value={value} onChange={(e) => onChange(e.target.value)} rows={3} className="w-full px-3 py-2 rounded-lg border bg-background text-sm" /></label>;
  if (field.type === "boolean") return <label onBlur={onBlur} className="space-y-1.5">{label}<select aria-label={field.label} value={value ? "true" : "false"} onChange={(e) => onChange(e.target.value === "true")} className={common}><option value="false">No</option><option value="true">Yes</option></select></label>;
  if (field.type === "select") return <label onBlur={onBlur} className="space-y-1.5">{label}<select aria-label={field.label} value={value} onChange={(e) => onChange(e.target.value)} className={common}><option value="">Select</option>{(field.options || []).map((o) => <option key={o} value={o}>{o}</option>)}</select></label>;
  const type = field.type === "email" ? "email" : field.type === "phone" ? "tel" : field.type === "number" || field.type === "currency" ? "number" : field.type === "date" ? "date" : field.type === "datetime" ? "datetime-local" : field.type === "url" ? "url" : "text";
  return <label onBlur={onBlur} className="space-y-1.5">{label}<input aria-label={field.label} type={type} value={value} onChange={(e) => onChange(e.target.value)} className={common} /></label>;
}
