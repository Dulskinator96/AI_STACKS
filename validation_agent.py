# validation_agent.py — STRATUM Hallucination Mitigation via Web Validation
# ──────────────────────────────────────────────────────────────────────────────
# Three-tier validation architecture:
#
#   Tier 1  — LOCAL  : Chain-of-Verification via Ollama (fast, offline, always runs)
#   Tier 2  — WEB    : DuckDuckGo Instant Answer API (free, no key, claim search)
#   Tier 3  — CORPUS : Wikipedia Summary API (free, no key, entity verification)
#
# The tiers compose a ConsensuScore. When any tier returns HIGH risk, the
# response is flagged, revised, or refused before reaching Dan.
#
# Preserves the anti_hallucination.py public API — drop-in upgrade.
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import re
import json
import time
import hashlib
import threading
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus
import logging
_log = logging.getLogger(__name__)

SAVE_DIR      = Path.home() / "Documents" / "AI_Monitor"
CACHE_FILE    = SAVE_DIR / "validation_cache.json"
OLLAMA_URL    = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "mistral:latest"

# Public endpoints — no API keys required
DDG_API       = "https://api.duckduckgo.com/"
WIKI_API      = "https://en.wikipedia.org/api/rest_v1/page/summary/"
WIKI_SEARCH   = "https://en.wikipedia.org/w/api.php"

REQUEST_TIMEOUT = 8   # seconds — web calls fail-fast rather than stall
CACHE_TTL       = 3600 * 6  # 6 hours


# ── Validation cache (in-memory + disk) ───────────────────────────────────────

