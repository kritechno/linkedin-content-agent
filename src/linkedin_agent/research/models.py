"""Data models for the research stage."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Story:
    """A single ranked candidate, normalized across sources."""

    object_id: str
    title: str
    url: str
    points: int
    num_comments: int
    author: str
    created_at_i: int  # unix seconds
    source: str = "hackernews"
    matched_queries: set[str] = field(default_factory=set)

    # Filled in by the ranker.
    score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    matched_keywords: list[str] = field(default_factory=list)

    @property
    def age_hours(self) -> float:
        return max(0.0, (time.time() - self.created_at_i) / 3600.0)

    @property
    def comment_point_ratio(self) -> float:
        """Debate signal: lots of comments relative to points = people arguing."""
        return self.num_comments / (self.points + 5)

    @property
    def discussion_url(self) -> str:
        if self.source == "hackernews":
            return f"https://news.ycombinator.com/item?id={self.object_id}"
        return self.url
