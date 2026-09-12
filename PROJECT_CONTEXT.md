# AI Website Project Context

This document is a handoff for another AI coding agent working on this repository.

## Project Summary

This is Arevei, an AI-powered website growth and management platform. It combines:

- A React frontend for the public landing page and authenticated workspace dashboard.
- A FastAPI backend for authentication, workspaces, CRM, content, workflows, AI services, and calls.
- MongoDB for application data.
- Plivo and an external AI-agent trigger for automated lead qualification calls.
- Daytona for coding-agent sandboxes and website development workflows.

The repository is located at `aiwebsite/`.

## Main Structure

```text
aiwebsite/
  backend/
    server.py          FastAPI app and route registration
    crm.py             CRM settings, lead CRUD, payments, notes
    plivo_calls.py     Plivo calls, callbacks, qualification, transcripts
    auth.py            Authentication and admin seeding
    coding_agent.py    Coding-agent integration
    llm_service.py     LLM provider integrations
    models.py          Pydantic/domain models
    tests/             Backend tests
  frontend/
    src/App.js         React routes
    src/pages/Landing.jsx
    src/pages/CheckDemo.jsx
    src/pages/sections/CrmInbox.jsx
    src/lib/api.js     Axios API client
  scripts/start-backend.ps1
  package.json         Root npm launcher
```

## Running Locally

Run commands from the repository root:

```powershell
# Frontend
npm run dev

# Backend, in another terminal
.\scripts\start-backend.ps1
```

The root `npm run dev` forwards to `frontend` and runs `craco start`.

- Frontend normally uses `http://localhost:3000`.
- Backend uses `http://127.0.0.1:8000`.
- If a port is occupied, set `PORT` before starting the frontend.

Frontend dependencies are installed under `frontend/node_modules`. Backend dependencies use `.venv` and `backend/requirements.txt`.

## Environment Files

Runtime configuration is intentionally not committed:

- `backend/.env`: MongoDB, JWT, AI provider, Plivo, SMTP, OAuth, Daytona, and public callback settings.
- `frontend/.env`: `REACT_APP_BACKEND_URL` and frontend build settings.

Never copy credentials, API keys, private keys, or passwords into source files or documentation. Use the local ignored `.env` files or deployment secrets.

Important backend variables for calls include:

- `MONGO_URL`, `DB_NAME`
- `PLIVO_AUTH_ID`, `PLIVO_AUTH_TOKEN`, `PLIVO_FROM_NUMBER`
- `PLIVO_AGENT_TRIGGER_URL`
- `PUBLIC_BASE_URL`
- Optional `PLIVO_AGENT_TRIGGER_TOKEN` and `PLIVO_AGENT_CALLBACK_TOKEN`

`PUBLIC_BASE_URL` must be an externally reachable HTTPS URL when the external AI/Plivo service needs to call back into the local backend. A local `127.0.0.1` URL cannot receive external callbacks.

## Check Demo Flow

The public landing page has a separate **Check Demo** button. It routes to `/check-demo` and renders `frontend/src/pages/CheckDemo.jsx`.

Flow:

1. User submits name, email, and phone number.
2. Frontend calls `POST /api/public/check-demo`.
3. Backend selects the configured demo workspace (`CHECK_DEMO_WORKSPACE_ID` if set, otherwise the oldest workspace).
4. Backend creates a CRM lead with `source=check_demo` and `qualification_status=pending`.
5. Backend immediately calls the existing `start_qualification_call` function in `plivo_calls.py`.
6. The external AI agent calls the supplied phone number.
7. The agent must POST the final result to:

   ```text
   /api/plivo/workspaces/{workspace_id}/calls/{lead_id}/qualification/result
   ```

8. `save_qualification_result` stores the result on the lead, including summary, transcript, duration, timestamp, category, and qualification status.
9. The Check Demo page polls `GET /api/public/check-demo/{lead_id}` every five seconds.
10. After completion, the public page displays only:

    - Qualified or Not Qualified
    - Call status
    - Call timestamp
    - Call duration
    - AI summary

The public status endpoint intentionally exposes only these result fields and does not expose the transcript or recording.

## Qualification Rules

Existing AI categories are `hot`, `warm`, `cold`, and `junk`.

- `hot` and `warm` map to public `qualified`.
- `cold` and `junk` map to public `not_qualified`.
- `junk` also changes the CRM lead state to `lost`.

The detailed CRM record still stores the full transcript and call history under `qualification_call`, `communication_summary`, `lead_notes`, and `crm_call_logs`.

## CRM Call Data

Relevant lead fields include:

- `field_values.full_name`
- `field_values.email`
- `field_values.phone`
- `qualification_status`
- `qualification_call.status`
- `qualification_call.qualification_status`
- `qualification_call.qualification_category`
- `qualification_call.summary`
- `qualification_call.transcript`
- `qualification_call.call_timestamp`
- `qualification_call.duration`
- `communication_summary`
- `lead_notes`