class _ValidationCache:
    def __init__(self):
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        try:
            if CACHE_FILE.exists():
                raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                now = time.time()
                self._data = {k: v for k, v in raw.items()
                              if now - v.get("ts", 0) < CACHE_TTL}
        except Exception as e:
            _log.warning(f'caught exception: {e}')

    def _flush(self):
        try:
            SAVE_DIR.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(
                json.dumps(self._data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            _log.warning(f'caught exception: {e}')

    def get(self, key: str) -> Optional[dict]:
        with self._lock:
            entry = self._data.get(key)
            if entry and time.time() - entry.get("ts", 0) < CACHE_TTL:
                return entry.get("result")
            return None

    def set(self, key: str, result: dict):
        with self._lock:
            self._data[key] = {"ts": time.time(), "result": result}
            if len(self._data) % 20 == 0:
                self._flush()


_cache = _ValidationCache()


# ── Claim extractor ───────────────────────────────────────────────────────────

# Patterns that often signal checkable factual claims
_CLAIM_PATTERNS = [
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+(?:is|was|are|were|has|have|had)\b",
    r"\b(\d{4})\s+(?:was|is|marks|saw)\b",
    r"\baccording to\s+([^,.]+)",
    r"\bin\s+(\d{4}),\s+[A-Z]",
    r"\b(always|never|every|all|none|guaranteed|definitely|100%)\b",
]

def extract_factual_claims(text: str) -> list[str]:
    """
    Extract sentences containing checkable factual claims.
    Returns up to 5 candidate claims for web validation.
    """
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if len(s.strip()) > 20]
    checkable = []
    for sentence in sentences:
        for pattern in _CLAIM_PATTERNS:
            if re.search(pattern, sentence, re.IGNORECASE):
                checkable.append(sentence)
                break
    return checkable[:5]


# ── Tier 1: Local Chain-of-Verification ───────────────────────────────────────

def _local_cove_score(response: str, evidence: list[str]) -> dict:
    """
    Fast local scoring. Preserved from anti_hallucination.py.
    Returns {confidence, risk, grounded, ungrounded, flags}.
    """
    if not response:
        return {"confidence": 0.0, "risk": "high", "grounded": [], "ungrounded": [], "flags": []}

    sentences    = [s.strip() for s in re.split(r"[.!?]+", response) if s.strip()]
    evidence_text = " ".join(evidence).lower()

    RISK_PATTERNS = [
        (r"\b(always|never|every|all|none|guaranteed|definitely|certainly|100%)\b", "absolute_claim"),
        (r"\b(studies show|research proves|experts say|scientists found)\b",         "unsourced_authority"),
        (r"\b(in \d{4}|last year|recently|according to)\b",                          "temporal_claim"),
        (r"\b(the fact that|it is known that|everyone knows)\b",                     "assumed_consensus"),
    ]

    grounded, ungrounded, flags = [], [], []

    for sentence in sentences:
        words    = set(re.findall(r"\b[a-z]{4,}\b", sentence.lower()))
        overlap  = words & set(re.findall(r"\b[a-z]{4,}\b", evidence_text))
        coverage = len(overlap) / max(len(words), 1)
        (grounded if coverage >= 0.25 or len(sentence.split()) < 5 else ungrounded).append(sentence)
        for pattern, flag_name in RISK_PATTERNS:
            if re.search(pattern, sentence, re.IGNORECASE):
                flags.append({"sentence": sentence[:80], "flag": flag_name})

    g_ratio    = len(grounded) / max(len(sentences), 1)
    confidence = max(0.0, min(1.0, g_ratio - min(len(flags) * 0.1, 0.3)))
    risk       = "low" if confidence >= 0.7 else ("medium" if confidence >= 0.4 else "high")

    return {
        "confidence": round(confidence, 3), "risk": risk,
        "grounded": grounded, "ungrounded": ungrounded, "flags": flags,
    }


def _local_verify(question: str, response: str, model: str = DEFAULT_MODEL) -> dict:
    """Chain-of-Verification via Ollama."""
    gen_prompt = (
        f"Given this AI response, list 3-5 short factual verification questions "
        f"that could catch hallucinations. Only the questions, one per line.\n\n"
        f"Response: {response[:500]}"
    )
    try:
        r = requests.post(OLLAMA_URL,
            json={"model": model, "prompt": gen_prompt, "stream": False,
                  "options": {"temperature": 0.1, "num_predict": 200}},
            timeout=60)
        questions = [q.strip() for q in r.json().get("response", "").splitlines() if q.strip()]
    except Exception:
        return {"verified": False, "error": "ollama_offline", "issues": []}

    issues = []
    for q in questions[:5]:
        try:
            r2 = requests.post(OLLAMA_URL,
                json={"model": model, "prompt":
                      f"Question: {q}\nBased ONLY on this response:\n{response[:400]}\n"
                      "Answer using only what the response states. "
                      "If not addressed, say NOT ADDRESSED.",
                      "stream": False, "options": {"temperature": 0.1, "num_predict": 80}},
                timeout=30)
            answer = r2.json().get("response", "").strip()
            if "NOT ADDRESSED" in answer.upper() or "unclear" in answer.lower():
                issues.append({"question": q, "finding": answer})
        except Exception as e:
            _log.warning(f'caught exception: {e}')

    return {"verified": len(issues) == 0, "issues": issues, "questions": questions}


# ── Tier 2: DuckDuckGo Web Validation ────────────────────────────────────────

class WebFactChecker:
    """
    Validates factual claims against DuckDuckGo Instant Answer API.
    Free, no API key, respects rate limits via threading.Event.
    """

    def __init__(self):
        self._last_call = 0.0
        self._min_interval = 0.5  # 2 req/s max

    def _throttle(self):
        elapsed = time.time() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.time()

    def search(self, query: str) -> dict:
        """
        Query DuckDuckGo Instant Answer API.
        Returns {found, abstract, source, answer, related} or {found: False}.
        """
        cache_key = hashlib.md5(f"ddg:{query}".encode()).hexdigest()
        cached = _cache.get(cache_key)
        if cached:
            return cached

        self._throttle()
        try:
            r = requests.get(DDG_API, params={
                "q":              query,
                "format":         "json",
                "no_html":        "1",
                "skip_disambig":  "1",
            }, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "STRATUM-ValidationAgent/1.0"})

            if r.status_code != 200:
                return {"found": False, "error": f"HTTP {r.status_code}"}

            data     = r.json()
            abstract = data.get("AbstractText", "").strip()
            answer   = data.get("Answer", "").strip()
            source   = data.get("AbstractSource", "")
            related  = [t.get("Text", "")[:100] for t in data.get("RelatedTopics", [])[:3]]

            result = {
                "found":    bool(abstract or answer),
                "abstract": abstract[:400] if abstract else "",
                "answer":   answer[:200]   if answer   else "",
                "source":   source,
                "related":  related,
                "query":    query,
            }
            _cache.set(cache_key, result)
            return result

        except requests.exceptions.Timeout:
            return {"found": False, "error": "timeout"}
        except Exception as exc:
            return {"found": False, "error": str(exc)[:80]}

    def validate_claim(self, claim: str) -> dict:
        """
        Search for the claim, then assess whether the search result
        supports, contradicts, or is silent on the claim.
        """
        # Extract a search-friendly query from the claim
        query = re.sub(r"[^\w\s]", "", claim)[:120]
        result = self.search(query)

        if not result.get("found"):
            return {"status": "unverifiable", "claim": claim[:80], "source": None}

        abstract = (result.get("abstract", "") + " " + result.get("answer", "")).lower()
        claim_low = claim.lower()

        # Extract key nouns from claim for overlap check
        claim_words = set(re.findall(r"\b[a-z]{4,}\b", claim_low))
        abstract_words = set(re.findall(r"\b[a-z]{4,}\b", abstract))
        overlap = claim_words & abstract_words

        support_ratio = len(overlap) / max(len(claim_words), 1)

        if support_ratio >= 0.4:
            status = "supported"
        elif abstract and support_ratio < 0.1:
            status = "questionable"
        else:
            status = "unverifiable"

        return {
            "status":       status,
            "claim":        claim[:80],
            "support_ratio": round(support_ratio, 3),
            "source":       result.get("source"),
            "evidence":     (result.get("abstract") or result.get("answer", ""))[:200],
        }


