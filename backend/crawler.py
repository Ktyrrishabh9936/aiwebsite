import re
import logging
from urllib.parse import urljoin, urlparse
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("crawler")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AreveiBot/1.0; +https://arevei.ai)"}


def _clean_text(soup):
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text)


async def crawl_site(url, max_pages=5):
    if not url.startswith("http"):
        url = "https://" + url
    base = urlparse(url)
    origin = f"{base.scheme}://{base.netloc}"
    visited = []
    pages_text = []
    to_visit = [url]

    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=HEADERS) as client:
        while to_visit and len(visited) < max_pages:
            current = to_visit.pop(0)
            if current in visited:
                continue
            try:
                r = await client.get(current)
                if r.status_code >= 400 or "text/html" not in r.headers.get("content-type", ""):
                    visited.append(current)
                    continue
                soup = BeautifulSoup(r.text, "lxml")
                title = (soup.title.string if soup.title else "") or ""
                text = _clean_text(soup)[:6000]
                pages_text.append({"url": current, "title": title.strip(), "text": text})
                visited.append(current)

                if len(visited) < max_pages:
                    for a in soup.find_all("a", href=True):
                        href = urljoin(current, a["href"])
                        p = urlparse(href)
                        if p.netloc == base.netloc and href not in visited and href not in to_visit:
                            if any(k in href.lower() for k in ["about", "service", "product", "pricing", "contact", "team", "solution"]):
                                to_visit.insert(0, href)
                            elif href not in to_visit:
                                to_visit.append(href)
            except Exception:
                logger.warning("crawl failed for %s", current)
                visited.append(current)

    combined = "\n\n".join(f"URL: {p['url']}\nTITLE: {p['title']}\n{p['text']}" for p in pages_text)
    return {
        "origin": origin,
        "pages": [p["url"] for p in pages_text],
        "combined_text": combined[:18000],
        "page_count": len(pages_text),
    }
