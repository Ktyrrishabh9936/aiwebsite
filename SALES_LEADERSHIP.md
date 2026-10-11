# Sales leadership

## Customer lifecycle

The Customers page derives customer relationships from original won/converted CRM leads. Existing records appear without a migration. Payment completion is shown separately from the existing conversion flag: positive recorded contract value with collected payments covering it is fully paid; otherwise the relationship remains payment pending. LTV is collected receipt revenue across the original deal and explicitly linked repeat deals, excluding failed/pending receipts and test leads. Archived deals remain in history. This is collected revenue, not a forecast of future customer value.

Create repeat opportunities from the customer's lifecycle panel. Upsell, cross-sell and repeat purchase each create a new lead with `customer_id` pointing to the original deal, preserving its payments and identity. Existing qualification configuration is unchanged; explicit repeat creation skips automatic initial qualification for the known customer. Required CRM contact fields are still validated. Leads are never merged automatically by name or phone. Customer lists are paginated and linked history limits are disclosed.

Per-lead insights and the Agent Mode lead-insights tool include linked customer LTV, payment history and the current product/service request.

Open **Sales Strategy** in a workspace to talk with the sales strategist. It asks one missing-context question at a time, uses the selected workspace model to polish each answer, and saves the conversation and draft on the workspace. Existing sales context is retained. Unclear answers get a clarification; optional feedback, sources and constraints can be skipped. The strategy brief supports revising any answer through chat. Review it and choose **Complete sales strategy** to save the profile and generate the plan from Brain knowledge and CRM evidence. If Brain training is incomplete, the context can be saved first. Both frontend and backend must be deployed for the new `/sales/conversation` endpoints.

Draft answers do not update the active sales profile until completion. Chat saves use revisions to prevent overwriting another session's answers. Numeric targets, budgets and all other answers are checked against the existing profile constraints; model failure leaves the previous draft intact. Existing briefing time, timezone and pipeline settings are retained for saved profiles; new profiles use the current timezone and the existing default briefing settings.

The overview briefing refreshes recorded CRM evidence every 60 seconds; selected-lead insights refresh every 30 seconds while the page is visible. These are polling updates, not streaming. Pipeline value uses only an explicitly selected opportunity-value field; lead budgets are never treated as revenue.

The background worker checks every five minutes and creates one morning briefing per local day after the saved briefing hour. It requires a running backend with background jobs enabled. Existing workspace background-job restrictions still apply.

Sales Manager tasks are manual actions with recorded outcomes. They are deduplicated against existing pending lead work. Superseded Sales Manager tasks are cancelled; unrelated tasks are preserved. Briefing and insight reads never initiate calls, move leads, or change qualification settings. Existing Agent Mode and voice qualification remain the execution paths.

Strategy generation uses Brain knowledge, company context and current CRM evidence. Missing feedback or an unvalidated offer becomes a question or validation action rather than an assumed growth result. Snapshot limits are exposed in the briefing.

Validation covers sales evidence, task deduplication, ownership, morning timing, strategy setup, and existing manager/qualification flows. Frontend checks cover setup, briefing and changing the selected lead.
