# Workspace voice qualification providers

## Repository inspection (before implementation)

AREVEI uses FastAPI with Motor/MongoDB and a React frontend. Workspace access in
`crm.require_workspace_access` is restricted to the workspace owner or system admin;
there is no separate workspace-member administrator role in this repository.

CRM lead creation/import and public lead submission schedule qualification through
`plivo_calls.schedule_first_qualification_call`. `server.scheduler_loop` selects due
leads and invokes `start_qualification_call`; manual CRM calls use the same entrypoint.
`PlivoCallTriggerService` serializes initiation using a Mongo lead lease. The existing
preflight checks enforce DND, junk, active calls, calling windows and retry limits.

Plivo qualification is primarily an AI Studio/Agent Flow HTTP trigger, with configurable
input mappings, basic/bearer authentication, and workspace agent selection. A separate
legacy staff-bridge call path also exists. It is not the qualification engine.

Callbacks in `server.py` cover outbound answer/status, recording, qualification result,
inbound answer and a legacy unscoped agent callback. `PlivoResponseAdapter` normalizes
payloads into `CallResult`. `qualification_service` resolves frozen profile snapshots,
extracts grounded facts using the existing workspace AI model, runs the deterministic
`LeadQualificationEngine`, and applies results through `CRMLeadUpdateService`.
Event IDs, lead leases and deterministic task/history IDs support retry-safe processing.

Existing collections: `workspaces`, `crm_settings`, `crm_leads`, `qualification_profiles`,
`plivo_agent_configs`, `plivo_workflow_configs`, `plivo_call_sessions`, `plivo_call_events`,
`crm_call_logs`, `tasks`. Workspace settings include the independent AI model and default
qualification profile. Plivo credentials previously lived in plaintext agent documents
and global `PLIVO_*` environment variables; there was no reusable encrypted secret store.
Callback URLs previously fell back to request headers and could contain a global token.

Sarvam previously appeared only in `manager_voice.py`: `/api/ai-manager/voice`,
`ai_manager_voice_connections`, and `ai_manager_voice_sessions`. It invokes the existing
manager services and CRM/Brain tools. That inbound assistant is unchanged and independent.

Frontend entrypoints: workspace `Settings.jsx`, `Qualification.jsx`, CRM agent controls in
`CrmInbox.jsx`, existing `LeadQualificationPanel.jsx` and independent `ModelPicker.jsx`.

## Implementation and changed files

| Files | Purpose |
| --- | --- |
| `backend/voice_config.py` | Workspace/provider encryption, safe configuration, rotation, public projections |
| `backend/voice_providers.py` | Plivo and Sarvam transport, normalization and real API probes |
| `backend/voice_api.py` | Owner/admin settings, connection test, authenticated Sarvam callback |
| `backend/migrate_voice_providers.py` | Explicit workspace migration and encryption-key rotation |
| `backend/plivo_calls.py` | Existing checks/sessions/scheduler entrypoint with adapter dispatch; workspace Plivo authentication |
| `backend/qualification_engine.py` | Profile `voice_provider` enum, default `plivo` |
| `backend/qualification_service.py` | Shared provider-aware controller, canonical callback deduplication, normalized status and structured logs |
| `backend/plivo_response_adapter.py` | Nonterminal initiated/unknown statuses |
| `backend/plivo_agents.py` | Encrypt legacy agent writes; restrict session API projection |
| `backend/qualification_api.py` | Updated authentication guidance; profile APIs automatically accept new field |
| `backend/crm.py` | Redact legacy voice secrets from lead responses |
| `backend/server.py` | Register new APIs/index; scope existing Plivo callback and debug handling |
| `frontend/src/components/VoiceProviders.jsx` | Dynamic workspace configuration, masked secret replacement, test/copy/status controls |
| `frontend/src/pages/sections/Settings.jsx` | Mount Voice Providers beside existing independent AI Manager settings |
| `frontend/src/pages/sections/Qualification.jsx` | Separate voice provider selector |
| `frontend/src/pages/sections/CrmInbox.jsx` | Permit profile-driven calls without requiring a Plivo agent selection |
| `backend/tests/test_voice_providers.py` | Encryption, isolation, normalization, probes and Sarvam integration/replay |
| `backend/tests/test_plivo_calls.py`, `test_qualification_integration.py` | Plivo regression fixtures migrated to tenant credentials/header auth |
| `frontend/src/components/VoiceProviders.test.jsx` | Provider field switching, masking and verification UI |

