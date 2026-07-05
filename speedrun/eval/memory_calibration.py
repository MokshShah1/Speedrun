# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Calibration of the MEMORY model (Anki's FSRS recall) on held-out reviews.

This is the memory-side counterpart to `calibration.py` (which calibrates the
*transfer* model). "Memory" here is Anki's built-in FSRS retrievability R - the
`R` in the gap `G = R - T` - and the claim we must back is Step 1 of the PRD:
*when the model says 80%, the student recalls about 80% of the time*, proven on
held-out reviews.

How we stay honest:

1. **Real engine.** We score the actual FSRS model through the backend RPC
   `evaluate_params`, which fits FSRS and scores it with
   `evaluate_with_time_series_splits` - i.e. it trains on each card's earlier
   reviews and tests on the *later* ones. So the reported numbers are held-out,
   not in-sample, and they come from the shipping engine, not a reimplementation.

2. **A data-generating process FSRS does not use.** We do not generate reviews
   from FSRS's own curve (that would be circular - a model grading its own
   homework). Each card instead forgets on a plain **exponential** curve
   `p_recall = exp(-delta_t / S)` with a per-card stability `S` that grows on a
   success and collapses on a lapse. FSRS assumes a *power* forgetting curve, so
   it has to learn to predict data drawn from a different family - a fair test of
   whether its probabilities are calibrated, not a tautology.

We report the engine's held-out **log-loss** (a proper scoring rule) and
**rmse_bins** (the root-mean-square error of the reliability curve - literally
"predicted minus observed, binned"), against an always-base-rate baseline. The
script exits non-zero unless the engine beats the base rate and the calibration
error is small, so it can gate a build.

