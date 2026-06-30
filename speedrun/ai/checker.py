# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Gold-set checker for generated transfer items.

Every candidate item must pass a fixed set of rules before it can be stored.
The rules are deliberately mechanical (no model in the loop) so the bar is
auditable and stable. `check_item` returns the list of failed rule names; an
empty list means the item is accepted."""

from __future__ import annotations

import re

MIN_STEM_LEN = 15
MIN_CHOICES = 3
MIN_CHOICE_LEN = 1


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower()).strip()


def _tokens(text: str) -> set[str]:
    return {w for w in _norm(text).split() if len(w) >= 4}


def check_item(item: dict, concept_title: str = "", source_text: str = "") -> list[str]:
    """Return the names of the rules this item fails (empty == accepted)."""
    fails: list[str] = []
    stem = (item.get("stem") or "").strip()
    choices = item.get("choices") or []
    answer = item.get("answer", -1)
    explanation = (item.get("explanation") or "").strip()

    if len(stem) < MIN_STEM_LEN:
        fails.append("stem_too_short")
    if len(choices) < MIN_CHOICES:
        fails.append("too_few_choices")
    if any(len((c or "").strip()) < MIN_CHOICE_LEN for c in choices):
        fails.append("empty_choice")

    lowered = [(_norm(c)) for c in choices]
    if len(set(lowered)) != len(lowered):
        fails.append("duplicate_choices")

    if not isinstance(answer, int) or answer < 0 or answer >= len(choices):
        fails.append("answer_out_of_range")
    else:
        # Answer leakage: the correct option must not be embedded in the stem.
        correct = _norm(choices[answer])
        if correct and correct in _norm(stem):
            fails.append("answer_leaks_into_stem")

    if not explanation:
        fails.append("missing_explanation")

    # Grounding: the item must share real vocabulary with the concept/source.
    context_tokens = _tokens(concept_title) | _tokens(source_text)
    if context_tokens:
        item_tokens = _tokens(stem) | set().union(*(_tokens(c) for c in choices)) if choices else _tokens(stem)
        if not (item_tokens & context_tokens):
            fails.append("off_topic")

    return fails


def accepts(item: dict, concept_title: str = "", source_text: str = "") -> bool:
    return not check_item(item, concept_title, source_text)