Existing unrelated working-tree edits were preserved. No AI Manager or model-picker
implementation was replaced.

## Database changes

New `workspace_voice_provider_configs` documents:

```
workspace_id, provider (plivo | sarvam), enabled, config,
encrypted_credentials, configured_secrets (field names only),
status, error_code, revision, created_at, updated_at,
last_verified_at, last_callback_at
```

A unique `(workspace_id, provider)` index is created at startup and by migration.
Credentials are Fernet authenticated ciphertext with workspace/provider bindings inside
the encrypted envelope. `VOICE_CREDENTIAL_KEYS` is an application encryption key ring:
the first key encrypts; all configured keys may decrypt. It is not a customer credential.
Changing tenant or provider on an encrypted record fails decryption.

Existing profile records default to Plivo on read. Migration also backfills the field.
Existing session/event collections retain their names and records. Sessions include
provider, normalized status, provider identifiers, profile snapshot, direction, timestamps,
transcript, duration and engine result. Sarvam stores `attempt_id` and `interaction_id`;
its per-call callback capability is stored only as a digest. No duplicate qualification
result schema or retry scheduler was introduced.

## APIs

All paths are relative to `/api`:

| Method | Path | Authorization |
| --- | --- | --- |
| GET | `/workspaces/{ws_id}/voice-providers` | Workspace owner/admin |
| PUT | `/workspaces/{ws_id}/voice-providers/{provider}` | Workspace owner/admin |
| POST | `/workspaces/{ws_id}/voice-providers/{provider}/test` | Workspace owner/admin |
| POST | `/sarvam/workspaces/{ws_id}/calls/{session_id}/result` | Session-bound callback capability |
| POST | `/workspaces/{ws_id}/voice-providers/sarvam/calls/{session_id}/recording/refresh` | Workspace owner/admin |

PUT accepts `{enabled, config, credentials, revision}`. Empty/omitted credential values
preserve existing secrets. Nonempty values replace them; they are never returned.
Revision guards prevent concurrent settings changes overwriting one another.
Verification reports `connected`, `invalid_credentials`, `missing_configuration`,
`provider_unavailable`, or `configuration_error`; saving resets verification.

Plivo verification calls the account API with workspace credentials. Sarvam verification
calls the Voice Agents analytics API scoped to its organization/workspace/app. Neither
probe places a call. A successful probe proves API access, not a live telephony connection.

Existing Plivo route URLs remain. Workspace callback authentication now resolves the
workspace's token/signature secret. Qualification results accept
`X-Arevei-Webhook-Token` or Bearer authentication, or a valid Plivo V3 signature.
Status/recording/answer routes require a Plivo signature. Global signature-disable flags
and query-string tokens no longer bypass authentication. The legacy
`/plivo/agent/callback` requires `?workspace_id=...`; its call lookups are workspace-scoped.

Sarvam's official outbound API supports webhook metadata but does not document a webhook
signature header. AREVEI sends a per-session HMAC capability in echoed metadata, verifies
its stored digest, and also requires the returned attempt ID to match the session.
URLs contain no secrets. Credential rotation/disable does not invalidate an in-flight
Sarvam capability. Duplicate normalized events return success without another CRM write.
Concurrent processing returns 503 with Retry-After so the provider can retry.

## Provider configuration

Plivo: Auth ID, Auth Token, E.164 calling number, HTTPS `agentflow.plivo.com` trigger URL,
optional flow ID, basic/bearer flow authentication, optional callback token (32+ characters),
optional staff number for the existing staff-bridge feature. Existing default
agent input mappings and flow URL remain usable; account credentials and calling number
come from workspace provider settings. Third-party trigger hosts must be explicitly
reviewed/implemented rather than accepting arbitrary credential-bearing HTTP targets.

Sarvam: Voice Agents API key (not a speech-model subscription key), organization ID,
Sarvam workspace ID, published app ID/version, telephony connection ID and E.164 agent number.
AREVEI generates and encrypts the callback secret automatically; customers do not configure
or copy it into Sarvam. Workspace records use the canonical fields
`organization_id`, `workspace_id`, `app_id`, `app_version`, `connection_id`, and
`agent_phone_number`; older `org_id`, `sarvam_workspace_id`, and `from_number` records are
translated when read. Qualification calls use the Instant Outbound `/outbounds` endpoint,
one request per lead, and store its returned `attempt_id` on the existing call session. Secret
regeneration affects new calls only because each initiated session retains its capability digest.

