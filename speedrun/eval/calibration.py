# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Calibration of the transfer model, measured against the *real* engine.

We never have ground-truth student labels offline, so we use a stated
data-generating process: each concept has a fixed latent ability `true_theta`,
and a student answers an item of difficulty `b` correctly with probability
sigmoid(true_theta - b) (the 1-PL IRT model the engine assumes). We then drive
the actual backend:

    for each trial:
        theta_hat = engine's current estimate (mastery_query)
        p_hat     = sigmoid(theta_hat - b)          # the model's prediction
        outcome   ~ Bernoulli(sigmoid(true_theta - b))
        engine.record_transfer_review(outcome)      # engine updates theta_hat

and score the engine's predictions with Brier, log-loss and ECE, against two
baselines: always-0.5 and the base rate (predict the global correct fraction).
A genuinely informative, calibrated model beats the base rate on log-loss. The
script exits non-zero if it does not, so it can gate a build.

Run:  python speedrun/eval/calibration.py
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
import anki.speedrun_pb2 as pb  # noqa: E402

from eval import metrics  # noqa: E402

# Item difficulty ladder (L0..L5), matching the seed items.
LADDER_B = [-1.5, -0.9, -0.2, 0.5, 1.0, 1.6]


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def new_col() -> Collection:
    fd, path = tempfile.mkstemp(suffix=".anki2")
    os.close(fd)
    os.unlink(path)
    return Collection(path)


def run(n_concepts: int = 12, passes: int = 30, seed: int = 7) -> dict:
    rng = random.Random(seed)
    col = new_col()

    # Seed concepts and one item per ladder rung; remember each item's b.
    item_b: dict[int, float] = {}
    true_theta: dict[int, float] = {}
    iid = 1
    for cid in range(1, n_concepts + 1):
        col._backend.upsert_concept(
            pb.Concept(id=cid, outline_id=f"C{cid}", section="bb", title="t", exam_weight=1.0)
        )
        true_theta[cid] = rng.gauss(0.0, 1.3)
        for b in LADDER_B:
            col._backend.upsert_item(
                pb.Item(
                    id=iid, concept_id=cid, level=LADDER_B.index(b), difficulty=b,
                    source_ref="sim", ai_generated=False, stem="s",
                    choices=["a", "b", "c", "d"], answer=0, explanation="x",
                )
            )
            item_b[iid] = b
            iid += 1

    theta_by_concept: dict[int, float] = {cid: 0.0 for cid in range(1, n_concepts + 1)}
    preds: list[float] = []
    outcomes: list[int] = []

    items = sorted(item_b.items())  # (item_id, b)
    item_concept = {}
    iid = 1
    for cid in range(1, n_concepts + 1):
        for _ in LADDER_B:
            item_concept[iid] = cid
            iid += 1

    for _ in range(passes):
        rng.shuffle(items)
        for item_id, b in items:
            cid = item_concept[item_id]
            theta_hat = theta_by_concept[cid]
            p_hat = sigmoid(theta_hat - b)
            # Ground-truth outcome from the stated DGP.
            outcome = 1 if rng.random() < sigmoid(true_theta[cid] - b) else 0
            preds.append(p_hat)
            outcomes.append(outcome)
            col._backend.record_transfer_review(
                item_id=item_id, concept_id=cid, correct=bool(outcome), latency_ms=1000
            )
            # Refresh this concept's estimate from the engine.
            m = col._backend.mastery_query(concept_ids=[cid])
            theta_by_concept[cid] = m.entries[0].theta

    col.close()

    base_rate = metrics.mean([float(o) for o in outcomes])
    half = [0.5] * len(preds)
    rate = [base_rate] * len(preds)

    # Score the converged regime (second half) to exclude cold-start burn-in,
    # and report the full run too for honesty.
    h = len(preds) // 2
    return {
        "n": len(preds),
        "base_rate": base_rate,
        "engine": {
            "brier": metrics.brier_score(preds, outcomes),
            "log_loss": metrics.log_loss(preds, outcomes),
            "ece": metrics.expected_calibration_error(preds, outcomes),
        },
        "engine_converged": {
            "brier": metrics.brier_score(preds[h:], outcomes[h:]),
            "log_loss": metrics.log_loss(preds[h:], outcomes[h:]),
            "ece": metrics.expected_calibration_error(preds[h:], outcomes[h:]),
        },
        "baseline_half": {
            "brier": metrics.brier_score(half, outcomes),
            "log_loss": metrics.log_loss(half, outcomes),
        },
        "baseline_rate": {
            "brier": metrics.brier_score(rate, outcomes),
            "log_loss": metrics.log_loss(rate, outcomes),
        },
        "reliability": metrics.reliability_bins(preds[h:], outcomes[h:]),
    }


def main() -> int:
    r = run()
    print("Speedrun transfer-model calibration")
    print(f"  trials                 : {r['n']}   base rate {r['base_rate']:.3f}")
    print(f"  engine   (full) log-loss: {r['engine']['log_loss']:.4f}  "
          f"brier {r['engine']['brier']:.4f}  ece {r['engine']['ece']:.4f}")
    print(f"  engine (2nd-half)       : {r['engine_converged']['log_loss']:.4f}  "
          f"brier {r['engine_converged']['brier']:.4f}  ece {r['engine_converged']['ece']:.4f}")
    print(f"  baseline always-0.5     : {r['baseline_half']['log_loss']:.4f}  "
          f"brier {r['baseline_half']['brier']:.4f}")
    print(f"  baseline base-rate      : {r['baseline_rate']['log_loss']:.4f}  "
          f"brier {r['baseline_rate']['brier']:.4f}")
    print("  reliability (2nd half; pred -> observed):")
    for b in r["reliability"]:
        if b["n"]:
            print(f"    [{b['lo']:.1f},{b['hi']:.1f})  n={b['n']:4d}  "
                  f"pred {b['mean_pred']:.2f}  obs {b['obs_freq']:.2f}")

    beats_rate = r["engine"]["log_loss"] < r["baseline_rate"]["log_loss"]
    beats_half = r["engine"]["log_loss"] < r["baseline_half"]["log_loss"]
    print(f"  engine beats base-rate log-loss: {beats_rate}")
    print(f"  engine beats always-0.5 log-loss: {beats_half}")
    ok = beats_rate and beats_half
    print("  RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
