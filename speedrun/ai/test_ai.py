# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Offline tests for the AI transfer-item pipeline.

These run with no network and no API key (the MockProvider is deterministic),
so they exercise the full path: generate -> checker -> leakage -> cache, plus
the held-out gold-set evaluation. Run with:

    python -m pytest speedrun/ai/test_ai.py
"""

from __future__ import annotations

import os
import shutil
import tempfile

from speedrun.ai import checker, generate, leakage, run_eval
from speedrun.ai.provider import MockProvider

SOURCE = (
    "A buffer resists pH change near its pKa. The Henderson-Hasselbalch "
    "equation relates pH, pKa, and the ratio of conjugate base to acid."
)
CONCEPT = "buffers and the Henderson-Hasselbalch equation"


def test_mock_provider_items_are_well_formed():
    items = MockProvider().generate(CONCEPT, SOURCE, level=2, n=5)
    assert len(items) == 5
    for it in items:
        assert checker.accepts(it, CONCEPT, SOURCE), checker.check_item(it, CONCEPT, SOURCE)
        assert it["ai_generated"] is True
        # The mock must never place the answer verbatim in the stem.
        assert "answer_leaks_into_stem" not in checker.check_item(it, CONCEPT, SOURCE)


def test_checker_rejects_specific_defects():
    base = {
        "stem": "Which condition makes a weak-acid buffer most resistant to pH change?",
        "choices": ["Near the pKa", "Far below pKa", "Far above pKa", "No conjugate base"],
        "answer": 0,
        "explanation": "Buffering peaks near the pKa.",
    }
    assert checker.accepts(base, CONCEPT, SOURCE)

    short = {**base, "stem": "pH?"}
    assert "stem_too_short" in checker.check_item(short, CONCEPT, SOURCE)

    few = {**base, "choices": ["Near the pKa", "Far below pKa"]}
    assert "too_few_choices" in checker.check_item(few, CONCEPT, SOURCE)

    dup = {**base, "choices": ["Near the pKa", "Near the pKa", "Far above", "None"]}
    assert "duplicate_choices" in checker.check_item(dup, CONCEPT, SOURCE)

    oor = {**base, "answer": 9}
    assert "answer_out_of_range" in checker.check_item(oor, CONCEPT, SOURCE)

    no_expl = {**base, "explanation": "  "}
    assert "missing_explanation" in checker.check_item(no_expl, CONCEPT, SOURCE)


def test_checker_rejects_catchall_and_miscalibrated_level():
    # "All of the above" is banned (it hides answer-key errors, as the live
    # glucagon L2 item showed).
    catchall = {
        "stem": "After a meal, which insulin effects occur in the liver and muscle?",
        "choices": ["Glycogenesis", "Lipogenesis", "Reduced gluconeogenesis", "All of the above"],
        "answer": 3,
        "explanation": "Insulin is anabolic.",
    }
    assert "catchall_choice" in checker.check_item(catchall, CONCEPT, SOURCE)

    # A clinical vignette at L0/L1 is really an application item on the wrong rung;
    # it flattens the ladder G depends on, so it must be flagged.
    vignette_l0 = {
        "stem": ("A patient recently diagnosed with type 1 diabetes presents with "
                 "high blood glucose. Which mechanism explains why it stays elevated?"),
        "choices": ["Unopposed glucagon", "More insulin", "More GLUT4", "Glycogenesis"],
        "answer": 0,
        "explanation": "No insulin leaves glucagon unopposed.",
        "level": 0,
    }
    assert "level_miscalibrated" in checker.check_item(vignette_l0, CONCEPT, SOURCE)

    # The same item at L3 (application) is fine on that rung.
    vignette_l3 = {**vignette_l0, "level": 3}
    assert "level_miscalibrated" not in checker.check_item(vignette_l3, CONCEPT, SOURCE)


def test_leakage_flags_source_copy_and_duplicates():
    copied = {"stem": "The Henderson-Hasselbalch equation relates pH, pKa, and the ratio of conjugate base"}
    assert "copies_source" in leakage.scan(copied, SOURCE, [])

    original = {"stem": "A buffer near its working pKa best resists external pH swings"}
    assert leakage.scan(original, SOURCE, []) == []
    # An exact repeat of an existing stem is a near-duplicate.
    assert "near_duplicate" in leakage.scan(original, SOURCE, [original])


def test_generate_accepts_and_caches():
    tmp = tempfile.mkdtemp()
    orig = generate.CACHE_DIR
    generate.CACHE_DIR = tmp
    try:
        report = generate.generate_items(
            concept_id=101,
            concept_title=CONCEPT,
            source_ref="MileDown ch.3",
            source_text=SOURCE,
            level=2,
            n=5,
        )
        assert not report.from_cache
        assert report.accepted, "mock generation should yield accepted items"
        assert report.acceptance_rate > 0
        for it in report.accepted:
            assert it["concept_id"] == 101
            assert it["source_ref"] == "MileDown ch.3"
            assert it["ai_generated"] is True

        # Second call must hit the cache (the AI-off path) with identical output.
        cached = generate.generate_items(
            concept_id=101,
            concept_title=CONCEPT,
            source_ref="MileDown ch.3",
            source_text=SOURCE,
            level=2,
            n=5,
        )
        assert cached.from_cache
        assert cached.accepted == report.accepted
    finally:
        generate.CACHE_DIR = orig
        shutil.rmtree(tmp, ignore_errors=True)


def test_held_out_eval_beats_baseline():
    gold = run_eval.load_gold()
    assert len(gold) == 50
    r = run_eval.evaluate(gold)
    assert r["checker_accuracy"] >= r["baseline_accuracy"] + run_eval.CUTOFF
    assert r["checker_accuracy"] >= run_eval.MIN_ACCURACY