Sarvam supports two input modes. Existing configurations remain on the legacy
`qualification_profile`, `customer_name`, `previous_answers`, and `pending_discussion`
contract. New agents should use **Lead context**, which sends exactly three String variables:
`lead_name`, `lead_phone`, and `lead_context`. AREVEI builds `lead_context` from active CRM
fields, Meta campaign/form attribution, previous confirmed answers, pending discussion, and
the selected qualification profile. The workspace model condenses that briefing when
configured; a deterministic formatter is always available as a fallback.

Settings > Voice Providers > Sarvam includes a setup-guide generator. Paste its prompt into
Sarvam's AI agent builder. The builder is instructed to configure the three String inputs,
update the runtime instructions, and preserve every existing working final/output variable.
Review the proposed changes, test the agent, and commit a version before copying its technical
IDs into AREVEI. The callback may return facts in `final_agent_variables` or a nested
`qualification_data` object. AREVEI evaluates the facts and transcript itself; provider
scores, lead status, and decisions are ignored. The provider must have a committed agent and
working telephony connection. Switch an existing agent to Lead context only after its three
String inputs are configured.

For a fresh agent, the generated guide also includes a separate output-variable setup prompt.
Paste it into Sarvam's AI builder after the main prompt. It creates flat String outputs for
requirement, fit, explicit budget, eligibility, timeline, intent, decision-maker status,
location, preferences, objections, interest, and do-not-call. The separate prompt is not
needed when updating an agent whose qualification outputs already work.

### Automated Sarvam agent creation

Sarvam's public REST API cannot create, configure or commit agents; only the official
Voice Agents MCP server (`https://mcp.sarvam.ai/voice-agents`, OAuth 2.1 with PKCE, dynamic
client registration and rotating refresh tokens) exposes those operations. `backend/sarvam_agent_builder.py`
uses it so that an owner can create and connect an agent without opening the Sarvam dashboard:

1. Settings > Voice Providers > Sarvam > "Set up a new Sarvam agent" > **Connect Sarvam account**.
   The backend registers AREVEI once per callback URL (`{PUBLIC_BASE_URL}/api/sarvam/oauth/callback`,
   overridable with `SARVAM_OAUTH_REDIRECT_URI` for local development), opens Sarvam's consent page in a
   pop-up and stores the tokens in `sarvam_account_connections`, encrypted with `VOICE_CREDENTIAL_KEYS`
   and bound to the AREVEI workspace. Tokens are never returned to the browser. Access tokens last about
   a day and are refreshed server-side; a refresh failure marks the account `expired` and the UI asks to reconnect.
2. The owner fills the same business fields the manual guide uses, picks the telephony connection and
   onboarded number (read live from Sarvam), a language and optionally a voice, and clicks **Create agent in Sarvam**.
   The backend creates the agent, writes the shared runtime prompt (`voice_api.sarvam_runtime_prompt`),
   configures `lead_name`, `lead_phone` and `lead_context` as call-start inputs and the twelve qualification
   outputs as post-call variables, verifies the draft, commits a version and then calls the existing
   `save_config` with app ID, committed version, connection, number, `payload_mode=lead_context_v1`, followed by
   the existing connection probe. Calling, callbacks and qualification are unchanged.
3. The Voice Agents REST API key is still required for placing calls. It is requested once if the workspace
   has none, before anything is created in Sarvam.

Idempotency: every creation request carries a client-generated `creation_key` recorded in
`sarvam_agent_creations` (unique per workspace). A retry with the same key returns the existing agent, a
request still in progress is refused with `creation_in_progress`, and a Sarvam-side success followed by an
AREVEI persistence failure leaves the record in `created_unsaved` so the UI offers **Finish connecting**
(`POST .../sarvam/agents/{creation_key}/connect`) instead of creating a second agent. Sarvam validation
messages are surfaced with URLs and secrets removed.

APIs (all workspace owner/admin unless noted): `GET/DELETE /workspaces/{ws_id}/voice-providers/sarvam/account`,
`POST .../account/connect`, `GET .../account/connections`, `GET .../account/voices?language=`,
`POST .../sarvam/agents`, `GET .../sarvam/agents/{creation_key}`, `POST .../sarvam/agents/{creation_key}/connect`,
and the browser redirect `GET /sarvam/oauth/callback` (authenticated by the single-use OAuth state).
Run `python migrate_runtime.py` to create the unique indexes for the three new collections.
The manual setup guide remains available as a fallback.

