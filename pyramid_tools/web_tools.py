"""
pyramid_tools/web_tools.py — Web intelligence tools.

DuckDuckGo search and URL fetching — no API keys, robots.txt-aware.
Wraps the existing WebFetcher from pyramid_ensemble for consistency.
"""
from __future__ import annotations

import re

import requests

from config import USER_AGENT, WEB_TIMEOUT, DDGO_INSTANT_URL, DDGO_HTML_URL
import logging
_log = logging.getLogger(__name__)

_MIN_TRUST = 0.35   # skip results below this trust score


def tool_web_search(query: str, n: str = "5", **_) -> str:
    """
    DuckDuckGo web search. Returns top results with title, URL, and snippet.
    No API key required. Uses instant answer API + HTML fallback.
    """
    results: list[dict] = []
    limit = min(int(n), 8)

    # Instant Answer API
    try:
        r = requests.get(
            DDGO_INSTANT_URL,
            params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
            headers={"User-Agent": USER_AGENT},
            timeout=WEB_TIMEOUT,
        )
        data = r.json()
        if data.get("AbstractText"):
            results.append({
                "title":   data.get("Heading", query),
                "url":     data.get("AbstractURL", ""),
                "snippet": data["AbstractText"][:300],
            })
    except Exception as e:
        _log.warning(f'caught exception: {e}')

    # HTML search fallback
    try:
        r = requests.get(
            DDGO_HTML_URL,
            params={"q": query},
            headers={"User-Agent": USER_AGENT},
            timeout=WEB_TIMEOUT,
        )
        blocks = re.findall(
            r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
            r'.*?<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            r.text, re.S,
        )
        for url, title, snippet in blocks[:limit]:
            url     = re.sub(r"<[^>]+>", "", url).strip()
            title   = re.sub(r"<[^>]+>", "", title).strip()
            snippet = re.sub(r"<[^>]+>", "", snippet).strip()
            if url and url not in {x["url"] for x in results}:
                results.append({"title": title, "url": url, "snippet": snippet})
    except Exception as e:
        _log.warning(f'caught exception: {e}')

    if not results:
        return f"No results found for: {query}"

    lines = [f"## Search: {query}\n"]
    for i, r in enumerate(results[:limit], 1):
        lines.append(f"{i}. **{r['title']}**")
        lines.append(f"   {r['url']}")
        lines.append(f"   {r['snippet'][:250]}\n")
    return "\n".join(lines)


def tool_fetch_url(url: str, **_) -> str:
    """
    Fetch text content from a URL. Strips HTML tags, returns plain text excerpt.
    Respects robots.txt via existing WebFetcher when ensemble is available.
    """
    try:
        from pyramid_ensemble import WebFetcher, SourceRepDB
        fetcher = WebFetcher(SourceRepDB())
        content = fetcher.fetch(url)
        return content[:1000] if content else f"Could not fetch: {url}"
    except ImportError:
        pass

    # Standalone fallback
    try:
        r = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=WEB_TIMEOUT,
            allow_redirects=True,
        )
        r.raise_for_status()
        text = r.text
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.S)
        text = re.sub(r"<style[^>]*>.*?</style>",  "", text, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:1000]
    except Exception as exc:
        return f"Fetch error for {url}: {exc}"
