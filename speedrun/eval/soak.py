# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""20x soak / restart test for the Speedrun engine.

Simulates 20 app sessions against a single on-disk collection: each session
opens the file, records a batch of transfer reviews, exchanges a synthetic peer
sync log, reads the dashboard, exercises undo, and closes (a process restart).
After every reopen we assert durability and internal consistency:

- the review log persisted across the restart (expected count on disk),
- sum of per-concept observation counts == total reviews (replay is consistent),
- re-importing the same peer log adds nothing (idempotent sync),
- readiness/mastery values are finite and within their declared bands.

Any panic, corruption, or invariant break fails the run. This is the headless
half of the "20x crash test" bar; it does not yet cover a hard kill mid-write.

Run:  python speedrun/eval/soak.py
"""

from __future__ import annotations

import math
import os
import random
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "out", "pylib"))

from anki.collection import Collection  # noqa: E402
import anki.speedrun_pb2 as pb  # noqa: E402

N_SESSIONS = 20
N_CONCEPTS = 6
REVIEWS_PER_SESSION = 25
LADDER_B = [-1.5, -0.9, -0.2, 0.5, 1.0, 1.6]


def seed(col: Collection) -> None:
    iid = 1
    for cid in range(1, N_CONCEPTS + 1):
        col._backend.upsert_concept(
            pb.Concept(id=cid, outline_id=f"C{cid}", section="bb", title="t", exam_weight=1.0)
        )
        for lvl, b in enumerate(LADDER_B):
            col._backend.upsert_item(
                pb.Item(
                    id=iid, concept_id=cid, level=lvl, difficulty=b, source_ref="sim",
                    ai_generated=False, stem="s", choices=["a", "b"], answer=0, explanation="x",
                )
            )
            iid += 1


def synthetic_peer_log(rng: random.Random, n: int) -> list[pb.TransferReviewProto]:
    out = []
    for _ in range(n):
        cid = rng.randint(1, N_CONCEPTS)
        # item id for a random rung of this concept
        item_id = (cid - 1) * len(LADDER_B) + rng.randint(1, len(LADDER_B))
        out.append(
            pb.TransferReviewProto(
                guid=f"peer-{rng.getrandbits(64):016x}",
                item_id=item_id,
                concept_id=cid,
                correct=rng.random() < 0.5,
                latency_ms=1000,
                ts=rng.randint(1, 10**12),
            )
        )
    return out


def total_reviews(col: Collection) -> int:
    return len(list(col._backend.export_transfer_log()))


def assert_consistent(col: Collection) -> None:
    total = total_reviews(col)
    m = col._backend.mastery_query(concept_ids=[])  # empty == all concepts
    obs_sum = sum(e.n_transfer_obs for e in m.entries)
    assert obs_sum == total, f"obs sum {obs_sum} != total reviews {total}"
    assert 0.0 <= m.coverage <= 1.0
    for e in m.entries:
        assert math.isfinite(e.theta) and math.isfinite(e.transfer)
        assert 0.0 <= e.transfer <= 1.0

    r = col._backend.readiness_report()
    assert 472 <= r.readiness <= 528, r.readiness
    assert r.readiness_low <= r.readiness <= r.readiness_high
    assert 0.0 <= r.performance <= 1.0 and 0.0 <= r.memory <= 1.0


def main() -> int:
    fd, path = tempfile.mkstemp(suffix=".anki2")
    os.close(fd)
    os.unlink(path)
    rng = random.Random(99)

    expected = 0
    last_peer: list[pb.TransferReviewProto] = []
    try:
        for session in range(1, N_SESSIONS + 1):
            col = Collection(path)
            if session == 1:
                seed(col)

            # Live reviews this session.
            for _ in range(REVIEWS_PER_SESSION):
                cid = rng.randint(1, N_CONCEPTS)
                item_id = (cid - 1) * len(LADDER_B) + rng.randint(1, len(LADDER_B))
                col._backend.record_transfer_review(
                    item_id=item_id, concept_id=cid, correct=rng.random() < 0.55, latency_ms=900
                )
                expected += 1

            # Exercise undo while the last operation is still a live review, so
            # exactly one review is reversed.
            col.undo()
            expected -= 1

            # A peer sync arrives; importing is idempotent on re-send.
            peer = synthetic_peer_log(rng, 5)
            added1 = col._backend.import_transfer_log(reviews=peer).added
            expected += added1
            added2 = col._backend.import_transfer_log(reviews=peer).added
            assert added2 == 0, f"re-import not idempotent: added {added2}"

            # Re-sending the previous session's peer log must also add nothing.
            if last_peer:
                assert col._backend.import_transfer_log(reviews=last_peer).added == 0
            last_peer = peer

            assert_consistent(col)
            assert total_reviews(col) == expected, (
                f"session {session}: on-disk {total_reviews(col)} != expected {expected}"
            )
            col.close(downgrade=False)
            print(f"  session {session:2d}: reviews={expected} ok")

        # Final reopen to confirm durability after the last close.
        col = Collection(path)
        assert_consistent(col)
        assert total_reviews(col) == expected
        col.close(downgrade=False)
        print(f"  RESULT: PASS ({N_SESSIONS} sessions, {expected} reviews durable)")
        return 0
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(path + suffix)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
