"""realms/image_generation/pipeline.py — REAL image generation.

Backend priority:
  1. ComfyUI HTTP (127.0.0.1:8188) — workflow-based
  2. Automatic1111 HTTP (127.0.0.1:7860) — txt2img endpoint
  3. diffusers (Python) — local SD pipeline if installed + model on disk
  4. imageforge (local module) — STRATUM bridge if present

If none are ready, returns outcome=UNAVAILABLE with the remediation
hint that points the operator to the fastest path to enable a backend.

Every successful generation writes a PNG to the production session's
output directory and registers it with ArtifactLineageTracker.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)


def run(kind: str, params: dict) -> dict:
    """Public entry point. kind is 'synthesize' | 'concept_art' | 'storyboard'.
    Returns: {outcome, artifacts, backend, error, frames, ...}.
    """
    intent = params.get("intent_text", "")
    spec   = params.get("spec")
    psess  = params.get("session")
    frames = int(params.get("frames", 1))

    if psess is None:
        return {"outcome": "FAIL", "error": "missing session", "artifacts": []}

    out_dir = Path(psess.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    prompt = _build_prompt(intent, spec, kind)
    backends = _try_backends(prompt, frames, out_dir, psess, spec)
    return backends


def _build_prompt(intent_text: str, spec, kind: str) -> str:
    parts = [intent_text or "scene"]
    if spec is not None:
        if getattr(spec, "style", None):
            parts.append(spec.style)
        if getattr(spec, "lighting", None):
            parts.append(spec.lighting)
        if getattr(spec, "composition", None):
            parts.append(spec.composition)
        if getattr(spec, "atmosphere", None):
            parts.append(spec.atmosphere)
        if getattr(spec, "rendering_profile", None):
            parts.append(spec.rendering_profile)
    if kind == "concept_art":
        parts.append("concept art, production quality")
    elif kind == "storyboard":
        parts.append("storyboard frame, cinematic composition")
    return ", ".join(p for p in parts if p)


def _try_backends(prompt: str, frames: int, out_dir: Path, psess, spec) -> dict:
    """Try each backend in priority order. Returns on first success."""
    # 1. ComfyUI HTTP
    result = _try_comfyui(prompt, frames, out_dir, psess)
    if result["outcome"] == "OK":
        return result

    # 2. Automatic1111 HTTP
    result = _try_a1111(prompt, frames, out_dir, psess)
    if result["outcome"] == "OK":
        return result

    # 3. diffusers (Python)
    result = _try_diffusers(prompt, frames, out_dir, psess)
    if result["outcome"] == "OK":
        return result

    # 4. imageforge
    result = _try_imageforge(prompt, frames, out_dir, psess)
    if result["outcome"] == "OK":
        return result

    return {
        "outcome": "UNAVAILABLE",
        "error":   "no image backend reachable",
        "remediation": "start ComfyUI (port 8188) OR Automatic1111 (port 7860) "
                       "OR `pip install diffusers torch` with a local SD model",
        "backends_tried": ["comfyui", "a1111", "diffusers", "imageforge"],
        "artifacts": [],
        "backend":   "none",
    }


def _try_comfyui(prompt: str, frames: int, out_dir: Path, psess) -> dict:
    try:
        import requests
        url = "http://127.0.0.1:8188"
        # Probe
        try:
            r = requests.get(url + "/system_stats", timeout=1.5)
            if r.status_code not in (200, 404):
                return {"outcome": "UNAVAILABLE", "error": "ComfyUI unreachable",
                        "artifacts": [], "backend": "comfyui"}
        except Exception as e:
            return {"outcome": "UNAVAILABLE", "error": str(e),
                    "artifacts": [], "backend": "comfyui"}
        # Build a minimal default workflow (SDXL base — works on most ComfyUI
        # installs). If the operator has a custom model, results vary.
        # NB: ComfyUI workflows are user-specific; we use a generic baseline.
        workflow = _comfyui_default_workflow(prompt, frames)
        client_id = uuid.uuid4().hex
        r = requests.post(url + "/prompt",
                           json={"prompt": workflow, "client_id": client_id},
                           timeout=10.0)
        if r.status_code != 200:
            return {"outcome": "FAIL",
                    "error": f"ComfyUI rejected workflow: HTTP {r.status_code}",
                    "artifacts": [], "backend": "comfyui"}
        prompt_id = r.json().get("prompt_id")
        if not prompt_id:
            return {"outcome": "FAIL", "error": "no prompt_id from ComfyUI",
                    "artifacts": [], "backend": "comfyui"}
        # Poll history for completion
        artifacts: list[str] = []
        for _ in range(60):    # 60 × 2s = 2 minutes max
            time.sleep(2.0)
            h = requests.get(url + f"/history/{prompt_id}", timeout=5.0)
            if h.status_code != 200:
                continue
            history = h.json().get(prompt_id, {})
            outputs = history.get("outputs", {})
            if not outputs:
                continue
            for _node_id, node_out in outputs.items():
                for img_info in node_out.get("images", []):
                    filename = img_info.get("filename")
                    subfolder = img_info.get("subfolder", "")
                    itype = img_info.get("type", "output")
                    if not filename:
                        continue
                    view = requests.get(
                        url + "/view",
                        params={"filename": filename, "subfolder": subfolder,
                                 "type": itype},
                        timeout=10.0,
                    )
                    if view.status_code == 200:
                        out_path = out_dir / f"comfyui_{int(time.time()*1000)}_{filename}"
                        out_path.write_bytes(view.content)
                        artifacts.append(str(out_path))
                        _register(psess, out_path, "comfyui")
            if artifacts:
                break
        if artifacts:
            return {"outcome": "OK", "artifacts": artifacts,
                    "backend": "comfyui", "prompt": prompt}
        return {"outcome": "FAIL", "error": "ComfyUI returned no images",
                "artifacts": [], "backend": "comfyui"}
    except Exception as e:
        return {"outcome": "FAIL", "error": str(e),
                "artifacts": [], "backend": "comfyui"}


def _comfyui_default_workflow(prompt: str, frames: int) -> dict:
    """Default ComfyUI workflow — SDXL-style. Most installs include an
    SDXL or SD1.5 checkpoint by default. If your ComfyUI has different
    nodes, customize this."""
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed":         int(time.time()) & 0xffffffff,
                "steps":        25,
                "cfg":          7.0,
                "sampler_name": "euler",
                "scheduler":    "normal",
                "denoise":      1.0,
                "model":        ["4", 0],
                "positive":     ["6", 0],
                "negative":     ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 1024, "height": 1024, "batch_size": frames},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "lowres, blurry, watermark, jpeg artifacts",
                        "clip": ["4", 1]},
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "DBOMBLOCAL", "images": ["8", 0]},
        },
    }


def _try_a1111(prompt: str, frames: int, out_dir: Path, psess) -> dict:
    try:
        import requests
        url = "http://127.0.0.1:7860"
        try:
            r = requests.get(url + "/sdapi/v1/options", timeout=1.5)
            if r.status_code not in (200, 404):
                return {"outcome": "UNAVAILABLE", "error": "A1111 unreachable",
                        "artifacts": [], "backend": "automatic1111"}
        except Exception as e:
            return {"outcome": "UNAVAILABLE", "error": str(e),
                    "artifacts": [], "backend": "automatic1111"}
        payload = {
            "prompt":     prompt,
            "negative_prompt": "lowres, blurry, watermark, jpeg artifacts",
            "steps":      25,
            "cfg_scale":  7.0,
            "width":      1024,
            "height":     1024,
            "batch_size": min(frames, 4),
            "sampler_name": "Euler",
        }
        r = requests.post(url + "/sdapi/v1/txt2img", json=payload, timeout=180.0)
        if r.status_code != 200:
            return {"outcome": "FAIL",
                    "error": f"A1111 HTTP {r.status_code}",
                    "artifacts": [], "backend": "automatic1111"}
        body = r.json()
        artifacts: list[str] = []
        for i, b64 in enumerate(body.get("images", [])):
            try:
                data = base64.b64decode(b64.split(",", 1)[-1])
                out_path = out_dir / f"a1111_{int(time.time()*1000)}_{i:02d}.png"
                out_path.write_bytes(data)
                artifacts.append(str(out_path))
                _register(psess, out_path, "automatic1111")
            except Exception as e:
                _log.warning("A1111 decode failed for image %d: %s", i, e)
        if artifacts:
            return {"outcome": "OK", "artifacts": artifacts,
                    "backend": "automatic1111", "prompt": prompt}
        return {"outcome": "FAIL", "error": "A1111 returned no decodable images",
                "artifacts": [], "backend": "automatic1111"}
    except Exception as e:
        return {"outcome": "FAIL", "error": str(e),
                "artifacts": [], "backend": "automatic1111"}


def _try_diffusers(prompt: str, frames: int, out_dir: Path, psess) -> dict:
    try:
        from diffusers import StableDiffusionPipeline   # type: ignore
    except ImportError:
        return {"outcome": "UNAVAILABLE", "error": "diffusers not installed",
                "artifacts": [], "backend": "diffusers"}
    try:
        import torch     # type: ignore
        # Try common local model paths
        candidates = [
            "stabilityai/stable-diffusion-2-1",
            "runwayml/stable-diffusion-v1-5",
        ]
        pipe = None
        last_err = None
        for model_id in candidates:
            try:
                pipe = StableDiffusionPipeline.from_pretrained(
                    model_id,
                    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                )
                if torch.cuda.is_available():
                    pipe = pipe.to("cuda")
                break
            except Exception as e:
                last_err = e
        if pipe is None:
            return {"outcome": "UNAVAILABLE",
                    "error": f"no diffusers model loadable: {last_err}",
                    "remediation": "download an SD model via huggingface-cli",
                    "artifacts": [], "backend": "diffusers"}
        artifacts: list[str] = []
        for i in range(frames):
            image = pipe(prompt).images[0]
            out_path = out_dir / f"diffusers_{int(time.time()*1000)}_{i:02d}.png"
            image.save(str(out_path))
            artifacts.append(str(out_path))
            _register(psess, out_path, "diffusers")
        return {"outcome": "OK", "artifacts": artifacts,
                "backend": "diffusers", "prompt": prompt}
    except Exception as e:
        return {"outcome": "FAIL", "error": str(e),
                "artifacts": [], "backend": "diffusers"}


def _try_imageforge(prompt: str, frames: int, out_dir: Path, psess) -> dict:
    try:
        import imageforge   # type: ignore
        eng = imageforge.get_engine()
    except ImportError:
        return {"outcome": "UNAVAILABLE", "error": "imageforge not present",
                "artifacts": [], "backend": "imageforge"}
    except Exception as e:
        return {"outcome": "UNAVAILABLE", "error": str(e),
                "artifacts": [], "backend": "imageforge"}
    try:
        artifacts: list[str] = []
        for i in range(frames):
            result = eng.synthesize(prompt, style="cinematic")
            if result is None:
                continue
            # imageforge.synthesize returns path or PIL.Image — handle both
            if isinstance(result, str) and Path(result).is_file():
                # Move into our output dir
                src = Path(result)
                dst = out_dir / f"imageforge_{int(time.time()*1000)}_{i:02d}{src.suffix}"
                dst.write_bytes(src.read_bytes())
                artifacts.append(str(dst))
                _register(psess, dst, "imageforge")
            elif hasattr(result, "save"):
                dst = out_dir / f"imageforge_{int(time.time()*1000)}_{i:02d}.png"
                result.save(str(dst))
                artifacts.append(str(dst))
                _register(psess, dst, "imageforge")
        if artifacts:
            return {"outcome": "OK", "artifacts": artifacts,
                    "backend": "imageforge", "prompt": prompt}
        return {"outcome": "FAIL", "error": "imageforge produced nothing",
                "artifacts": [], "backend": "imageforge"}
    except Exception as e:
        return {"outcome": "FAIL", "error": str(e),
                "artifacts": [], "backend": "imageforge"}


def _register(psess, path: Path, backend: str) -> None:
    try:
        from engine.production_core import get_production_core
        get_production_core().register_artifact(psess, str(path), backend)
    except Exception:
        pass
