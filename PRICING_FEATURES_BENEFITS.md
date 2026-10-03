# Arevei pricing page: features and benefits draft

## Positioning

**Headline:** From new lead to next action, keep your sales team moving.

**Supporting copy:** Arevei brings AI lead qualification, CRM records, follow-ups, team assignments, and performance reporting into one workspace. Your team keeps control of customer conversations and closing decisions.

## Feature and benefit copy

| Feature to show on a plan | Customer-facing benefit | Scope to preserve in the final copy |
| --- | --- | --- |
| AI first-call qualification | Give salespeople a useful briefing before they call: answers, call outcome, summary, and next action stay with the lead. | Requires a configured voice provider, qualification profile, and calling mode. Calls depend on provider availability and usage. |
| Flexible lead capture and CRM | Keep names, contact details, campaign source, notes, and stage history in one place instead of switching between spreadsheets and chats. | Supports manual and connected lead sources; describe specific integrations separately. |
| AI Manager chat | Ask for lead information, create or update CRM records, and coordinate follow-ups in plain language. | Describe only supported CRM actions; specialist calls and saved writes appear in activity. |
| Follow-up planner and AI suggestions | See who needs attention and plan a relevant next conversation using the lead's history. | Suggestions are editable drafts. Saving a follow-up does not automatically call or message the lead. |
| Sales pipeline and assignments | Give each lead a clear owner and stage, so handoffs are visible and the next action is easier to find. | Stage names are configurable. Assigning a lead does not contact the salesperson. |
| Lead and sales performance | See lead volume, junk and not-qualified rates, conversions, stage counts, calling outcomes, and qualification accuracy. | Reports use selected date ranges; some sales stages appear only when configured in CRM. |
| Sales team access | Give sales agents and channel partners access to the leads they handle and their own performance. | Access is based on current assignment and membership. Invitation links are sent manually. |
| Payment records and documents | Track agreed amounts, payment plans, receipts, and final invoices alongside the customer record. | This records payments and creates documents; it is not a payment gateway. |
| Property inventory (for real estate teams) | Link leads to the right property and unit, see availability, and record completed sales or rentals. | Present as a real estate feature; linking interest does not reserve a unit. |
| Business knowledge and content tools | Keep company context available for the AI Manager and draft content aligned with the business. | Brain uses website content and saved edits. Content drafts need review where configured; social publishing and image generation are not connected. |

## Short card bullets

- Qualify new leads with an AI voice flow.
- Keep every lead, note, and call result together.
- Plan follow-ups and assign the right salesperson.
- See conversions and sales activity in one report.
- Give your team access to the leads they own.

## Suggested pricing-page sections

1. **Capture and qualify:** lead capture, first-call qualification, call summaries, qualification rules.
2. **Work and close:** CRM stages, notes, follow-ups, team assignments, payment records, property inventory where relevant.
3. **Measure and improve:** lead and sales performance, calling outcomes, qualification review, individual sales performance.

## Decisions needed before plan cards are published

- Which features are included in each plan, and whether real estate inventory is a separate plan or add-on.
- Usage allowances for AI model requests, voice calls/minutes, leads, workspaces, and team seats.
- Whether voice provider charges, telephony, SMS, and other external services are included or billed separately.
- Trial length, support level, billing interval, taxes, and overage policy.

These are copy and packaging suggestions. The repository does not currently define billing entitlements or public plan prices.

## Proposed $100 monthly AI credit: how to measure it

**Working definition:** One paying customer account receives $100 of included AI usage per billing month. Its workspaces and team members draw from the same balance. Keep voice-provider/telephony, SMS, and other external service charges separate unless a plan explicitly says they are included. A customer's own provider key should not consume an Arevei-funded credit unless Arevei is paying that provider bill.

