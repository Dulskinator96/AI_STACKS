"""
STRATUM icon — stylized eye with vertical slit pupil.
Void black bg · steel blue iris rings · plasma purple slit · white core pulse.
Writes assets/stratum_icon.ico (multi-size) + stratum_icon.ico in root.
Requires: pip install pillow
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ROOT   = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"

# STRATUM palette
BG         = (13,  17,  23,  255)   # void black
STEEL      = (88, 166, 255, 255)    # steel blue
STEEL_DIM  = (40,  90, 160, 255)
PURPLE     = (124, 58, 237, 255)    # plasma purple
PURPLE_DIM = (70,  30, 140, 255)
WHITE_CORE = (220, 240, 255, 240)
GLOW       = (88, 166, 255,  45)


def _draw(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), BG)
    d   = ImageDraw.Draw(img)
    cx = cy = size / 2

    # ── Outer ambient glow rings ────────────────────────────────────────────
    for i in range(5, 0, -1):
        rx = size * 0.46 + i * 2
        ry = size * 0.26 + i * 1.2
        alpha = 18 + i * 8
        d.ellipse(
            [cx - rx, cy - ry, cx + rx, cy + ry],
            outline=(*STEEL[:3], alpha),
            width=max(1, size // 72),
        )

    # ── Eye outline (almond shape via two arcs approximated with thick ellipse) ─
    ew = size * 0.44   # half-width
    eh = size * 0.24   # half-height
    d.ellipse(
        [cx - ew, cy - eh, cx + ew, cy + eh],
        fill=(22, 30, 48, 255),
        outline=STEEL,
        width=max(2, size // 40),
    )

    # ── Iris rings (concentric, purple → steel) ──────────────────────────────
    for idx, (frac, col) in enumerate([
        (0.74, (*PURPLE_DIM[:3], 255)),
        (0.56, (*PURPLE[:3], 255)),
        (0.40, (*STEEL_DIM[:3], 255)),
    ]):
        rx2 = ew * frac
        ry2 = eh * frac
        d.ellipse(
            [cx - rx2, cy - ry2, cx + rx2, cy + ry2],
            fill=col,
            outline=(*STEEL[:3], 100 + idx * 40),
            width=max(1, size // 80),
        )

    # ── Vertical slit pupil ──────────────────────────────────────────────────
    sw = max(3, size // 20)   # slit width
    sh = eh * 0.85             # slit height (near full iris height)
    # Dark slit body
    d.rounded_rectangle(
        [cx - sw, cy - sh, cx + sw, cy + sh],
        radius=max(2, sw),
        fill=(8, 8, 14, 255),
    )
    # Purple slit edge glow (slightly wider)
    gw = sw + max(1, size // 60)
    d.rounded_rectangle(
        [cx - gw, cy - sh - 1, cx + gw, cy + sh + 1],
        radius=max(2, gw),
        fill=None,
        outline=(*PURPLE[:3], 200),
        width=max(1, size // 64),
    )

    # ── White core pulse dot ─────────────────────────────────────────────────
    pr = max(2, size // 22)
    d.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], fill=WHITE_CORE)

    # ── Subtle scanline hatch (every 4px, very faint) ────────────────────────
    if size >= 64:
        scan_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        sd = ImageDraw.Draw(scan_layer)
        for y in range(0, size, 4):
            sd.line([(0, y), (size, y)], fill=(0, 0, 0, 28), width=1)
        img = Image.alpha_composite(img, scan_layer)

    # ── Soft glow pass via blur + composite ────────────────────────────────
    if size >= 64:
        glow_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow_layer)
        gd.ellipse(
            [cx - ew * 0.5, cy - eh * 0.5, cx + ew * 0.5, cy + eh * 0.5],
            fill=(*STEEL[:3], 55),
        )
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=size // 14))
        img = Image.alpha_composite(img, glow_layer)

    return img


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    base   = _draw(256)
    sizes  = [256, 128, 64, 48, 32, 16]
    frames = [base if s == 256 else base.resize((s, s), Image.Resampling.LANCZOS)
              for s in sizes]

    out_assets = ASSETS / "stratum_icon.ico"
    out_root   = ROOT   / "stratum_icon.ico"

    frames[0].save(
        out_assets, format="ICO",
        sizes=[(f.width, f.height) for f in frames],
        append_images=frames[1:],
    )
    out_root.write_bytes(out_assets.read_bytes())
    print(f"Written: {out_assets}")
    print(f"Written: {out_root}")


if __name__ == "__main__":
    main()
