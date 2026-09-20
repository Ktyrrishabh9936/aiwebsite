# AI Manager inbound phone test

Status: backend integration implemented, disabled by default. Sarvam account configuration,
public HTTPS reachability, real provider latency, and a real inbound call must still be verified.
This is a private test interface, not a general customer-facing phone service.

## Repository findings and integration point

| Area | Existing architecture and reuse |
| --- | --- |
| Application | `backend/server.py`: FastAPI `app`, `api` router with `/api` prefix; feature routers included near the bottom. |
| Authentication | `auth.py`: JWT from bearer header or access-token cookie, then lookup in `users`. `owned_workspace` checks owner or admin. |
| Manager | `POST /api/workspaces/{ws_id}/chat` produces a plain-text stream, not JSON. `agents.manager_chat_stream` uses Brain business profile, strategy and the last six history messages. |
| Providers | `llm_service.py` selects the configured workspace model and routes through existing Bedrock/Mantle, OpenRouter and NVIDIA integrations. No separate Sarvam reasoning provider added. |
| CRM | `crm_manager_context` loads existing CRM analytics and lead summaries. `try_manager_crm_action` handles notes, statuses, salesperson assignments and field updates. These functions are reused. |
| Brain | Business profile and strategy already supplied by the existing manager; no new crawler or Brain created. |
| Tasks/properties | Existing scoped collections and HTTP routes. General conversational task creation/assignment is **not** an existing manager tool. This change adds bounded read context to the shared manager, not new write tools. |
| History | Web views submit browser-held history. There was no server-side manager conversation store to reuse. Voice history therefore requires its own persistent adapter store. |
| Plivo | `plivo_calls.py`, `plivo_agents.py`, `qualification_api.py`, `qualification_service.py`, and existing `server.py` callback handlers implement CRM calling and qualification. Their callback behavior is unchanged. |
| Configuration | Existing dotenv loading from `backend/.env`; no secrets are embedded in the implementation. |

Both transports now call `ManagerService.stream` in `manager_service.py`. It reuses the
existing CRM context/actions and `agents.manager_chat_stream`. Web keeps streaming;
voice collects the same stream and normalizes it for speech. Web and voice retain
separate conversations; switching channels does not automatically merge transcripts.

The manager's CRM write helper now checks Mongo's matched record count before reporting
success. Phone-created notes use `source=ai_manager_voice`. This does not change any
Plivo callback, call UUID matching, qualification category, recording or outbound flow.

## Sarvam contract: verified versus account-specific

Sarvam's [API tools](https://docs.sarvam.ai/conversations/build/tools/https-tool)
support configurable HTTP requests and bearer authentication. We define the AREVEI JSON
contract below; it is **not a built-in Sarvam webhook payload**. Configure a during-conversation
tool, with a response field mapping to `reply`. Credentials belong in Sarvam's secure
secret input. Call-context values can be inserted using the editor's `@` picker.
The documented timeout maximum is 30 seconds.

| AREVEI body field | Sarvam mapping |
| --- | --- |
| `message` | Latest caller utterance supplied as a tool argument; verify this binding in your account. |
| `session_id` | **Interaction ID** from call context. |
| `caller_phone` | **User Identifier** from call context, in E.164 format. |
| `transcript` | **Call Transcript** from call context, preserving the actual JSON value. |

