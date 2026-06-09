"""Orchestrates the research stage: fetch → dedupe near-dupes → rank → top N."""

from __future__ import annotations

import re

from linkedin_agent.config import Settings, get_settings
from linkedin_agent.research import hackernews
from linkedin_agent.research.models import Story
from linkedin_agent.research.ranker import Weights, rank, topic_match

_WORD_RE = re.compile(r"[a-z0-9]+")


def _title_tokens(title: str) -> set[str]:
    return set(_WORD_RE.findall(title.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedupe_near_duplicates(ranked: list[Story], threshold: float = 0.6) -> list[Story]:
    """Drop near-identical titles, keeping the higher-scored one.

    Cheap stand-in for the LLM dedupe pass in the plan — token Jaccard on
    titles. Input must already be sorted high→low so we keep the best.
    """
    kept: list[Story] = []
    kept_tokens: list[set[str]] = []
    for story in ranked:
        tokens = _title_tokens(story.title)
        if any(_jaccard(tokens, prev) >= threshold for prev in kept_tokens):
            continue
        kept.append(story)
        kept_tokens.append(tokens)
    return kept


def filter_on_topic(
    stories: list[Story],
    focus_keywords: list[str],
    strict_keywords: list[str] | tuple[str, ...] = (),
) -> list[Story]:
    """Relevance gate (plan §2): drop stories whose title matches no focus
    keyword, so a high-controversy *off-topic* story can't float to the top."""
    keep = []
    for s in stories:
        score, _ = topic_match(s.title, focus_keywords, strict_keywords)
        if score > 0:
            keep.append(s)
    return keep


def filter_popular(stories: list[Story], min_points: int, min_comments: int) -> list[Story]:
    """Traction gate: keep stories that are either widely upvoted OR widely
    discussed. Filters out the tiny launches nobody's heard of."""
    return [s for s in stories if s.points >= min_points or s.num_comments >= min_comments]


def _gate_popular_with_fallback(
    stories: list[Story], min_points: int, min_comments: int, target: int
) -> list[Story]:
    """Prefer the strictest traction floor that still yields ``target`` stories;
    relax (then drop) the floor rather than returning too few."""
    gated = stories
    for mp, mc in ((min_points, min_comments), (min_points // 2, min_comments // 2), (0, 0)):
        gated = filter_popular(stories, mp, mc)
        if len(gated) >= target:
            break
    return gated


def get_top_topics(
    n: int = 5,
    *,
    settings: Settings | None = None,
    weights: Weights | None = None,
    require_topic: bool = True,
    require_popular: bool = True,
) -> list[Story]:
    settings = settings or get_settings()
    stories = hackernews.fetch_stories(
        settings.research_queries,
        max_age_hours=settings.research_max_age_hours,
        include_front_page=settings.include_front_page,
    )
    if require_topic:
        # Gate before ranking so normalization spreads over the relevant set.
        stories = filter_on_topic(
            stories, settings.focus_keywords, settings.focus_keywords_strict
        )
    if require_popular:
        stories = _gate_popular_with_fallback(
            stories, settings.min_points, settings.min_comments, n
        )
    ranked = rank(
        stories,
        focus_keywords=settings.focus_keywords,
        strict_keywords=settings.focus_keywords_strict,
        weights=weights,
    )
    deduped = dedupe_near_duplicates(ranked)
    return deduped[:n]
