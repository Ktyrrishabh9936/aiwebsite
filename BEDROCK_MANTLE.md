# Bedrock Mantle integration

Lead qualification now uses the application-owned engine described in
[QUALIFICATION_ENGINE.md](QUALIFICATION_ENGINE.md). Mantle extracts conversation
facts; deterministic product rules decide qualification, scores and next actions.
The historical qualification checks below describe the earlier implementation.

## Configuration

The growth AI service now registers `openai.gpt-oss-120b` with provider
`bedrock_mantle` and label `GPT-OSS 120B — Amazon Bedrock`. This is the default
for new workspaces, unknown model IDs, and qualification calls without an explicit
model selection. Existing workspace IDs are not bulk-migrated. The coding agent
and its model registry are unchanged.

Use the existing ignored `backend/.env` or deployment secrets:

| Variable | Behavior |
| --- | --- |
| `BEDROCK_MANTLE_API_KEY` | Preferred API key; optional if the existing Bedrock key is configured |
| `AWS_BEARER_TOKEN_BEDROCK` | Existing key used when the dedicated Mantle key is absent |
| `BEDROCK_MANTLE_BASE_URL` | Defaults to `https://bedrock-mantle.ap-south-1.api.aws/v1` |
| `BEDROCK_MANTLE_PROJECT` | Defaults to `default` |

Authentication is a direct bearer API key, with `OpenAI-Project: default`.
No IAM profile, token generator, or new dependency is required for this path.
Never put key values in this document or source files. The verified local setup
uses the existing Bedrock environment key; no secret was copied or rewritten.

AWS reference: https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions-mantle.html

## Existing application paths retained

- Manager: frontend chat -> authenticated `/api/workspaces/{id}/chat` -> owned
  workspace -> `crm_manager_context` -> optional deterministic CRM action ->
  `agents.manager_chat_stream` -> `llm_service.stream_text` -> provider.
- Manager context consists of business profile (2,500 characters), strategy
  summary, six history messages, and CRM analytics/lead summaries (9,000
  characters). CRM retrieval is workspace-scoped and capped at 5,000 leads,
  with up to 40 lead summaries passed onward. Existing note/status/assignment/
  field updates are deterministic application functions, not model tool calls.
- Existing limitations remain: Manager does not receive full Brain domains,
  detailed roadmap months, tasks, coding project files, full call transcripts,
  or comprehensive qualification/follow-up records. Provider replacement does
  not create access to these missing data sources. CRM counts reflect the existing
  retrieval cap. Do not interpret a successful model request as proof that all
  possible CRM or project questions are supported.
- Brain: website crawler -> `agents.build_brain` -> `generate_json` -> saved Brain.
  Roadmap, task generation, blogs, SEO and creative tasks retain their existing
  prompt construction and workspace-selected model.
- Qualification: existing Plivo/Contacto callback handling ->
  `save_qualification_result` -> `run_ai_qualification` -> `generate_json` ->
  existing CRM result updates. Workspace model selection is now forwarded to
  qualification. Its criteria, scoring normalization, categories and manual-review
  behavior are unchanged.

## Provider behavior

Mantle uses the existing OpenAI-compatible HTTP adapter. Its completion budget
uses `max_completion_tokens`. JSON output retains the existing JSON-only prompt
and parser; no unsupported provider-specific response-format parameter is added.
Mantle reasoning fields are not exposed as user-visible text.

Manager retains its existing text streaming response to the frontend. Provider
HTTP and explicit stream errors now propagate rather than becoming empty replies.
Request logs contain provider, actual model, start/finish, latency and error type;
they do not include prompts, response bodies, transcripts, headers or credentials.

OpenRouter registrations and credentials remain available. Existing non-streaming
fallback still retries the configured default on failure, which is now Mantle.
No new Mantle-to-OpenRouter failover was introduced. Streaming still has no model
failover. Existing generated-by metadata still records requested model IDs.