Run:  python speedrun/eval/memory_calibration.py
"""

from __future__ import annotations

import math
import os
import random
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "out", "pylib"))
sys.path.insert(0, os.path.join(REPO, "speedrun"))

from anki.collection import Collection  # noqa: E402

from eval import metrics  # noqa: E402

DAY_MS = 86_400_000
# Simulated "now": a fixed epoch so runs are deterministic. All review
# timestamps are placed before it.
EPOCH_MS = 1_600_000_000_000


def new_col() -> Collection:
    fd, path = tempfile.mkstemp(suffix=".anki2")
    os.close(fd)
    os.unlink(path)
    return Collection(path)


def simulate_revlog(
    col: Collection,
    n_cards: int,
    rng: random.Random,
) -> list[int]:
    """Create `n_cards` Basic cards and a review history for each from the
    exponential-forgetting DGP. Returns the list of graded review outcomes (0/1)
    for the base-rate baseline. Rows are written straight into the revlog table
    with the real schema (id,cid,usn,ease,ivl,lastIvl,factor,time,type)."""
    model = col.models.by_name("Basic")
    deck_id = col.decks.id("Default")
    outcomes: list[int] = []
    rows: list[tuple] = []

    for k in range(n_cards):
        note = col.new_note(model)
        note["Front"] = f"q{k}"
        note["Back"] = f"a{k}"
        col.add_note(note, deck_id)
        cid = note.card_ids()[0]

        # Per-card latent stability (days) after the first learning step, and a
        # random calendar start so cards are not all reviewed on the same days.
        stability = max(0.6, rng.gauss(1.6, 0.6))
        start_day = rng.uniform(0.0, 40.0)
        t_days = start_day
        prev_ivl = 0
        # First entry: the learning grade (type=0). No delta_t to score yet.
        first_ivl = max(1, round(stability))
        rows.append((cid, t_days, 3, first_ivl, prev_ivl, 0, k))
        prev_ivl = first_ivl

        n_reviews = rng.randint(6, 12)
        for _ in range(n_reviews):
            # Choose the next gap so delta_t/S (hence true recall) spans a wide
            # range - that is what populates the calibration bins from ~0.3..0.97.
            frac = rng.uniform(0.05, 1.6)
            delta = max(1, round(stability * frac))
            t_days += delta
            true_p = math.exp(-delta / stability)
            recalled = rng.random() < true_p
            outcomes.append(1 if recalled else 0)
            rating = 3 if recalled else 1  # Good vs Again
            rows.append((cid, t_days, rating, max(1, round(stability)), prev_ivl, 1, k))
            prev_ivl = max(1, round(stability))
            # Update stability: growth on success, collapse on a lapse.
            if recalled:
                stability = stability * max(1.2, rng.gauss(2.4, 0.35))
            else:
                stability = max(0.5, rng.gauss(0.8, 0.15))

    # Write revlog rows. id must be a unique ms timestamp; derive it from the
    # simulated calendar day (this is what FSRS reads for delta_t) plus a small
    # per-card, per-row offset to guarantee uniqueness without shifting the day.
    for i, (cid, day, ease, ivl, last_ivl, kind, k) in enumerate(rows):
        rid = EPOCH_MS - int((400 - day) * DAY_MS) + (k % 500) * 37 + (i % 37)
        col.db.execute(
            "insert or ignore into revlog (id,cid,usn,ease,ivl,lastIvl,factor,time,type) "
            "values (?,?,?,?,?,?,?,?,?)",
            rid, cid, -1, ease, ivl, last_ivl, 2500, 3000, kind,
        )
    col.save()
    return outcomes


def run(n_cards: int = 400, seed: int = 13) -> dict:
    rng = random.Random(seed)
    col = new_col()
    try:
        outcomes = simulate_revlog(col, n_cards, rng)
        # Real engine, held-out (time-series split) FSRS evaluation.
        resp = col._backend.evaluate_params(
            search="deck:Default",
            ignore_revlogs_before_ms=0,
            num_of_relearning_steps=1,
        )
        engine_log_loss = float(resp.log_loss)
        engine_rmse_bins = float(resp.rmse_bins)
    finally:
        col.close()

    base_rate = metrics.mean([float(o) for o in outcomes])
    baseline_rate_ll = metrics.log_loss([base_rate] * len(outcomes), outcomes)
    baseline_half_ll = metrics.log_loss([0.5] * len(outcomes), outcomes)
    return {
        "n_reviews": len(outcomes),
        "base_rate": base_rate,
        "engine_log_loss": engine_log_loss,
        "engine_rmse_bins": engine_rmse_bins,
        "baseline_rate_log_loss": baseline_rate_ll,
        "baseline_half_log_loss": baseline_half_ll,
    }


def main() -> int:
    r = run()
    print("Speedrun MEMORY-model (FSRS recall) calibration - held-out reviews")
    print(f"  graded reviews        : {r['n_reviews']}   base rate {r['base_rate']:.3f}")
    print(f"  engine log-loss       : {r['engine_log_loss']:.4f}   (held-out, time-series split)")
    print(f"  engine rmse (bins)    : {r['engine_rmse_bins']:.4f}   (calibration-curve error; lower=better)")
    print(f"  baseline base-rate    : {r['baseline_rate_log_loss']:.4f}")
    print(f"  baseline always-0.5   : {r['baseline_half_log_loss']:.4f}")

    beats_rate = r["engine_log_loss"] < r["baseline_rate_log_loss"]
    beats_half = r["engine_log_loss"] < r["baseline_half_log_loss"]
    # rmse_bins is the RMSE of the reliability curve; Anki treats an adjusted
    # value <= ~1.5% as well-calibrated, so a raw rmse under ~0.10 is a safe,
    # generous gate for a synthetic run of this size.
    well_calibrated = r["engine_rmse_bins"] < 0.10
    print(f"  engine beats base-rate log-loss : {beats_rate}")
    print(f"  engine beats always-0.5 log-loss: {beats_half}")
    print(f"  calibration error small (<0.10) : {well_calibrated}  <- load-bearing")
    ok = beats_rate and beats_half and well_calibrated
    print("  RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
