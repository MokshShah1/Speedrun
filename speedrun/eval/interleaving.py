# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Study-feature ablation: blocked vs interleaved practice ordering.

This is the experiment the PRD asks for, run honestly. We hold the amount of
practice per concept *equal* across arms, so the only thing that differs is the
ORDER:

- blocked     : c0 x K, then c1 x K, ...  (finish one concept before the next)
- interleaved : c0, c1, ..., cN, repeated K times (round-robin)

We run it under two explicit learner models and let the data speak:

1. order-agnostic learner - practice raises a concept's latent ability with
   diminishing returns and there is NO forgetting. Order cannot matter here, so
   the honest expected result is a NULL (95% CI spans 0). Reporting this guards
   against a rigged experiment: if our harness "found" an effect here it would
   be a bug.
2. forgetting learner - same practice gain, plus ability decays with the number
   of trials since a concept was last practiced. Now blocked practice lets the
   early concepts decay for a long time before the final test, while interleaved
   keeps them fresh, so interleaving should help (CI excludes 0). This is the
   spacing/contextual-interference mechanism, stated up front rather than assumed
   in the conclusion.

Outcome metric: mean true transfer probability across concepts at a
representative difficulty, measured on the ground-truth ability at the end (a
mixed/delayed test). Effect = interleaved - blocked, with a bootstrap 95% CI
over many simulated learners.

Run:  python speedrun/eval/interleaving.py
"""

from __future__ import annotations

import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from eval import metrics  # noqa: E402

REP_B = 0.5  # representative difficulty for the final transfer test


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _orders(n_concepts: int, k: int) -> tuple[list[int], list[int]]:
    blocked = [c for c in range(n_concepts) for _ in range(k)]
    interleaved = [c for _ in range(k) for c in range(n_concepts)]
    return blocked, interleaved


def _final_transfer(
    order: list[int],
    theta0: list[float],
    gain: float,
    decay: float,
) -> float:
    """Replay a practice schedule and return mean true transfer at the end.

    `gain` is the diminishing-returns practice increment; `decay` is the
    per-elapsed-trial forgetting applied from a concept's last practice to the
    end of the session."""
    n = len(theta0)
    theta = list(theta0)
    practiced_count = [0] * n
    last_practiced_at = [None] * n
    for t, c in enumerate(order):
        # Diminishing-returns gain: each successive rep on a concept adds less.
        theta[c] += gain / (1.0 + practiced_count[c])
        practiced_count[c] += 1
        last_practiced_at[c] = t

    total = len(order)
    out = 0.0
    for c in range(n):
        # Forgetting between last practice and the final test.
        elapsed = (total - 1 - last_practiced_at[c]) if last_practiced_at[c] is not None else total
        theta_final = theta[c] - decay * elapsed
        out += sigmoid(theta_final - REP_B)
    return out / n


def run_scenario(
    name: str,
    decay: float,
    n_concepts: int = 8,
    k: int = 12,
    n_learners: int = 400,
    gain: float = 0.6,
    seed: int = 11,
) -> dict:
    rng = random.Random(seed)
    blocked_order, inter_order = _orders(n_concepts, k)
    diffs: list[float] = []
    blocked_scores: list[float] = []
    inter_scores: list[float] = []
    for _ in range(n_learners):
        theta0 = [rng.gauss(-0.5, 1.0) for _ in range(n_concepts)]
        b = _final_transfer(blocked_order, theta0, gain, decay)
        i = _final_transfer(inter_order, theta0, gain, decay)
        blocked_scores.append(b)
        inter_scores.append(i)
        diffs.append(i - b)
    eff, lo, hi = metrics.bootstrap_ci(diffs, seed=seed)
    null = lo <= 0.0 <= hi
    return {
        "name": name,
        "decay": decay,
        "blocked_mean": metrics.mean(blocked_scores),
        "interleaved_mean": metrics.mean(inter_scores),
        "effect": eff,
        "ci": (lo, hi),
        "null": null,
        "n_learners": n_learners,
    }


def main() -> int:
    scenarios = [
        run_scenario("order-agnostic (no forgetting)", decay=0.0),
        run_scenario("forgetting learner", decay=0.04),
    ]
    print("Speedrun interleaving ablation (blocked vs interleaved, equal practice)")
    for s in scenarios:
        lo, hi = s["ci"]
        verdict = "NULL (CI spans 0)" if s["null"] else "EFFECT (CI excludes 0)"
        print(f"\n  Scenario: {s['name']}  (decay={s['decay']}, n={s['n_learners']})")
        print(f"    blocked mean transfer    : {s['blocked_mean']:.4f}")
        print(f"    interleaved mean transfer: {s['interleaved_mean']:.4f}")
        print(f"    effect (interleaved-blocked): {s['effect']:+.4f}  "
              f"95% CI [{lo:+.4f}, {hi:+.4f}]")
        print(f"    verdict: {verdict}")

    # Honest validation of the harness itself:
    #  - the order-agnostic scenario MUST be null (else the harness is biased),
    #  - the forgetting scenario should detect the known spacing effect.
    agnostic, forgetting = scenarios
    print("\n  Harness checks:")
    print(f"    order-agnostic is null (required): {agnostic['null']}")
    print(f"    forgetting shows an effect       : {not forgetting['null']}")
    ok = agnostic["null"] and (not forgetting["null"])
    print("\n  RESULT:", "PASS" if ok else "FAIL")
    print("  Interpretation: interleaving helps only when forgetting is present;"
          " with an order-agnostic learner there is no free lunch.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
