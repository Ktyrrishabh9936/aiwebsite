# Plan: Guided Onboarding, AI Manager Knowledge & Landing Page Forms

> Status: **Proposed** · Date: 2026-10-10 · Owner: Arevei product

Three connected features:

| # | Feature | What the user gets |
|---|---------|--------------------|
| **A** | Guided onboarding | A 3-step flow after sign-up: **Account → About you → AI Manager setup**, with a skip option at every step |
| **B** | Product knowledge for the AI Manager | The AI Manager can explain what Arevei does and how to get value from each feature |
| **C** | Landing Page Form connection | A new connector in **Workflows** that sends leads from any landing page into the CRM, with country codes and UTM tracking |

---

## 0. What exists today (starting point)

| Area | Current state | Gap |
|------|---------------|-----|
| Sign-up | [Register.jsx](frontend/src/pages/Register.jsx) → `POST /api/auth/register` ([auth.py:121](backend/auth.py#L121)) → `/welcome` | Saves only name, email and password. Nothing about the user's role or how they found us. |
| Onboarding | [Onboarding.jsx](frontend/src/pages/Onboarding.jsx) is a single form for the website URL. It lists 3 steps as text but has no wizard. | "Onboarded" is a `localStorage` flag (`arevei_onboarded`), so the server doesn't know it and it is lost on a new device. |
| Business info / strategy | `sales_profile` is stored on the workspace ([sales_leadership.py:21](backend/sales_leadership.py#L21)). It is filled from a long form in [SalesStrategy.jsx](frontend/src/pages/sections/SalesStrategy.jsx). | There is no conversational, guided setup. |
| AI Manager chat | Two modes: human chat ([manager_service.py](backend/manager_service.py)) and Agent Mode with about 22 tools ([manager_agent.py](backend/manager_agent.py), [manager_tools.py](backend/manager_tools.py)) | It only knows the website brain, CRM data and the strategy. **It has no knowledge of Arevei's own features.** |
| Voice / SMS | [VoiceProviders.jsx](frontend/src/components/VoiceProviders.jsx) is under Settings. [TwilioSmsSettings.jsx](frontend/src/components/TwilioSmsSettings.jsx) is under CRM Inbox. | Both are scattered and neither is part of onboarding. |
| Workflows | [Workflows.jsx](frontend/src/pages/sections/Workflows.jsx) has a hardcoded card grid: "Ads to CRM" is active, "Google Forms" is coming soon | There is no generic form connector. The `Workflow` model only supports Google Sheets. |
| Lead model | `CRMLead` ([models.py:136](backend/models.py#L136)) | It has **no UTM fields** and **no country-code field**. Manual and public creation don't check for duplicates. The only public lead endpoint (`/public/check-demo`) has no workspace key and no rate limit. |

---

## A. Guided Onboarding

### A.1 Flow at a glance

```
 ┌──────────────┐   ┌──────────────────┐   ┌────────────────────────────────────────────┐
 │ 1. Create    │──▶│ 2. About you      │──▶│ 3. AI Manager setup                        │
 │    account   │   │  • Your role      │   │                                            │
 │ (existing)   │   │  • How you heard  │   │  ┌─ 3a. Choose how to set up ───────────┐  │
 └──────────────┘   │  • Website URL    │   │  │ ◉ Set up with AI   (~8 min)          │  │
                    └──────────────────┘   │  │ ○ Contact Arevei to set up for me     │  │
                      brain build starts   │  │ ○ Skip to dashboard                   │  │
                      in the background ──▶│  └───────────────────────────────────────┘  │
                                           │  3b. AI chat: business + sales strategy     │
                                           │      (progress bar · time left · skip any)  │
                                           │  3c. Voice agent & SMS   [Skip → Dashboard] │
                                           │  3d. ✓ Done → Dashboard                     │
                                           └────────────────────────────────────────────┘
      Footer on every step:  Need help?  arevei  ·  admin@arevei.com
```

**Why the website URL goes in step 2:** the brain crawl (`_build_brain_bg`, [server.py:252](backend/server.py#L252)) takes a while. If it starts at step 2, the brain is usually ready by the end of the AI chat, so `POST /sales/strategy` can run right away.

### A.2 Step 1: Create account
- Keep the current Register page.
- Set `user.onboarding = { step: "about", started_at }` at registration.
- **Login routing** ([Login.jsx:31](frontend/src/pages/Login.jsx#L31)): read `user.onboarding.completed_at` from `/api/auth/me` instead of `localStorage`. If onboarding isn't complete, resume at the saved step.
- Existing users (who have no `onboarding` field) are treated as **completed**. A one-off migration sets this so nobody is pushed into the wizard.

### A.3 Step 2: About you
| Field | Type | Options |
|-------|------|---------|
| Role | Single-select chips | Founder / Business Owner · Marketer · Real Estate Broker · Sales Leader · Agency · Other (free text) |
| How did you hear about us? | Single-select chips | Social Media · ChatGPT / AI tools · WhatsApp · Google Search · Referral · Other (free text) |
| Website URL | URL input | Required to build the brain. A "No website yet" link skips the crawl. |

- **Backend:** `PUT /api/auth/me/onboarding` with body `{ role, role_other, heard_from, heard_from_other, step }`. Saved to `users.onboarding`.
- `heard_from` is also copied into the admin "new sign-up" email ([mailer.py](backend/mailer.py)) for marketing attribution.
- Role adjusts the setup:
  - **Real Estate Broker** pre-enables the `real_estate` module and uses property-focused questions in the AI chat.
  - **Agency** enables `agency`.

### A.4 Step 3a: Choose the setup path
Three cards:
1. **Set up with AI (recommended) · about 8 minutes** → 3b
2. **Contact Arevei for setup.** Shows the contact card and a "Request a call" button. This sends an email to `admin@arevei.com` with the user, role and website, sets `onboarding.assisted_requested_at`, then goes to the dashboard.
3. **Skip to dashboard.** Sets `onboarding.skipped = true`. The Overview page keeps showing a "Finish AI Manager setup" banner (this ties into the existing prompt at [Overview.jsx:125](frontend/src/pages/sections/Overview.jsx#L125)).

### A.5 Step 3b: AI-guided business and sales strategy chat

A dedicated **interview mode**, separate from the normal Manager chat, so it stays focused and its output is structured.

**Question script** (each question maps to a `SalesProfile` field, so nothing new is needed in the strategy engine):

| # | Topic | Fills `sales_profile.*` | Skippable |
|---|-------|-------------------------|-----------|
| 1 | Confirm the business summary (pre-filled from the brain if ready) | `organisation` | ✓ |
| 2 | What you sell, with price ranges | `offerings` | ✓ |
| 3 | Ideal customer | `ideal_customer` | ✓ |
| 4 | Where leads come from today | `lead_sources` | ✓ |
| 5 | Team size and daily capacity | `team_capacity` | ✓ |
| 6 | Monthly revenue target | `monthly_revenue_target` | ✓ |
| 7 | Monthly sales and marketing budget | `monthly_sales_budget` | ✓ |
| 8 | New or established business | `business_stage` | ✓ |
| 9 | How confident you are in the offer, plus customer feedback | `offer_confidence`, `customer_feedback` | ✓ |
| 10 | Constraints (geography, compliance, hours) | `constraints` | ✓ |
| 11 | Timezone and morning briefing hour | `timezone`, `morning_hour` | defaults |

**UX**
- Chat bubbles with **quick-reply chips** for common answers, plus a free-text box.
- On every question: **Skip this question** and **Skip the rest**.
- A header progress bar: `●●●●○○○○○○  4 of 11 · about 4 min left`. Time left is the remaining questions × about 40 seconds, recalculated after each answer.
- The AI can answer side questions ("what does the voice agent do?") using the product knowledge from **Part B**, then return to the script.
- At the end, a **review card** lists every captured field. The user can edit any of them, then confirm with **Build my sales strategy**.

**Backend:** new module `backend/onboarding.py`

| Endpoint | Purpose |
|----------|---------|
| `GET  /api/workspaces/{ws}/onboarding/state` | Current answers, next question, progress and ETA |
| `POST /api/workspaces/{ws}/onboarding/chat` | `{ message \| skip: true }` → `{ reply, extracted, next_question, progress, eta_seconds }` |
| `POST /api/workspaces/{ws}/onboarding/complete` | Saves the reviewed profile (`PUT /sales/profile` logic), then calls `sales_strategy()` (or queues it until the brain is `ready`) |

- Each turn makes one `llm_service.generate_json` call that returns `{ reply, extracted_fields }`, validated against `SalesProfile`.
- The question script is server-side, so progress can't drift.
- The transcript is saved in `workspaces.onboarding_interview`, so a refresh resumes where the user left off.

### A.6 Step 3c: Voice agent and SMS
- Two compact cards that reuse existing components through a new `compact` prop:
  - **Voice agent:** `VoiceProviders` (Plivo / Sarvam). The Sarvam "setup guide" endpoint (`voice_api.py:209`) is pre-filled with `business_name` and `offer` from 3b.
  - **SMS:** `TwilioSmsSettings`.
- Saving sets `sales_profile.voice_setup = "configured"`. **Skip to dashboard** sets `"skipped"`.
- Both remain fully editable later in Settings. TwilioSmsSettings will **also** be added to the Settings page.

### A.7 Step 3d: Done
Show a checklist of what's ready (Brain ✓ · Strategy ✓ · Voice ✓/skipped · SMS ✓/skipped), with the CTA **Go to dashboard** and a secondary **Connect your landing page form →** (Part C).
Set `onboarding.completed_at`.

### A.8 Contact info
A shared `<SetupHelpCard />` component appears on every onboarding step and in the "Contact Arevei" path:
> **Need a hand?** Our team can set this up for you: **arevei** · **admin@arevei.com**

---

## B. Product knowledge for the AI Manager

**Goal:** when someone asks "What can you do?", "How do I get leads from my website?" or "Why should I set up the voice agent?", the AI Manager gives an accurate, actionable answer and points to the right screen.

### B.1 Product docs (source of truth)
A new folder, `backend/product_docs/`, with one short Markdown file per capability. Every file uses the same template:

```markdown
# <Feature name>
## What it does        – 2–3 sentences, plain language
## Why it matters      – the business benefit (more meetings, faster response, …)
## How to set it up    – numbered steps, with the exact menu path (e.g. Workflows → Landing Page Forms)
## Tips to get the most out of it
## Questions people ask
```

**Initial set** (about 14 files):

`ai-manager` · `business-brain` · `sales-strategy-and-briefings` · `crm-and-pipeline` · `lead-qualification` · `voice-agent` · `sms` · `whatsapp` · `workflows-ads-to-crm` · `workflows-landing-page-forms` · `sales-team-and-portal` · `properties-inventory` · `push-notifications` · `billing-and-plans`

Content can be drafted from the existing docs (`PRICING_FEATURES_BENEFITS.md`, `QUALIFICATION_ENGINE.md`, `VOICE_PROVIDERS.md`, `SALES_LEADERSHIP.md`, `PRODUCT_UPDATES.md`, …). Each file then needs product review.

### B.2 How the AI uses it
| Surface | How it's added |
|---------|----------------|
| **Agent Mode** | New tool `get_product_help(topic \| question)` in [manager_tools.py](backend/manager_tools.py). It returns the best-matching doc sections. A line is added to the `SYSTEM` prompt: *"For questions about Arevei's features, call get_product_help."* |
| **Human chat** | In `ManagerService.stream`, detect product or help intent (keywords plus a cheap classifier) and add the top 1–2 matching sections (about 1,500 characters) to the prompt. |
| **Onboarding interview** | The same lookup answers side questions during step 3b. |
| **Voice manager (Sarvam)** | Optional: add the docs to `manager_voice_grounding.py` so spoken answers match. |

- **Retrieval (v1):** load every file at startup and split it by `##` headings. Score with keyword/BM25 against each feature's title and its "Questions people ask" section. This needs no vector DB and is enough for about 14 docs. Embeddings can come later if the docs grow.
- **Benefit nudges:** a **"What should I set up next?"** quick action compares the workspace state (no form connected, voice skipped, etc.) with the docs and suggests the most valuable next step.

---

## C. Landing Page Form connection (Workflows)

### C.1 User experience

**Workflows grid** gets a new active card:
> 📝 **Landing Page Forms**: capture leads from any website or landing page, with UTM tracking.

**Connector page** `/app/w/:wsId/workflows/landing-forms` follows the [AdsToCrmWorkflow.jsx](frontend/src/pages/sections/AdsToCrmWorkflow.jsx) layout:

```
┌ Landing Page Forms ─────────────────────────────────────── [+ New form] ┐
│  Form: "Summer Villa Campaign" ▾        Status: ● Active   [Pause]       │
├──────────────────────────────────────────────────────────────────────────┤
│ ① Fields                                                                 │
│   Field                 Show   Required   Default / setting              │
│   Name                   ✓        ✓                                      │
│   Email                  ✓        ○                                      │
│   Phone + country code   ✓        ✓       Default country: 🇮🇳 +91 ▾      │
│   Requirement / Query    ✓        ○       Label: "Tell us what you need" │
│   UTM parameters      hidden   auto       source·medium·campaign·term·content │
│                                                                          │
│ ② Lead defaults (optional)                                              │
│   Lead source label [Landing page]  Pipeline stage [New ▾]  Tags [+]     │
│   Assign to [Round-robin ▾]   ☑ Trigger AI qualification call            │
│   After submit: ◉ Show message  ○ Redirect to URL                        │
│                                                                          │
│ ③ Install on your website                                               │
│   [ Embed script ] [ Connect existing form ] [ API / Webhook ]           │
│   <script src="https://…/embed/form.js" data-form="lf_9ab3…"></script>   │
│   [Copy]   Allowed domains: villas.example.com  [+]                      │
│                                                                          │
│ ④ Test & recent submissions                                              │
│   [Send test lead]   10:42  Priya S · +91… · utm_source=facebook  ✓ CRM  │
└──────────────────────────────────────────────────────────────────────────┘
```

- **Multiple forms per workspace**, one per landing page or campaign. Each has its own key, defaults and stats.
- The **"Settings can be optional or default"** requirement maps to: every field has a **Show / Required** toggle (Name and Phone are required by default, Email and Requirement are optional), and each form has a **Lead defaults** block.

### C.2 Three ways to install
| Tab | For | How it works |
|-----|-----|--------------|
| **Embed script** | No-code users | `/embed/form.js` renders a styled form with a **country-code dropdown** (searchable, flags, default from settings). It captures UTMs automatically and submits via `fetch`. |
| **Connect existing form** | Webflow, WordPress, Elementor, Framer and custom HTML | A small snippet (`/embed/form-connect.js`) attaches to an existing `<form>`. It adds hidden UTM inputs and posts to our endpoint. The user maps their input names in the UI. |
| **API / Webhook** | Developers, Zapier, Make | Shows the `POST` URL, the JSON schema, a cURL example, and the form key. |

**UTM capture (hidden):**
- Fields captured: `utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content`, plus `gclid`, `fbclid`, `page_url` and `referrer`.
- Stored as **first touch** in `localStorage` (with a 30-day expiry) and as **last touch** from the current URL, so attribution survives when visitors browse between pages before submitting.

### C.3 Backend design

**New collection `lead_forms`** (new module `backend/lead_forms.py`):
```jsonc
{
  "id": "…", "workspace_id": "…", "name": "Summer Villa Campaign",
  "form_key": "lf_<24 random chars>",      // public, rotatable
  "status": "active" | "paused",
  "allowed_origins": ["https://villas.example.com"],   // empty = any
  "fields": {
    "full_name":   { "enabled": true,  "required": true,  "label": "Name" },
    "email":       { "enabled": true,  "required": false },
    "phone":       { "enabled": true,  "required": true,  "default_country": "IN" },
    "requirement": { "enabled": true,  "required": false, "label": "Requirement" }
  },
  "defaults": { "source_label": "Landing page", "status": "new", "tags": [],
                "assign": "round_robin" | "<salesperson_id>" | null,
                "trigger_ai_call": true },
  "after_submit": { "mode": "message" | "redirect", "message": "…", "redirect_url": "…" },
  "stats": { "submissions": 0, "last_submission_at": null },
  "created_at": "…"
}
```

**Authenticated endpoints** (`/api/workspaces/{ws}/lead-forms`, `require_workspace_access`):
`GET /` · `POST /` · `PATCH /{id}` · `DELETE /{id}` · `POST /{id}/rotate-key` · `POST /{id}/test` · `GET /{id}/submissions`

**Public endpoint:** `POST /api/public/forms/{form_key}/submit`
- Accepts **JSON** or **`application/x-www-form-urlencoded`**, so a plain HTML `<form action=…>` works without JS. In that case the response is a redirect or a thank-you page instead of JSON.
- Payload: `full_name, email, phone, country_code, requirement, utm_*, gclid, fbclid, page_url, referrer, submission_id, _hp` (honeypot)

**Processing pipeline:**
```
validate key & status ─▶ origin allowlist ─▶ rate limit (key+IP) ─▶ honeypot
   ─▶ validate required fields per form settings
   ─▶ phone: country_code + local number ─▶ E.164 (reject with a clear error if invalid,
        so a typo doesn't become a "junk" lead — schedule_first_qualification_call junks non-E.164)
   ─▶ idempotency: sheet_row_key = "form:{form_id}:{submission_id or sha256(payload+minute)}"
   ─▶ dedup: same phone or email in this workspace within 30 days?
        ├─ yes → append a "Re-submitted via <form>" timeline note + new UTM touch, update requirement
        └─ no  → build_manual_lead(...) with source="landing_form", workflow_kind="landing_form"
   ─▶ apply defaults (stage, tags, assignment)
   ─▶ schedule_first_qualification_call (if trigger_ai_call)
   ─▶ notify() + push notification "New lead from <form name>"
   ─▶ increment stats, log submission
```

- **Security:** reuse the `public_key` patterns from [server.py:169-185](backend/server.py#L169-L185) (origin allowlist and rate bucket). The current rate bucket is in memory, which doesn't hold up across Lambda instances, so use a Mongo TTL counter instead. Never expose workspace IDs. Errors are generic. Body size is capped at 10 KB.
- **CORS:** the public form route must reply to preflight requests from the allowed origins. On Lambda, check that the Function URL CORS config allows it.

### C.4 Lead model changes ([models.py](backend/models.py), [crm.py](backend/crm.py))
| Change | Detail |
|--------|--------|
| `utm` | `{ source, medium, campaign, term, content, gclid, fbclid, page_url, referrer, first_touch: {…}, captured_at }` |
| `phone_country_code` | e.g. `"+91"`, kept alongside the E.164 `phone` |
| `form_id` | Links the lead to `lead_forms` |
| `requirement` | New default CRM field (type `textarea`) in `DEFAULT_FIELDS`, so it shows in the lead view and filters |
| `normalize_field` | Reserve the `utm_*` prefix like `meta_*` |
| Indexes | `(workspace_id, phone)` and `(workspace_id, email)` for fast dedup |

**Lead detail UI:** a new **Source attribution** panel next to [MetaAttribution.jsx](frontend/src/components/MetaAttribution.jsx) that shows the form name, UTMs and landing page. The CRM list gets filters for **Source = Landing page** and **UTM campaign**.

### C.5 Frontend files
- `Workflows.jsx`: add the card (`kind: "landing_form"`, status from `/lead-forms`).
- `App.js`: add the route `workflows/landing-forms`.
- New `pages/sections/LandingFormsWorkflow.jsx`, reusing the `CodeBlock` and tabs from [Embed.jsx](frontend/src/pages/sections/Embed.jsx).
- New `components/CountryCodeSelect.jsx`. It is shared by the embed form, the onboarding voice step and the manual lead creation form.
- New public scripts `embed/form.js` and `embed/form-connect.js`, served by the backend like the existing `/embed/widget.js`.

---

## D. Data model summary

| Collection | Change |
|------------|--------|
| `users` | `+ onboarding { step, role, role_other, heard_from, heard_from_other, skipped, assisted_requested_at, completed_at }` |
| `workspaces` | `+ onboarding_interview { transcript[], answers{}, current_q, updated_at }` |
| `lead_forms` | **new** |
| `lead_form_submissions` | **new** (log with a 90-day TTL: payload summary, result, lead_id, error) |
| `crm_leads` | `+ utm, phone_country_code, form_id`, plus the new default field `requirement` |
| migration | `migrate_onboarding.py`: mark existing users `completed`, create indexes |

---

## E. Delivery phases

| Phase | Scope | Est. |
|-------|-------|------|
| **1. Foundations** | `users.onboarding`, `/me/onboarding` API, login routing, migration, `CountryCodeSelect`, lead model fields (`utm`, `phone_country_code`, `requirement`) | 2–3 days |
| **2. Landing Page Forms** | `lead_forms` backend, public submit pipeline, connector page, embed scripts, attribution panel, tests | 5–6 days |
| **3. Onboarding wizard UI** | Steps 2, 3a, 3c and 3d, `SetupHelpCard`, "Contact Arevei" email, compact Voice/SMS cards | 3–4 days |
| **4. AI interview** | `onboarding.py` chat engine, question script, progress/ETA, review card, strategy hand-off | 4–5 days |
| **5. Product knowledge** | Write the 14 docs, retrieval, `get_product_help` tool, chat injection, "What should I set up next?" | 3–4 days (plus content review) |

Phase 2 can be built in parallel with phases 3–4. Phase 5 docs can be written alongside, but the interview's side questions need them before launch.

---

## F. Testing and acceptance

**Onboarding**
- [ ] A new user lands on step 2 after sign-up. Refreshing at any step resumes at the same step, on any device.
- [ ] Every step can be skipped and still reaches the dashboard. Skipped setup shows a "Finish setup" banner.
- [ ] Completing the AI interview creates `sales_profile` and a strategy. If the brain isn't ready yet, the strategy is built automatically when it is.
- [ ] Existing users are never shown the wizard.
- [ ] Contact info (arevei · admin@arevei.com) is visible on every step.

**AI Manager knowledge**
- [ ] "What can you do?", "How do I connect my website form?" and "What is the voice agent?" each return answers grounded in the docs, with the correct menu path, in both chat modes.

**Landing Page Forms**
- [ ] The embed form creates a lead with an E.164 phone, the requirement, and all 5 UTMs plus the page URL.
- [ ] A plain HTML `<form>` post (no JS) works and redirects.
- [ ] Resubmitting the same submission creates no duplicate. The same phone within 30 days updates the existing lead.
- [ ] Paused forms, wrong origins, honeypot hits and rate-limit excess are all rejected.
- [ ] With "Trigger AI call" on, the qualification call is scheduled according to the calling settings.
- [ ] Backend pytest covers the submit pipeline. Frontend tests cover the connector page and `CountryCodeSelect`.

---

## G. Open questions

1. **"Address" in "How did you hear about us"**: should this be an option such as an offline event or office visit, or was it meant as a separate *business address* field in step 2?
2. **"arevei" contact**: is this a WhatsApp number, an Instagram/LinkedIn handle, or a website link? It decides whether the contact card shows a click-to-chat button.
3. **Duplicate leads**: should we update the existing lead (as proposed), or always create a new lead or opportunity per submission?
4. **AI call on form leads**: should "trigger AI qualification call" be **on** by default for form leads?
5. **Plans and billing**: is the number of landing page forms limited by plan?
