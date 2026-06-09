"""Hacker News source via the free Algolia API.

No auth, no key. Two complementary pulls, merged + deduped by objectID:

1. Keyword search on the popularity-ranked ``search`` endpoint (not
   ``search_by_date``) — so we get widely-discussed stories, not just the
   newest tiny Show HN launches.
2. The current ``front_page`` — literally "what HN is discussing right now",
   the most relatable, widely-seen stories. The topic gate downstream keeps
   only the AI ones.
"""

from __future__ import annotations

import time

import httpx

from linkedin_agent.research.models import Story

# Popularity/relevance-ranked (favours stories with traction), not by date.
SEARCH_URL = "https://hn.algolia.com/api/v1/search"


def _parse_hit(hit: dict, query: str) -> Story | None:
    object_id = hit.get("objectID")
    title = hit.get("title")
    if not object_id or not title:
        return None
    url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
    return Story(
        object_id=str(object_id),
        title=title.strip(),
        url=url,
        points=int(hit.get("points") or 0),
        num_comments=int(hit.get("num_comments") or 0),
        author=hit.get("author") or "",
        created_at_i=int(hit.get("created_at_i") or 0),
        source="hackernews",
        matched_queries={query},
    )


def _merge(by_id: dict[str, Story], story: Story) -> None:
    existing = by_id.get(story.object_id)
    if existing is None:
        by_id[story.object_id] = story
    else:
        existing.matched_queries |= story.matched_queries


def fetch_stories(
    queries: list[str],
    *,
    max_age_hours: float = 96,
    hits_per_page: int = 40,
    min_points_server: int = 20,
    include_front_page: bool = True,
    timeout: float = 20.0,
) -> list[Story]:
    """Fetch + merge HN stories (keyword search + front page), deduped by id.

    ``min_points_server`` is a lenient server-side floor just to cut obvious
    noise; the real "is this big enough" gate lives in the engine.
    """
    cutoff = int(time.time() - max_age_hours * 3600)
    by_id: dict[str, Story] = {}

    with httpx.Client(timeout=timeout, headers={"User-Agent": "linkedin-agent/0.1"}) as client:
        for query in queries:
            filters = [f"created_at_i>{cutoff}"]
            if min_points_server > 0:
                filters.append(f"points>={min_points_server}")
            resp = client.get(SEARCH_URL, params={
                "tags": "story",
                "query": query,
                "hitsPerPage": hits_per_page,
                "numericFilters": ",".join(filters),
            })
            resp.raise_for_status()
            for hit in resp.json().get("hits", []):
                story = _parse_hit(hit, query)
                if story is not None:
                    _merge(by_id, story)

        if include_front_page:
            # Current front page — high-traffic, widely-seen stories.
            resp = client.get(SEARCH_URL, params={
                "tags": "front_page",
                "hitsPerPage": 50,
            })
            resp.raise_for_status()
            for hit in resp.json().get("hits", []):
                story = _parse_hit(hit, "front_page")
                if story is not None:
                    _merge(by_id, story)

    return list(by_id.values())