## Verification commands

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_llm_mantle.py backend/tests/test_plivo_calls.py backend/tests/test_crm_embedded_payment_plan.py -q
.\.venv\Scripts\python.exe scripts/verify-mantle.py
```

The live script uses the backend URL configured for the frontend, real configured
credentials, an existing workspace, actual CRM analytics and a synthetic
qualification transcript. It makes billable model requests. Its optional
`--activate` flag selects Mantle for the tested workspace after context checks.
It does not place calls or submit fabricated callback data to real CRM leads.

The live Manager check initially exposed a pre-existing zero-payment formatting
error (`int.is_integer`) in CRM analytics. `money_text` now keeps the lower bound
as a float, preserving formatting and allowing existing context retrieval to run.
A regression test covers empty CRM analytics.

## Verified local results (2026-09-13)

| Check | Result |
| --- | --- |
| Mantle bearer authentication | PASS, HTTP 200 |
| Direct request | PASS, exact `BEDROCK_OK` |
| Shared AI service | PASS, exact `BEDROCK_APP_OK` |
| Running model catalog | PASS, Mantle visible and configured |
| Manager streaming / Brain company context | PASS, matched the actual workspace business profile |
| CRM context | PASS, model count matched independently retrieved CRM analytics |
| Saved workspace selection | PASS, Manager request without model override |
| Qualification | PASS, live synthetic transcript through existing qualification function |
| Existing OpenRouter model | PASS, exact `OPENROUTER_OK` with fallback bypassed |
| Frontend | HTTP 200; production build compiled successfully |
| Automated tests | 76 distinct targeted tests passed across the verification runs |

The backend was restarted on the frontend-configured `127.0.0.1:8000`, and the
tested existing workspace was selected through its PATCH configuration endpoint.
The other existing workspace retained its stored selection. No live call was
placed and no synthetic qualification result was written into a customer's lead.
Callback/CRM write behavior was covered by the existing automated tests; the live
qualification test covered the actual qualification service and Mantle response.
The frontend API path was exercised over HTTP, not by automated browser clicks.

Failures encountered and resolved/qualified:

- Stale running backend initially omitted Mantle from its catalog: restarted the
  existing local server, then confirmed the real catalog and chat endpoints.
- Manager initially returned HTTP 500 because `money_text(0)` called
  `is_integer()` on an integer: fixed the float lower bound and added regression
  coverage, then repeated the real request successfully.
- One service request raised `httpx.ReadTimeout` after 120 seconds while waiting
  for response headers. Subsequent complete live runs passed. The precise upstream
  cause is unknown; this is a reliability limitation, not proof of bad credentials.
  No automatic retry/failover policy was added to conceal it.

Files changed for this integration: `backend/llm_service.py`, `backend/server.py`,
`backend/plivo_calls.py`, `backend/models.py` (default only), `backend/crm.py`
(numeric formatting only), `frontend/src/pages/Dashboard.jsx`,
`frontend/src/pages/WorkspaceLayout.jsx` (creation defaults only),
`backend/tests/test_llm_mantle.py`, `scripts/verify-mantle.py`, `.gitignore`
(local backend logs), and this document. Other pre-existing working-tree changes
were preserved.

## Active workspace routing correction

The initial live verification selected an admin-owned Stripe test workspace.
The admin workspace-list endpoint only lists that administrator's workspaces;
it did not represent all application workspaces. A subsequent real user request
identified the active Arevei Technologies workspace in backend access logs.
That workspace still selected OpenRouter Llama, which returned HTTP 402.

The affected Arevei Technologies workspace was then switched to Mantle through
the existing authenticated configuration API. A real Manager request without a
model override returned 7 leads, matching an independent workspace-scoped MongoDB
count of 7. Both Manager chat frontends now omit the redundant `model_id` request
override, allowing the server to use the latest saved workspace selection even
when browser workspace state is stale. Explicit API overrides remain supported.
The frontend production build passed after this correction.
