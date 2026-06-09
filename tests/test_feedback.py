"""Voice-learning loop: capture finals/edits and feed them into the prompt."""

from __future__ import annotations

from linkedin_agent import feedback, store
from linkedin_agent.draft import prompts, writer
from linkedin_agent.draft.llm import MockProvider


def _queue_draft(settings, story):
    ds = writer.generate_draft_set(
        title=story.title, why_hot="hot", url=story.url,
        discussion_url=story.discussion_url, settings=settings,
        provider=MockProvider(), ground=False,
    )
    draft_id = store.create_draft(settings, story, ds)
    return store.get_draft(settings, draft_id)


def test_record_finalization_approved(settings, story):
    record = _queue_draft(settings, story)
    feedback.record_finalization(settings, record)
    st = feedback.stats(settings)
    assert st["total"] == 1
    assert st["edited"] == 0  # approved as-is
    finals = feedback.recent_finals(settings)
    assert finals and finals[0] == record.effective_text


def test_record_finalization_edited_captures_pair(settings, story):
    record = _queue_draft(settings, story)
    store.set_override_text(settings, record.id, "My own punchier version. No fluff.")
    record = store.get_draft(settings, record.id)
    feedback.record_finalization(settings, record)

    st = feedback.stats(settings)
    assert st["edited"] == 1
    pairs = feedback.recent_edits(settings)
    assert len(pairs) == 1
    assert pairs[0].final_text == "My own punchier version. No fluff."
    assert pairs[0].ai_draft  # the model's original is retained for the diff


def test_record_edit_captures_without_posting(settings, story):
    record = _queue_draft(settings, story)
    store.set_override_text(settings, record.id, "Edited but never posted.")
    record = store.get_draft(settings, record.id)
    feedback.record_edit(settings, record)
    st = feedback.stats(settings)
    assert st["total"] == 1 and st["edited"] == 1
    assert feedback.recent_edits(settings)[0].final_text == "Edited but never posted."


def test_edit_then_publish_not_double_counted(settings, story):
    record = _queue_draft(settings, story)
    store.set_override_text(settings, record.id, "My version.")
    record = store.get_draft(settings, record.id)
    feedback.record_edit(settings, record)        # captured at edit time
    feedback.record_finalization(settings, record)  # then published
    assert feedback.stats(settings)["total"] == 1   # one row per draft, not two


def test_record_edit_noop_when_unchanged(settings, story):
    record = _queue_draft(settings, story)  # no override
    feedback.record_edit(settings, record)
    assert feedback.stats(settings)["total"] == 0


def test_recent_finals_dedupes(settings, story):
    for _ in range(3):
        record = _queue_draft(settings, story)
        store.set_override_text(settings, record.id, "identical final text")
        record = store.get_draft(settings, record.id)
        feedback.record_finalization(settings, record)
    finals = feedback.recent_finals(settings)
    assert finals.count("identical final text") == 1


def test_learned_signal_enters_system_prompt(settings, story):
    record = _queue_draft(settings, story)
    store.set_override_text(settings, record.id, "A very distinctive Amir sentence about yaks.")
    record = store.get_draft(settings, record.id)
    feedback.record_finalization(settings, record)

    system = writer._build_system(settings)
    assert "PUBLISHED posts" in system
    assert "yaks" in system
    assert "How the author edits AI drafts" in system


def test_prompt_without_learned_signal_omits_sections():
    system = prompts.build_system_prompt("persona", ["a sample"])
    assert "PUBLISHED posts" not in system
    assert "How the author edits" not in system
