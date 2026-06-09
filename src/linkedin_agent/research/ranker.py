"""Scoring + ranking.

    score = ( w_points      * norm(points)              # how widely upvoted
            + w_comments    * norm(num_comments)         # how widely discussed
            + w_controversy * controversy(volume-gated)  # how much arguing
            + w_topic       * topic_match(focus areas)   # relevant to my niche
            + w_recency     * recency_decay(age_hours)    # freshness (tiebreaker)
            ) * show_hn_penalty

Tuned for *big, widely-discussed, relatable* topics (LinkedIn presence), not
fresh-but-obscure side projects. So popularity (points + comments) dominates,
controversy only counts when there's real comment volume behind it, recency is
a light tiebreaker, and "Show HN / Launch HN" project launches are demoted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from linkedin_agent.research.models import Story

# A debate needs real volume to count — a high comment:point ratio on a
# 3-comment post isn't "what people are arguing about".
MIN_DEBATE_COMMENTS = 40

# Project-launch / self-promo prefixes a LinkedIn audience rarely relates to.
_LAUNCH_PREFIXES = ("show hn", "launch hn")
SHOW_HN_PENALTY = 0.6


@lru_cache(maxsize=256)
def _word_pattern(keyword: str) -> re.Pattern[str]:
    """Whole-word matcher for short/ambiguous tokens (\\bai\\b, not 'available')."""
    return re.compile(rf"(?<!\w){re.escape(keyword)}(?!\w)")


@dataclass(frozen=True)
class Weights:
    points: float = 0.30        # widely upvoted = widely seen
    comments: float = 0.25      # widely discussed
    controversy: float = 0.20   # actively argued (volume-gated)
    topic: float = 0.15         # in my niche
    recency: float = 0.10       # freshness, just a tiebreaker

    def total(self) -> float:
        return self.points + self.comments + self.controversy + self.topic + self.recency


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
        r_recency = recency_decay(s.age_hours)

        breakdown = {
            "points": weights.points * r_points,
            "comments": weights.comments * r_comments,
            "controversy": weights.controversy * r_contro,
            "topic": weights.topic * r_topic,
            "recency": weights.recency * r_recency,
        }
        score = sum(breakdown.values())
        if is_launch_post(s.title):
            score *= SHOW_HN_PENALTY
        s.score = score
        s.score_breakdown = breakdown
        s.matched_keywords = matched

    return sorted(stories, key=lambda s: s.score, reverse=True)
