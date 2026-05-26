"""engine/creative_composition/aesthetic_director.py — palette + atmosphere.

Consolidates the style/palette/atmosphere fields from ExpandedSpec into
an AestheticProfile that workers can quote in their generation prompts.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class AestheticProfile:
    profile_id:       str
    style:            str
    palette:          list
    atmosphere:       str
    architecture:     str
    soundtrack:       str
    rendering:        str
    detail_level:     str
    emotional_anchor: str
    created_at:       float

    def to_dict(self) -> dict:
        return asdict(self)

    def render(self) -> str:
        return (f"  ▸ style: {self.style}  ·  detail: {self.detail_level}\n"
                f"  ▸ palette: {' '.join(self.palette) if self.palette else '—'}\n"
                f"  ▸ atmosphere: {self.atmosphere or '—'}\n"
                f"  ▸ architecture: {self.architecture or '—'}\n"
                f"  ▸ soundtrack: {self.soundtrack or '—'}\n"
                f"  ▸ rendering: {self.rendering or '—'}")


class AestheticDirector:
    """Pulls style/palette/atmosphere together from ExpandedSpec."""

    def direct(self, spec) -> AestheticProfile:
        return AestheticProfile(
            profile_id=f"aes-{uuid.uuid4().hex[:8]}",
            style=getattr(spec, "style", "") or "open",
            palette=list(getattr(spec, "color_palette", []) or []),
            atmosphere=getattr(spec, "atmosphere", "") or "",
            architecture=getattr(spec, "architecture_style", "") or "",
            soundtrack=getattr(spec, "soundtrack_profile", "") or "",
            rendering=getattr(spec, "rendering_profile", "") or "",
            detail_level=getattr(spec, "detail_level", "") or "moderate",
            emotional_anchor=getattr(spec, "emotion", "") or "neutral",
            created_at=time.time(),
        )
