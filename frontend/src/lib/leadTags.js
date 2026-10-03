export const tagColors = {
  emerald: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  amber: "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400",
  blue: "border-blue-500/40 bg-blue-500/10 text-blue-700 dark:text-blue-400",
  violet: "border-violet-500/40 bg-violet-500/10 text-violet-700 dark:text-violet-400",
  rose: "border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-400",
  slate: "border-slate-500/40 bg-slate-500/10 text-slate-700 dark:text-slate-300",
  cyan: "border-cyan-500/40 bg-cyan-500/10 text-cyan-700 dark:text-cyan-400",
  orange: "border-orange-500/40 bg-orange-500/10 text-orange-700 dark:text-orange-400",
};
export const defaultTagLibrary = [
  { label: "Qualified", color: "emerald" }, { label: "Manual Review", color: "amber" },
  { label: "Pending", color: "slate" }, { label: "VIP", color: "violet" },
  { label: "Hot Lead", color: "orange" }, { label: "Follow-up", color: "blue" },
  { label: "Repeat Enquiry", color: "cyan" }, { label: "Not Interested", color: "rose" },
];
export function tagColor(tag, library = defaultTagLibrary) {
  return library.find((item) => item.label.toLowerCase() === tag.toLowerCase())?.color || "slate";
}