**Current state:** `backend/ai_usage.py` records provider, model, process, token counts, status, and timestamp under `workspace_id`. Settings shows token counts for 7, 30, or 90 days. The Billing section combines this month's workspace events for an owner and estimates Bedrock cost using operator-configured model rates. There is no immutable dollar ledger, provider invoice reconciliation, credit adjustment workflow, or limit enforcement. The estimate therefore cannot prove the final billable amount.

**Metering design:**

1. Assign every workspace to a stable `billing_account_id`. Shared workspaces and invited team members use the paying account's balance. Do not infer the payer from the signed-in user for each request.
2. At each billable model request, record one immutable usage event with `billing_account_id`, `workspace_id`, workflow, provider, resolved model, provider request ID, idempotency key, UTC time, reported input/output/cache token counts, and status. Never store prompts or model responses in this ledger.
3. Calculate a USD amount from a versioned rate card for that provider, model, region/service tier, and token type. When the provider supplies an authoritative per-request charge, store that separately and use it to reconcile the calculated amount. Store money as integer microdollars (or another fixed-point unit), not floating-point dollars. Missing usage or price data must be marked **unpriced**, never silently counted as $0.
4. Sum priced events for the account's billing period. `remaining = max(0, $100 - used)`. Show used, remaining, reset date, unpriced usage, and a breakdown by workspace/workflow/model. Keep the provider's actual cost and the customer-facing credit deduction as separate fields if pricing includes a markup or discount.
5. Before a new AI request, atomically reserve an estimated maximum cost from the remaining balance; on completion, replace the reservation with actual usage and release any difference. Use idempotency keys so retries and callbacks cannot deduct twice. At the limit, block new included AI work or offer a top-up/overage plan; keep ordinary CRM access available.
6. Reconcile the event ledger with provider billing reports daily. Investigate missing usage, failed requests that incurred a provider charge, and model/rate changes. Do not use the provider's delayed invoice as the real-time gate.

**Example display:** `$23.40 of $100 AI credit used` · `$76.60 remaining` · `Resets on [billing date]`.

**Implementation gap to resolve before launch:** Route every included AI feature through the meter, including streaming calls, background jobs, model fallbacks, and the separate coding agent if it belongs in the credit. Decide whether the credit covers voice AI minutes and whose provider credentials pay for them. Existing `ai_usage_events` are useful operational history, but old events cannot be priced reliably without complete usage and a historical rate card.

**Provider references:** [Amazon Bedrock Converse usage fields](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html), [Amazon Bedrock cost reconciliation](https://docs.aws.amazon.com/bedrock/latest/userguide/cost-mgmt-understanding-cur-data.html), and [OpenRouter per-generation cost metadata](https://openrouter.ai/docs/api/api-reference/generations/get-generation).

### Billing view in Settings

The first Billing view reports the current UTC calendar month's AI usage across workspaces owned by the same account. It shows a $100 monthly credit, an estimated priced Bedrock amount, a model breakdown, and a warning when any call has no token count or matching price. Only workspace owners can request this report. It does not stop AI calls at the credit limit.

Set `AI_MONTHLY_CREDIT_USD=100` and configure the current provider/model prices on the backend using `AI_BILLING_RATES_JSON`. Values are USD per million tokens; the provider/model key must match the recorded usage event exactly. For example, the **illustrative values below are placeholders and must be replaced with the account's verified AWS prices before use**:

```text
AI_BILLING_RATES_JSON={"bedrock::your-model-id":{"input_per_million_usd":"1.00","output_per_million_usd":"2.00","cache_read_per_million_usd":"0.10","cache_write_per_million_usd":"1.25"}}
```

If cache tokens are present, the rate for each used cache token type must be supplied to price that event. Model rates vary by region, service tier, and contract. The current report applies the configured rates to all events in the displayed month, including earlier events, so it is an estimate rather than an immutable invoice. A production credit ledger still needs rate snapshots at request time, explicit handling of credit adjustments, and reconciliation against AWS billing data. Voice, telephony, SMS, and non-Bedrock model charges are excluded from the priced amount and are flagged where usage events exist.
