"""Generate Amir's LinkedIn banner (1584x396).

Premium editorial look in the same palette as the agent's content cards
(warm lacquer black + restrained gold). Layout keeps all text clear of the
lower-left zone where LinkedIn overlays the circular profile photo, and clear
of the far-right edge that gets cropped on some viewports.

Run:  uv run python scripts/make_banner.py
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from linkedin_agent.enrich.images import _load_font  # reuse the font resolver

W, H = 1584, 396

# Palette
BG_TOP = (27, 25, 22)
BG_BOTTOM = (16, 15, 13)
FG = (247, 242, 232)        # warm white
MUTED = (178, 171, 154)     # warm grey
GOLD = (184, 149, 82)       # restrained kinpaku gold
GOLD_BRIGHT = (210, 174, 104)

# Text block left edge: clears the profile-photo circle that LinkedIn pins to
# the lower-left of the banner.
X0 = 470
MOTIF_X = (1150, 1545)      # node-graph lives in the right region


def _vertical_gradient() -> Image.Image:
    base = Image.new("RGB", (W, H))
    px = base.load()
    for y in range(H):
        t = y / (H - 1)
        r = round(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = round(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = round(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        for x in range(W):
            px[x, y] = (r, g, b)
    return base.convert("RGBA")


def _add_glow(img: Image.Image, center, radius, color, strength) -> None:
    """Soft warm glow to give the flat fill depth (upper-right)."""
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    cx, cy = center
    rw, rh = radius
    d.ellipse([cx - rw, cy - rh, cx + rw, cy + rh], fill=strength)
    mask = mask.filter(ImageFilter.GaussianBlur(130))
    tint = Image.new("RGBA", (W, H), color + (0,))
    img.paste(tint, (0, 0), mask)


def _add_grain(img: Image.Image, seed: int = 11) -> None:
    rng = random.Random(seed)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    px = overlay.load()
    for _ in range(14000):
        x, y = rng.randrange(W), rng.randrange(H)
        v = rng.randrange(190, 256)
        px[x, y] = (v, v, v, rng.randrange(2, 9))
    img.alpha_composite(overlay)


def _node_graph(img: Image.Image, seed: int = 7) -> None:
    """A faint 'agent graph' of connected nodes in the right region."""
    rng = random.Random(seed)
    pts = [(rng.randint(*MOTIF_X), rng.randint(50, 360)) for _ in range(12)]
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # connect each node to its two nearest neighbours
    for i, a in enumerate(pts):
        dists = sorted(
            (math.dist(a, b), j) for j, b in enumerate(pts) if j != i
        )
        for _, j in dists[:2]:
            d.line([a, pts[j]], fill=GOLD + (38,), width=1)
    for i, p in enumerate(pts):
        r = 5 if i % 4 == 0 else 3
        col = GOLD_BRIGHT + (150,) if i % 4 == 0 else GOLD + (95,)
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=col)
    layer = layer.filter(ImageFilter.GaussianBlur(0.4))
    img.alpha_composite(layer)


def _spaced(text: str, spacing: str = "  ") -> str:
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x


def _pill(draw: ImageDraw.ImageDraw, text: str) -> None:
    """'Open to internships' outline pill, top-right."""
    font = _load_font(20, "body")
    tw = draw.textlength(text, font=font)
    pad_x, pad_y = 22, 11
    right = W - 64
    x1, y1 = right, 40
    x0 = x1 - (tw + 2 * pad_x)
    y0_ = y1
    y1b = y1 + 20 + 2 * pad_y
    draw.rounded_rectangle([x0, y0_, x1, y1b], radius=(y1b - y0_) // 2,
                           outline=GOLD, width=2)
    draw.text((x0 + pad_x, y0_ + pad_y - 1), text, font=font, fill=GOLD_BRIGHT)


def main() -> str:
    img = _vertical_gradient()
    _add_glow(img, center=(1230, 70), radius=(460, 300), color=GOLD, strength=46)
    _node_graph(img)
    _add_grain(img)
    draw = ImageDraw.Draw(img)

    # eyebrow
    eyebrow_font = _load_font(22, "display")
    draw.text((X0 + 3, 96), _spaced("BUILDING PRACTICAL AI"),
              font=eyebrow_font, fill=GOLD_BRIGHT)

    # name
    name_font = _load_font(78, "display")
    draw.text((X0, 122), "Amir Buzubayev", font=name_font, fill=FG)

    # tagline
    tag_font = _load_font(31, "body")
    draw.text((X0 + 2, 218),
              "AI Engineer — LLM agents & automation that ship",
              font=tag_font, fill=MUTED)

    # gold divider
    draw.line([(X0 + 3, 270), (X0 + 3 + 470, 270)], fill=GOLD, width=2)

    # keyword strip
    kw_font = _load_font(24, "body")
    parts = ["Python", "LLMs", "RAG", "Automation", "Full-Stack"]
    x = X0 + 3
    y = 286
    for i, part in enumerate(parts):
        if i:
            dot = "  ·  "
            draw.text((x, y), dot, font=kw_font, fill=GOLD)
            x += draw.textlength(dot, font=kw_font)
        draw.text((x, y), part, font=kw_font, fill=FG)
        x += draw.textlength(part, font=kw_font)

    _pill(draw, "OPEN TO AI / ML INTERNSHIPS")

    out = Path("generated_images/linkedin_banner.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, "PNG")
    print(f"wrote {out.resolve()}  ({W}x{H})")
    return str(out)


if __name__ == "__main__":
    main()
