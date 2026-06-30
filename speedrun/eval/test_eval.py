# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Unit tests for the pure evaluation helpers (no backend needed).

Run:  python -m pytest speedrun/eval/test_eval.py
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval import metrics  # noqa: E402
from eval.interleaving import run_scenario  # noqa: E402


def test_brier_known_values():
    assert metrics.brier_score([0.5, 0.5], [1, 0]) == 0.25
    assert metrics.brier_score([1.0, 0.0], [1, 0]) == 0.0
    assert abs(metrics.brier_score([0.0], [1]) - 1.0) < 1e-12


def test_log_loss_is_clipped_and_ordered():
    # Perfect-ish prediction has lower loss than a hedge.
    confident = metrics.log_loss([0.99, 0.01], [1, 0])
    hedge = metrics.log_loss([0.5, 0.5], [1, 0])
    assert confident < hedge
    # A confident miss is finite (clipped), not inf.
    assert math.isfinite(metrics.log_loss([0.0], [1]))


def test_reliability_bins_and_ece():
    # Perfectly calibrated synthetic data -> ECE ~ 0.
    preds = [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]
    # Build outcomes so each bin's frequency matches its midpoint over many reps.
    big_preds: list[float] = []
    big_out: list[int] = []
    for p in preds:
        n = 100
        ones = round(p * n)
        big_preds += [p] * n
        big_out += [1] * ones + [0] * (n - ones)
    ece = metrics.expected_calibration_error(big_preds, big_out)
    assert ece < 0.02


def test_bootstrap_ci_brackets_mean():
    mean, lo, hi = metrics.bootstrap_ci([0.2] * 50)
    assert abs(mean - 0.2) < 1e-9
    assert lo <= mean <= hi
    # A noisy zero-centred sample should include 0.
    sample = [(-1) ** i * 0.1 for i in range(100)]
    _, lo2, hi2 = metrics.bootstrap_ci(sample)
    assert lo2 <= 0.0 <= hi2


def test_interleaving_order_agnostic_is_null():
    s = run_scenario("agnostic", decay=0.0, n_learners=200)
    lo, hi = s["ci"]
    assert s["null"]
    assert lo <= 0.0 <= hi
    assert abs(s["effect"]) < 1e-9  # identical practice, no forgetting


def test_interleaving_forgetting_shows_effect():
    s = run_scenario("forgetting", decay=0.05, n_learners=200)
    lo, hi = s["ci"]
    assert not s["null"]
    assert lo > 0.0  # interleaving strictly helps under forgetting