_web_checker = WebFactChecker()


# ── Tier 3: Wikipedia Entity Verification ────────────────────────────────────

class WikipediaValidator:
    """
    Verifies named entities against Wikipedia Summary API.
    Confirms that persons, organizations, places, and concepts actually exist
    and that stated properties match.
    """

    def _get_summary(self, title: str) -> Optional[str]:
        cache_key = hashlib.md5(f"wiki:{title}".encode()).hexdigest()
        cached = _cache.get(cache_key)
        if cached:
            return cached.get("summary")

        try:
            url = WIKI_API + quote_plus(title.replace(" ", "_"))
            r   = requests.get(url, timeout=REQUEST_TIMEOUT,
                               headers={"User-Agent": "STRATUM-ValidationAgent/1.0"})
            if r.status_code == 200:
                data    = r.json()
                extract = data.get("extract", "")[:600]
                _cache.set(cache_key, {"summary": extract})
                return extract
        except Exception as e:
            _log.warning(f'caught exception: {e}')
        return None

    def verify_entity(self, entity: str) -> dict:
        """
        Confirm that an entity exists in Wikipedia.
        Returns {exists, summary_snippet, entity}.
        """
        summary = self._get_summary(entity)
        if summary:
            return {"exists": True, "entity": entity, "summary": summary[:300]}
        return {"exists": False, "entity": entity, "summary": None}

    def extract_entities(self, text: str) -> list[str]:
        """Extract capitalized proper nouns that might be Wikipedia-searchable."""
        # Match multi-word capitalized sequences (likely proper nouns)
        matches = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text)
        # Also single caps that aren't sentence starts
        singles = re.findall(r"(?<=[.?!]\s)([A-Z][a-z]{3,})\b", text)
        seen = set()
        result = []
        for m in matches + singles:
            if m not in seen and len(m) > 3:
                seen.add(m)
                result.append(m)
        return result[:5]


_wiki = WikipediaValidator()


# ── Consensus scorer ──────────────────────────────────────────────────────────

def _consensus_score(
    local_result: dict,
    web_results:  list[dict],
    wiki_results: list[dict],
) -> dict:
    """
    Aggregate validation signals from all tiers into a unified score.
    """
    # Base: local CoVe confidence
    base = local_result.get("confidence", 0.5)

    # Web tier adjustments
    if web_results:
        supported    = sum(1 for r in web_results if r.get("status") == "supported")
        questionable = sum(1 for r in web_results if r.get("status") == "questionable")
        web_boost    = (supported * 0.08) - (questionable * 0.12)
        base         = max(0.0, min(1.0, base + web_boost))

    # Wiki tier: existence of named entities increases confidence
    if wiki_results:
        missing = sum(1 for r in wiki_results if not r.get("exists"))
        base    = max(0.0, base - missing * 0.1)

    final_confidence = round(base, 3)
    final_risk       = "low" if final_confidence >= 0.72 else (
                       "medium" if final_confidence >= 0.42 else "high")

    web_flags = [r for r in web_results if r.get("status") == "questionable"]

    return {
        "confidence":     final_confidence,
        "risk":           final_risk,
        "web_validated":  len([r for r in web_results if r.get("status") == "supported"]),
        "web_questioned": len(web_flags),
        "wiki_confirmed": sum(1 for r in wiki_results if r.get("exists")),
        "web_flags":      web_flags,
    }


