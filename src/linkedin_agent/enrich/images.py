"""Self-made visuals — text cards and charts.

The plan's recommendation: default to recreated charts / text cards. They look
more credible than generic AI art and sidestep copyright entirely. We never
fetch or embed third-party marketing images.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# LinkedIn landscape (1.91:1) renders cleanly in-feed.
WIDTH, HEIGHT = 1200, 627
CARD_STYLE_VERSION = "minimal_v1"
BG = (22, 20, 18)        # warm lacquer black
FG = (247, 242, 232)     # warm white
ACCENT = (184, 149, 82)  # restrained kinpaku gold

# Candidate fonts (macOS first, then common Linux), with PIL default fallback.
_FONT_CANDIDATES = {
    "display": [
        "/System/Library/Fonts/Avenir Next Condensed.ttc",
        "/Library/Fonts/DINPro Bold.otf",
        "/System/Library/Fonts/SFCompact.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ],
    "body": [
        "/System/Library/Fonts/Avenir Next.ttc",
        "/System/Library/Fonts/SFNS.ttf",
        "/Library/Fonts/SourceSansPro-Regular.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
    "mono": [
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/Library/Fonts/SourceCodePro-Medium.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ],
}


def _load_font(size: int, role: str = "body") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES.get(role, _FONT_CANDIDATES["body"]):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _split_long_word(draw, word: str, font, max_width: int) -> list[str]:
    """Break a single long token so it cannot overflow the card."""
    if draw.textlength(word, font=font) <= max_width:
        return [word]

    pieces: list[str] = []
    cur = ""
    for char in word:
        trial = cur + char
        if cur and draw.textlength(trial, font=font) > max_width:
            pieces.append(cur)
            cur = char
        else:
            cur = trial
    if cur:
        pieces.append(cur)
    return pieces


def _wrap_to_width(draw, text: str, font, max_width: int) -> list[str]:
    """Greedy wrap that respects pixel width, not just char count."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = [
            piece
            for word in paragraph.split()
            for piece in _split_long_word(draw, word, font, max_width)
        ]
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for word in words[1:]:
            trial = f"{cur} {word}"
            if draw.textlength(trial, font=font) <= max_width:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _seed(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _add_texture(img: Image.Image, seed: int) -> None:
    """Low-cost deterministic texture so the card does not read as a flat fill."""
    rng = random.Random(seed)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    # Subtle paper grain, not visible geometry.
    px = overlay.load()
    for _ in range(8500):
        x = rng.randrange(WIDTH)
        y = rng.randrange(HEIGHT)
        v = rng.randrange(190, 256)
        px[x, y] = (v, v, v, rng.randrange(3, 11))
    img.alpha_composite(overlay)


def _fit_quote(draw, text: str, max_width: int, max_height: int):
    for size in (74, 68, 62, 56, 50, 44, 39, 34, 30):
        font = _load_font(size, "display")
        lines = _wrap_to_width(draw, text.strip(), font, max_width)
        line_h = int(size * 1.05)
        if len(lines) * line_h <= max_height:
            return font, lines, line_h

    font = _load_font(28, "display")
    lines = _wrap_to_width(draw, text.strip(), font, max_width)
    return font, lines, 31


def text_card(
    quote: str,
    out_path: str | Path,
    *,
    attribution: str = "Amir",
    bg: tuple = BG,
    fg: tuple = FG,
    accent: tuple = ACCENT,
) -> str:
    """Render a premium editorial text card. Returns the saved path."""
    clean_quote = " ".join(quote.strip().split())
    if not clean_quote:
        clean_quote = "A sharper point belongs here."

    img = Image.new("RGBA", (WIDTH, HEIGHT), bg + (255,))
    draw = ImageDraw.Draw(img)
    seed = _seed(clean_quote)
    _add_texture(img, seed)

    # The headline is the design. Keep it airy and asymmetric: no rules,
    # borders, quote marks, labels, side rails, or decorative geometry.
    content_x = 96
    content_y = 94
    content_w = 860
    content_h = 440

    font, lines, line_h = _fit_quote(draw, clean_quote, content_w, content_h)
    total_h = len(lines) * line_h
    y = content_y + max(0, (content_h - total_h) // 2) - 4
    for line in lines:
        draw.text((content_x, y), line, font=font, fill=fg)
        y += line_h

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, "PNG")
    return str(out_path)


def bar_chart(
    title: str,
    labels: list[str],
    values: list[float],
    out_path: str | Path,
) -> str:
    """A clean recreated chart (matplotlib, Agg backend). Returns saved path."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(WIDTH / 100, HEIGHT / 100), dpi=100)
    fig.patch.set_facecolor("#131210")
    ax.set_facecolor("#131210")
    bars = ax.bar(labels, values, color="#b79450")
    ax.set_title(title, color="#f6f2e8", fontsize=18, pad=16, weight="bold")
    ax.tick_params(colors="#b2ab9a", labelsize=12)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.bar_label(bars, color="#f6f2e8", fontsize=11, padding=3)
    fig.tight_layout()
    fig.savefig(out_path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return str(out_path)


def make_card_for_draft(card_text: str, out_dir: str | Path, draft_id: int) -> str:
    """Default enrichment: turn the approved image text into a text card."""
    out_path = Path(out_dir) / f"draft_{draft_id}_{CARD_STYLE_VERSION}.png"
    return text_card(card_text, out_path)
