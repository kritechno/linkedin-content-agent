"""LLM provider abstraction.

`AnthropicProvider` is the production path (Claude). `MockProvider` returns
deterministic structured drafts so the whole pipeline runs offline / in tests
without an API key. `get_provider()` picks based on config.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from linkedin_agent.config import Settings


class LLMProvider(Protocol):
    name: str

    def complete_json(self, system: str, user: str) -> dict:
        """Return a parsed JSON object from the model."""
        ...


def _extract_json(text: str) -> dict:
    """Best-effort: parse JSON even if the model wrapped it in prose/fences."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fall back to the outermost {...} span.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


class AnthropicProvider:
    name = "anthropic"
    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, settings: Settings):
        from anthropic import Anthropic

        self._client = Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.llm_model or self.DEFAULT_MODEL

    def complete_json(self, system: str, user: str) -> dict:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in resp.content if block.type == "text")
        return _extract_json(text)


class OpenAIProvider:
    name = "openai"
    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, settings: Settings):
        from openai import OpenAI

        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = settings.llm_model or self.DEFAULT_MODEL

    def complete_json(self, system: str, user: str) -> dict:
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=2000,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return _extract_json(resp.choices[0].message.content or "")


class MockProvider:
    """Deterministic stand-in. Echoes the topic so output is recognizably tied
    to the input, and exercises every field (hooks, hashtags, fact_flags)."""

    name = "mock"

    def __init__(self, settings: Settings | None = None):
        self._settings = settings

    def complete_json(self, system: str, user: str) -> dict:
        topic = "this topic"
        for line in user.splitlines():
            if line.startswith("TOPIC:"):
                topic = line.split("TOPIC:", 1)[1].strip()
                break
        low = user.lower()
        wants = []
        if "contrarian" in low:
            wants.append("contrarian")
        if "practical" in low:
            wants.append("practical")
        if "missing" in low or "missed" in low:  # brief says "what everyone's missing"
            wants.append("missed")
        wants = wants or ["practical"]

        def angle(kind: str) -> dict:
            return {
                "contrarian": {
                    "angle_type": "contrarian",
                    "hook": f"Everyone's hyping \"{topic}\" — I'm not sold.",
                    "body": (
                        f"Everyone's hyping \"{topic}\" — I'm not sold.\n\n"
                        "Running a small business taught me to distrust benchmark "
                        "victory laps. The demo always works; the Tuesday-afternoon "
                        "edge case is what bites. Show me it surviving real load, "
                        "then I'll celebrate."
                    ),
                    "hashtags": ["AI", "MachineLearning", "BuildInPublic"],
                    "fact_flags": [{"claim": "any benchmark numbers cited",
                                    "reason": "mock provider can't verify live figures"}],
                    "suggested_image": "text card with the hook as a pull-quote",
                },
                "practical": {
                    "angle_type": "practical",
                    "hook": f"How I'd actually use \"{topic}\" this week:",
                    "body": (
                        f"How I'd actually use \"{topic}\" this week:\n\n"
                        "I'd wire it into the one workflow that already wastes my "
                        "time — routing customer messages for my tour business — and "
                        "measure whether it saves an hour, not whether it tops a "
                        "leaderboard. Tools earn their keep on real jobs."
                    ),
                    "hashtags": ["AIEngineering", "Automation", "SmallBusiness"],
                    "fact_flags": [],
                    "suggested_image": None,
                },
                "missed": {
                    "angle_type": "missed",
                    "hook": f"The part of \"{topic}\" nobody's talking about:",
                    "body": (
                        f"The part of \"{topic}\" nobody's talking about:\n\n"
                        "The second-order effect. When the tool gets cheap, the "
                        "bottleneck moves — usually to the boring glue work nobody "
                        "wants to own. That's where the real leverage (and the real "
                        "moat) quietly ends up."
                    ),
                    "hashtags": ["AI", "Strategy", "Engineering"],
                    "fact_flags": [],
                    "suggested_image": None,
                },
            }[kind]

        return {"angles": [angle(k) for k in wants]}


def get_provider(settings: Settings, *, force_mock: bool = False) -> LLMProvider:
    if force_mock or not settings.has_llm:
        return MockProvider(settings)
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(settings)
    if settings.llm_provider == "openai":
        return OpenAIProvider(settings)
    raise RuntimeError(f"Unknown LLM provider: {settings.llm_provider}")
