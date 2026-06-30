# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""LLM provider abstraction for transfer-item generation.

Two providers implement the same interface:

- ``MockProvider`` is fully offline and deterministic. It is what the test
  suite and the AI-off path use, so generation is reproducible without a
  network call or an API key.
- ``OpenAIProvider`` calls a real model when ``OPENAI_API_KEY`` is set and the
  ``openai`` package is installed. It degrades gracefully (raising a clear
  error) when neither is available.

A provider returns a list of raw item dicts; quality is enforced afterwards by
``checker.py`` and ``leakage.py``, never trusted blindly."""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Protocol

LADDER = {
    0: "definition",
    1: "paraphrase",
    2: "single-concept application",
    3: "novel application",
    4: "multi-concept reasoning",
    5: "full passage",
}

# Difficulty prior per ladder level (matches the seed items' scale).
LEVEL_DIFFICULTY = {0: -1.5, 1: -0.9, 2: -0.2, 3: 0.5, 4: 1.0, 5: 1.6}


class Provider(Protocol):
    name: str

    def generate(
        self, concept_title: str, source_text: str, level: int, n: int
    ) -> list[dict]:
        ...


def _keywords(text: str, k: int = 8) -> list[str]:
    """Pull the most frequent significant tokens from a source text."""
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", text.lower())
    stop = {
        "this", "that", "with", "from", "which", "into", "they", "their",
        "have", "when", "then", "than", "also", "such", "these", "those",
        "where", "while", "because", "about", "between",
    }
    freq: dict[str, int] = {}
    for w in words:
        if w in stop:
            continue
        freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


class MockProvider:
    """Deterministic, offline generator.

    Produces structurally valid multiple-choice items that are *grounded* in
    the source keywords and the concept, with the correct answer never embedded
    verbatim in the stem. Output is stable for a given (concept, source, level,
    index), so the cache and tests are reproducible."""

    name = "mock"

    def generate(
        self, concept_title: str, source_text: str, level: int, n: int
    ) -> list[dict]:
        kws = _keywords(source_text) or [concept_title.split()[0].lower()]
        templates = [
            "At the {descriptor} level, which statement about {concept} best explains {kw}?",
            "Consider a {descriptor} scenario involving {kw}. How does {concept} most directly govern the result?",
            "Working at the {descriptor} level, a student applies {concept} to {kw}. Which reasoning is correct?",
            "Which {descriptor}-level prediction about {kw} follows directly from {concept}?",
            "In an unfamiliar {descriptor} context featuring {kw}, what does {concept} let you conclude?",
        ]
        items: list[dict] = []
        for idx in range(n):
            seed = f"{concept_title}|{level}|{idx}"
            h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
            # Spread keyword and template choice across idx so candidates differ
            # enough to survive near-duplicate detection.
            kw = kws[(h + idx) % len(kws)]
            descriptor = LADDER.get(level, "application")
            template = templates[idx % len(templates)]
            stem = template.format(descriptor=descriptor, concept=concept_title, kw=kw)
            correct = f"The {kw} behaviour follows directly from {concept_title}."
            distractors = [
                f"{concept_title} has no relationship to {kw}.",
                f"The {kw} effect contradicts {concept_title}.",
                f"{kw.capitalize()} is irrelevant outside {concept_title}.",
            ]
            choices = [correct] + distractors
            # Deterministic shuffle of the answer position.
            answer_pos = h % len(choices)
            choices[0], choices[answer_pos] = choices[answer_pos], choices[0]
            items.append(
                {
                    "level": level,
                    "b": LEVEL_DIFFICULTY.get(level, 0.0),
                    "ai_generated": True,
                    "stem": stem,
                    "choices": choices,
                    "answer": answer_pos,
                    "explanation": (
                        f"{concept_title} predicts the {kw} behaviour; the other "
                        f"options misstate or deny that relationship."
                    ),
                }
            )
        return items


class OpenAIProvider:
    """Real LLM provider. Requires OPENAI_API_KEY and the openai package."""

    name = "openai"

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model

    def generate(
        self, concept_title: str, source_text: str, level: int, n: int
    ) -> list[dict]:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set; use MockProvider for the offline path."
            )
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on env
            raise RuntimeError(
                "openai package not installed (`pip install openai`)."
            ) from exc

        client = OpenAI(api_key=api_key)
        descriptor = LADDER.get(level, "application")
        prompt = (
            f"You write MCAT transfer questions. Using ONLY the source below, "
            f"write {n} multiple-choice items at the '{descriptor}' level that test "
            f"whether a student can USE the concept '{concept_title}' on a NOVEL "
            f"problem (do not copy sentences from the source, do not put the answer "
            f"in the stem). Return JSON: a list of objects with keys stem, choices "
            f"(4 strings), answer (0-based index), explanation.\n\nSOURCE:\n{source_text}"
        )
        resp = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        raw = json.loads(resp.choices[0].message.content or "{}")
        rows = raw if isinstance(raw, list) else raw.get("items", [])
        for r in rows:
            r.setdefault("level", level)
            r.setdefault("b", LEVEL_DIFFICULTY.get(level, 0.0))
            r["ai_generated"] = True
        return rows


def get_provider(name: str | None = None) -> Provider:
    """Return the requested provider, defaulting to whatever is usable offline.

    Set SPEEDRUN_AI_PROVIDER=openai to force the real model."""
    name = name or os.environ.get("SPEEDRUN_AI_PROVIDER", "mock")
    if name == "openai":
        return OpenAIProvider()
    return MockProvider()
