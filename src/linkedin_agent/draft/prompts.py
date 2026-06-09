"""Prompt construction for the draft writer.

Two levers from the plan: persona grounding (§3b) and voice priming with real
samples (§3a). We ask the model for STRICT JSON so we can parse multiple angles
plus a fact-check pass (§3 "flag any specific claim it isn't certain about").
"""

from __future__ import annotations

from linkedin_agent.draft.models import AngleType

# The three angles we always want — distinct takes, not three tones of one take.
ANGLE_BRIEF = {
    AngleType.CONTRARIAN: "Contrarian — everyone's celebrating this; argue why it's overhyped or wrong.",
    AngleType.PRACTICAL: "Practical — how Amir would actually use this in a real workflow / for his business.",
    AngleType.MISSED: "What everyone's missing — the under-discussed second-order effect.",
}

JSON_SCHEMA_HINT = """\
Return ONLY valid JSON (no markdown fences, no prose) of this exact shape:
{
  "angles": [
    {
      "angle_type": "contrarian" | "practical" | "missed",
      "hook": "first line, <= 120 chars, must land before the 'see more' fold",
      "body": "the rest of the post (the hook may be repeated at the start)",
      "hashtags": ["3-5 relevant tags, no # symbol"],
      "fact_flags": [
        {"claim": "any specific number/date/quote you are NOT certain about",
         "reason": "why it needs verifying"}
      ],
      "suggested_image": "one short phrase describing a useful chart/text-card, or null"
    }
  ]
}"""


def _truncate(text: str, limit: int = 700) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


def build_system_prompt(
    persona: str,
    voice_samples: list[str],
    *,
    published_posts: list[str] | None = None,
    edit_pairs: list | None = None,
) -> str:
    parts = [
        "You are a ghostwriter drafting LinkedIn posts. You write AS the author "
        "below, in their voice — not as a generic AI assistant.",
        "",
        "## Who you are writing as",
        persona,
        "",
        "## Hard rules",
        "- LinkedIn sweet spot: ~150-250 words. Hook in the FIRST line, before the fold.",
        "- Always carry a clear opinion. Never just summarize the news.",
        "- No hashtag soup: 3-5 relevant tags max, and put them ONLY in the "
        "'hashtags' array — never inside 'hook' or 'body'.",
        "- Plain language. No corporate filler, no '🚀 game-changer' clichés, no em-dash-spam.",
        "- Ground the take in the actual story; don't claim the news as your own discovery.",
        "- FACT-CHECK YOURSELF: list any specific stat/quote/date you're unsure of in "
        "fact_flags so the human can verify. Hallucinated stats are the #1 credibility killer.",
    ]
    if voice_samples:
        parts += ["", "## The author's own writing (match this voice, rhythm, vocabulary)"]
        for i, sample in enumerate(voice_samples, 1):
            parts.append(f"--- sample {i} ---\n{sample}")
    else:
        parts += ["", "(No seed writing samples — infer voice from the persona above.)"]

    # Learned signal: the author's actual published posts are the strongest
    # voice reference we have.
    if published_posts:
        parts += ["", "## The author's recent PUBLISHED posts (strongest voice signal — "
                  "weight these most)"]
        for i, post in enumerate(published_posts, 1):
            parts.append(f"--- published {i} ---\n{_truncate(post)}")

    # Learned signal: how the author revises AI drafts. Learn the corrections.
    if edit_pairs:
        parts += ["", "## How the author edits AI drafts (study what they change and why; "
                  "pre-apply these tendencies)"]
        for i, pair in enumerate(edit_pairs, 1):
            parts.append(
                f"--- edit {i} ---\nAI draft:\n{_truncate(pair.ai_draft, 500)}\n\n"
                f"Author's final:\n{_truncate(pair.final_text, 500)}"
            )

    parts += ["", "## Output format", JSON_SCHEMA_HINT]
    return "\n".join(parts)


def build_user_prompt(
    *,
    title: str,
    why_hot: str,
    url: str,
    discussion_url: str,
    angle_types: list[AngleType],
    article_excerpt: str | None = None,
) -> str:
    briefs = "\n".join(f"- {ANGLE_BRIEF[a]}" for a in angle_types)
    parts = [
        "Write LinkedIn post drafts about this trending topic.",
        "",
        f"TOPIC: {title}",
        f"WHY IT'S HOT: {why_hot}",
        f"SOURCE: {url}",
        f"DISCUSSION: {discussion_url}",
    ]
    if article_excerpt:
        parts += [
            "",
            "ARTICLE EXCERPT (for grounding — quote facts only from here or flag them):",
            article_excerpt[:4000],
        ]
    parts += [
        "",
        f"Produce exactly {len(angle_types)} DISTINCT angles:",
        briefs,
        "",
        "Each angle must be self-contained and ready to post.",
    ]
    return "\n".join(parts)


def build_regenerate_user_prompt(base_prompt: str, angle_type: AngleType) -> str:
    return (
        base_prompt
        + f"\n\nThe previous {angle_type.value} draft missed. Write a fresh, "
        "noticeably different take for that SAME angle. Return the same JSON shape "
        "with a single angle."
    )
