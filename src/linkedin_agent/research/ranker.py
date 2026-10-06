"""Scoring + ranking.

    score = ( w_points      * norm(points)              # how widely upvoted
            + w_comments    * norm(num_comments)         # how widely discussed
            + w_controversy * controversy(volume-gated)  # how much arguing
            + w_topic       * topic_match(focus areas)   # relevant to my niche
            + w_source      * source_quality              # primary launch/news source
            + w_evergreen   * evergreen_discussion        # durable practitioner debate
            + w_recency     * recency_decay(age_hours)    # freshness (tiebreaker)
            ) * launch/discussion penalties

Tuned for *big, widely-discussed, relatable* topics (LinkedIn presence), not
fresh-but-obscure side projects. So popularity (points + comments) dominates,
controversy only counts when there's real comment volume behind it, recency is
a light tiebreaker, launches are one useful lane, and durable engineering /
founder discussions can compete with news when the debate has traction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

from linkedin_agent.research.models import Story

# A debate needs real volume to count — a high comment:point ratio on a
# 3-comment post isn't "what people are arguing about".
MIN_DEBATE_COMMENTS = 40

# Project-launch / self-promo prefixes a LinkedIn audience rarely relates to.
_LAUNCH_PREFIXES = ("show hn", "launch hn")
_DISCUSSION_PREFIXES = ("ask hn", "tell hn")
SHOW_HN_PENALTY = 0.6
DISCUSSION_POST_PENALTY = 0.8
RELEASE_NOTES_PENALTY = 0.65
META_DISCUSSION_PENALTY = 0.82

PRIMARY_SOURCE_DOMAINS = (
    "anthropic.com",
    "openai.com",
    "mistral.ai",
    "deepseek.com",
    "ai.google.dev",
    "blog.google",
    "googleblog.com",
    "deepmind.google",
    "microsoft.com",
    "nvidia.com",
    "meta.com",
    "ai.meta.com",
    "huggingface.co",
)

RELEASE_TITLE_RE = re.compile(
    r"\b(announc(?:e|es|ed|ing)|introduc(?:e|es|ed|ing)|launch(?:es|ed|ing)?|"
    r"releas(?:e|es|ed|ing)|ship(?:s|ped|ping)?|unveil(?:s|ed|ing)?|"
    r"new|model|version|v\d+|[a-z]+[- ]?\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)
RELEASE_PATH_RE = re.compile(r"/(news|blog|research|announcements?)/", re.IGNORECASE)
RELEASE_NOTES_RE = re.compile(r"(release[-_ ]?notes?|changelog|docs?/)", re.IGNORECASE)
META_DISCUSSION_RE = re.compile(
    r"\b(repl(?:y|ies) to comments?|comments? on my .+ post|discussion about|"
    r"thread about|response to|follow[- ]?up to)\b",
    re.IGNORECASE,
)
EVERGREEN_AUDIENCE_RE = re.compile(
    r"\b(engineers?|developers?|programmers?|founders?|entrepreneurs?|startups?|"
    r"solo founders?|indie hackers?|builders?|teams?|managers?|students?|"
    r"juniors?|seniors?)\b",
    re.IGNORECASE,
)
EVERGREEN_PRACTICE_RE = re.compile(
    r"\b(vibe[- ]?coding|vibecoding|ai[- ]?engineering|coding agents?|"
    r"agents? in production|prompt(?:ing)?|code review|debug(?:ging)?|"
    r"shipping|production|workflow|productivity|hiring|jobs?|careers?|"
    r"business|customers?|operations|sales|marketing|bootstrapp(?:ed|ing)?|"
    r"pricing|costs?|trust|evals?|evaluation|benchmarks?|technical debt|"
    r"architecture|maintenance|security|privacy|"
    # LinkedIn-native career/work themes — the human-interest topics that
    # reliably travel on LinkedIn even when they aren't AI news.
    r"layoffs?|laid off|fired|return to office|rto|remote work|"
    r"work[- ]?life|burnout|overwork|salary|salaries|compensation|"
    r"promotion|promoted|interview(?:s|ing)?|resume|recruit(?:er|ing|ment)?|"
    r"job (?:market|search|hunt)|mentor(?:ship|ing)?|leadership|management|"
    r"managers?|onboarding|self[- ]?taught|bootcamp|imposter syndrome|"
    r"upskill(?:ing)?|freelanc(?:e|ing)|consulting|solopreneur)\b",
    re.IGNORECASE,
)
EVERGREEN_FRAME_RE = re.compile(
    r"\b(why|how|should|will|what|when|stop|replace|replac(?:e|ing)|"
    r"kill|worth|hard|fails?|failure|trap|myth|problem|future|lessons?|"
    r"mistakes?|trade[- ]?offs?|versus|overrated|underrated|better|worse)\b|vs\.?",
    re.IGNORECASE,
)


@lru_cache(maxsize=256)
def _word_pattern(keyword: str) -> re.Pattern[str]:
    """Whole-word matcher for short/ambiguous tokens (\\bai\\b, not 'available')."""
    return re.compile(rf"(?<!\w){re.escape(keyword)}(?!\w)")


@dataclass(frozen=True)
class Weights:
    points: float = 0.26        # widely upvoted = widely seen
    comments: float = 0.20      # widely discussed
    controversy: float = 0.15   # actively argued (volume-gated)
    topic: float = 0.12         # in my niche
    source: float = 0.08        # primary-source launch/news signals
    evergreen: float = 0.14     # AI/engineering/career debates that go viral on LinkedIn
    recency: float = 0.05       # freshness, just a tiebreaker

    def total(self) -> float:
        return (
            self.points
            + self.comments
            + self.controversy
            + self.topic
            + self.source
            + self.evergreen
            + self.recency
        )


def recency_decay(age_hours: float, half_life_hours: float = 36.0) -> float:
    """1.0 at age 0, 0.5 at one half-life. Longer half-life than before: big
    stories build over days, so a 2-day-old hot story shouldn't be buried."""
    return 0.5 ** (age_hours / half_life_hours)


