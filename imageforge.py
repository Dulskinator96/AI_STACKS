"""
imageforge.py — IMAGEFORGE-GEMINI Deterministic Image Synthesis Engine.

This module converts visual intent (prompts) into concrete image artifacts.
It sits as a specialized high-fidelity layer ABOVE synthesis.py.

Mandates:
  1. Standalone artifacts only — NO UI screens, dashboards, or screenshots.
  2. Default to cinematic photorealism (35mm, volumetric lighting).
  3. Strict negative prompt enforcement.
"""

import logging
import random
from pathlib import Path
from typing import Optional, Dict, Any

# AI_MONITOR Imports
import synthesis
import truth_layer

_log = logging.getLogger("stratum.imageforge")


class ImageForge:
    DEFAULT_NEGATIVE = synthesis.SDClient.NEGATIVE_PROMPT

    def __init__(self):
        self.use_sd = True
        try:
            self.sd_available = synthesis.SDClient.is_available()
        except Exception as exc:
            _log.warning(f"SDClient availability probe failed: {exc}")
            self.sd_available = False

    def generate(
        self,
        prompt: str,
        style_tags: Optional[str] = None,
        width: int = 512,
        height: int = 512,
        seed: int = -1,
    ) -> Dict[str, Any]:
        full_prompt = f"{prompt}, {style_tags}" if style_tags else prompt
        spec = {
            "prompt":     prompt,
            "style_tags": style_tags,
            "width":      width,
            "height":     height,
            "seed":       seed,
        }
        output_path: Optional[Path] = None
        mode = "PROMPT_FALLBACK"

        if self.use_sd and self.sd_available:
            try:
                output_path = synthesis.SDClient.txt2img(
                    prompt=full_prompt,
                    negative=self.DEFAULT_NEGATIVE,
                    width=width,
                    height=height,
                    seed=seed if seed != -1 else random.randint(0, 1000000)
                )
                if output_path:
                    mode = "SD_WEBUI"
            except Exception as exc:
                _log.error(f"SD synthesis failed: {exc}")

        # 4. Result Payload
        audit = truth_layer.get_audit()
        verdict = None
        if output_path:
            verdict = audit.verify_image(str(output_path))
            if not audit.commit(output_path, verdict):
                _log.error(f"AUDIT FAILURE: {verdict['reason']}")
                return {
                    "status": "failed",
                    "reason": verdict["reason"],
                    "path": str(output_path),
                    "mode": mode,
                    "audit_result": verdict
                }

        return {
            "status": "success" if output_path else "prompt_fallback",
            "path": str(output_path) if output_path else None,
            "mode": mode,
            "spec": spec,
            "audit_result": verdict,
            "metadata": {
                "engine": "IMAGEFORGE-GEMINI",
                "interpretation": "physical_scene"
            }
        }


# ── Singleton Interface ───────────────────────────────────────────────────────

_engine = None

def get_engine() -> ImageForge:
    global _engine
    if _engine is None:
        _engine = ImageForge()
    return _engine

def synthesize(prompt: str, style: str = None) -> Dict[str, Any]:
    """Helper for one-shot synthesis."""
    return get_engine().generate(prompt, style_tags=style)
