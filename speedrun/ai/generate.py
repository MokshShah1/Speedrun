# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Generate transfer items for a concept from a named source.

Pipeline per item: provider -> checker (quality) -> leakage scanner. Only items
that pass both are kept. Results are cached on disk keyed by
(provider, concept, source, level), so the AI-off path replays accepted items
with no network call and no API key."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

from . import checker, leakage
from .provider import LEVEL_DIFFICULTY, get_provider

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")


@dataclass
class GenerationReport:
    requested: int = 0
    accepted: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)  # {item, reasons}
    from_cache: bool = False

    @property
    def acceptance_rate(self) -> float:
        total = len(self.accepted) + len(self.rejected)
        return len(self.accepted) / total if total else 0.0


def _cache_key(provider: str, concept_title: str, source_text: str, level: int) -> str:
    h = hashlib.sha256(
        f"{provider}|{concept_title}|{level}|{source_text}".encode()
    ).hexdigest()[:16]
    safe = "".join(c if c.isalnum() else "_" for c in concept_title)[:40]
    return f"{safe}_L{level}_{h}.json"


def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, key)


def generate_items(
    concept_id: int,
    concept_title: str,
    source_ref: str,
    source_text: str,
    level: int,
    n: int = 5,
    *,
    provider_name: str | None = None,
    existing: list[dict] | None = None,
    use_cache: bool = True,
) -> GenerationReport:
    provider = get_provider(provider_name)
    existing = list(existing or [])
    key = _cache_key(provider.name, concept_title, source_text, level)

    # AI-off path: replay accepted items from cache.
    if use_cache and os.path.exists(_cache_path(key)):
        with open(_cache_path(key), encoding="utf-8") as f:
            cached = json.load(f)
        report = GenerationReport(requested=n, from_cache=True)
        report.accepted = cached["accepted"]
        return report

    report = GenerationReport(requested=n)
    raw_items = provider.generate(concept_title, source_text, level, n)
    for raw in raw_items:
        raw.setdefault("concept_id", concept_id)
        raw.setdefault("source_ref", source_ref)
        raw.setdefault("b", LEVEL_DIFFICULTY.get(level, 0.0))
        raw["ai_generated"] = True

        quality = checker.check_item(raw, concept_title, source_text)
        leaks = leakage.scan(raw, source_text, existing + report.accepted)
        problems = quality + leaks
        if problems:
            report.rejected.append({"item": raw, "reasons": problems})
        else:
            report.accepted.append(raw)

    if use_cache:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(key), "w", encoding="utf-8") as f:
            json.dump({"accepted": report.accepted}, f, indent=2)
    return report
