# Arevei — AI-Native Website Growth OS (PRD)

## Original Problem Statement
Build a complete agentic system (per the AREVEI Product Direction doc) that works as an AI Manager: a "Brain" trained by crawling a website URL, an AI Manager that auto-creates and schedules/executes tasks on time, and an advanced blog system (auto blog creation, advanced editor, full public blog previews like ai.arevei.com/blog/...). Plus an "Add Blog System" embed so external codebases can render the managed blog, with this app as the control panel. UI/flow inspired by app.arevei.com.

## Architecture
- **Frontend**: React (CRA) + Tailwind + shadcn/ui + framer-motion. Dark/light themes. JWT auth via localStorage Bearer token.
- **Backend**: FastAPI + MongoDB (motor). All routes under `/api`.
- **Agents** (`agents.py`): Brain Builder, Manager (roadmap + tasks + streaming chat), Content Agent (blog writing as content blocks).
- **LLM layer** (`llm_service.py`): multi-provider with model switching — Emergent Universal Key (Claude Sonnet 4.6, GPT-5.4, Gemini 3 Flash) + OpenRouter (DeepSeek, Llama 3.3) + NVIDIA NIM. `generate_json`, `generate_text`, `stream_text`.
- **Crawler** (`crawler.py`): httpx + BeautifulSoup, crawls up to 5 pages, prioritizing about/product/pricing pages.
- **Scheduler**: asyncio loop (30s) auto-runs due, non-approval tasks. First 3 content tasks per roadmap forced to auto-run within ~2 min.

## User Personas
- Founders/indie hackers who want their website managed by AI.
- Marketers who want auto-generated, on-brand, publishable content.
- Developers who want to embed a managed blog into any codebase.

## Core Requirements (static)
1. Brain: crawl URL → structured 6-domain business knowledge (editable).
2. Manager: 12-month roadmap + auto-scheduled daily tasks + streaming chat.
3. Specialist agents: content/seo/creative/analytics task execution with approval gating.
4. Blog system: AI generation, advanced block editor, SEO metadata, public preview pages.
5. Add Blog System: public JSON API + embeddable widget.js + React snippet, keyed by workspace public_key.
6. Multi-model selection; JWT auth; dark+light.

## Implemented (2026-06)
- JWT auth (register/login/me/logout), seeded admin, min password length. ✅
- Workspace CRUD + background brain build (crawl + LLM → 6 domains). ✅
- Roadmap generation (12 months) + task auto-creation & scheduling. ✅
- Task board with Run/Approve/Delete, live status, scheduler auto-execution. ✅
- Manager streaming chat (SSE-style text stream), roadmap timeline UI. ✅
- Blog generation (Content Agent), advanced block editor (add/move/delete/edit blocks, SEO sidebar, preview), publish toggle. ✅
- Public blog reading page `/blog/:slug` (editorial layout, hero, tags, author). ✅
- Embed page: public key, script/React/API snippets with copy, live preview iframe; widget.js served over public HTTPS host. ✅
- Notifications/activity feed, model picker, theme toggle. ✅
- Verified E2E by testing agent: backend 20/20; all AI features produce real LLM output.

## AI Coding Platform (Phase 1+2 — added 2026-06)
Daytona-backed Lovable/Bolt/v0-style coding workspace, reachable via the "Workspace" nav (2nd sidebar item + Dashboard link).
- **Daytona sandboxes**: per-project persistent cloud workspace; auto-provision + scaffold a Vite+React app; `ensure_started` auto-starts stopped/paused/archived sandboxes and recovers errored ones; "Sync" button to wake manually. (`daytona_service.py`) ✅ verified
- **Streaming coding agent**: OpenAI tool-calling loop (list_files/read_file/write_file/run_command) that edits the REAL sandbox filesystem and streams events → Codex-style summary per turn; persistent chat history per project. Model switching per task: GPT-4o / GPT-4o-mini (OpenAI), Claude 3.5 Sonnet / DeepSeek V3 / Qwen2.5 Coder (OpenRouter, incl. cheap models). (`coding_agent.py`, `coding.py`) ✅ verified via curl
- **Professional IDE**: Monaco editor; Code / Preview / Terminal as a single common block (one view at a time); file tree on the far right, togglable; Run button boots the dev server and shows the live Daytona preview URL in an iframe; real interactive terminal (arbitrary commands). ✅ compiles; backend flows verified
- Env creds stored for GitHub App, Vercel OAuth (deferred to next phase).

### Coding Platform Backlog (next)
- GitHub import (clone repo into sandbox) + push/PR via the stored GitHub App creds.
- Vercel one-click deploy (OAuth) + auto-attach deployed URL to the marketing Brain.
- v0-style quick-generate mode (prompt → full scaffold in one shot).
- WebSocket PTY terminal + streaming command logs (currently request/response exec).
- Not yet screenshot-verified in-browser (screenshot tool captures pre-auth redirect for protected routes); backend verified end-to-end.

## Backlog / Remaining
- **P1**: Run long blog generations as background jobs (avoid ingress timeout on manual Run).
- **P1**: Surface non-emergent provider failures to the user instead of silent fallback to default model.
- **P2**: Image generation via Creative Agent (currently blogs pull from a curated image pool).
- **P2**: Scheduler claims a batch per tick; cron-like recurring publishing cadence.
- **P2**: GitHub push of blog pages (currently embed/API only, per user's chosen scope).
- **P2**: Stripe billing + per-model usage metering.

## Test Credentials
admin@arevei.ai / arevei123 (see /app/memory/test_credentials.md)
