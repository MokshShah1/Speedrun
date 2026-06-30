# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Engine benchmark (the `make bench` target).

Times the hot Speedrun paths through the real backend and reports throughput and
per-call latency. Useful as a smoke gate against accidental O(n^2) regressions:
the script fails if review recording or the dashboard fall below soft floors.

Run:  python speedrun/eval/bench.py   (or: make -C speedrun bench)
"""

from __future__ import annotations

import os
import random
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "out", "pylib"))

from anki.collection import Collection  # noqa: E402
import anki.speedrun_pb2 as pb  # noqa: E402

N_CONCEPTS = 30
LADDER_B = [-1.5, -0.9, -0.2, 0.5, 1.0, 1.6]

# Soft regression floors (very lax; catch catastrophic slowdowns, not microregressions).
MIN_REVIEWS_PER_SEC = 100.0
MIN_DASHBOARD_PER_SEC = 20.0


def new_col() -> Collection:
    fd, path = tempfile.mkstemp(suffix=".anki2")
    os.close(fd)
    os.unlink(path)
    return Collection(path)


def seed(col: Collection) -> list[tuple[int, int]]:
    """Return list of (item_id, concept_id)."""
    pairs = []
    iid = 1
    for cid in range(1, N_CONCEPTS + 1):
        col._backend.upsert_concept(
            pb.Concept(id=cid, outline_id=f"C{cid}", section="bb", title="t", exam_weight=1.0)
        )
        for lvl, b in enumerate(LADDER_B):
            col._backend.upsert_item(
                pb.Item(id=iid, concept_id=cid, level=lvl, difficulty=b, source_ref="b",
                        ai_generated=False, stem="s", choices=["a", "b"], answer=0, explanation="x")
            )
            pairs.append((iid, cid))
            iid += 1
    return pairs


def timed(label: str, n: int, fn) -> dict:
    # Warm up once.
    fn(0)
    t0 = time.perf_counter()
    for i in range(n):
        fn(i)
    dt = time.perf_counter() - t0
    per_sec = n / dt if dt > 0 else float("inf")
    us = (dt / n) * 1e6 if n else 0.0
    return {"label": label, "n": n, "secs": dt, "per_sec": per_sec, "us": us}


def main() -> int:
    rng = random.Random(5)
    col = new_col()
    pairs = seed(col)

    results = []

    n_reviews = 3000
    def rec(i):
        item_id, cid = pairs[rng.randrange(len(pairs))]
        col._backend.record_transfer_review(
            item_id=item_id, concept_id=cid, correct=rng.random() < 0.6, latency_ms=900
        )
    results.append(timed("record_transfer_review", n_reviews, rec))

    results.append(timed("mastery_query(all)", 300,
                         lambda i: col._backend.mastery_query(concept_ids=[])))
    results.append(timed("readiness_report", 300,
                         lambda i: col._backend.readiness_report()))
    results.append(timed("transfer_gap_queue", 300,
                         lambda i: col._backend.transfer_gap_queue(limit=0)))
    results.append(timed("next_transfer_item", 300,
                         lambda i: col._backend.next_transfer_item(concept_id=0)))
    results.append(timed("export_transfer_log", 100,
                         lambda i: col._backend.export_transfer_log()))

    # One bulk import of a 1000-review peer log.
    peer = [
        pb.TransferReviewProto(
            guid=f"b-{j:08d}", item_id=pairs[j % len(pairs)][0],
            concept_id=pairs[j % len(pairs)][1], correct=bool(j % 2), latency_ms=900, ts=j + 1,
        )
        for j in range(1000)
    ]
    t0 = time.perf_counter()
    added = col._backend.import_transfer_log(reviews=peer).added
    import_dt = time.perf_counter() - t0

    col.close()

    print("Speedrun engine benchmark")
    print(f"  {'operation':28s} {'n':>6s} {'per_sec':>12s} {'us/op':>10s}")
    for r in results:
        print(f"  {r['label']:28s} {r['n']:6d} {r['per_sec']:12.0f} {r['us']:10.1f}")
    print(f"  {'import_transfer_log(1000)':28s} {added:6d} "
          f"{added / import_dt:12.0f} {import_dt * 1e6 / max(added,1):10.1f}")

    reviews_ps = results[0]["per_sec"]
    dashboard_ps = results[2]["per_sec"]
    ok = reviews_ps >= MIN_REVIEWS_PER_SEC and dashboard_ps >= MIN_DASHBOARD_PER_SEC
    print(f"\n  floors: record >= {MIN_REVIEWS_PER_SEC}/s ({reviews_ps:.0f}), "
          f"readiness >= {MIN_DASHBOARD_PER_SEC}/s ({dashboard_ps:.0f})")
    print("  RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
