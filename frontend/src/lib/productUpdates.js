// Add a release here when its features are ready to ship. IDs must remain stable.
export const PRODUCT_UPDATES = [{
  id: "2026-10-10-sales-lifecycle", date: "2026-10-10", title: "Customer lifecycle & sales intelligence",
  features: [
    { id: "customers", title: "Customers & lifetime value", description: "View customer relationships, collected lifetime value, payment status and linked purchases. Add an upsell lead or remove a customer from the list while preserving payment history.", path: "customers", selectors: ['[data-testid="nav-customers"]'] },
    { id: "upsells", title: "Customer selection & upsell leads", description: "Select an existing customer in Create Lead. Repeat requests create linked opportunities, highlighted as UPSELL in CRM list and pipeline views.", path: "crm", selectors: ['[data-testid="nav-crm"]', '[data-update="customer-selection"]'] },
    { id: "insights", title: "AI Insights for each lead", description: "Open a lead's AI Insights tab to review next actions, customer history, LTV and outstanding payments.", path: "crm", selectors: ['[data-update="lead-insights"]'] },
    { id: "manager", title: "AI Manager: Check Insights", description: "Use Check Insights in chat to review live CRM priorities. An empty pipeline guides you to train your Brain and build a sales strategy.", path: "manager", selectors: ['[data-testid="nav-ai-manager"]', '[data-update="check-insights"]'] },
    { id: "strategy", title: "Sales strategy in your Brain", description: "Save company, offer, customer, team, budget and revenue context under Brain → Sales strategy, then prepare an evidence-led sales plan.", path: "brain?tab=sales", selectors: ['[data-testid="nav-brain"]', '[data-update="sales-strategy"]'] },
  ],
}];

export function readSeenUpdates(key) {
  try { const ids = JSON.parse(localStorage.getItem(key) || "[]"); return Array.isArray(ids) ? ids : []; } catch { return []; }
}

export function unreadUpdates(seen) { return PRODUCT_UPDATES.filter(release => !seen.includes(release.id)); }
