"""Central configuration, loaded from environment / .env.

Nothing here raises on import — missing LinkedIn secrets only matter once you
actually try to authenticate or post (Phase 0). Phase 1 (research) needs none
of them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()  # read .env if present; real env vars win

# Default research queries (plan §2). Each is a separate HN Algolia query; we
# merge + dedupe the results.
DEFAULT_QUERIES = [
    "LLM",
    "AI agent",
    "vibe coding",
    "Claude",
    "GPT",
    "AI engineering",
]

# Focus keywords for the ranker's topic_match signal AND the relevance gate.
# Lowercased SUBSTRINGS matched against the story title. Safe to keep here only
# tokens long enough that substring matching won't misfire (e.g. "model" is
# fine; short ambiguous tokens like "ai"/"ml" go in the STRICT list below).
DEFAULT_FOCUS_KEYWORDS = [
    "claude", "gemini", "anthropic", "openai", "mistral", "deepseek", "ollama",
    "chatgpt", "copilot", "cursor", "langchain", "hugging face",
    "agent", "agentic", "ai engineer", "vibe coding", "vibecoding",
    "fine-tun", "prompt", "inference", "local llm", "open-source model",
    "open source model", "foundation model", "frontier model", "coding agent",
    "benchmark", "model", "transformer", "diffusion", "embedding",
    "machine learning", "neural net", "quantiz",
]

# STRICT keywords matched on WORD BOUNDARIES (\bkw\b), so short/ambiguous tokens
# don't false-match inside longer words ("ai" must not match "available").
DEFAULT_FOCUS_KEYWORDS_STRICT = [
    "ai", "ml", "llm", "llms", "gpt", "rag", "mcp", "agi", "nlp", "rl",
]

# Persona grounding (plan §3b) — the thing nobody else can copy. Injected into
# the draft-writer system prompt. Override with PERSONA in .env.
DEFAULT_PERSONA = (
    "You write as Amir: a BSc AI student at JKU Linz who also runs a real "
    "adventure-tour business (SilkOffRoad) in Central Asia. You prefer concrete, "
    "practical takes grounded in actually shipping software for a small business "
    "over abstract hype. You're skeptical of benchmarks-as-marketing. You "
    "sometimes connect AI topics to running operations on the ground. You write "
    "plainly, with a point of view, and never sound like a press release."
)


def _split_csv(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    # LinkedIn
    linkedin_client_id: str = field(default_factory=lambda: os.getenv("LINKEDIN_CLIENT_ID", ""))
    linkedin_client_secret: str = field(default_factory=lambda: os.getenv("LINKEDIN_CLIENT_SECRET", ""))
    linkedin_redirect_uri: str = field(default_factory=lambda: os.getenv("LINKEDIN_REDIRECT_URI", "http://localhost:8000/callback"))
    linkedin_scopes: str = field(default_factory=lambda: os.getenv("LINKEDIN_SCOPES", "openid profile w_member_social"))
    linkedin_api_version: str = field(default_factory=lambda: os.getenv("LINKEDIN_API_VERSION", "202506"))

    # Storage
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", "linkedin_agent.db"))

    # Research
    research_queries: list[str] = field(
        default_factory=lambda: _split_csv(os.getenv("RESEARCH_QUERIES"), DEFAULT_QUERIES)
    )
    # Wider window: big stories build over days, not hours.
    research_max_age_hours: float = field(
        default_factory=lambda: float(os.getenv("RESEARCH_MAX_AGE_HOURS", "96"))
    )
    # Minimum traction to qualify as "widely discussed" — keep a story if it's
    # either this widely upvoted OR this widely commented. Filters out obscure
    # tiny launches. Relaxed automatically if too few topics qualify.
    min_points: int = field(default_factory=lambda: int(os.getenv("MIN_POINTS", "80")))
    min_comments: int = field(default_factory=lambda: int(os.getenv("MIN_COMMENTS", "60")))
    include_front_page: bool = field(
        default_factory=lambda: os.getenv("INCLUDE_FRONT_PAGE", "true").lower() == "true"
    )
    focus_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_FOCUS_KEYWORDS))
    focus_keywords_strict: list[str] = field(
        default_factory=lambda: list(DEFAULT_FOCUS_KEYWORDS_STRICT)
    )

    # ── Draft writer (Phase 2) ────────────────────────────────────────────
    # provider: "openai" or "anthropic". llm_model is optional; each provider
    # falls back to a sensible default when it's blank.
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "anthropic").lower())
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", ""))
    persona: str = field(default_factory=lambda: os.getenv("PERSONA", DEFAULT_PERSONA))
    voice_samples_dir: str = field(default_factory=lambda: os.getenv("VOICE_SAMPLES_DIR", "voice_examples"))
    n_angles: int = field(default_factory=lambda: int(os.getenv("N_ANGLES", "3")))
    ground_with_article: bool = field(
        default_factory=lambda: os.getenv("GROUND_WITH_ARTICLE", "true").lower() == "true"
    )

    # ── Telegram review (Phase 3) ─────────────────────────────────────────
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))

    # ── Images (Phase 5) ──────────────────────────────────────────────────
    image_default: bool = field(
        default_factory=lambda: os.getenv("IMAGE_DEFAULT", "false").lower() == "true"
    )
    image_dir: str = field(default_factory=lambda: os.getenv("IMAGE_DIR", "generated_images"))

    # ── Scheduling / polish (Phase 6) ─────────────────────────────────────
    post_days: list[str] = field(
        default_factory=lambda: _split_csv(os.getenv("POST_DAYS"), ["mon", "wed", "fri"])
    )
    post_hour: int = field(default_factory=lambda: int(os.getenv("POST_HOUR", "8")))
    post_minute: int = field(default_factory=lambda: int(os.getenv("POST_MINUTE", "0")))
    topic_memory_days: int = field(default_factory=lambda: int(os.getenv("TOPIC_MEMORY_DAYS", "30")))
    topics_per_cycle: int = field(default_factory=lambda: int(os.getenv("TOPICS_PER_CYCLE", "1")))
    max_posts_per_week: int = field(default_factory=lambda: int(os.getenv("MAX_POSTS_PER_WEEK", "4")))

    def require_linkedin(self) -> None:
        """Raise a clear error if LinkedIn credentials are missing."""
        missing = [
            name
            for name, val in (
                ("LINKEDIN_CLIENT_ID", self.linkedin_client_id),
                ("LINKEDIN_CLIENT_SECRET", self.linkedin_client_secret),
            )
            if not val
        ]
        if missing:
            raise RuntimeError(
                "Missing LinkedIn credentials: "
                + ", ".join(missing)
                + ". Copy .env.example to .env and fill them in "
                "(see README → Phase 0 setup)."
            )

    @property
    def llm_api_key(self) -> str:
        return {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
        }.get(self.llm_provider, "")

    @property
    def has_llm(self) -> bool:
        return self.llm_provider in {"anthropic", "openai"} and bool(self.llm_api_key)

    def require_llm(self) -> None:
        if not self.has_llm:
            env_var = "OPENAI_API_KEY" if self.llm_provider == "openai" else "ANTHROPIC_API_KEY"
            raise RuntimeError(
                f"LLM provider '{self.llm_provider}' is not configured. "
                f"Set {env_var} in .env (or use --dry-run for offline testing)."
            )

    def require_telegram(self) -> None:
        missing = [
            name for name, val in (
                ("TELEGRAM_BOT_TOKEN", self.telegram_bot_token),
                ("TELEGRAM_CHAT_ID", self.telegram_chat_id),
            ) if not val
        ]
        if missing:
            raise RuntimeError(
                "Missing Telegram config: " + ", ".join(missing)
                + ". Create a bot with @BotFather and get your chat id from "
                "@userinfobot (see README → Phase 3 setup)."
            )


def get_settings() -> Settings:
    return Settings()