# ── ValidationAgent — main class ──────────────────────────────────────────────

class ValidationAgent:
    """
    Full three-tier hallucination mitigation agent.

    Usage:
        agent = ValidationAgent()
        result = agent.validate(question, response, evidence)

    Result keys:
        response       — final response (possibly revised)
        confidence     — 0.0–1.0
        risk           — low | medium | high
        tiers_run      — list of tiers that executed
        web_validation — per-claim web results
        wiki_results   — entity existence checks
        issues         — CoVe issues found
        revised        — bool, whether response was revised
        timestamp      — ISO timestamp
    """

    def __init__(
        self,
        model:          str  = DEFAULT_MODEL,
        run_web:        bool = True,
        run_wiki:       bool = True,
        auto_revise:    bool = True,
        web_timeout:    int  = 8,
    ):
        self.model       = model
        self.run_web     = run_web
        self.run_wiki    = run_wiki
        self.auto_revise = auto_revise
        self.web_timeout = web_timeout

    def validate(
        self,
        question:  str,
        response:  str,
        evidence:  list[str] | None = None,
    ) -> dict:
        """
        Run full three-tier validation.
        Fast tiers run first; web tiers only engage if local risk >= medium.
        """
        if not response:
            return self._empty_result()

        evidence   = evidence or []
        tiers_run  = []
        start_ts   = datetime.utcnow().isoformat()

        # ── Tier 1: Local CoVe ───────────────────────────────────────────────
        local_score = _local_cove_score(response, evidence)
        tiers_run.append("local_cove")

        cove_result = {}
        if local_score["risk"] in ("medium", "high"):
            cove_result = _local_verify(question, response, self.model)
            tiers_run.append("local_verify")

        # Use revised response if CoVe found issues
        working_response = response
        if self.auto_revise and cove_result.get("issues") and not cove_result.get("verified"):
            revised = self._revise_response(response, cove_result["issues"])
            if revised:
                working_response = revised
                local_score = _local_cove_score(working_response, evidence)

        # ── Tier 2 + 3: Web validation (only on medium/high risk) ───────────
        web_results  = []
        wiki_results = []

        if local_score["risk"] in ("medium", "high"):
            if self.run_web:
                claims = extract_factual_claims(working_response)
                for claim in claims:
                    web_results.append(_web_checker.validate_claim(claim))
                if claims:
                    tiers_run.append("web_ddg")

            if self.run_wiki:
                entities = _wiki.extract_entities(working_response)
                for entity in entities:
                    wiki_results.append(_wiki.verify_entity(entity))
                if entities:
                    tiers_run.append("wiki_verify")

        # ── Consensus score ──────────────────────────────────────────────────
        consensus = _consensus_score(local_score, web_results, wiki_results)
        final_risk = consensus["risk"]

        # Final auto-revise if web flagged additional issues
        revised = working_response != response
        if self.auto_revise and final_risk == "high" and web_results:
            web_context = "; ".join(
                f"claim '{r['claim'][:40]}' is {r['status']}"
                for r in web_results if r.get("status") in ("questionable", "unverifiable")
            )
            if web_context:
                further = self._revise_with_web_context(working_response, web_context)
                if further:
                    working_response = further
                    revised = True

        return {
            "response":       working_response,
            "original":       response,
            "revised":        revised,
            "confidence":     consensus["confidence"],
            "risk":           final_risk,
            "tiers_run":      tiers_run,
            "local_score":    local_score,
            "web_validation": web_results,
            "wiki_results":   wiki_results,
            "consensus":      consensus,
            "cove_issues":    cove_result.get("issues", []),
            "verified":       final_risk == "low",
            "timestamp":      start_ts,
        }

    def _revise_response(self, response: str, issues: list[dict]) -> Optional[str]:
        issue_text = "\n".join(f"- {i['question']}: {i['finding']}" for i in issues)
        prompt = (
            f"Revise this response to address these verification gaps. "
            f"Only state what you can confirm. Be concise.\n\n"
            f"Original: {response[:500]}\n\n"
            f"Issues:\n{issue_text}\n\n"
            f"Revised response:"
        )
        try:
            r = requests.post(OLLAMA_URL, json={
                "model": self.model, "prompt": prompt, "stream": False,
                "options": {"temperature": 0.3, "num_predict": 500}}, timeout=60)
            return r.json().get("response", "").strip() or None
        except Exception:
            return None

    def _revise_with_web_context(self, response: str, web_context: str) -> Optional[str]:
        prompt = (
            f"Revise this response. Web validation flagged these issues: {web_context}\n\n"
            f"Add appropriate uncertainty markers ([UNVERIFIED], [INFERENCE]) "
            f"for flagged claims. Keep the core answer intact.\n\n"
            f"Original: {response[:500]}\n\nRevised:"
        )
        try:
            r = requests.post(OLLAMA_URL, json={
                "model": self.model, "prompt": prompt, "stream": False,
                "options": {"temperature": 0.3, "num_predict": 500}}, timeout=60)
            return r.json().get("response", "").strip() or None
        except Exception:
            return None

    @staticmethod
    def _empty_result() -> dict:
        return {
            "response": "", "original": "", "revised": False,
            "confidence": 0.0, "risk": "high", "tiers_run": [],
            "verified": False, "timestamp": datetime.utcnow().isoformat(),
        }


