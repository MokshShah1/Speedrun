# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Pure scoring + statistics helpers for the evaluation harnesses.

No backend, no numpy: kept dependency-free so they can be unit-tested from a
bare Python and reused by the calibration and interleaving scripts."""

from __future__ import annotations

import math
import random

EPS = 1e-12


def brier_score(preds: list[float], outcomes: list[int]) -> float:
    """Mean squared error between predicted probabilities and 0/1 outcomes.

    Lower is better; 0 is perfect, 0.25 is the always-0.5 baseline."""
    if not preds:
        return 0.0
    return sum((p - y) ** 2 for p, y in zip(preds, outcomes)) / len(preds)


def log_loss(preds: list[float], outcomes: list[int]) -> float:
    """Mean negative log-likelihood (cross-entropy). Lower is better. Predictions
    are clipped away from 0/1 so a single confident miss cannot return inf."""
    if not preds:
        return 0.0
    total = 0.0
    for p, y in zip(preds, outcomes):
        p = min(1.0 - EPS, max(EPS, p))
        total += -(y * math.log(p) + (1 - y) * math.log(1.0 - p))
    return total / len(preds)


def reliability_bins(
    preds: list[float], outcomes: list[int], n_bins: int = 10
) -> list[dict]:
    """Group predictions into equal-width bins and report, per bin, the mean
    predicted probability vs the observed frequency. A well-calibrated model has
    observed ~= predicted in every populated bin."""
    bins: list[dict] = [
        {"lo": i / n_bins, "hi": (i + 1) / n_bins, "n": 0, "sum_pred": 0.0, "sum_obs": 0}
        for i in range(n_bins)
    ]
    for p, y in zip(preds, outcomes):
        idx = min(n_bins - 1, max(0, int(p * n_bins)))
        b = bins[idx]
        b["n"] += 1
        b["sum_pred"] += p
        b["sum_obs"] += y
    for b in bins:
        if b["n"]:
            b["mean_pred"] = b["sum_pred"] / b["n"]
            b["obs_freq"] = b["sum_obs"] / b["n"]
        else:
            b["mean_pred"] = None
            b["obs_freq"] = None
    return bins


def expected_calibration_error(
    preds: list[float], outcomes: list[int], n_bins: int = 10
) -> float:
    """Weighted mean gap between confidence and accuracy across bins (lower is
    better calibrated)."""
    if not preds:
        return 0.0
    total = len(preds)
    ece = 0.0
    for b in reliability_bins(preds, outcomes, n_bins):
        if b["n"]:
            ece += (b["n"] / total) * abs(b["mean_pred"] - b["obs_freq"])
    return ece


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def bootstrap_ci(
    samples: list[float], n_boot: int = 2000, alpha: float = 0.05, seed: int = 0
) -> tuple[float, float, float]:
    """Bootstrap (mean, low, high) for the mean of `samples` at the given alpha.

    Used to report effect sizes with an honest interval - if the interval spans
    0, we call the result null."""
    if not samples:
        return (0.0, 0.0, 0.0)
    rng = random.Random(seed)
    n = len(samples)
    means: list[float] = []
    for _ in range(n_boot):
        resample = [samples[rng.randrange(n)] for _ in range(n)]
        means.append(sum(resample) / n)
    means.sort()
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[int((1 - alpha / 2) * n_boot) - 1]
    return (mean(samples), lo, hi)