def _norm_by_max(value: float, max_value: float) -> float:
    """Proportional normalization that preserves a true zero."""
    if max_value <= 0:
        return 0.0
    return min(1.0, value / max_value)


def controversy_signal(story: Story) -> float:
    """Comment:point ratio, damped by absolute comment volume so tiny threads
    with a high ratio don't masquerade as big debates."""
    volume_factor = min(story.num_comments / MIN_DEBATE_COMMENTS, 1.0)
    return story.comment_point_ratio * volume_factor


def is_launch_post(title: str) -> bool:
    low = title.strip().lower()
    return any(low.startswith(p) for p in _LAUNCH_PREFIXES)


def is_discussion_post(title: str) -> bool:
    low = title.strip().lower()
    return any(low.startswith(p) for p in _DISCUSSION_PREFIXES)


def is_release_notes_story(story: Story) -> bool:
    haystack = f"{story.title} {story.url}"
    return bool(RELEASE_NOTES_RE.search(haystack))


def is_meta_discussion_story(story: Story) -> bool:
    return bool(META_DISCUSSION_RE.search(story.title))


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _host_matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def source_quality_signal(story: Story) -> float:
    """Prefer the actual launch/news source over meta threads and release-note crumbs."""
    host = _host(story.url)
    score = 0.0
    if _host_matches(host, PRIMARY_SOURCE_DOMAINS):
        score += 0.55
    if RELEASE_TITLE_RE.search(story.title):
        score += 0.20
    if RELEASE_PATH_RE.search(urlparse(story.url).path or ""):
        score += 0.25
    if is_release_notes_story(story):
        score -= 0.35
    if is_discussion_post(story.title) or host == "news.ycombinator.com":
        score -= 0.20
    return max(0.0, min(score, 1.0))


def evergreen_discussion_signal(story: Story) -> float:
    """Score durable AI/engineering/founder debates, not only launch news.

    This intentionally looks at the title only. It is a lightweight lane signal
    for "people like us are arguing about this" topics: vibe coding, AI agents
    in real workflows, developer careers, shipping, startup operations, etc.
    """
    title = story.title
    host = _host(story.url)
    score = 0.0
    if EVERGREEN_AUDIENCE_RE.search(title):
        score += 0.30
    if EVERGREEN_PRACTICE_RE.search(title):
        score += 0.35
    if EVERGREEN_FRAME_RE.search(title):
        score += 0.25
    if is_discussion_post(title) or host == "news.ycombinator.com":
        score += 0.10
    if is_release_notes_story(story):
        score -= 0.35
    if is_meta_discussion_story(story):
        score -= 0.15
    return max(0.0, min(score, 1.0))


def topic_match(
    title: str,
    focus_keywords: list[str],
    strict_keywords: list[str] | tuple[str, ...] = (),
) -> tuple[float, list[str]]:
    """Fraction of focus relevance, capped. Returns (score, matched_terms).

    ``focus_keywords`` match as substrings; ``strict_keywords`` match on word
    boundaries (for short/ambiguous tokens like "ai"/"ml"). score =
    min(distinct_matches, 3) / 3 — one keyword gets partial credit, three or
    more saturates. Off-topic titles return (0.0, []), which the relevance gate
    uses to drop them.
    """
    low = title.lower()
    matched = [kw for kw in focus_keywords if kw in low]
    matched += [kw for kw in strict_keywords if _word_pattern(kw).search(low)]
    # Dedupe overlapping matches (e.g. "model" inside "foundation model").
    distinct = sorted(set(matched), key=len, reverse=True)
    score = min(len(distinct), 3) / 3.0
    return score, distinct


def rank(
    stories: list[Story],
    *,
    focus_keywords: list[str],
    strict_keywords: list[str] | tuple[str, ...] = (),
    weights: Weights | None = None,
) -> list[Story]:
    """Score every story in place and return them sorted high→low."""
    weights = weights or Weights()
    if not stories:
        return []

    max_points = max((s.points for s in stories), default=0)
    max_comments = max((s.num_comments for s in stories), default=0)
    max_contro = max((controversy_signal(s) for s in stories), default=0.0)

    for s in stories:
        r_points = _norm_by_max(s.points, max_points)
        r_comments = _norm_by_max(s.num_comments, max_comments)
        r_contro = _norm_by_max(controversy_signal(s), max_contro)
        r_topic, matched = topic_match(s.title, focus_keywords, strict_keywords)
        r_source = source_quality_signal(s)
        r_evergreen = evergreen_discussion_signal(s)
        r_recency = recency_decay(s.age_hours)

        breakdown = {
            "points": weights.points * r_points,
            "comments": weights.comments * r_comments,
            "controversy": weights.controversy * r_contro,
            "topic": weights.topic * r_topic,
            "source": weights.source * r_source,
            "evergreen": weights.evergreen * r_evergreen,
            "recency": weights.recency * r_recency,
        }
        score = sum(breakdown.values())
        if is_launch_post(s.title):
            score *= SHOW_HN_PENALTY
        if is_discussion_post(s.title) and r_evergreen < 0.45:
            score *= DISCUSSION_POST_PENALTY
        if is_release_notes_story(s):
            score *= RELEASE_NOTES_PENALTY
        if is_meta_discussion_story(s):
            score *= META_DISCUSSION_PENALTY
        s.score = score
        s.score_breakdown = breakdown
        s.matched_keywords = matched

    return sorted(stories, key=lambda s: s.score, reverse=True)
