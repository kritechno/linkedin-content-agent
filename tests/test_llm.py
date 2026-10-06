"""LLM provider config: model defaults + GPT-5-class parameter selection."""

from __future__ import annotations

from linkedin_agent.draft.llm import (
    OpenAIProvider,
    _is_next_gen,
    _supports_reasoning_effort,
)


def test_default_openai_model_is_gpt5_flagship():
    assert OpenAIProvider.DEFAULT_MODEL.startswith("gpt-5")


def test_next_gen_models_use_completion_tokens():
    # GPT-5-class + o-series reject the legacy max_tokens param.
    for model in ("gpt-5.5", "gpt-5.4-mini", "gpt-5-chat-latest", "o3", "o4-mini", "chat-latest"):
        assert _is_next_gen(model), model
    # Older chat models still take max_tokens.
    for model in ("gpt-4o", "gpt-4.1", "gpt-3.5-turbo"):
        assert not _is_next_gen(model), model


def test_reasoning_effort_only_for_reasoning_models():
    assert _supports_reasoning_effort("gpt-5.5")
    assert _supports_reasoning_effort("gpt-5.4-mini")
    # Instant "chat" variants are non-reasoning — don't send reasoning_effort.
    assert not _supports_reasoning_effort("gpt-5-chat-latest")
    assert not _supports_reasoning_effort("chat-latest")
    # Legacy models don't take it either.
    assert not _supports_reasoning_effort("gpt-4o")
