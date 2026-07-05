# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Paraphrase test (PRD 7d): prove Performance (T) is not a copy of Memory (R).

The failure this guards against: a "performance" model that is really just the
memory model wearing a hat. If a student's accuracy on *reworded* exam-style
questions always equals their recall on the original card, then T carries no
signal beyond R and the R-T gap is fake.

We test it with the **real engine** and a data-generating process where the two
abilities are deliberately decoupled. Each concept gets two latent abilities:

  theta_recall   - how well the student recalls the original card wording (memory)
  theta_transfer - how well they solve the same idea in NEW words (performance)

Two archetypes (this is the whole point):

  memorizer    - high theta_recall, low theta_transfer: recalls the wording, cannot
                 use it. This is SPOV 2, "the weakest topic is the one you get right
                 by memorizing the wording." Expect R high, T low, gap large.
  understander - theta_recall ~= theta_transfer: expect R and T close, small gap.

For each concept we measure:
  R = empirical recall accuracy on the original-wording prompt (the memory model),
  T = the engine's learned transfer probability from graded REWORDED items, read
      back from the real backend (record_transfer_review -> mastery_query),
  G = R - T.

The load-bearing claims, asserted so the script can gate a build:
  1. The engine RECOVERS transfer ability: measured T ~= the true transfer prob,
     not the recall prob. (If T copied R, it would track recall instead.)
  2. The gap is REAL and CONDITIONAL: the memorizer shows a large R-T gap while
     the understander does not. A copy-of-R model would show ~0 gap for both.

Run:  python speedrun/eval/paraphrase.py
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

# The representative difficulty the engine reports T at (mirrors the Rust
# REPRESENTATIVE_DIFFICULTY constant), and the reworded-item difficulty ladder.
REP_B = 0.5
LADDER_B = [-1.5, -0.9, -0.2, 0.5, 1.0, 1.6]
# The original card is an easy, exact-wording recall prompt (ladder rung L0).
RECALL_B = -1.5


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def new_col() -> Collection:
    fd, path = tempfile.mkstemp(suffix=".anki2")
    os.close(fd)
    os.unlink(path)
    return Collection(path)


def run_archetype(
    label: str,
    recall_mean: float,
    transfer_mean: float,
    n_concepts: int = 20,
    passes: int = 40,
    recall_trials: int = 40,
    seed: int = 5,
) -> dict:
    """Drive the real engine for one student archetype and return R/T/G stats."""
    rng = random.Random(seed)
    col = new_col()

    true_recall: dict[int, float] = {}
    true_transfer: dict[int, float] = {}
    iid = 1
    item_concept: dict[int, float] = {}
    item_b: dict[int, float] = {}
    for cid in range(1, n_concepts + 1):
        col._backend.upsert_concept(
            pb.Concept(id=cid, outline_id=f"C{cid}", section="bb", title="t", exam_weight=1.0)
        )
        true_recall[cid] = rng.gauss(recall_mean, 0.3)
        true_transfer[cid] = rng.gauss(transfer_mean, 0.3)
        for b in LADDER_B:
            col._backend.upsert_item(
                pb.Item(
                    id=iid, concept_id=cid, level=LADDER_B.index(b), difficulty=b,
                    source_ref="sim", ai_generated=False, stem="reworded",
                    choices=["a", "b", "c", "d"], answer=0, explanation="x",
                )
            )
            item_concept[iid] = cid
            item_b[iid] = b
            iid += 1

    # Transfer phase: grade REWORDED items through the real engine. Outcomes are
    # drawn from the transfer ability, so a correct estimate must recover it.
    items = list(item_concept.keys())
    for _ in range(passes):
        rng.shuffle(items)
        for item_id in items:
            cid = item_concept[item_id]
            b = item_b[item_id]
            outcome = 1 if rng.random() < sigmoid(true_transfer[cid] - b) else 0
            col._backend.record_transfer_review(
                item_id=item_id, concept_id=cid, correct=bool(outcome), latency_ms=1000
            )

    # Read the engine's learned transfer per concept, and compare against R
    # (empirical recall on the original card) and the true transfer prob.
    rows = []
    for cid in range(1, n_concepts + 1):
        theta_hat = col._backend.mastery_query(concept_ids=[cid]).entries[0].theta
        t_engine = sigmoid(theta_hat - REP_B)
        t_true = sigmoid(true_transfer[cid] - REP_B)
        # R: empirical recall accuracy on the original-wording prompt.
        hits = sum(
            1 for _ in range(recall_trials) if rng.random() < sigmoid(true_recall[cid] - RECALL_B)
        )
        r = hits / recall_trials
        rows.append({"cid": cid, "R": r, "T": t_engine, "T_true": t_true, "G": r - t_engine})

    col.close()

    return {
        "label": label,
        "R": metrics.mean([x["R"] for x in rows]),
        "T": metrics.mean([x["T"] for x in rows]),
        "T_true": metrics.mean([x["T_true"] for x in rows]),
        "G": metrics.mean([x["G"] for x in rows]),
        # How closely the engine's T tracks the TRUE transfer prob vs recall R.
        "T_err_vs_true": metrics.mean([abs(x["T"] - x["T_true"]) for x in rows]),
        "T_err_vs_recall": metrics.mean([abs(x["T"] - x["R"]) for x in rows]),
        "rows": rows,
    }


def main() -> int:
    memorizer = run_archetype("memorizer", recall_mean=2.2, transfer_mean=-0.8)
    understander = run_archetype("understander", recall_mean=1.6, transfer_mean=1.6)

    print("Speedrun paraphrase test (PRD 7d): does Performance T copy Memory R?")
    for a in (memorizer, understander):
        print(f"\n  {a['label']}:")
        print(f"    Memory   R (recall on original card)      : {a['R']:.3f}")
        print(f"    Perf     T (engine, on reworded items)    : {a['T']:.3f}")
        print(f"    true transfer prob (ground truth)         : {a['T_true']:.3f}")
        print(f"    Gap      G = R - T                        : {a['G']:+.3f}")
        print(f"    |T - true transfer| (engine recovers T?)  : {a['T_err_vs_true']:.3f}")
        print(f"    |T - R|  (would be ~0 if T just copied R) : {a['T_err_vs_recall']:.3f}")

    # Load-bearing gates. Note R (recall) is measured at an easy retrieval
    # difficulty and T at the harder representative-application difficulty, so a
    # small positive gap is intrinsic even for a true understander; the 7d claim
    # is that the memorizer's gap is much LARGER (the ability mismatch T captures
    # beyond R), not that the understander's gap is zero.
    gap_delta = memorizer["G"] - understander["G"]
    recovers = memorizer["T_err_vs_true"] < 0.10 and understander["T_err_vs_true"] < 0.10
    not_a_copy = memorizer["T_err_vs_recall"] > 0.30
    gap_conditional = gap_delta > 0.30

    print("\n  Checks:")
    print(f"    engine recovers true transfer (|T-true|<0.10 both) : {recovers}")
    print(f"    memorizer T is NOT a copy of R (|T-R|>0.30)        : {not_a_copy}")
    print(f"    gap is conditional (memorizer G - understander G = {gap_delta:+.3f} > 0.30) : {gap_conditional}")
    ok = recovers and not_a_copy and gap_conditional
    print("\n  RESULT:", "PASS" if ok else "FAIL")
    print("  Interpretation: the engine's T tracks reworded-question ability, not"
          " card recall - so R-T is a real 'illusion of mastery' gap, largest exactly"
          " for the student who memorized the wording (SPOV 2), not an artifact of"
          " copying the memory model.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
