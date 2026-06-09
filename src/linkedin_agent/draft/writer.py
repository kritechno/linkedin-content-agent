"""Turn a topic into opinionated, voice-matched draft angles."""

from __future__ import annotations

import re
from html.parser import HTMLParser

import httpx

from linkedin_agent import feedback
from linkedin_agent.config import Settings, get_settings
from linkedin_agent.draft import prompts
from linkedin_agent.draft.llm import LLMProvider, get_provider
from linkedin_agent.draft.models import AngleType, DraftAngle, DraftSet, FactFlag
from linkedin_agent.research.models import Story
from linkedin_agent.voice import load_voice_samples

DEFAULT_ANGLES = [AngleType.CONTRARIAN, AngleType.PRACTICAL, AngleType.MISSED]


def _build_system(settings: Settings) -> str:
    """System prompt = persona + seed samples + learned voice (published posts
    and edit corrections accumulated from past approvals)."""
    return prompts.build_system_prompt(
        settings.persona,
        load_voice_samples(settings.voice_samples_dir),
        published_posts=feedback.recent_finals(settings),
        edit_pairs=feedback.recent_edits(settings),
    )


class _TextExtractor(HTMLParser):
    """Collect readable text from content tags; skip script/style/nav."""

    _CONTENT = {"p", "h1", "h2", "h3", "li", "blockquote"}
    _SKIP = {"script", "style", "noscript", "nav", "header", "footer"}

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._capture = False
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._CONTENT:
            self._capture = True

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._CONTENT:
            self._capture = False
            self._chunks.append("\n")

    def handle_data(self, data):
        if self._capture and not self._skip_depth:
            text = data.strip()
            if text:
                self._chunks.append(text + " ")

    @property
    def text(self) -> str:
        joined = "".join(self._chunks)
        return "\n".join(line.strip() for line in joined.splitlines() if line.strip())


def fetch_article_excerpt(url: str, *, max_chars: int = 4000, timeout: float = 12.0) -> str | None:
    """Best-effort: pull readable text so the draft is grounded in the real
    story, not the model's stale priors. Returns None on any failure."""
    if not url or "news.ycombinator.com" in url:
        return None  # HN discussion pages aren't the article
    try:
        resp = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; linkedin-agent/0.1)"},
        )
        resp.raise_for_status()
        if "text/html" not in resp.headers.get("content-type", ""):
            return None
        parser = _TextExtractor()
        parser.feed(resp.text)
        text = parser.text
        return text[:max_chars] if len(text) > 200 else None
    except Exception:
        return None


def _strip_trailing_hashtags(text: str) -> str:
    """Models often duplicate hashtags inside the body even when told not to.
    Remove a trailing run of #tags so full_text doesn't render them twice."""
    return re.sub(r"(\s*#[\w-]+)+\s*$", "", text).rstrip()


def _parse_angles(data: dict) -> list[DraftAngle]:
    angles: list[DraftAngle] = []
    for a in data.get("angles", []):
        try:
            atype = AngleType(str(a.get("angle_type", "practical")).lower())
        except ValueError:
            atype = AngleType.PRACTICAL
        flags = [
            FactFlag(claim=f.get("claim", ""), reason=f.get("reason", ""))
            for f in a.get("fact_flags", []) or []
            if f.get("claim")
        ]
        hashtags = [str(t).lstrip("#") for t in a.get("hashtags", []) or []][:5]
        img = a.get("suggested_image")
        angles.append(
            DraftAngle(
                angle_type=atype,
                hook=_strip_trailing_hashtags(str(a.get("hook", "")).strip()),
                body=_strip_trailing_hashtags(str(a.get("body", "")).strip()),
                hashtags=hashtags,
                fact_flags=flags,
                suggested_image=img if img and str(img).lower() != "null" else None,
            )
        )
    return angles


def generate_draft_set(
    *,
    title: str,
    why_hot: str,
    url: str,
    discussion_url: str,
    settings: Settings | None = None,
    provider: LLMProvider | None = None,
    angle_types: list[AngleType] | None = None,
    ground: bool | None = None,
) -> DraftSet:
    settings = settings or get_settings()
    provider = provider or get_provider(settings)
    angle_types = angle_types or DEFAULT_ANGLES[: settings.n_angles]
    ground = settings.ground_with_article if ground is None else ground

    system = _build_system(settings)
    excerpt = fetch_article_excerpt(url) if ground else None
    user = prompts.build_user_prompt(
        title=title,
        why_hot=why_hot,
        url=url,
        discussion_url=discussion_url,
        angle_types=angle_types,
        article_excerpt=excerpt,
    )
    data = provider.complete_json(system, user)
    angles = _parse_angles(data)
    if not angles:
        raise RuntimeError("LLM returned no usable angles.")
    return DraftSet(topic_title=title, topic_url=url, why_hot=why_hot, angles=angles)


def regenerate_angle(
    *,
    title: str,
    why_hot: str,
    url: str,
    discussion_url: str,
    angle_type: AngleType,
    settings: Settings | None = None,
    provider: LLMProvider | None = None,
) -> DraftAngle:
    settings = settings or get_settings()
    provider = provider or get_provider(settings)
    system = _build_system(settings)
    base = prompts.build_user_prompt(
        title=title, why_hot=why_hot, url=url, discussion_url=discussion_url,
        angle_types=[angle_type],
        article_excerpt=fetch_article_excerpt(url) if settings.ground_with_article else None,
    )
    user = prompts.build_regenerate_user_prompt(base, angle_type)
    angles = _parse_angles(provider.complete_json(system, user))
    if not angles:
        raise RuntimeError("LLM returned no usable angle on regenerate.")
    return angles[0]


def why_hot_from_story(story: Story) -> str:
    return (
        f"{story.points} points, {story.num_comments} comments in "
        f"{story.age_hours:.0f}h (comment:point ratio {story.comment_point_ratio:.2f} "
        f"= active debate); matched: {', '.join(story.matched_keywords) or 'AI topic'}."
    )


def draft_from_story(
    story: Story,
    *,
    settings: Settings | None = None,
    provider: LLMProvider | None = None,
) -> DraftSet:
    return generate_draft_set(
        title=story.title,
        why_hot=why_hot_from_story(story),
        url=story.url,
        discussion_url=story.discussion_url,
        settings=settings,
        provider=provider,
    )
