import { useState } from "react";
import { NavLink } from "react-router-dom";
import { LayoutDashboard, Users, Building2, Boxes, ListChecks, Brain, MessageSquare, Bot, Workflow, FileText, Code2, Settings, Search, PackageOpen } from "lucide-react";

export const navigationGroups = [
  { label: "Workspace", items: [{ to: "", label: "Overview", icon: LayoutDashboard }, { to: "crm", label: "CRM", icon: Users }, { to: "properties", label: "Properties", icon: Building2, module: "real_estate" }, { to: "products-services", label: "Products & Services", icon: PackageOpen, module: "agency" }, { to: "projects", label: "Projects", icon: Boxes }, { to: "tasks", label: "Tasks", icon: ListChecks }] },
  { label: "AI & automation", items: [{ to: "manager", label: "Manager", icon: MessageSquare }, { to: "agents", label: "AI Agents", icon: Bot }, { to: "qualification", label: "Qualification", icon: ListChecks }, { to: "brain", label: "Brain", icon: Brain }, { to: "workflows", label: "Workflows", icon: Workflow }] },
  { label: "Content", items: [{ to: "blogs", label: "Blogs", icon: FileText }, { to: "embed", label: "Add Blog System", icon: Code2 }] },
  { label: "Preferences", items: [{ to: "settings", label: "Settings", icon: Settings }] },
];

export function visibleNavigationGroups(modules = { real_estate: true, agency: false }) {
  return navigationGroups.map((group) => ({ ...group, items: group.items.filter((item) => !item.module || modules?.[item.module] === true) })).filter((group) => group.items.length);
}

export default function WorkspaceNavigation({ wsId, modules, collapsed = false, onNavigate }) {
  const [search, setSearch] = useState("");
  const groups = visibleNavigationGroups(modules).map((group) => ({ ...group, items: group.items.filter((item) => collapsed || `${item.label} ${group.label}`.toLowerCase().includes(search.toLowerCase().trim())) })).filter((group) => group.items.length);
  return <div className="flex-1 min-h-0 flex flex-col">
    {!collapsed && <label className="relative block mx-3 mt-3"><Search size={14} className="absolute left-3 top-3 text-muted-foreground" /><input aria-label="Find a page" placeholder="Find a page…" value={search} onChange={(e) => setSearch(e.target.value)} className="h-9 w-full rounded-lg border bg-background pl-9 pr-3 text-xs focus:outline-none focus:ring-2 focus:ring-ring" /></label>}
    <nav aria-label="Workspace navigation" className="flex-1 overflow-y-auto overscroll-contain p-3 space-y-4">
      {groups.map((group) => <div key={group.label}>
        {!collapsed && <p className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">{group.label}</p>}
        <div className="space-y-1">{group.items.map(({ to, label, icon: Icon }) => <NavLink key={to} to={`/app/w/${wsId}${to ? `/${to}` : ""}`} end={!to} title={collapsed ? label : undefined} aria-label={label} data-testid={`nav-${label.toLowerCase().replace(/\s/g, "-")}`} onClick={onNavigate} className={({ isActive }) => `flex items-center ${collapsed ? "justify-center" : "gap-3 px-3"} min-h-10 rounded-lg text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${isActive ? "bg-primary/10 text-primary ring-1 ring-inset ring-primary/20" : "text-muted-foreground hover:bg-accent hover:text-foreground"}`}><Icon size={17} className="shrink-0" />{!collapsed && <span className="truncate">{label}</span>}</NavLink>)}</div>
      </div>)}
      {!groups.length && <p className="text-xs text-muted-foreground px-3">No pages found. Try CRM, tasks or settings.</p>}
    </nav>
  </div>;
}
