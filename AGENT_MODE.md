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

This first version exposes CRM operations, business context, task/property reads,
and existing follow-up/qualification specialists. Other galaxy sections remain
conversation focus controls; they do not imply tools for every application action.
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
