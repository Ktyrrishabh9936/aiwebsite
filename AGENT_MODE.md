# Agent Mode testing

Deploy both backend and frontend. Agent Mode uses the workspace's selected model
and existing provider credentials; the model must support native tool calling.
No additional notification or voice keys are needed for internal CRM actions.
Initial qualification still needs the existing voice provider configuration.

Switch to Agent Mode and use the chat. The manager chooses application tools from
conversation context and their results, rather than matching predefined command
sequences. The galaxy highlights the section currently being used. Team activity
shows confirmed reads, saved changes, failures, and pending specialist calls.

Try these using a test lead:

- “How many pending follow-ups do we have? Which leads should I call?”
- “Read Rahul's details.” If multiple leads match, specify which one.
- “Schedule a follow-up for him tomorrow at 11 AM.”
- “Add a note: I called him; he asked for the brochure.”
- “Assign him to [salesperson name].”
- “Ask the follow-up specialist what we should do next.”

Check the saved records in Human Mode. Chat-created leads preserve the existing
automatic initial qualification workflow, including lead context preparation,
the configured voice agent, and qualification results saved on the lead. Ask to
skip the AI call explicitly when creating a lead if needed. Do not separately
request another call for a lead already scheduled. Initial AI qualification for
an existing unscheduled lead can also be explicitly delegated;
subsequent customer calls remain human work. Assignment saves the handover but
does not telephone or message the salesperson.

Conversation memory and execution events are stored per user and workspace in
`manager_conversations` and `manager_runs`. Completed writes are deduplicated
within a run; the same request ID replays its recorded run. Reads refresh actual
application state. Returning to Agent Mode restores conversation and activity.
The activity panel polls qualification sessions for actual call outcomes.

The manager operates every workspace page from chat (`manager_tools.py` for leads and
follow-ups, `manager_page_tools.py` for the rest). Each tool calls the page's own route
handler, so validation and module gating match Human Mode:

- CRM: leads, stages, notes, tags, follow-ups, assignment, attached offerings, trash/restore.
- Customers and payments: customer LTV and dues, conversion (single payment or plan),
  payment plans, payment receipts, final invoices, repeat/upsell opportunities.
- Products & Services, Properties and flats, Tasks (run, approve, record outcomes),
  Brain facts, sales setup, strategy and review, sales team, Qualification calling
  settings and profiles, Landing Page Forms, Workflows, Blogs, settings and notifications.

Not available from chat: permanent deletion, sending SMS/WhatsApp/email, charging
payments, billing changes, voice provider keys and Google Sheet connection. For those
the manager answers from the product guide with the menu path.

Writes are refused until the record was read in the same conversation (IDs read are
remembered across turns in `manager_conversations.known`). Payments require reading
the lead's payments first; a payment plan without a total defaults to the stage sum.
Every tool result carries `shown_on`, the exact menu location, and chat links open it.
The floating chat in Human Mode and the AI Manager page use the same agent and
conversation; they send the current page (and open lead) as context. After a saved
change the visible page reloads (CRM refreshes in place).

Try, with a test lead: "Priya closed at 50000 single payment, convert her",
"She paid 20000 by UPI today", "Which customers owe money?", "Add a service called
SEO Retainer at 25000", "Add Surat to our locations in the Brain",
"Add Neha to the sales team and assign Rahul to her", "Switch AI calling to manual".
Analytics disclose the existing 5,000-lead cap and provide an exact active total.
Each request is limited to 48 model rounds, 96 operations and five minutes.

Orchestration continues in the current backend process if the chat stream closes.
Returning to Agent Mode restores saved activity; do not repeat a running request.
Already saved changes and already delegated provider calls remain in place.
Check activity before resubmitting after an interrupted connection. A separate
durable worker is needed for orchestration that must survive backend restarts.

Automated tests use mocked model replies and an isolated database. They verify
real follow-up persistence, request replay, permissions, tool results and activity
states. Live model/voice behavior still needs testing with the deployed providers.
