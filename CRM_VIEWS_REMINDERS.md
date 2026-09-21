# CRM views and reminders

- **Records → List / Kanban** switches between the existing list and a board grouped by CRM stages. Each board column has its own count and pagination (30 leads per page), so it is not limited to the currently visible list page. Search matches name, phone and email. Open a card to see the full lead; its stage menu saves a pipeline move. Trash continues to use the list.
- **Lead details** has top navigation for Details, Qualification, Reminders, Payments, Receipts, Invoice and Notes. Qualification is no longer placed before every section. Switching leads resets the panel to Details.
- **Lead details → Reminders** creates a manual follow-up with title, local date/time, and what to discuss or share. Existing reminders can be completed, cancelled, reopened, edited or rescheduled.
- **CRM → Reminders** shows the daily contact planner. Choose a date, Today, Overdue or All dates; filter pending/completed/cancelled reminders. Each item shows the lead, phone and sharing instructions. Selecting an active lead opens its record.

Reminders are in-app records, not push/email notifications or automatic calls. Local date boundaries are converted to UTC in the browser (including daylight-saving transitions); the database stores UTC times. The planner paginates at 50 records and supports manual refresh.

## Data and permissions

Uses existing `tasks` with `source=crm_reminder`, `lead_id`, `scheduled_time`, `objective`, `requires_approval=true` and `status`. No separate reminder collection or duplicated lead contact snapshot. The scheduler does not execute them; the task executor rejects manual reminders, and Tasks renders them as human follow-ups. Reminder mutations record actor and time in the task's timeline. Workspace authorization is applied to every new endpoint, including joins to current lead details.

Endpoints under `/api/workspaces/{ws_id}/crm`:

- `GET /pipeline`: stage, search, offset, limit.
- `PATCH /pipeline/leads/{lead_id}`: stage change through the existing CRM update behavior.
- `POST /leads/{lead_id}/reminders`: title, note, timezone-aware due_at.
- `GET /reminders`: lead_id, start/end (exclusive), status, overdue, offset/limit.
- `PATCH /reminders/{id}`: new title/note/due_at or pending/done/cancelled status.

Run `python migrate_crm_performance.py` from the backend directory during deployment for the additional task-date and lead-stage indexes. This adds indexes only. No calling/provider configuration is changed.
