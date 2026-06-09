"""Draft data models, with JSON (de)serialization for DB persistence."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum


class AngleType(str, Enum):
    CONTRARIAN = "contrarian"          # "everyone's celebrating X, here's why it's overhyped"
    PRACTICAL = "practical"            # "here's how I'd actually use this in a real workflow"
    MISSED = "missed"                  # the under-discussed second-order effect

    @property
    def label(self) -> str:
        return {
            AngleType.CONTRARIAN: "Contrarian",
            AngleType.PRACTICAL: "Practical",
            AngleType.MISSED: "What everyone's missing",
        }[self]


@dataclass
class FactFlag:
    """A specific claim the model isn't sure about — verify before posting."""
    claim: str
    reason: str = ""


@dataclass
class DraftAngle:
    angle_type: AngleType
    hook: str                          # first line, before the "…see more" fold
    body: str
    hashtags: list[str] = field(default_factory=list)
    fact_flags: list[FactFlag] = field(default_factory=list)
    suggested_image: str | None = None  # short description, or None

    @property
    def full_text(self) -> str:
        text = self.body.strip()
        if not text.startswith(self.hook.strip()):
            text = f"{self.hook.strip()}\n\n{text}"
        tags = " ".join(f"#{t.lstrip('#')}" for t in self.hashtags)
        return f"{text}\n\n{tags}".strip() if tags else text


@dataclass
class DraftSet:
    topic_title: str
    topic_url: str
    why_hot: str
    angles: list[DraftAngle]

    # ── serialization ────────────────────────────────────────────────────
    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)

    @classmethod
    def from_json(cls, raw: str) -> "DraftSet":
        data = json.loads(raw)
        angles = [
            DraftAngle(
                angle_type=AngleType(a["angle_type"]),
                hook=a["hook"],
                body=a["body"],
                hashtags=a.get("hashtags", []),
                fact_flags=[FactFlag(**f) for f in a.get("fact_flags", [])],
                suggested_image=a.get("suggested_image"),
            )
            for a in data["angles"]
        ]
        return cls(
            topic_title=data["topic_title"],
            topic_url=data["topic_url"],
            why_hot=data.get("why_hot", ""),
            angles=angles,
        )
