"""Arevei product documentation retrieval for the AI Manager.

The docs live in product_docs.md. Retrieval is keyword scoring over feature
sections; the document set is small, so no vector store is needed.
"""
import re
from functools import lru_cache
from pathlib import Path

DOCS_PATH = Path(__file__).with_name("product_docs.md")
STOPWORDS = {
    "a", "an", "and", "are", "can", "do", "does", "for", "how", "i", "in", "is", "it", "me", "my", "of", "on",
    "or", "the", "to", "what", "with", "you", "your", "we", "our", "this", "that", "be", "should", "get", "use",
}
HELP_INTENT = re.compile(
    r"\b(what can you do|what do you do|capabilit|feature|how (do|can|to) i|how does|set ?up|setup|configure|connect|"
    r"explain|help me (with|understand)|what is|where (do|can) i|benefit|get the most|arevei|onboard|landing page|"
    r"embed|utm|voice agent|sms|whatsapp|workflow|brain|strategy|qualification)\b",
    re.I,
)


def _tokens(text):
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in STOPWORDS and len(t) > 1]


@lru_cache(maxsize=1)
def load_features():
    raw = DOCS_PATH.read_text(encoding="utf-8")
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    features = []
    for block in re.split(r"(?m)^# ", raw):
        block = block.strip()
        if not block:
            continue
        title, _, body = block.partition("\n")
        keywords = ""
        match = re.search(r"(?m)^Keywords:(.*)$", body)
        if match:
            keywords = match.group(1)
            body = body.replace(match.group(0), "")
        sections = {}
        for part in re.split(r"(?m)^## ", body):
            part = part.strip()
            if not part:
                continue
            heading, _, text = part.partition("\n")
            sections[heading.strip()] = text.strip()
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        features.append({
            "slug": slug,
            "title": title.strip(),
            "keywords": keywords.strip(),
            "sections": sections,
            "_title_tokens": set(_tokens(title)),
            "_keyword_tokens": set(_tokens(keywords)),
            "_body_tokens": _tokens(" ".join(sections.values())),
        })
    return features


def search(query, limit=2):
    """Return the best-matching feature docs for a question or topic."""
    words = _tokens(query)
    phrase = (query or "").lower()
    scored = []
    for feature in load_features():
        score = 0.0
        for word in words:
            if word in feature["_title_tokens"]:
                score += 4
            if word in feature["_keyword_tokens"]:
                score += 3
            score += min(feature["_body_tokens"].count(word), 4) * 0.5
        for keyword in feature["keywords"].split(","):
            keyword = keyword.strip().lower()
            if len(keyword) > 3 and " " in keyword and keyword in phrase:
                score += 6
        if score:
            scored.append((score, feature))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [public(feature) for _, feature in scored[:limit]]


def public(feature):
    return {"slug": feature["slug"], "title": feature["title"], "sections": feature["sections"]}


def catalog():
    return [{"slug": f["slug"], "title": f["title"], "summary": f["sections"].get("What it does", "")} for f in load_features()]


def get(slug):
    return next((public(f) for f in load_features() if f["slug"] == slug), None)


def as_text(features, max_chars=1800):
    parts = []
    for feature in features:
        lines = [f"# {feature['title']}"]
        lines.extend(f"## {heading}\n{text}" for heading, text in feature["sections"].items())
        parts.append("\n".join(lines))
    return "\n\n".join(parts)[:max_chars]


def is_help_question(message):
    return bool(HELP_INTENT.search(message or ""))


def help_context(message, max_chars=1800):
    """Prompt context for product questions, or '' when the message is not about Arevei itself."""
    if not is_help_question(message):
        return ""
    matches = search(message, limit=2)
    if not matches:
        matches = [get("getting-started-with-arevei")] if get("getting-started-with-arevei") else []
    return as_text(matches, max_chars)
