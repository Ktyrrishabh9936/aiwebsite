"""Agentic layer: Brain builder, Manager (roadmap + tasks), Content agent (blogs)."""
import re
import json
import logging
from llm_service import generate_json, generate_text

logger = logging.getLogger("agents")

AGENT_META = {
    "content": {"name": "Content Agent", "role": "Blogs, page copy, metadata, social content"},
    "seo": {"name": "SEO Agent", "role": "Search strategy, audits, optimization"},
    "creative": {"name": "Creative Agent", "role": "Images and visual content"},
    "analytics": {"name": "Analytics Agent", "role": "Performance interpretation & CRO"},
}


def slugify(text):
    s = re.sub(r"[^a-z0-9\s-]", "", (text or "").lower()).strip()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:80] or "post"


# ---------------- BRAIN ----------------
BRAIN_SYSTEM = (
    "You are the Brain Builder of AREVEI, an AI-native website growth operating system. "
    "You read raw crawled website text and distil it into a structured, versioned business knowledge base. "
    "Be concrete and specific. Infer sensibly where data is thin, but never invent fake contact details."
)


def normalize_brain_organization(brain, crawl):
    organization = brain.get("organization") if isinstance(brain.get("organization"), dict) else {}
    business_profile = brain.get("business_profile") if isinstance(brain.get("business_profile"), dict) else {}
    source_url = crawl.get("origin", "")
    normalized = {
        "company_name": organization.get("company_name") or business_profile.get("company_name") or "",
        "logo_url": organization.get("logo_url") or "",
        "address": organization.get("address") or "",
        "phone": organization.get("phone") or "",
        "email": organization.get("email") or "",
        "website": organization.get("website") or source_url,
        "tax_number": organization.get("tax_number") or "",
        "bank_details": organization.get("bank_details") or "",
        "authorized_signatory": organization.get("authorized_signatory") or "",
        "receipt_prefix": organization.get("receipt_prefix") or "",
        "invoice_prefix": organization.get("invoice_prefix") or "",
        "document_accent_color": organization.get("document_accent_color") or "",
        "document_text_color": organization.get("document_text_color") or "",
        "document_muted_color": organization.get("document_muted_color") or "",
        "document_table_header_color": organization.get("document_table_header_color") or "",
    }
    brain["organization"] = normalized
    return brain


async def build_brain(model_id, crawl):
    prompt = f"""Analyse this crawled website content and produce the business Brain.

CRAWLED CONTENT (from {crawl['page_count']} pages):
{crawl['combined_text']}

Return JSON with EXACTLY this shape:
{{
  "business_profile": {{"company_name": "", "industry": "", "description": "", "offers": ["..."], "pricing_summary": "", "locations": ["..."], "founders": ["..."]}},
  "organization": {{"company_name": "", "logo_url": "", "address": "", "phone": "", "email": "", "website": "", "tax_number": "", "bank_details": "", "authorized_signatory": "", "receipt_prefix": "", "invoice_prefix": "", "document_accent_color": "", "document_text_color": "", "document_muted_color": "", "document_table_header_color": ""}},
  "brand_identity": {{"voice": "", "personality": "", "tone_words": ["..."], "approved_wording": ["..."]}},
  "audience": {{"icps": [{{"name": "", "pains": ["..."], "motivations": ["..."], "objections": ["..."]}}], "buying_triggers": ["..."]}},
  "goals_constraints": {{"kpis": ["..."], "priorities": ["..."], "restrictions": ["..."], "publishing_cadence": "e.g. 2 blogs/week"}},
  "evidence": {{"summary": "", "testimonials": ["..."], "differentiators": ["..."]}},
  "decision_memory": {{"approved": [], "rejected": [], "notes": []}}
}}

For organization, extract only details visible in the crawled content. Use business_profile.company_name for organization.company_name when the same company is clear, and use the crawled origin URL for organization.website when no better website value appears. Leave tax, bank, prefix, signatory, and color fields empty unless the content explicitly provides them."""
    brain = await generate_json(model_id, BRAIN_SYSTEM, prompt, temperature=0.4, max_tokens=4000)
    brain = normalize_brain_organization(brain, crawl)
    brain["_source_url"] = crawl["origin"]
    brain["_pages_crawled"] = crawl["pages"]
    return brain


