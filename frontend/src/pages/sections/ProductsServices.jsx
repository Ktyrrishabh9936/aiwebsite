import { useCallback, useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { Box, Loader2, PackageOpen, Pencil, Plus, Trash2, Wrench, X } from "lucide-react";
import { toast } from "sonner";
import api, { formatError } from "../../lib/api";
import { formatMoney } from "../../lib/currency";

const EMPTY = { kind: "service", name: "", description: "", sku: "", price: "", stock_quantity: 0, status: "active" };

export default function ProductsServices() {
  const { ws } = useOutletContext();
  const [items, setItems] = useState([]);
  const [currency, setCurrency] = useState(ws.currency || "INR");
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState("");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const enabled = ws.modules?.agency === true;

  const load = useCallback(async () => {
    if (!enabled) { setLoading(false); return; }
    try {
      const { data } = await api.get(`/workspaces/${ws.id}/catalog`);
      setItems(data.items || []);
      setCurrency(data.currency || ws.currency || "INR");
    } catch (error) { toast.error(formatError(error.response?.data?.detail)); }
    finally { setLoading(false); }
  }, [enabled, ws.currency, ws.id]);
  useEffect(() => { load(); }, [load]);

  const close = () => { setOpen(false); setEditing(""); setForm(EMPTY); };
  const edit = (item) => {
    setEditing(item.id);
    setForm({ kind: item.kind, name: item.name, description: item.description || "", sku: item.sku || "", price: item.price || "", stock_quantity: item.stock_quantity || 0, status: item.status || "active" });
    setOpen(true);
  };
  const save = async (event) => {
    event.preventDefault(); setSaving(true);
    try {
      if (editing) await api.patch(`/workspaces/${ws.id}/catalog/${editing}`, form);
      else await api.post(`/workspaces/${ws.id}/catalog`, form);
      toast.success(editing ? "Item updated" : "Item added"); close(); await load();
    } catch (error) { toast.error(formatError(error.response?.data?.detail)); }
    finally { setSaving(false); }
  };
  const remove = async (item) => {
    if (!window.confirm(`Delete ${item.name}?`)) return;
    try { await api.delete(`/workspaces/${ws.id}/catalog/${item.id}`); setItems((current) => current.filter((row) => row.id !== item.id)); }
    catch (error) { toast.error(formatError(error.response?.data?.detail)); }
  };

  if (!enabled) return <ModuleDisabled title="Products & Services" wsId={ws.id} />;
  return <div className="p-6 sm:p-10 max-w-7xl mx-auto space-y-8">
    <header className="flex items-end justify-between gap-4 flex-wrap"><div><div className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.2em] font-bold text-primary"><PackageOpen className="w-4 h-4" /> Agency module</div><h1 className="mt-2 font-display text-3xl font-black tracking-tight">Products & Services</h1><p className="text-muted-foreground mt-1">Manage what your team sells and connect it to CRM opportunities.</p></div><button onClick={() => setOpen(true)} className="inline-flex items-center gap-2 px-4 h-10 rounded-full bg-primary text-primary-foreground text-sm font-semibold"><Plus className="w-4 h-4" /> Add item</button></header>
    {loading ? <div className="flex items-center gap-2 text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin" /> Loading catalog...</div> : !items.length ? <div className="border border-dashed rounded-xl p-12 text-center bg-card"><PackageOpen className="w-10 h-10 mx-auto text-muted-foreground" /><h2 className="mt-4 font-display text-xl font-bold">No products or services yet</h2><p className="mt-1 text-sm text-muted-foreground">Create the first item your sales team can attach to a lead.</p></div> : <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{items.map((item) => <article key={item.id} className="rounded-xl border bg-card p-5"><div className="flex items-start justify-between"><div className="w-10 h-10 rounded-lg bg-primary/10 text-primary grid place-items-center">{item.kind === "product" ? <Box className="w-5 h-5" /> : <Wrench className="w-5 h-5" />}</div><div className="flex gap-1"><button onClick={() => edit(item)} className="p-2 text-muted-foreground hover:text-foreground" title="Edit"><Pencil className="w-4 h-4" /></button><button onClick={() => remove(item)} className="p-2 text-muted-foreground hover:text-destructive" title="Delete"><Trash2 className="w-4 h-4" /></button></div></div><h2 className="mt-4 font-display text-lg font-bold">{item.name}</h2><p className="mt-1 text-sm text-muted-foreground min-h-10">{item.description || "No description"}</p><div className="mt-4 flex items-center justify-between text-sm"><span className="capitalize rounded border px-2 py-1 text-xs">{item.kind} · {item.status.replaceAll("_", " ")}</span><strong>{formatMoney(item.price, currency)}</strong></div>{item.kind === "product" && <p className="mt-3 text-xs text-muted-foreground">{item.stock_quantity} in stock{item.sku ? ` · ${item.sku}` : ""}</p>}</article>)}</div>}
    {open && <div className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm p-4 overflow-y-auto"><form onSubmit={save} className="max-w-xl mx-auto my-8 rounded-xl border bg-card p-6 space-y-5"><div className="flex justify-between"><div><p className="text-xs uppercase tracking-widest font-bold text-primary">Agency catalog</p><h2 className="font-display text-2xl font-black mt-1">{editing ? "Edit item" : "Add item"}</h2></div><button type="button" onClick={close} aria-label="Close"><X className="w-5 h-5" /></button></div><div className="grid sm:grid-cols-2 gap-4"><Field label="Type"><select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} className="w-full h-10 rounded-md border bg-background px-3 text-sm"><option value="service">Service</option><option value="product">Product</option></select></Field><Field label="Status"><select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })} className="w-full h-10 rounded-md border bg-background px-3 text-sm"><option value="active">Active</option><option value="inactive">Inactive</option><option value="sold_out">Sold out</option></select></Field><Field label="Name"><input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="w-full h-10 rounded-md border bg-background px-3 text-sm" /></Field><Field label={`Price (${currency})`}><input required type="number" min="0" step="0.01" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} className="w-full h-10 rounded-md border bg-background px-3 text-sm" /></Field>{form.kind === "product" && <><Field label="SKU"><input value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} className="w-full h-10 rounded-md border bg-background px-3 text-sm" /></Field><Field label="Stock quantity"><input type="number" min="0" step="1" value={form.stock_quantity} onChange={(e) => setForm({ ...form, stock_quantity: e.target.value })} className="w-full h-10 rounded-md border bg-background px-3 text-sm" /></Field></>}</div><Field label="Description"><textarea rows="4" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="w-full rounded-md border bg-background px-3 py-2 text-sm" /></Field><button disabled={saving} className="w-full h-11 rounded-lg bg-primary text-primary-foreground font-semibold disabled:opacity-60">{saving ? "Saving..." : editing ? "Save changes" : "Add item"}</button></form></div>}
  </div>;
}

function Field({ label, children }) { return <label className="block space-y-1.5"><span className="text-xs font-semibold uppercase text-muted-foreground">{label}</span>{children}</label>; }
function ModuleDisabled({ title, wsId }) { return <div className="p-6 sm:p-10 max-w-3xl mx-auto"><div className="rounded-xl border border-dashed bg-card p-10 text-center"><PackageOpen className="w-10 h-10 mx-auto text-muted-foreground" /><h1 className="mt-4 font-display text-2xl font-black">{title} is not active</h1><p className="mt-2 text-sm text-muted-foreground">Install the Agency module in workspace settings to manage your catalog.</p><Link to={`/app/w/${wsId}/settings`} className="mt-5 inline-flex h-10 items-center rounded-full bg-primary px-4 text-sm font-semibold text-primary-foreground">Open settings</Link></div></div>; }
