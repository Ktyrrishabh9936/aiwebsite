# Workspace login and sales access

Owners retain the existing workspace dashboard. In **CRM > Sales team > Workspace login & access**, select an active sales agent or channel partner, enter their login email, and create an invitation. Copy and send the invitation link yourself; creating it does not send email or SMS. Invitations expire after seven days and a replacement invitation invalidates the previous link.

The invited person opens the link and signs in or creates an account using the specified email. Their account is linked to the existing sales contact and opens that workspace's sales portal. Accounts can belong to several workspaces; the workspace switcher lists the workspaces they can currently access.

| Workspace role | Access |
| --- | --- |
| Owner | Existing workspace, sales assignments, invitations, payment and conversion controls, settings, and team reports |
| Sales agent | Currently assigned leads, contact details, ordinary notes, follow-ups, referral/marketing lead creation, and their own performance |
| Channel partner | Leads assigned to them or introduced by them, notes, follow-ups, referral/marketing lead creation, and their own performance |

Member lead creation records introduction credit and marketing/referral source. Selecting a property records the referral property; it does not reserve an inventory unit. Automatic AI calls are disabled for these leads.

Permitted lead panels reuse the desktop CRM's qualification results, call history, summaries, transcripts, recordings and notes components. Members can compose WhatsApp messages, mark them sent into the shared lead notes, and send/view SMS using the workspace's enabled Twilio configuration. Each messaging and history request checks the current lead assignment. Members cannot edit Twilio credentials, change qualification profiles, delete notes, or trigger/cancel AI calls.

Owners can revoke or restore membership, deactivate a sales contact, and revoke or reassign shared leads. The API checks live membership, contact status, workspace, and lead assignment on every member request. A signed-in member cannot use the owner CRM or settings API. Existing login tokens do not retain revoked workspace access. The portal refreshes every 15 seconds and on window focus to clear inaccessible lead details.

Lead sharing now uses an authenticated workspace URL. Invite the agent and have them accept first. Former unauthenticated bearer links return HTTP 410. Reassignment preserves historical sales credit after conversion.

For deployment, run the idempotent migration from the repository before starting the updated API:

```powershell
& .\.venv\Scripts\python.exe backend/migrate_workspace_access.py
```

It creates membership uniqueness and lookup indexes, preserves existing owners, and removes retired bearer-link metadata. Ownership is also recognized directly from each workspace's existing `user_id`, including newly created workspaces.

Invitation and lead URLs use the frontend's current address. For remote team members, generate links on a publicly reachable deployment; localhost URLs are usable only on that computer.