The authenticated CRM UI in `CrmInbox.jsx` shows qualification badges, call summaries, structured details, transcripts, recordings, and notes. The public Check Demo result intentionally shows less information.

## Callback Troubleshooting

If the public page stays on “Your AI demo call is in progress”:

1. Check MongoDB for recent leads where `source=check_demo`.
2. If `qualification_call.status=started` and `qualification_status=pending`, the external callback has not arrived.
3. Confirm `PUBLIC_BASE_URL` is live, HTTPS, and forwards to local port `8000`.
4. Confirm the AI agent receives `callbacks.result_url`, `result_url`, and `qualification_result_url` in its trigger payload.
5. Check backend logs for callback HTTP errors or callback-token failures.

The frontend WebSocket warning usually means an old CRA process is still running with stale environment variables. Stop the old Node process and restart `npm run dev`; CRA reads `.env` only at startup.

## Validation Commands

```powershell
# Backend syntax
.\.venv\Scripts\python.exe -m py_compile backend\server.py backend\plivo_calls.py

# Frontend build
Set-Location frontend
npm run build

# Backend tests
Set-Location ..
.\.venv\Scripts\python.exe -m pytest backend\tests
```

Avoid unrelated refactors. Preserve the existing API conventions, ignored environment-file setup, and CRM data shape unless the requested feature requires a contract change.

## Property Management Direction

The property-management system must use a generic property inventory foundation. Do not assume every property follows `Project -> Tower -> Flat`.

The system must support:

- Project-based inventory: residential, commercial, and mixed-use developments.
- Independent properties: villas, farmhouses, independent houses, offices, shops, warehouses, and other properties.
- Land and plots: residential plots, commercial plots, agricultural land, industrial land, and plotted developments.
- Future property types through configurable categories, subtypes, and custom attributes.

### User-facing terminology

Prefer **Properties** in the primary navigation and user-facing copy. Internally, properties can still be treated as inventory.

Primary navigation may eventually include:

```text
Dashboard
CRM
Properties
Calls
```

Properties can contain views such as Projects, All Properties, Activity, Bookings, and Sales.

### Creation flow

The first question in an Add Property/Add Inventory flow should be simple:

```text
What are you adding?

- Project / Development
- Individual Property
- Land / Plots
```

Use progressive disclosure. The form must adapt to the selected category and subtype instead of showing every possible field.

Examples:

- Apartment: tower, floor, unit number, BHK, area, facing, price.
- Villa: bedrooms, bathrooms, built-up area, plot area, parking, price.
- Land/plot: plot area, land area, dimensions, land type, location, price.
- Commercial office: floor, carpet area, built-up area, furnishing, parking, price.

### Recommended domain model

Use one unified property/container model with optional relationships:

```text
Property Container
  - Project
  - Independent Property
  - Land Development

Inventory Unit / Property
  - Can belong to a project
  - Can belong to a tower or other optional structure
  - Can exist independently
```

Common property fields should include:

- `name`
- `category`
- `subtype`
- `location`
- `price`
- `status`
- `workspaceId`
- `inventoryOwner`
- `sellingOrganization`
- `assignedAgent`
- Optional `projectId`, `towerId`, and `unitNumber`
- Flexible type-specific `attributes`

Example attributes:

```json
{
  "bedrooms": 3,
  "bathrooms": 3,
  "carpetArea": 1850,
  "facing": "Park"
}
```

Do not create separate database architectures for apartments, villas, land, shops, offices, or warehouses. Use configurable top-level categories such as Residential, Commercial, Land, Industrial, and Other, with configurable subtypes and a Custom option.

### Supported hierarchy patterns

The model should support all of these without special-case assumptions:

```text
Apartment project   -> Project -> Tower -> Unit
Villa project       -> Project -> Villa Unit
Plot development    -> Project -> Plot
Commercial building -> Project -> Floor -> Office/Shop
Individual farmhouse -> Independent Property
Land parcel         -> Independent Property
```

### Customer-specific workflows

Creation and visibility should adapt to the user type:

- Builder/Developer: create projects, choose property type and structure, generate or import units, manage availability.
- Channel Partner/Broker/Agency: manage authorized inventory from builder projects, individual properties, and land. Preserve owner, selling workspace, and assigned-agent fields for future inventory sharing.
- Individual Salesperson: use a simple Properties experience focused on search, filtering, viewing, pitching, site visits, bookings, and sales. Hide unnecessary hierarchy concepts.

The guiding product requirement is:

> Build one unified Property Management system capable of handling project-based inventory and independent properties. Use property category, subtype, optional hierarchy, and dynamic attributes to adapt to apartments, commercial spaces, villas, farmhouses, land, plots, warehouses, and future property types. Do not force every property into a project/tower/unit structure.