Official contracts consulted:
- https://docs.sarvam.ai/voice-agents/mcp (Voice Agents MCP server, agent creation and commit)
- https://docs.sarvam.ai/conversations/api/introduction
- https://docs.sarvam.ai/conversations/api/instant-outbound/create
- https://docs.sarvam.ai/conversations/api/instant-outbound/webhook-payload
- https://docs.sarvam.ai/conversations/api/analytics/attempts

### AI Voice Agent: 14-day trial (master agent) and dedicated agents

Every workspace has one **AI Voice Agent** (Settings > AI Voice Agent, the onboarding "Voice agent" step, and a
setup banner on Overview and CRM). The workspace owner chooses one of two agent types:

| | Master agent (free trial) | Dedicated agent |
|---|---|---|
| Sarvam account | AREVEI's, from `backend/.env` | the workspace's own (OAuth via `sarvam_agent_builder`) |
| Agent | one shared master agent | the workspace's own agent, app ID and committed version |
| Stored in | `workspace_voice_agents` profile + platform env | `workspace_voice_provider_configs` (unchanged) |
| Per-workspace content | sent every call as `agent_name`, `business_name`, `agent_brief` | baked into the agent's prompt at creation |
| Calling number | `SARVAM_AGENT_PHONE_NUMBER` (shared) | the workspace's onboarded number |
| Limits | 14 days from explicit activation, once per workspace | none |

`workspace_voice_agents` (unique per workspace) holds `agent_type` (`master` / `dedicated`, the one that handles
new calls), `enabled` (pause / resume), the profile (`agent_name`, `business_name`, `business_details`, `behaviour`) and
`trial_started_at` / `trial_expires_at`. The trial is started by a conditional update that only matches a record that
has never started one, so it can't be restarted or extended by re-activating, editing or switching. Expiry is enforced
by the backend on every call.

