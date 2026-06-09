"""Shared fixtures."""

from __future__ import annotations

import time

import pytest

from linkedin_agent.config import Settings
from linkedin_agent.research.models import Story


@pytest.fixture
def settings(tmp_path):
    """Settings pointed at a throwaway DB and the offline mock provider."""
    return Settings(db_path=str(tmp_path / "test.db"), llm_provider="mock", image_dir=str(tmp_path / "img"))


@pytest.fixture
def story():
    return Story(
        object_id="42",
        title="New LLM agent framework ships",
        url="https://example.com/llm-agent",
        points=120,
        num_comments=80,
        author="someone",
        created_at_i=int(time.time() - 3600),
        matched_keywords=["llm", "agent"],
    )
