"""Pipeline orchestration + image generation + LinkedIn body building (offline)."""

from __future__ import annotations

from pathlib import Path

from linkedin_agent import pipeline, store
from linkedin_agent.enrich import images
from linkedin_agent.linkedin import client
from linkedin_agent.review import bot


def test_text_card_creates_valid_png(tmp_path):
    out = tmp_path / "card.png"
    path = images.text_card("A bold pull quote about shipping software.", out)
    assert Path(path).exists()
    from PIL import Image
    im = Image.open(path)
    assert im.size == (images.WIDTH, images.HEIGHT)


def test_run_cycle_with_mock(monkeypatch, settings, story):
    # Avoid network: fake the research feed and the article fetch.
    monkeypatch.setattr(pipeline, "get_top_topics", lambda **kw: [story])
    monkeypatch.setattr(
        "linkedin_agent.draft.writer.fetch_article_excerpt", lambda *a, **k: None
    )
    result = pipeline.run_cycle(settings=settings, force_mock=True, topics_limit=1, enrich=True)
    assert len(result.draft_ids) == 1
    rec = store.get_draft(settings, result.draft_ids[0])
    assert rec.image_path is None
    assert pipeline.image_card_text(rec) == rec.current_angle.hook
    # second run skips the now-seen topic
    result2 = pipeline.run_cycle(settings=settings, force_mock=True, topics_limit=1)
    assert result2.draft_ids == []
    assert result2.skipped_seen == 1


def test_render_review_text(settings, story, monkeypatch):
    monkeypatch.setattr(pipeline, "get_top_topics", lambda **kw: [story])
    monkeypatch.setattr(
        "linkedin_agent.draft.writer.fetch_article_excerpt", lambda *a, **k: None
    )
    result = pipeline.run_cycle(settings=settings, force_mock=True, topics_limit=1)
    rec = store.get_draft(settings, result.draft_ids[0])
    text = pipeline.render_review_text(rec)
    assert story.title in text
    assert "angle:" in text
    assert "Image card text proposal" in text
    assert "Create image" in text


def test_cycle_angle_wraps(settings, story, monkeypatch):
    monkeypatch.setattr(pipeline, "get_top_topics", lambda **kw: [story])
    monkeypatch.setattr(
        "linkedin_agent.draft.writer.fetch_article_excerpt", lambda *a, **k: None
    )
    result = pipeline.run_cycle(settings=settings, force_mock=True, topics_limit=1)
    rec = store.get_draft(settings, result.draft_ids[0])
    n = len(rec.draft_set.angles)
    pipeline.cycle_angle(settings, rec)
    rec2 = store.get_draft(settings, rec.id)
    assert rec2.current_idx == 1 % n


def test_image_generation_waits_for_effective_text(settings, story, monkeypatch):
    monkeypatch.setattr(pipeline, "get_top_topics", lambda **kw: [story])
    monkeypatch.setattr(
        "linkedin_agent.draft.writer.fetch_article_excerpt", lambda *a, **k: None
    )
    result = pipeline.run_cycle(settings=settings, force_mock=True, topics_limit=1)
    rec = store.get_draft(settings, result.draft_ids[0])
    store.set_override_text(settings, rec.id, "My approved image headline.\n\nBody copy.")
    rec = store.get_draft(settings, rec.id)

    seen = {}

    def fake_card(card_text, out_dir, draft_id):
        seen["card_text"] = card_text
        out = Path(out_dir) / f"draft_{draft_id}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"fake")
        return str(out)

    monkeypatch.setattr(images, "make_card_for_draft", fake_card)
    path = pipeline.regenerate_image(settings, rec)

    assert Path(path).exists()
    assert seen["card_text"] == "My approved image headline."


def test_linkedin_post_bodies():
    text_body = client.build_text_post_body("urn:li:person:abc", "hello")
    assert text_body["author"] == "urn:li:person:abc"
    assert text_body["commentary"] == "hello"
    assert text_body["lifecycleState"] == "PUBLISHED"

    img_body = client.build_image_post_body("urn:li:person:abc", "hi", "urn:li:image:1", "alt")
    assert img_body["content"]["media"]["id"] == "urn:li:image:1"
    assert img_body["content"]["media"]["altText"] == "alt"


def test_bot_keyboard_callback_data():
    kb = bot.keyboard(7)
    datas = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "approve:7" in datas
    assert "image:7" in datas
    assert "skip:7" in datas
    assert "🖼 Create image" in labels
    assert "🖼 Regenerate image" in [
        btn.text for row in bot.keyboard(7, has_image=True).inline_keyboard for btn in row
    ]
    # parsing round-trip
    action, _, raw_id = "approve:7".partition(":")
    assert action == "approve" and int(raw_id) == 7
