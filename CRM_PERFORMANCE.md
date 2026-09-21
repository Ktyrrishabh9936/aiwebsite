# CRM Performance and qualification review

Open **CRM → Performance**. Review AI results in **CRM → Records → select a lead → AI Qualification Review**.

## Scope and calculations

The default is the last 30 UTC calendar days, inclusive. This is a **lead cohort** report: it selects non-trashed leads created in the date range. It reports their current qualification and current human review, and calls attempted in the same date range for those leads. It is not a historical end-of-day snapshot or a report of calls to older leads. The UI explains this scope.

Lead status filters use the current CRM sales-pipeline `status`. Qualification profile filters use recorded call profile IDs for calls and the latest saved result's profile for qualification/review. A lead is included if its current result/assignment or an in-range call matches the profile. Calls without a recorded profile are not attributed to a newly assigned profile.

| Metric | Definition |
| --- | --- |
| Eligible leads | Saved normalized phone, no DND, no junk restriction. This is basic lead eligibility, not confirmation of provider readiness, calling hours, active calls or remaining automatic retries. |
| Calls attempted | Existing sessions that reached/may have reached a provider, merged with matching qualification decision logs. Provider identifiers are scoped by provider; callback events never count as new calls. Legacy latest-call data is used only when no session/history exists. |
| Connected | Engine connection outcome, or answer/completion evidence when no engine outcome exists. Dropped conversations may be connected but not completed. |
| No answer | No answer, switched off and unreachable outcomes. |
| Failed | Technical failures, invalid numbers, or failed/error/cancelled transport status without an engine outcome. |
| Completed conversations | Connected terminal conversations, excluding dropped calls. |
| Connection rate | Connected calls / attempted calls. |
| Average duration | Mean recorded seconds for completed conversations; missing values are excluded. |
| Qualified | Latest AI result QUALIFIED/SALES_READY, or a legacy qualified result. |
| Disqualified | Latest AI result UNQUALIFIED/JUNK, or a legacy not-qualified result. |
| Follow-up required | Partial qualification, retry/callback/follow-up next action, or an open qualification follow-up task. May overlap other qualification outcomes. |
| Qualification completion | Qualified + disqualified results / saved AI qualification results. Pending/partial results are incomplete. |
| Accuracy | Current Correct reviews / (current Correct + Incorrect reviews). Not Reviewed is excluded. With no reviewed results, API accuracy is null and UI says “Not enough reviewed data”. |

Unknown rates and durations are `null`, displayed as an em dash. There are no synthetic metrics, cost metrics, campaign metrics or provider comparisons.

## Existing data and APIs

- `crm_leads`: current qualification result/data, pipeline status, review state, existing `timeline` for review audit events.
- `plivo_call_sessions`: transport attempts, identifiers, status, duration, frozen profile ID.
- `crm_call_logs` with `kind=qualification_engine`: normalized per-call decisions and facts.
- `tasks`: existing open qualification follow-ups.
- `qualification_profiles`: existing filter options. Raw `plivo_call_events` are not counted as calls.

`GET /api/workspaces/{ws_id}/crm/performance?start=YYYY-MM-DD&end=YYYY-MM-DD&profile_id=...&status=...`

Returns `funnel`, `calling`, `qualification`, `reviews`, `filters` and `date_basis`. Mongo performs an initial workspace/date/status match and indexed workspace/lead lookups. Results are projected and streamed into counters, without loading a capped lead list, transcripts or raw provider payloads. Performance is fetched only while the tab is mounted or filters/Refresh change; no new polling loop is introduced.

`GET /api/workspaces/{ws_id}/crm/leads/{lead_id}/qualification-review`

Returns the result to review, its `source_version`, whether an older review is stale, and current review state. Existing leads default to Not Reviewed without a migration.

`PUT` to the same path accepts `status`, `note`, `incorrect_fields` (top-level fact keys) and `source_version`. It validates workspace ownership and the existence of an AI qualification, derives reviewer ID/name from authentication, and atomically saves `qualification_review` and appends a `qualification_review` event to the lead's existing `timeline`. The event records the old/new state, actor, timestamp and reviewed result. AI facts and calling behavior are untouched.

A source fingerprint binds a review to the exact result and call. If a later call changes the result, the old review remains in the timeline but no longer contributes to accuracy. An optimistic database condition rejects concurrent result/review changes with HTTP 409. Clearing a review to Not Reviewed is also audited.

## Indexes

Existing indexes cover call-session and call-history workspace/lead joins. For growing workspaces, apply these additive indexes during database deployment/setup (not on every function cold start):

Run `python migrate_crm_performance.py` from the backend directory with that deployment's `MONGO_URL` and `DB_NAME`. The script adds only the indexes below and does not change lead records.

```javascript
db.crm_leads.createIndex({workspace_id: 1, created_at: -1})
db.tasks.createIndex({workspace_id: 1, lead_id: 1, source: 1, status: 1})
```

The report does not write or duplicate call/qualification records. No calling scheduler, Plivo transport, Sarvam transport, qualification rules or webhook behavior is changed.
