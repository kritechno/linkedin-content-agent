"""Load Amir's writing samples for voice priming (plan §3a).

The model mimics rhythm/vocabulary far better from real examples than from
instructions, so we feed these as few-shot examples in the system prompt.
Supports .txt / .md / .rtf files dropped in the samples directory.
"""

from __future__ import annotations

from pathlib import Path

from striprtf.striprtf import rtf_to_text


def _read_sample(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() == ".rtf":
        raw = rtf_to_text(raw)
    return raw.strip()


def load_voice_samples(samples_dir: str, *, min_chars: int = 20) -> list[str]:
    """Return non-trivial writing samples, sorted by filename for determinism."""
    directory = Path(samples_dir)
    if not directory.is_dir():
        return []
    samples: list[str] = []
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in {".txt", ".md", ".rtf"}:
            continue
        text = _read_sample(path)
        if len(text) >= min_chars:
            samples.append(text)
    return samples
