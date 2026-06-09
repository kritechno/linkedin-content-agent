"""Config: provider selection + required-credential guards."""

from __future__ import annotations

import pytest

from linkedin_agent.config import Settings
from linkedin_agent.draft.llm import get_provider


def test_has_llm_openai():
    s = Settings(llm_provider="openai", openai_api_key="sk-test")
    assert s.has_llm is True
    assert s.llm_api_key == "sk-test"


def test_has_llm_anthropic():
    s = Settings(llm_provider="anthropic", anthropic_api_key="ak-test")
    assert s.has_llm is True


def test_has_llm_false_without_key():
    s = Settings(llm_provider="openai", openai_api_key="")
    assert s.has_llm is False
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        s.require_llm()


def test_get_provider_selects_by_provider():
    # No real network/SDK init for mock; key present selects openai class lazily.
    s_mock = Settings(llm_provider="openai", openai_api_key="")
    assert get_provider(s_mock).name == "mock"


def test_require_linkedin_and_telegram():
    s = Settings(linkedin_client_id="", linkedin_client_secret="")
    with pytest.raises(RuntimeError, match="LinkedIn"):
        s.require_linkedin()
    s2 = Settings(telegram_bot_token="", telegram_chat_id="")
    with pytest.raises(RuntimeError, match="Telegram"):
        s2.require_telegram()


def test_post_days_default():
    s = Settings()
    assert s.post_days == ["mon", "wed", "fri"]
