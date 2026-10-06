"""Deterministic tests for the ranker — no network."""

from __future__ import annotations

import time

from linkedin_agent.research.models import Story
from linkedin_agent.research.ranker import (
    Weights,
    controversy_signal,
    evergreen_discussion_signal,
    is_discussion_post,
    is_launch_post,
    is_release_notes_story,
    rank,
    recency_decay,
    source_quality_signal,
    topic_match,
)
from linkedin_agent.research.engine import (
    dedupe_near_duplicates,
    filter_on_topic,
    filter_popular,
    _gate_popular_with_fallback,
)


def make_story(**kw) -> Story:
    now = int(time.time())
    defaults = dict(
        object_id="1",
        title="Some AI story",
        url="https://example.com",
        points=100,
        num_comments=50,
        author="someone",
        created_at_i=now - 3600,
    )
    defaults.update(kw)
    return Story(**defaults)


def test_recency_decay_half_life():
    assert recency_decay(0) == 1.0
    assert recency_decay(18, half_life_hours=18) == 0.5
    assert recency_decay(36, half_life_hours=18) == 0.25


def test_topic_match_on_and_off_topic():
    on_score, matched = topic_match("New LLM agent beats GPT benchmark", [
        "llm", "agent", "gpt", "benchmark", "crypto",
    ])
    assert on_score == 1.0  # saturates at 3+ matches
    assert "llm" in matched

    off_score, matched = topic_match("Local bakery wins award", ["llm", "agent", "gpt"])
    assert off_score == 0.0
    assert matched == []


def test_controversy_ranks_above_raw_points():
    now = int(time.time())
    # Same recency + topic. The high comment:point ratio should win given the
    # default weights (controversy 0.25 > points 0.15).
    popular = make_story(
        object_id="pop", title="LLM release", points=500, num_comments=50,
        created_at_i=now - 3600,
    )
    debated = make_story(
        object_id="deb", title="LLM controversy", points=120, num_comments=400,
        created_at_i=now - 3600,
    )
    ranked = rank([popular, debated], focus_keywords=["llm"])
    assert ranked[0].object_id == "deb"


def test_scores_are_bounded_and_sorted():
    stories = [
        make_story(object_id=str(i), title=f"AI agent story {i}",
                   points=10 * i, num_comments=5 * i)
        for i in range(1, 6)
    ]
    ranked = rank(stories, focus_keywords=["ai", "agent"], weights=Weights())
    scores = [s.score for s in ranked]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_rank_handles_empty():
    assert rank([], focus_keywords=["llm"]) == []


def test_rank_handles_zero_points_no_div_by_zero():
    stories = [make_story(object_id="z", points=0, num_comments=0)]
    ranked = rank(stories, focus_keywords=["ai"])
    assert ranked[0].score >= 0.0


def test_strict_keywords_word_boundary():
    # "ai" as a whole word matches…
    score, matched = topic_match("Why won't you be replaced by AI?", [], ["ai", "ml"])
    assert score > 0 and "ai" in matched
    # …but must NOT match inside another word.
    score, matched = topic_match("New tools are available today", [], ["ai", "ml"])
    assert score == 0.0 and matched == []


def test_filter_on_topic_drops_offtopic():
    cells = make_story(object_id="cells", title="Why are cells small?")
    llm = make_story(object_id="llm", title="New LLM agent benchmark")
    kept = filter_on_topic([cells, llm], ["agent", "benchmark"], ["llm", "ai"])
    ids = [s.object_id for s in kept]
    assert ids == ["llm"]  # biology story gated out


def test_controversy_is_volume_gated():
    # Same ratio, but the tiny-volume thread is damped toward zero.
    big = make_story(object_id="big", points=100, num_comments=200)     # ratio ~1.9
    tiny = make_story(object_id="tiny", points=2, num_comments=4)        # ratio ~0.57 but 4 comments
    assert controversy_signal(big) > controversy_signal(tiny)
    # A 4-comment thread is damped by volume_factor 4/40 = 0.1
    assert controversy_signal(tiny) < 0.1


def test_filter_popular_drops_obscure():
    big = make_story(object_id="big", points=300, num_comments=120)
    debated = make_story(object_id="deb", points=20, num_comments=150)   # low pts, high comments
    tiny = make_story(object_id="tiny", points=8, num_comments=3)
    kept = filter_popular([big, debated, tiny], min_points=80, min_comments=60)
    ids = {s.object_id for s in kept}
    assert ids == {"big", "deb"}  # tiny launch dropped; debate kept on comments


def test_gate_popular_falls_back_when_too_few():
    small = [make_story(object_id=str(i), points=10, num_comments=5) for i in range(4)]
    # Nothing passes the strict floor, but we still need 3 → fallback returns all.
    out = _gate_popular_with_fallback(small, min_points=80, min_comments=60, target=3)
    assert len(out) == 4


def test_show_hn_is_demoted():
    launch = make_story(object_id="show", title="Show HN: my tiny AI tool",
                        points=120, num_comments=40)
    news = make_story(object_id="news", title="OpenAI releases a new AI model",
                      points=120, num_comments=40)
    ranked = rank([launch, news], focus_keywords=["ai"], strict_keywords=["ai"])
    assert ranked[0].object_id == "news"  # launch penalty pushes Show HN below
    assert is_launch_post("Show HN: foo") and not is_launch_post("OpenAI ships X")


