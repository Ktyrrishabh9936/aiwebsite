# Workspace login and sales access

Owners retain the existing workspace dashboard. In **CRM > Sales team > Workspace login & access**, select an active sales agent or channel partner, enter their login email, and create an invitation. Copy and send the invitation link yourself; creating it does not send email or SMS. Invitations expire after seven days and a replacement invitation invalidates the previous link.

The invited person opens the link and signs in or creates an account using the specified email. Their account is linked to the existing sales contact and opens that workspace's shared CRM. Accounts can belong to several workspaces: the **Workspaces** menu lists their own workspaces and the ones shared with them, and lets them create a workspace of their own, which stays separate from the shared one.

| Workspace role | Access |
| --- | --- |
| Owner | Existing workspace, sales assignments, invitations, settings, and team reports, plus everything below on every lead |
| Sales agent | Currently assigned leads: stage and contact-detail edits, notes, follow-ups, conversion, payment plans, receipts and final invoices, AI Insights, referral/marketing lead creation, Agent Mode, and their own performance |
| Channel partner | Leads assigned to them or introduced by them, with the same lead controls as a sales agent |

Member lead creation records introduction credit and marketing/referral source. Selecting a property records the referral property; it does not reserve an inventory unit. Automatic AI calls are disabled for these leads.

The shared page uses the owner CRM itself (list and pipeline views, stage dropdowns, follow-up rows) with a header that names the organization, who shared the workspace, the member's sales identity and role, and the scope of their access. The lead panel shows every owner tab: AI Insights, Details, Qualification, Follow-up, Payments, Receipts, Invoice and Notes. Members can move a lead to any pipeline stage, including **Won**; marking a real-estate lead won books its unit exactly as the owner CRM does. Members convert leads and record payments, receipts and final invoices; these reuse the owner's handlers after the lead permission check. Phone, source, assignment and Meta import fields stay owner-managed. Each member stage change or conversion records `status_changed_by` on the lead and triggers the same Google Sheet status sync as owner changes. Follow-ups use the owner's planner (edit, reschedule, complete, cancel, reopen) without device push setup. Labels, test-lead, sharing, assignment, trash, Meta mapping, note deletion, AI calling, and the CRM Settings, Sales team, Performance and Follow-up calendar tabs remain owner-only. AI Insights for members omit the customer's lifetime history, because it spans deals other salespeople may own.

**Agent Mode** is available in the shared workspace. The member's AI Manager uses a narrower tool set (`backend/member_manager.py`): it can search and read the member's leads, update stages and contact fields, add notes, manage follow-ups, read insights and qualification status, convert leads, manage payment plans, record payments, generate invoices, and report the member's own performance. Every tool call re-checks membership and resolves leads only through the member's permitted-lead scope. AI usage is billed to the shared workspace.

Permitted lead panels reuse the desktop CRM's qualification results, call history, summaries, transcripts, recordings and notes components. Members can compose WhatsApp messages, mark them sent into the shared lead notes, and send/view SMS using the workspace's enabled Twilio configuration. Each messaging and history request checks the current lead assignment. Members cannot edit Twilio credentials, change qualification profiles, delete notes, or trigger/cancel AI calls.

Owners can revoke or restore membership, deactivate a sales contact, and revoke or reassign shared leads. The API checks live membership, contact status, workspace, and lead assignment on every member request. A signed-in member cannot use the owner CRM or settings API; their shared CRM uses the `/sales-portal` routes, which mirror the owner CRM's route shapes. Existing login tokens do not retain revoked workspace access. The portal refreshes every 15 seconds and on window focus to clear inaccessible lead details.

Lead sharing now uses an authenticated workspace URL. Invite the agent and have them accept first. Former unauthenticated bearer links return HTTP 410. Reassignment preserves historical sales credit after conversion.

For deployment, run the idempotent migration from the repository before starting the updated API:

```powershell
& .\.venv\Scripts\python.exe backend/migrate_workspace_access.py
```

It creates membership uniqueness and lookup indexes, preserves existing owners, and removes retired bearer-link metadata. Ownership is also recognized directly from each workspace's existing `user_id`, including newly created workspaces.

Invitation and lead URLs use the frontend's current address. For remote team members, generate links on a publicly reachable deployment; localhost URLs are usable only on that computer.