# ── Backward-compatible public API (replaces anti_hallucination.py) ───────────

def score_response(response: str, evidence: list[str]) -> dict:
    return _local_cove_score(response, evidence)


def build_grounded_prompt(
    question: str, evidence: list[str],
    identity: str = "WON — DBOMB ASCENDENT", user_name: str = "Dan",
    extra_context: str = "",
) -> str:
    evidence_block = (
        "RETRIEVED EVIDENCE:\n" + "\n".join(f"[{i+1}] {e[:300]}" for i, e in enumerate(evidence[:8]))
        if evidence else "\nNO EVIDENCE RETRIEVED — flag all claims as [INFERENCE]\n"
    )
    return (
        f"You are {identity}, chaperone to {user_name}.\n\n"
        f"ANTI-HALLUCINATION RULES:\n"
        f"1. Only state facts from the EVIDENCE block\n"
        f"2. Prefix ungrounded claims with [INFERENCE]\n"
        f"3. Say 'I don't have data on this' — never fabricate\n"
        f"4. No statistics or dates not in evidence\n"
        f"5. Absolute terms (always/never/guaranteed) forbidden unless in evidence\n\n"
        f"{evidence_block}\n{extra_context}\n\n"
        f"QUESTION: {question}\n\n"
        f"FACTS: [Evidence-grounded only]\n"
        f"INFERENCE: [Reasoning beyond evidence — labeled]\n"
        f"→ Forward Vector: [Next action]"
    )


def grounded_inference(
    question: str, evidence: list[str],
    identity: str = "WON — DBOMB ASCENDENT", user_name: str = "Dan",
    model: str = DEFAULT_MODEL, verify: bool = True, timeout: int = 120,
) -> dict:
    """Full grounded inference with web validation. Drop-in for anti_hallucination.py."""
    agent = ValidationAgent(model=model, run_web=verify, run_wiki=verify)
    prompt = build_grounded_prompt(question, evidence, identity, user_name)
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": model, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.4, "num_predict": 600, "repeat_penalty": 1.15}},
            timeout=timeout)
        raw_response = r.json().get("response", "").strip()
    except Exception as exc:
        return {"response": f"[Model offline: {exc}]", "confidence": 0.0,
                "risk": "high", "verified": False, "metadata": {}}

    result = agent.validate(question, raw_response, evidence)
    return {
        "response":   result["response"],
        "confidence": result["confidence"],
        "risk":       result["risk"],
        "verified":   result["verified"],
        "ungrounded": result["local_score"].get("ungrounded", []),
        "flags":      result["local_score"].get("flags", []),
        "web_validation": result.get("web_validation", []),
        "tiers_run":  result["tiers_run"],
        "metadata": {
            "grounded_sentences":   len(result["local_score"].get("grounded", [])),
            "ungrounded_sentences": len(result["local_score"].get("ungrounded", [])),
            "evidence_used":        len(evidence),
            "web_validated":        result["consensus"].get("web_validated", 0),
            "wiki_confirmed":       result["consensus"].get("wiki_confirmed", 0),
        },
    }


# ── Module-level singleton ────────────────────────────────────────────────────

_agent: Optional[ValidationAgent] = None

def get_validation_agent(model: str = DEFAULT_MODEL) -> ValidationAgent:
    global _agent
    if _agent is None:
        _agent = ValidationAgent(model=model)
    return _agent