def test_release_announcement_beats_release_notes_artifact():
    official = make_story(
        object_id="official",
        title="Anthropic releases Claude Fable 5",
        url="https://www.anthropic.com/news/claude-fable-5",
        points=180,
        num_comments=50,
    )
    notes = make_story(
        object_id="notes",
        title="Claude Fable 5 release notes discussion",
        url="https://docs.anthropic.com/en/release-notes/claude-fable-5",
        points=190,
        num_comments=55,
    )
    ranked = rank(
        [notes, official],
        focus_keywords=["claude", "anthropic"],
        strict_keywords=[],
    )

    assert ranked[0].object_id == "official"
    assert source_quality_signal(official) > source_quality_signal(notes)
    assert is_release_notes_story(notes)


def test_discussion_thread_is_demoted_below_primary_release():
    ask = make_story(
        object_id="ask",
        title="Ask HN: What do you think about Claude Fable 5?",
        url="https://news.ycombinator.com/item?id=1",
        points=230,
        num_comments=90,
    )
    release = make_story(
        object_id="release",
        title="Claude Fable 5",
        url="https://www.anthropic.com/news/claude-fable-5",
        points=210,
        num_comments=70,
    )
    ranked = rank([ask, release], focus_keywords=["claude"], strict_keywords=[])

    assert ranked[0].object_id == "release"
    assert is_discussion_post(ask.title)


def test_evergreen_practitioner_discussion_can_beat_routine_launch():
    debate = make_story(
        object_id="debate",
        title="Ask HN: Are AI coding agents making junior engineers worse?",
        url="https://news.ycombinator.com/item?id=2",
        points=190,
        num_comments=160,
    )
    launch = make_story(
        object_id="launch",
        title="OpenAI releases a new AI model",
        url="https://openai.com/news/new-ai-model",
        points=200,
        num_comments=70,
    )
    ranked = rank(
        [launch, debate],
        focus_keywords=["coding agent", "engineer", "model"],
        strict_keywords=["ai"],
    )

    assert ranked[0].object_id == "debate"
    assert evergreen_discussion_signal(debate) > evergreen_discussion_signal(launch)
    assert debate.score_breakdown["evergreen"] > 0


def test_weights_sum_to_one_keeps_scores_bounded():
    # Per-signal scores are 0..1, so weights summing to 1.0 keeps the final
    # score in [0, 1] (asserted elsewhere). Guard against a rebalance that
    # accidentally pushes the total over 1.0.
    assert abs(Weights().total() - 1.0) < 1e-9


def test_linkedin_career_theme_scores_evergreen():
    # A career/work story with no AI keyword should still light up the
    # evergreen lane — these are the topics that travel on LinkedIn.
    story = make_story(
        object_id="rto",
        title="Why returning to the office is making senior engineers quit",
        url="https://example.com/rto-engineers-quit",
    )
    assert evergreen_discussion_signal(story) > 0


def test_career_debate_competes_with_routine_ai_launch():
    layoffs = make_story(
        object_id="layoffs",
        title="Ask HN: How are engineers coping with the latest tech layoffs?",
        url="https://news.ycombinator.com/item?id=9",
        points=180,
        num_comments=170,
    )
    launch = make_story(
        object_id="launch",
        title="OpenAI releases a new AI model",
        url="https://openai.com/news/new-ai-model",
        points=190,
        num_comments=70,
    )
    ranked = rank(
        [launch, layoffs],
        focus_keywords=["engineer", "layoff", "model"],
        strict_keywords=["ai"],
    )
    assert ranked[0].object_id == "layoffs"
    assert layoffs.score_breakdown["evergreen"] > 0


def test_meta_followup_is_demoted_below_original_debate():
    original = make_story(
        object_id="original",
        title="LLMs are eroding my software engineering career and I don't know what to do",
        url="https://example.com/llms-eroding-software-engineering-career",
        points=200,
        num_comments=180,
    )
    followup = make_story(
        object_id="followup",
        title='Replies to comments on my "LLMs are eroding my career" post',
        url="https://example.com/replies-to-comments-on-my-llms-career-post",
        points=220,
        num_comments=240,
    )
    ranked = rank(
        [followup, original],
        focus_keywords=["software engineer", "career"],
        strict_keywords=["llms"],
    )

    assert ranked[0].object_id == "original"


def test_big_story_beats_fresh_tiny_one():
    import time
    now = int(time.time())
    big_old = make_story(object_id="big", title="New AI model breaks records",
                         points=900, num_comments=600, created_at_i=now - 40 * 3600)
    fresh_tiny = make_story(object_id="tiny", title="New AI side project",
                            points=15, num_comments=3, created_at_i=now - 1800)
    ranked = rank([big_old, fresh_tiny], focus_keywords=["ai"], strict_keywords=["ai"])
    assert ranked[0].object_id == "big"  # popularity beats freshness


def test_dedupe_near_duplicates_keeps_higher_scored():
    a = make_story(object_id="a", title="OpenAI releases GPT-5 model today")
    a.score = 0.9
    b = make_story(object_id="b", title="OpenAI releases GPT-5 model")  # near-dup
    b.score = 0.5
    c = make_story(object_id="c", title="Anthropic ships new Claude feature")
    c.score = 0.7
    kept = dedupe_near_duplicates([a, c, b])  # pre-sorted high→low
    ids = [s.object_id for s in kept]
    assert "a" in ids and "c" in ids
    assert "b" not in ids
