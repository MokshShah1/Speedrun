# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Leakage scanner for generated transfer items.

Two failure modes are caught:

1. **Source copying** - the item reproduces a long verbatim span of the source
   text (memorisation, not transfer).
2. **Near-duplication** - the item is essentially a copy of an item we already
   have (seed, gold, or previously generated).

Both are cheap n-gram / set-overlap checks, run before an item is accepted."""

from __future__ import annotations

import re

COPY_NGRAM = 8  # consecutive words shared with the source => flagged as copied
DUP_JACCARD = 0.80  # token-set overlap with an existing item => duplicate


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _ngrams(words: list[str], n: int) -> set[str]:
    return {" ".join(words[i : i + n]) for i in range(0, max(0, len(words) - n + 1))}


def copies_source(stem: str, source_text: str, n: int = COPY_NGRAM) -> bool:
    item_ngrams = _ngrams(_words(stem), n)
    if not item_ngrams:
        return False
    return bool(item_ngrams & _ngrams(_words(source_text), n))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_duplicate(item: dict, existing: list[dict], threshold: float = DUP_JACCARD) -> bool:
    item_tokens = set(_words(item.get("stem", "")))
    for other in existing:
        if _jaccard(item_tokens, set(_words(other.get("stem", "")))) >= threshold:
            return True
    return False


def scan(item: dict, source_text: str, existing: list[dict]) -> list[str]:
    """Return leakage problems for an item (empty == clean)."""
    problems: list[str] = []
    # Check verbatim source copying across all learner-visible text, not just the
    # stem: an answer, distractor, or (especially) explanation lifted word-for-word
    # from the source is memorisation just as much as a copied stem.
    choices = [c for c in (item.get("choices") or []) if isinstance(c, str)]
    parts = [item.get("stem", ""), item.get("explanation", ""), *choices]
    if any(part and copies_source(part, source_text) for part in parts):
        problems.append("copies_source")
    if is_duplicate(item, existing):
        problems.append("near_duplicate")
    return problems
