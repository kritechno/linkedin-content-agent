"""Draft writer + models — offline (MockProvider, no network)."""

from __future__ import annotations

from linkedin_agent.draft.llm import MockProvider, get_provider
from linkedin_agent.draft.models import AngleType, DraftAngle, DraftSet, FactFlag
from linkedin_agent.draft import prompts, writer


def test_mock_provider_returns_three_distinct_angles():
    sys = "system"
    user = "TOPIC: X\n- Contrarian — ...\n- Practical — ...\n- What everyone's missing — ..."
    data = MockProvider().complete_json(sys, user)
    types = [a["angle_type"] for a in data["angles"]]
    assert types == ["contrarian", "practical", "missed"]


def test_strip_trailing_hashtags():
    assert writer._strip_trailing_hashtags("Great point. #AI #ML") == "Great point."
    assert writer._strip_trailing_hashtags("no tags here") == "no tags here"


def test_full_text_does_not_duplicate_hashtags():
    angle = DraftAngle(
        angle_type=AngleType.PRACTICAL,
        hook="Hook line.",
        body="Hook line.\n\nThe real body.",
        hashtags=["AI", "Engineering"],
    )
    text = angle.full_text
    assert text.count("#AI") == 1
    assert text.endswith("#AI #Engineering")


def test_draftset_json_round_trip():
    ds = DraftSet(
        topic_title="T", topic_url="u", why_hot="hot",
        angles=[DraftAngle(
            angle_type=AngleType.CONTRARIAN, hook="h", body="b",
            hashtags=["A"], fact_flags=[FactFlag(claim="stat", reason="why")],
            suggested_image="card",
        )],
    )
    restored = DraftSet.from_json(ds.to_json())
    assert restored.angles[0].angle_type is AngleType.CONTRARIAN
    assert restored.angles[0].fact_flags[0].claim == "stat"
    assert restored.topic_title == "T"


def test_generate_draft_set_with_mock(settings, story):
    ds = writer.generate_draft_set(
        title=story.title, why_hot="hot", url=story.url,
        discussion_url=story.discussion_url, settings=settings,
        provider=MockProvider(), ground=False,
    )
    assert len(ds.angles) == 3
    assert ds.topic_title == story.title
    assert all(a.full_text for a in ds.angles)


def test_parse_angles_tolerates_bad_input():
    angles = writer._parse_angles({"angles": [
        {"angle_type": "nonsense", "hook": "h"},  # bad type, missing body
        {"hook": "h2", "body": "b2", "hashtags": ["#x", "y"]},
    ]})
    assert angles[0].angle_type is AngleType.PRACTICAL  # fallback
    assert angles[1].hashtags == ["x", "y"]  # leading # stripped


def test_get_provider_falls_back_to_mock_without_key(settings):
    # settings has llm_provider="mock" → not has_llm → mock
    assert get_provider(settings).name == "mock"


def test_prompts_allow_evergreen_practitioner_debates():
    system = prompts.build_system_prompt("persona", [])
    user = prompts.build_user_prompt(
        title="Ask HN: Are AI coding agents making junior engineers worse?",
        why_hot="widely discussed",
        url="https://news.ycombinator.com/item?id=2",
        discussion_url="https://news.ycombinator.com/item?id=2",
        angle_types=[AngleType.PRACTICAL],
    )

    assert "Not every post has to be breaking news" in system
    assert "recurring practitioner debate" in user