Sarvam describes its [agent variables](https://docs.sarvam.ai/conversations/build/variables-personalization)
as readable/writable by tools during a call. Output-variable extraction runs after the call;
do not assume it automatically supplies the latest utterance mid-call.

**Still to verify in your Sarvam account:** the tool editor's exact latest-utterance
argument binding, runtime phone-number formatting, transcript value shape, stable retry
payloads, and response mapping. No agent export, real request sample, or account access
was supplied. If the editor cannot supply a fresh `message` argument, obtain its supported
binding or a documented transcript sample before enabling calls. Do not map the full
transcript to `message`: historical requests could otherwise execute again. This adapter
deliberately does not guess undocumented template expressions or parse transcript schemas.

No agent-phone-number field is required. AREVEI dynamically resolves the caller's phone
number through a connection created by the signed-in workspace owner.
No Sarvam platform API key, agent ID, outbound API, or call-completion webhook is used.

## Backend configuration

Copy the settings from `backend/sarvam-ai-manager.env.example` into `backend/.env`:

- `SARVAM_AI_MANAGER_ENABLED`: `false` by default; enables the shared Sarvam voice service.
- `SARVAM_AI_MANAGER_API_KEY`: a fresh random bearer secret, at least 32 characters,
  used to authenticate Sarvam's API tool with AREVEI.

Generate the secret locally with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
Store it in `backend/.env` and Sarvam's secret input, never in agent instructions, an
example file, or Git. Workspace and user IDs are deliberately absent from the environment.
Each user connects their calling phone from the Settings page of the workspace they want
the phone manager to use. Reconnecting the same phone in another workspace owned by that
user moves the connection to the new workspace.
The original JWT, Mongo, provider and Plivo settings are unchanged. Restart the backend
after configuration. Voice connection and session indexes initialize even while calls are
disabled so users can prepare their connection; failure disables voice requests without
preventing the rest of the application from starting.

### Authentication boundaries

1. Dedicated bearer secret authenticates the configured Sarvam tool.
2. Caller number must match an enabled AREVEI voice connection; unknown numbers fail closed.
3. The connection resolves the user and workspace dynamically. The user is loaded on
   **every turn**, including retries, and the existing owner/admin check authorizes the workspace.
4. Request-supplied workspace, user, history, model and any other unknown keys are rejected.
5. A session is bound to mapping plus caller and cannot be reused by another caller.

Bind caller number and Interaction ID through **system call context**, never an argument
the caller can dictate. Caller-number matching is only a routing and test restriction, not strong human
identity verification; caller ID can be spoofed. Keep this private and add verified user
authentication before a production rollout. Sarvam receives conversational data through
the tool and never receives Mongo credentials or direct database access.

## Exact AREVEI HTTP contract

### `GET /api/ai-manager/voice/health`

Public, no secrets:

```json
{"enabled": false, "configured": false}
```

`configured` means settings pass syntax checks. It does **not** confirm workspace ownership,
Mongo availability, index readiness, provider credentials, Sarvam deployment or phone connectivity.

### `POST /api/ai-manager/voice`

Headers:

```text
Content-Type: application/json
Authorization: Bearer <AREVEI tool secret>
```

Example synthetic request (replace test values with actual call-context bindings):

```json
{
  "message": "How many hot leads do we have?",
  "session_id": "sample-interaction-id",
  "caller_phone": "+14155550123",
  "transcript": "User: How many hot leads do we have?"
}
```

Required: `message` (1–2000 characters), `session_id` (1–160 letters/digits/`_.:-`),
`caller_phone` (E.164). Optional: `transcript` (any JSON value), `request_id` (1–160 characters).
Whitespace-only messages and unknown fields are rejected. Total body limit: 32 KiB.
No full audio recording is accepted or stored.

### Signed-in workspace connection API

- `GET /api/ai-manager/voice/workspaces/{workspace_id}/connection`
- `PUT /api/ai-manager/voice/workspaces/{workspace_id}/connection` with
  `{"caller_phone":"+919876543210"}`
- `DELETE /api/ai-manager/voice/workspaces/{workspace_id}/connection`

These routes use normal AREVEI JWT authentication and the existing workspace ownership
check. Phone numbers use E.164 format. A number connected to another account cannot be
claimed. For the same account, connecting that number from a different workspace changes
which workspace manager answers future calls. Active calls retain the workspace resolved
when their session began.

`request_id` is an optional **AREVEI per-turn idempotency key**, not a documented Sarvam
field. Omit it unless your adapter supplies a stable unique ID for each utterance, reused
on HTTP retries. Never populate it with Interaction ID, which identifies the whole call.
Otherwise deduplication uses the exact message plus transcript. Without a transcript,
repeating the same text during a call returns the earlier answer. With a changed transcript,
it counts as a new turn. Changed payloads are not guaranteed to deduplicate, so disable
agent-driven automatic retries of mutations; check uncertain actions in the workspace.

Success (`200`, `Cache-Control: no-store`):

```json
{
  "reply": "You have four hot leads. Rahul is first.",
  "session_id": "sample-interaction-id",
  "ok": true
}
```

Handled execution failure (`200`, speak the safe explanation; do not infer completion):

```json
{
  "reply": "I couldn't complete that request. If you requested a change, check the workspace before trying it again.",
  "session_id": "sample-interaction-id",
  "ok": false
}
```

Transport/auth errors use `{"detail":"safe explanation"}` with HTTP status:

| Status | Meaning |
| --- | --- |
| 401 | Missing/incorrect bearer secret. |
| 403 | Caller or mapped user/workspace unauthorized; caller/session mismatch. |
| 404 | Feature disabled. |
| 409 | Turn in progress, session expired/full, or reused request ID with changed content. |
| 413 / 415 / 422 | Oversized body / wrong content type / invalid contract. |
| 429 | More than 30 authenticated requests per minute per backend process. |
| 503 / 504 | Configuration/storage unavailable or request deadline exceeded. |

Manager execution is limited to 20 seconds. Processing deadline is 25 seconds;
body reading has a separate 5-second deadline. Normal small requests should finish inside
Sarvam's 30-second tool wait; actual model performance must be measured. The original
web manager can wait longer. The voice path does not change the provider's global settings.

## Sarvam agent setup

1. Create a separate test voice agent and a during-conversation API tool named
   `arevei_ai_manager`. Point it to your public HTTPS `/api/ai-manager/voice` URL.
2. Use POST, JSON, bearer authentication; store the new AREVEI secret securely.
3. Configure the body mappings above. Verify fresh `message` values on two consecutive
   utterances. This verification is required before enabling mutation tests.
4. Map the response's `reply` as the spoken result; do not speak the JSON envelope.
   Check `ok` and never improvise successful actions after a failure.
5. Set Max wait to 30 seconds. Configure a failure message such as:
   "I couldn't reach the manager. Please check the workspace before repeating a change."
6. Enable this tool and use the following instruction text:

```text
You are the phone interface for the AREVEI AI Manager.
For each business question or action request, call tool:arevei_ai_manager
with the caller's latest utterance as message. Preserve the caller's meaning.
Use system call-context bindings for caller and session identity.
Do not answer business questions from your own knowledge or invent data.
You may briefly say that you are checking with the manager before calling the tool.
Speak the returned reply naturally. Do not add claims that an action succeeded.
If the tool fails or ok is false, explain the failure; do not repeat a mutation.
Never reveal tool credentials or ask the caller to choose a workspace ID.
```

7. Test and commit this agent version. In [Deploy → Inbounds](https://docs.sarvam.ai/conversations/deploy/inbounds),
   associate the purchased number with this test agent and choose an availability window
   covering the test. This routes incoming calls; no outbound campaign is needed.

Account configuration is not automated here. A separate public HTTPS deployment is required;
local source changes alone do not make the endpoint reachable from Sarvam.

## Sessions, audit and recovery

`ai_manager_voice_sessions` is separate from all Plivo and CRM qualification call collections.
Each document stores configured mapping, original Interaction ID, caller phone, first/last
observed request time, latest supplied transcript, recent message history, turn responses,
tool outcomes, safe error codes and processing duration. Logs contain event names and a
hashed session reference, never transcripts, bearer keys, caller numbers or raw exceptions.

The session keeps the last 12 messages; the existing manager consumes the last six.
Stored history uses the speech reply actually sent to Sarvam. Each session permits 100
turns and four hours of activity. Mongo's TTL removes records seven days after first use;
verify that the index exists before using sensitive real data. These records contain
personal/business information and should stay accessible only to authorized database operators.

The observed first/last request timestamps are **not** actual call start/end events. This
implementation does not ingest call-completion webhooks, recording URLs or full call audio.

One atomic Mongo lock serializes turns per session across workers. The reply, history and
audit are persisted together before returning success. Exact repeated HTTP payloads replay
the saved response. A tool error/timeout is cached too; no automatic action replay occurs.
Existing multi-field CRM actions are not transactions: a failure can follow a partial update,
which is why uncertain responses tell callers to check the workspace.

After a process crash or storage failure, a `busy_token`/`pending` record can remain. It
intentionally does not expire automatically: a write may have succeeded. An operator should
inspect the pending request and actual affected records, reconcile the outcome, then have
the caller start a fresh call. Do not blindly clear the lock or replay the pending mutation.
No public session-inspection or lock-reset endpoint was added.

The dynamic connection collection supports multiple users and workspaces while keeping
authorization in AREVEI. A future version can add verified caller identity and an in-call
workspace switcher. Reuse `ManagerService` for other transports. No proactive or outbound
calling is implemented.

## Testing

Offline backend tests (from `backend`, Windows):

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_manager_voice.py tests/test_manager_service.py tests/test_plivo_calls.py tests/test_crm_embedded_payment_plan.py -q -n 0
```

Serial execution avoids this machine's pytest worker temporary-directory permission issue;
the repository's pytest configuration is unchanged. Tests use synthetic in-memory state and
mock provider output, and do not place calls or mutate production records.

Verified locally: the combined regression run passed 138 tests (existing Plivo, CRM and
qualification coverage plus the new manager/voice tests). The focused voice/manager suite
was expanded afterward and also passed all 29 tests.
The qualification engine's Mongo integration test was explicitly excluded; no real
database or telephone call was exercised. Existing multipart/FastAPI deprecation warnings remain.

### End-to-end test checklist

1. Use a test workspace with known sample CRM leads, Brain, tasks and properties. Configure
   the shared secret and a working saved model, sign in, then connect your calling phone
   from that workspace's Settings page.
2. Restart the backend; confirm health settings and storage indexes. Verify missing/wrong
   bearer headers return 401 and an unlisted caller returns 403 before using real data.
3. In the Sarvam tool editor, test a read question. Confirm the exact incoming body mappings
   and that it speaks only `reply`. Measure response latency under 30 seconds.
4. Call the purchased number from the allowed phone. Ask "How many hot leads do we have?"
   Compare with CRM, then ask "Tell me about the first one." Verify continuity.
5. Ask about business knowledge, existing tasks and a property. The manager can only use
   recorded context; it must acknowledge missing data.
6. On a **synthetic lead only**, say "Add a note for Rahul: Follow up tomorrow." Verify the
   actual saved note and its `ai_manager_voice` source. Replay the identical HTTP request;
   it should return the cached answer without a second note.
7. Ask to create a task. Expect an explicit unsupported-action answer, not "Done".
8. Simulate provider failure in the test environment. Confirm no secret details or false
   success are spoken. Inspect session audit, then run an existing Plivo regression check.

### Remaining limitations

- No live Sarvam account or phone test has been performed; current utterance binding and
  real call metadata still require account-level verification.
- Natural-language CRM writes retain the existing rule-based parser. Ambiguous requests
  may require a lead name or clarification; this is not a new general-purpose tool-calling agent.
- General assigned-task creation, property writes, outbound/proactive calls, recordings,
  and cross-channel conversation synchronization are not implemented.
- Rate limiting is process-local, matching the project's existing lightweight approach.
  Use a shared gateway limit and stronger user verification before production exposure.
- Brain/profile and CRM detail prompts retain existing size/sample limits. This is not
  unrestricted access to every document in the database.

## Files changed

- `backend/manager_service.py`: shared manager orchestration and bounded read context.
- `backend/manager_voice.py`: isolated API, authentication, sessions, audit, speech normalization.
- `backend/server.py`: shared-service wiring, voice router/index registration, manager write checks/source.
- `backend/agents.py`: optional spoken-reply style and truthful action-capability instructions.
- `backend/sarvam-ai-manager.env.example`: required, disabled-by-default settings.
- `backend/tests/test_manager_voice.py`, `backend/tests/test_manager_service.py`: offline coverage.
- `SARVAM_AI_MANAGER.md`: this setup and verification guide.

No frontend changes are required for phone access. Earlier Agent Mode UI changes remain separate.
