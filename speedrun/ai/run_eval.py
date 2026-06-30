# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Evaluate the checker against the labelled gold set.

Each gold entry is labelled good/bad by hand. The checker predicts "accept"
(good) or "reject" (bad). We report accuracy/precision/recall and compare to a
trivial *accept-all* baseline. The checker must beat the baseline by a pre-set
margin (CUTOFF) and clear an absolute accuracy floor (MIN_ACCURACY); otherwise
this script exits non-zero so CI / `make`-style runs fail loudly.

Run directly:  python -m speedrun.ai.run_eval
"""

from __future__ import annotations

import json
import os
import sys

from . import checker

GOLD_PATH = os.path.join(os.path.dirname(__file__), "gold", "gold_set.json")

# Pre-set, committed thresholds (no post-hoc tuning).
CUTOFF = 0.25  # checker accuracy must exceed accept-all baseline by this much
MIN_ACCURACY = 0.90  # absolute floor


def load_gold() -> list[dict]:
    with open(GOLD_PATH, encoding="utf-8") as f:
        return json.load(f)


def evaluate(gold: list[dict]) -> dict:
    tp = tn = fp = fn = 0  # positive == "good/accept"
    misclassified: list[dict] = []
    for entry in gold:
        is_good = entry["label"] == "good"
        accepted = checker.accepts(
            entry["item"],
            entry.get("concept_title", ""),
            entry.get("source_text", ""),
        )
        if is_good and accepted:
            tp += 1
        elif not is_good and not accepted:
            tn += 1
        elif not is_good and accepted:
            fp += 1
            misclassified.append({"entry": entry, "kind": "false_accept"})
        else:
            fn += 1
            fails = checker.check_item(
                entry["item"], entry.get("concept_title", ""), entry.get("source_text", "")
            )
            misclassified.append({"entry": entry, "kind": "false_reject", "fails": fails})

    total = len(gold)
    n_good = sum(1 for e in gold if e["label"] == "good")
    checker_acc = (tp + tn) / total if total else 0.0
    baseline_acc = n_good / total if total else 0.0  # accept-all
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return {
        "total": total,
        "n_good": n_good,
        "n_bad": total - n_good,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "checker_accuracy": checker_acc,
        "baseline_accuracy": baseline_acc,
        "precision": precision,
        "recall": recall,
        "misclassified": misclassified,
    }


def main() -> int:
    gold = load_gold()
    r = evaluate(gold)
    print("Speedrun AI checker evaluation")
    print(f"  gold items      : {r['total']}  ({r['n_good']} good / {r['n_bad']} bad)")
    print(f"  checker accuracy: {r['checker_accuracy']:.3f}")
    print(f"  baseline (all)  : {r['baseline_accuracy']:.3f}")
    print(f"  precision       : {r['precision']:.3f}")
    print(f"  recall          : {r['recall']:.3f}")
    print(f"  confusion       : tp={r['tp']} tn={r['tn']} fp={r['fp']} fn={r['fn']}")
    beats = r["checker_accuracy"] >= r["baseline_accuracy"] + CUTOFF
    floor = r["checker_accuracy"] >= MIN_ACCURACY
    if r["misclassified"]:
        print("  misclassified:")
        for m in r["misclassified"]:
            e = m["entry"]
            print(f"    - [{m['kind']}] {e.get('failure', 'none')}: "
                  f"{e['item'].get('stem', '')[:60]!r}")
    ok = beats and floor
    print(f"  beats baseline by >= {CUTOFF}: {beats}")
    print(f"  accuracy >= {MIN_ACCURACY}: {floor}")
    print("  RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
