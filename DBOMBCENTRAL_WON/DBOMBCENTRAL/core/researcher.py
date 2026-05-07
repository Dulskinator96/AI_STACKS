# core/researcher.py — WON public source intelligence
"""
Free research engine. Uses DuckDuckGo (no API key) + BeautifulSoup for extraction.
Structures raw results into summarised intel blocks.
"""
import requests
from bs4 import BeautifulSoup
from datetime import datetime

_HEADERS = {"User-Agent": "Mozilla/5.0 (WON-Agent/1.0)"}
_DDG_URL  = "https://html.duckduckgo.com/html/"

class Researcher:
    def pull(self, query: str, max_results: int = 5) -> list[dict]:
        """Search DuckDuckGo and return structured result blocks."""
        raw = self._ddg_search(query, max_results)
        out = []
        for r in raw:
            out.append({
                "title":   r.get("title", ""),
                "url":     r.get("url", ""),
                "summary": r.get("snippet", ""),
                "source":  r.get("source", ""),
                "fetched": datetime.utcnow().isoformat(),
            })
        return out

    def fetch_page(self, url: str, max_chars: int = 1500) -> str:
        """Fetch and clean a specific page's text content."""
        try:
            r = requests.get(url, headers=_HEADERS, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = " ".join(soup.get_text(separator=" ").split())
            return text[:max_chars]
        except Exception as e:
            return f"[fetch error: {e}]"

    def _ddg_search(self, query: str, max_results: int) -> list[dict]:
        try:
            r = requests.post(
                _DDG_URL,
                data={"q": query, "b": "", "kl": "us-en"},
                headers=_HEADERS,
                timeout=10,
            )
            soup  = BeautifulSoup(r.text, "html.parser")
            items = soup.select(".result")
            results = []
            for item in items[:max_results]:
                title_el   = item.select_one(".result__title")
                url_el     = item.select_one(".result__url")
                snippet_el = item.select_one(".result__snippet")
                title   = title_el.get_text(strip=True)   if title_el   else ""
                url     = url_el.get_text(strip=True)     if url_el     else ""
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                if title:
                    results.append({
                        "title":   title,
                        "url":     f"https://{url}" if url and not url.startswith("http") else url,
                        "snippet": snippet,
                        "source":  url.split("/")[0] if url else "",
                    })
            return results
        except Exception as e:
            return [{"title": "Research unavailable", "url": "", "snippet": str(e), "source": ""}]