Calling: `start_qualification_call` routes a workspace that has an agent type to the Sarvam provider, and
`SarvamVoiceProvider.configuration` resolves the master (platform config and key, the workspace's own callback secret)
or the dedicated configuration. Paused agents and expired trials are refused there. Payloads, sessions, callbacks,
qualification, CRM notes and tasks are unchanged. The call's `agent_snapshot.voice_agent_type` makes recording
retrieval use the account that placed the call. Workspaces without a `workspace_voice_agents` record keep their
previous routing, so existing Plivo and Sarvam setups keep working untouched. A previously configured Sarvam agent is
shown as an active dedicated agent.

Switching: the UI asks for confirmation. Switching never deletes either configuration; only the selected type
places new calls. A dedicated agent created while the trial is active doesn't take over until the owner switches.
Switching back to the master agent is allowed only while the trial is active. After expiry the profile, call history
and CRM data stay, trial calls stop, and the screen offers to connect a dedicated agent. (There is no billing or plan
system in AREVEI yet, so "upgrade" means connecting a dedicated agent.)

APIs (workspace owner or admin): `GET /workspaces/{ws}/voice-agent`, `PUT` (profile only), `POST .../voice-agent/trial`,
`POST .../voice-agent/calling` `{enabled}`, `POST .../voice-agent/switch` `{agent_type}`, `POST .../voice-agent/generate`.
Dedicated creation uses the existing `/voice-providers/sarvam/...` builder routes; the full manual provider panel is
available under "Advanced: set up an existing agent manually".

One-time master agent setup (admin):

1. In the Sarvam dashboard, onboard the calling number on a telephony connection and create a Voice Agents API key.
2. Add `SARVAM_API_KEY=<key>` to `backend/.env` (plus `SARVAM_OAUTH_REDIRECT_URI=http://localhost:8000/api/sarvam/oauth/callback`
   locally) and start the backend. This key is used only for master-agent calls; it is never given to dedicated workspaces.
3. From `backend/`, run `python scripts/setup_sarvam_master_agent.py` (options `--language`, `--voice-id`, `--connection-id`,
   `--phone`) and sign in to Sarvam. It creates, verifies and commits the master agent and prints `SARVAM_ORG_ID`,
   `SARVAM_WORKSPACE_ID`, `SARVAM_APP_ID`, `SARVAM_APP_VERSION`, `SARVAM_CONNECTION_ID`, `SARVAM_AGENT_PHONE_NUMBER`.
4. Paste them into `backend/.env`, run `python migrate_runtime.py` (unique index on `workspace_voice_agents`) and restart.

Rollback: remove the `SARVAM_*` master variables (the trial becomes unavailable and trial calls fail closed) and/or
delete `workspace_voice_agents` records. Workspaces then return to their previous provider routing; no existing
collection was altered.

## Deployment and Plivo migration

1. Back up MongoDB and retain the existing environment values. Drain active legacy calls
   and pause automatic calling during cutover, since callback authentication changes.
2. Generate a Fernet key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
   Store it securely as `VOICE_CREDENTIAL_KEYS` on all API/scheduler workers. The repository
   already depends on cryptography; no extra package is required. Back up the key securely.
3. Set `PUBLIC_BASE_URL=https://your-production-host` consistently on all workers.
   It is required for qualification initiation. Do not derive production URLs from client headers.
4. From `backend`, with the normal `MONGO_URL` and `DB_NAME` configured, migrate each workspace:
   `python migrate_voice_providers.py --workspace-id WORKSPACE_ID`.
   For the explicitly identified owner of the global Plivo account, use
   `python migrate_voice_providers.py --workspace-id WORKSPACE_ID --from-environment`.
   Never run environment import for unrelated customers. Migration refuses to overwrite
   an existing provider configuration, encrypts all workspace legacy agent credentials,
   and preserves agent IDs/mappings and historical calls while redacting legacy tokens from historical snapshots.
5. In Settings > Voice Providers, complete missing account fields, save and test. Bearer-only
   legacy agents need account Auth ID/Token for account verification and signed callbacks.
   Short legacy callback tokens must be replaced with a 32+ character token.
6. Update the Plivo agent's result tool to send the saved callback token as a header,
   or use provider-signed callbacks. Configure legacy unscoped callbacks with explicit
   workspace context. URLs/methods are displayed in settings; lead/session placeholders
   are filled automatically for initiated calls.
7. Choose Plivo or Sarvam per qualification profile. Run a real call for each migrated
   workspace and verify transcript, qualification result, CRM note, task and retry behavior.
   Resume the existing calling workflow after verification. Remove global customer Plivo
   environment secrets only after successful migration and rollback planning.

No customer secret is automatically inherited from environment variables at runtime.
New customers configure credentials entirely through workspace settings.

For key rotation, deploy `VOICE_CREDENTIAL_KEYS=NEW_KEY,OLD_KEY`, run
`python migrate_voice_providers.py --workspace-id WORKSPACE_ID --rotate-key` for each
workspace, verify decryption, then remove the old key. Provider credential rotation is
performed through Settings. Coordinate Plivo webhook token/account rotation with active
calls; old Plivo tokens are not retained indefinitely.

## Failure handling and operational limits

Missing/disabled configuration fails before sending a call. Provider rejection is recorded
without response bodies or credentials. Timeouts and successful responses without a call ID
enter `reconcile_required`, blocking automatic redial because the provider may have accepted
the call. An administrator must reconcile those sessions with the provider before retrying.

Sarvam final callbacks include transcript turns and extracted variables. Missing transcripts
fall back to structured facts and existing manual-review behavior. The interaction ID is
retained as the provider media reference. Sarvam recording URLs are fetched from the documented
`audio_url` field in the attempts analytics API, scoped and filtered to the exact attempt.
Media lookup failure never blocks qualification. Recordings published later can be retried
through the recording refresh API; this updates media only, without rerunning qualification.
Existing Plivo recording URLs/transcript callbacks continue to use the shared result flow.

The adapter does not provision or publish provider-hosted agents, configure telephony accounts,
or terminate active calls; these operations were not part of the existing qualification flow.
The existing scheduled-call cancellation remains available. Connection tests cannot establish
that an agent follows the supplied profile; verify the deployed agent with a live call.

Tests use synthetic records in isolated `qual_test_*` databases and mocked call transport.
Live provider calls and production migration were not executed. Existing Mongo event leases
last five minutes; long AI processing must remain within that lease. No new queue was added.

## Validation commands

From backend:
```
../.venv/Scripts/python.exe -m pytest tests/test_voice_providers.py tests/test_plivo_calls.py tests/test_qualification_integration.py tests/test_qualification_engine.py tests/test_manager_voice.py tests/test_crm_embedded_payment_plan.py -q -o addopts=''
```

From frontend:
```
npm test -- --watchAll=false --runInBand --runTestsByPath src/components/VoiceProviders.test.jsx src/pages/sections/Qualification.test.jsx src/components/LeadQualificationPanel.test.jsx
npm run build
```

Validation results: the expanded 160-test backend regression run passed; after adding media/migration coverage, the updated provider and Plivo suites passed 76 tests. The independent model-selection suite passed 7 tests. Six frontend tests and the final production build passed. Live provider accounts were not exercised.