# ---------------- MANAGER ROADMAP + TASKS ----------------
MANAGER_SYSTEM = (
    "You are the AREVEI Manager. You own the 12-month website growth strategy. "
    "You translate the business Brain into a roadmap and concrete, schedulable daily tasks delegated to specialist agents "
    "(content, seo, creative, analytics). Tasks must be specific and measurable."
)


async def build_roadmap(model_id, brain):
    brain_str = json.dumps(brain, ensure_ascii=False)[:6000]
    prompt = f"""Business Brain:
{brain_str}

Create a 12-month growth roadmap. Return JSON:
{{
  "strategy_summary": "2-3 sentences on the overall 12-month growth thesis.",
  "months": [
    {{"month_number": 1, "theme": "", "goal": "", "kpis": ["..."], "initiatives": ["..."]}}
    // exactly 12 months
  ]
}}"""
    data = await generate_json(model_id, MANAGER_SYSTEM, prompt, temperature=0.6, max_tokens=4000)
    return data


async def generate_tasks(model_id, brain, roadmap, count=8):
    brain_str = json.dumps(brain.get("business_profile", {}), ensure_ascii=False)[:2000]
    months = json.dumps(roadmap.get("months", [])[:2], ensure_ascii=False)[:2000]
    prompt = f"""Business summary: {brain_str}
Near-term roadmap: {months}

Generate the next {count} concrete daily tasks the Manager should schedule and delegate.
Return JSON:
{{
  "tasks": [
    {{
      "title": "",
      "objective": "",
      "agent": "content|seo|creative|analytics",
      "deliverable_type": "blog_post|seo_audit|image_set|analytics_report|page_copy",
      "success_criteria": "",
      "month_number": 1,
      "requires_approval": false
    }}
  ]
}}
At least half the tasks must be content agent blog_post tasks. Make blog titles specific and SEO-driven."""
    data = await generate_json(model_id, MANAGER_SYSTEM, prompt, temperature=0.7, max_tokens=3500)
    return data.get("tasks", [])


async def manager_chat_stream(model_id, brain, roadmap, history, user_message):
    brain_str = json.dumps(brain.get("business_profile", {}), ensure_ascii=False)[:2500]
    strat = roadmap.get("strategy_summary", "") if roadmap else ""
    convo = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history[-6:])
    system = (
        MANAGER_SYSTEM
        + f"\n\nBusiness context: {brain_str}\nStrategy: {strat}\n"
        + "Speak as a decisive growth manager. Be concise, actionable, and reference the business specifics."
    )
    prompt = f"Conversation so far:\n{convo}\n\nUSER: {user_message}\n\nManager reply:"
    async for delta in _stream(model_id, system, prompt):
        yield delta


async def _stream(model_id, system, prompt):
    from llm_service import stream_text
    async for d in stream_text(model_id, system, prompt):
        yield d


# ---------------- CONTENT AGENT (BLOG) ----------------
CONTENT_SYSTEM = (
    "You are the AREVEI Content Agent, an expert SEO content writer. "
    "You write on-brand, high-quality, publish-ready blog articles as structured content blocks. "
    "Match the brand voice. Write substantive, specific content (no filler)."
)


async def write_blog(model_id, brain, topic, objective=""):
    brand = json.dumps(brain.get("brand_identity", {}), ensure_ascii=False)[:1500]
    biz = json.dumps(brain.get("business_profile", {}), ensure_ascii=False)[:1500]
    prompt = f"""Business: {biz}
Brand voice: {brand}
Blog topic/title: {topic}
Objective: {objective}

Write a complete, publish-ready blog article. Return JSON:
{{
  "title": "compelling final title",
  "excerpt": "1-2 sentence summary",
  "tags": ["3-5 tags"],
  "read_time": "e.g. 6 min read",
  "meta_title": "SEO title < 60 chars",
  "meta_description": "SEO description < 155 chars",
  "keywords": ["5-8 keywords"],
  "blocks": [
    {{"type": "paragraph", "text": "intro..."}},
    {{"type": "heading", "text": "Section heading"}},
    {{"type": "paragraph", "text": "..."}},
    {{"type": "list", "items": ["...", "..."]}},
    {{"type": "quote", "text": "a punchy insight"}},
    {{"type": "heading", "text": "..."}},
    {{"type": "paragraph", "text": "..."}}
  ]
}}
Write 6-10 sections. Use heading, paragraph, list, and quote block types. Make it genuinely useful and 900-1400 words."""
    data = await generate_json(model_id, CONTENT_SYSTEM, prompt, temperature=0.75, max_tokens=7000)
    return data
