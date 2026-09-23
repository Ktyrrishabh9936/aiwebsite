# Meta leads through Google Sheets

The existing Google Sheets integration imports leads and writes CRM status changes back to their source Sheet. No Meta credentials, OAuth, campaign automation, CAPI calls, or conversion events are added.

## Deployment and configuration

1. Deploy backend and frontend together. From `backend`, run `../.venv/Scripts/python.exe migrate_meta_sheets.py` (or `python migrate_meta_sheets.py` in an activated environment). Use `--workspace-id ID` to limit the backfill. This follows the existing explicit Python/Mongo migration convention; it is idempotent, adds indexes, and backfills attribution from saved raw rows. It never changes CRM statuses or sends Sheet writes. It has not been run against the application database by this implementation task.
2. Reconnect Google from the Ads → CRM workflow to grant `https://www.googleapis.com/auth/spreadsheets`. Old read-only grants cannot write status. Existing Google OAuth client configuration is reused. See [Google's values.update reference](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/update).
3. Bind the source spreadsheet/tab and save the mapping. Map `id` to **Meta Lead ID**, all desired attribution fields, and an existing status column to **CRM Status (write-back)**. The existing Phone mapping remains required. Preserve IDs as plain text in Sheets, especially long IDs: digits already rounded by Sheets cannot be recovered by CRM.
   Binding runs the workspace's configured AI model against header names and CRM field definitions, then fills suggested mappings for review. Only exact Sheet headers and valid CRM targets are accepted, and one Sheet column cannot be assigned twice. If the model is unavailable, high-confidence exact/alias matches are applied with a visible warning. Nothing is saved until the user selects **Save Column Mapping**.
4. Add any form-answer fields through existing CRM field settings, then map their Sheet columns. No industry-specific fields were added. Headers are matched case-insensitively after trimming; ambiguous duplicates are rejected. Columns beyond Z and tabs with spaces/apostrophes are supported.
5. Set `PUBLIC_BASE_URL` to the backend's stable public HTTPS origin, then activate the workflow. Activation registers a Google Drive `files.watch` channel for the bound spreadsheet. Google calls `/api/google/webhooks/drive` when the file changes, and the backend imports appended rows immediately. Drive file channels expire after at most one day, so `DISABLE_BACKGROUND_JOBS` must not be true in production: the background job renews channels before expiry but does not poll rows. `BACKGROUND_WORKSPACE_IDS`, when set, must include the workspace. Automatic status-write retries use the same background job; direct CRM edits still attempt write-back immediately.
6. For old rows lacking enough stored attribution, refresh/rebind the original Sheet and reimport with Meta ID mapping. Review the source binding before migration if a workspace previously switched spreadsheets. Legacy rows with an ID-only key do not encode their original spreadsheet, so migration can only associate them with the current binding. Failed/unverifiable matching is visible in lead details.

## Behavior

- All twelve Meta fields are nullable source fields. Existing internal `campaign_id` belongs to qualification campaigns, so external attribution uses `meta_campaign_id` to avoid mixing identities.
- The existing `status` is the sales status; `lead_status` remains the separate qualification-engine result. Conversion continues to set `won`. Write-back uses the configured status label (default `Won`, or a custom label such as `Converted`). It does not introduce or rename pipeline states.
- CRM edits, pipeline moves, conversion, manager changes, qualification decisions, and junk marking enqueue status writes atomically with the CRM update. Unchanged statuses do not enqueue writes. Background-origin changes are processed by the poller.
- The stored source spreadsheet/tab is checked against the connection. Meta Lead ID locates the row every time; cached row numbers are diagnostic references, not authoritative identifiers. Missing or duplicate IDs fail without guessing by phone/email/name. Restoring the original binding is required after a source mismatch.
- Only the mapped status cell is written, using RAW input. If it already contains the desired label, no write is issued. Sheet import initializes status for a new lead from a recognized mapped state; replay never overwrites an existing CRM status or enqueues write-back.
- Imports are webhook-triggered and remain append/cursor based. Google notifications contain no row data, so an authenticated notification causes the backend to fetch only bounded new-row batches. Replays enrich attribution without replacing user-edited general fields, and an import lease plus the existing unique row key makes duplicate/concurrent notifications safe.
- Sync fields expose `pending`, `success`, or `failed`, a safe error, and the last **successful** sync time. Failures preserve CRM changes and retry with capped exponential delay. Manual retry bypasses the delay. A database lease prevents overlapping workers; a crashed worker's lease expires after five minutes. Completion only acknowledges the status version sent, so a newer change stays pending.
- Rows must not be sorted/deleted concurrently during a write: Google values updates have no atomic “write where ID equals X” operation. Lookup handles rows moved before the sync; concurrent structural Sheet changes remain a limitation.

## Files changed for this feature

- `backend/models.py`: nullable Meta/source/sync fields.
- `backend/meta_fields.py`: attribution mapping, header matching, status-change detection.
- `backend/google_sheets.py`: Drive webhook registration/validation/renewal, mapping targets/validation, import helper, status write-back, retries.
- `backend/crm.py`: status/conversion triggers and reserved source fields.
- `backend/server.py`: webhook-channel renewal and manager status triggers; row polling was removed.
- `backend/qualification_service.py`, `backend/plivo_calls.py`: automated status triggers.
- `backend/migrate_meta_sheets.py`: backfill and indexes.
- `backend/tests/test_meta_sheets.py`: mapping, matching, status transitions, retry, races, migration, legacy behavior, and HTTP contract tests.
- `frontend/src/pages/sections/AdsToCrmWorkflow.jsx`: mapping choices and Google reconnection button.
- `frontend/src/pages/sections/CrmInbox.jsx`: attribution section in existing details panel.
- `frontend/src/components/MetaAttribution.jsx`, `MetaAttribution.test.jsx`: read-only attribution and retry UI/tests.
- `META_SHEETS_SYNC.md`: setup, behavior, and implementation record.
- `test_reports/meta-sheets-backend.xml`: generated backend test report.

## Verification

The automated tests mock Google HTTP calls and use isolated Mongo test databases. A live Google end-to-end check still requires reconnection, mappings, and an authorized test Sheet. No real Google Sheet was modified during testing.

Backend regression command (excludes existing tests that target live preview/Daytona services):

```text
python -m pytest tests --ignore=tests/backend_test.py --ignore=tests/test_coding.py --ignore=tests/test_lead_connector.py -q --junitxml=../test_reports/meta-sheets-backend.xml
```

Frontend: `npm test -- --watchAll=false --runInBand`; production build: `npm run build`.

Results: **221 backend tests passed**, **34 frontend tests passed across 11 suites**, and the production build compiled successfully. Changed Python modules passed `py_compile`; `git diff --check` passed. Backend tests emitted existing dependency/lifecycle and test-key warnings. The initial sandboxed backend test attempt could not access pytest's Windows temporary directory; the approved rerun succeeded. Existing live-preview/Daytona test modules were excluded as shown above.
