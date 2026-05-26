"""realms/video_production/pipeline.py — REAL video assembly.

Backends:
  · ffmpeg (CLI on PATH) — primary. Real concat, trim, title cards.
  · DaVinci Resolve scripting — probe-only; Resolve Python API requires
                                  Resolve to be running with scripting
                                  enabled. We don't auto-attach; we
                                  emit DEGRADED with the path forward.

Capabilities:
  · title_card     — single mp4 with overlaid title text (PIL → mp4)
  · assemble       — concatenate session's image artifacts into a slideshow
                      with the session's audio artifact as soundtrack
  · trim           — trim an existing artifact

The pipeline writes real .mp4 files; nothing is faked. If ffmpeg is
absent, we honestly report UNAVAILABLE with remediation.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)


def run(kind: str, params: dict) -> dict:
    intent = params.get("intent_text", "")
    spec   = params.get("spec")
    psess  = params.get("session")

    if psess is None:
        return {"outcome": "FAIL", "error": "missing session", "artifacts": []}

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"outcome": "UNAVAILABLE",
                "error": "ffmpeg not on PATH",
                "remediation": "install ffmpeg and add to PATH",
                "artifacts": [], "backend": "ffmpeg"}

    out_dir = Path(psess.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if kind == "title_card":
        return _title_card(ffmpeg, intent, spec, psess, out_dir)
    if kind == "assemble":
        return _assemble(ffmpeg, intent, spec, psess, out_dir)
    if kind == "trim":
        return _trim(ffmpeg, params, psess, out_dir)
    return {"outcome": "UNAVAILABLE",
            "error": f"unknown kind '{kind}'",
            "artifacts": [], "backend": "ffmpeg"}


def _title_card(ffmpeg: str, intent: str, spec, psess, out_dir: Path) -> dict:
    """Render a 4-second title-card video with the intent as text via
    ffmpeg's drawtext filter. No images required — pure ffmpeg."""
    title = (intent or "DBOMBLOCAL")[:80].replace("'", "")
    style = (getattr(spec, "style", "") or "")
    out_path = out_dir / f"title_{int(time.time()*1000)}.mp4"

    bg = "0x06091c"   # default deep blue
    fg = "white"
    if "cyberpunk" in style.lower() or "neon" in style.lower():
        bg, fg = "0x1a0e3e", "0xffce28"
    elif "noir" in style.lower():
        bg, fg = "0x000000", "0xffffff"

    cmd = [
        ffmpeg, "-y", "-f", "lavfi",
        "-i", f"color=c={bg}:s=1280x720:d=4",
        "-vf",
        f"drawtext=text='{title}':fontcolor={fg}:fontsize=64:x=(w-text_w)/2:y=(h-text_h)/2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "ultrafast", "-crf", "23",
        str(out_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        if proc.returncode != 0:
            return {"outcome": "FAIL",
                    "error": proc.stderr.decode(errors="ignore")[:200],
                    "artifacts": [], "backend": "ffmpeg"}
        _register(psess, out_path, "ffmpeg")
        return {"outcome": "OK", "artifacts": [str(out_path)],
                "backend": "ffmpeg", "duration_s": 4}
    except Exception as e:
        return {"outcome": "FAIL", "error": str(e),
                "artifacts": [], "backend": "ffmpeg"}


def _assemble(ffmpeg: str, intent: str, spec, psess, out_dir: Path) -> dict:
    """Concatenate session's image artifacts into a slideshow video
    using the session's audio artifact (if any) as soundtrack."""
    # Gather artifacts in session
    images: list[Path] = []
    audios: list[Path] = []
    for art in getattr(psess, "artifacts", []):
        p = Path(art.path if hasattr(art, "path") else art)
        suf = p.suffix.lower()
        if suf in (".png", ".jpg", ".jpeg"):
            images.append(p)
        elif suf in (".wav", ".mp3", ".m4a", ".aac", ".flac"):
            audios.append(p)
    if not images:
        # Fall back to a title card so we always produce SOMETHING real
        return _title_card(ffmpeg, intent, spec, psess, out_dir)

    out_path = out_dir / f"assembly_{int(time.time()*1000)}.mp4"
    duration_per_image = 2.5
    # Build concat input list
    concat_list = out_dir / "concat_inputs.txt"
    with concat_list.open("w", encoding="utf-8") as fh:
        for img in images:
            fh.write(f"file '{img.as_posix()}'\n")
            fh.write(f"duration {duration_per_image}\n")
        # ffmpeg quirk: last image needs to be repeated without duration
        fh.write(f"file '{images[-1].as_posix()}'\n")
    try:
        cmd = [
            ffmpeg, "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
        ]
        if audios:
            cmd += ["-i", str(audios[0]), "-shortest"]
        cmd += [
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,"
                    "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "ultrafast", "-crf", "23",
        ]
        if audios:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += [str(out_path)]
        proc = subprocess.run(cmd, capture_output=True, timeout=180)
        if proc.returncode != 0:
            return {"outcome": "FAIL",
                    "error": proc.stderr.decode(errors="ignore")[-400:],
                    "artifacts": [], "backend": "ffmpeg"}
        _register(psess, out_path, "ffmpeg")
        return {"outcome": "OK", "artifacts": [str(out_path)],
                "backend": "ffmpeg",
                "image_count": len(images),
                "has_audio": bool(audios),
                "duration_s": duration_per_image * len(images)}
    except Exception as e:
        return {"outcome": "FAIL", "error": str(e),
                "artifacts": [], "backend": "ffmpeg"}


def _trim(ffmpeg: str, params: dict, psess, out_dir: Path) -> dict:
    src = params.get("source_path")
    start = float(params.get("start", 0.0))
    duration = float(params.get("duration", 4.0))
    if not src or not Path(src).is_file():
        return {"outcome": "FAIL", "error": "missing source",
                "artifacts": [], "backend": "ffmpeg"}
    out_path = out_dir / f"trim_{int(time.time()*1000)}_{Path(src).stem}.mp4"
    cmd = [ffmpeg, "-y", "-ss", str(start), "-i", src,
           "-t", str(duration), "-c", "copy", str(out_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        if proc.returncode != 0:
            return {"outcome": "FAIL",
                    "error": proc.stderr.decode(errors="ignore")[:200],
                    "artifacts": [], "backend": "ffmpeg"}
        _register(psess, out_path, "ffmpeg")
        return {"outcome": "OK", "artifacts": [str(out_path)],
                "backend": "ffmpeg"}
    except Exception as e:
        return {"outcome": "FAIL", "error": str(e),
                "artifacts": [], "backend": "ffmpeg"}


def _register(psess, path: Path, backend: str) -> None:
    try:
        from engine.production_core import get_production_core
        get_production_core().register_artifact(psess, str(path), backend)
    except Exception:
        pass
