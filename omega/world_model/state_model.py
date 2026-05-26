"""omega.world_model.state_model — L2 probabilistic behavior model.

GOLD PILLAR v2 L2 ("World Model"). Builds probabilistic structure over OBSERVED
system behavior (real run telemetry) — it is NOT a prediction engine. It emits
likely-next-state DISTRIBUTIONS with confidence bounds + explicit KNOWN-UNKNOWNS,
always assuming incomplete information. Deterministic claims are forbidden.

Read-only (L2): consumes telemetry only; never executes, never mutates, never
defines shared types. Imports only stdlib + omega.paths (L0-ish path leaf).
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

from omega.paths import omega_telemetry_dir, telemetry_root

# Realms the kernel can route to (for known-unknown detection).
_KNOWN_REALMS = ("image", "video", "audio", "game", "simulation", "code", "cast")


def _load_runs() -> list[dict]:
    runs = []
    try:
        for p in sorted(omega_telemetry_dir().glob("run-*.json"),
                        key=lambda x: x.stat().st_mtime):
            try:
                runs.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
    except Exception:
        pass
    return runs


def _wilson_95(k: int, n: int) -> list[float]:
    """95% Wilson score interval for a proportion (honest small-sample bounds)."""
    if n == 0:
        return [0.0, 1.0]
    z = 1.96
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def _confidence(n: int) -> str:
    return ("VERY_LOW" if n < 5 else "LOW" if n < 15
            else "MEDIUM" if n < 40 else "HIGH")


def build_world_model(*, persist: bool = True) -> dict:
    runs = _load_runs()
    n_total = len(runs)

    # per-realm observed outcome distribution
    per_realm: dict[str, dict] = {}
    observed_realms: set[str] = set()
    for r in runs:
        for t in r.get("tasks", []):
            realm = t.get("realm", "unknown")
            outcome = t.get("truth", "UNRESOLVED")
            observed_realms.add(realm)
            d = per_realm.setdefault(realm, {})
            d[outcome] = d.get(outcome, 0) + 1

    realm_models = {}
    for realm, counts in per_realm.items():
        n = sum(counts.values())
        dist = {k: round(v / n, 3) for k, v in counts.items()}
        dominant = max(counts.items(), key=lambda kv: kv[1])[0]
        realm_models[realm] = {
            "observations": n,
            "likely_next_states": dict(sorted(dist.items(), key=lambda kv: -kv[1])),
            "dominant_outcome": dominant,
            "confidence": _confidence(n),
            "wilson_95_dominant": _wilson_95(counts[dominant], n),
        }

    # drift: recent half vs older half RESOLVED-rate (probabilistic, low-n aware)
    drift = {"measurable": False}
    if n_total >= 6:
        mid = n_total // 2
        def resolved_rate(subset):
            ok = sum(1 for r in subset if r.get("overall_truth") == "RESOLVED")
            return ok / len(subset) if subset else 0.0
        older, recent = runs[:mid], runs[mid:]
        ro, rr = resolved_rate(older), resolved_rate(recent)
        drift = {"measurable": True,
                 "older_resolved_rate": round(ro, 3),
                 "recent_resolved_rate": round(rr, 3),
                 "delta": round(rr - ro, 3),
                 "direction": ("improving" if rr > ro else "degrading" if rr < ro else "stable"),
                 "confidence": _confidence(n_total),
                 "caveat": "two-window estimate; runs are independent, not a Markov chain"}

    known_unknowns = [{"kind": "unobserved_realm", "realm": r,
                       "note": "no behavioral data — cannot model"}
                      for r in _KNOWN_REALMS if r not in observed_realms]
    if n_total < 5:
        known_unknowns.append({"kind": "insufficient_history", "n": n_total,
                               "note": "distributions are wide; treat as priors only"})

    model = {
        "generated_at": time.time(),
        "NOT_A_PREDICTION": True,
        "framing": "probabilistic structure over observed behavior under incomplete "
                   "information; outputs are distributions + confidence ranges, "
                   "never deterministic forecasts",
        "observed_runs": n_total,
        "observed_realms": sorted(observed_realms),
        "realm_models": realm_models,
        "drift": drift,
        "known_unknowns": known_unknowns,
        "assumptions": ["incomplete information always",
                        "runs treated as independent observations",
                        "absence of data => widened uncertainty, not zero risk"],
    }
    if persist:
        try:
            (telemetry_root() / "world_model.json").write_text(
                json.dumps(model, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass
    return model
