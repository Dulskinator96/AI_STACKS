"""realms/ — BUILD-021 ASCENSION PHASE.

Real production pipelines. Each subpackage exports `run(kind, params)`
returning {outcome, artifacts, error, backend, ...}.

Subpackages:
  · image_generation   — ComfyUI HTTP, A1111 HTTP, diffusers fallback
  · audio_engine       — pyttsx3, Bark, ambient synthesis via numpy
  · video_production   — ffmpeg assembly + title cards via PIL
  · game_creation      — Godot/Blender/Unreal project scaffolds
  · simulation         — procedural terrain + faction maps via numpy

Reality Enforcement: every realm probes its backend FIRST. Missing
dependencies → outcome=UNAVAILABLE with remediation. Never fakes.
"""
