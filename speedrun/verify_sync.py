# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Headless two-device check of the Speedrun transfer-log sync RPCs.

Loads the *built* backend from `out/pylib` and simulates two devices studying
offline, then exchanging their append-only review logs. Verifies the union
merge converges and is idempotent. This mirrors `pylib/tests/test_speedrun_sync.py`
but runs without the pytest `tests` package, so it works from a bare Python as
long as pylib was built (`tools/ninja pylib`).

Run:  python speedrun/verify_sync.py
"""

import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "out", "pylib"))

from anki.collection import Collection  # noqa: E402
import anki.speedrun_pb2 as pb  # noqa: E402


def new_col() -> Collection:
    fd, path = tempfile.mkstemp(suffix=".anki2")
    os.close(fd)
    os.unlink(path)
    return Collection(path)


def seed(col: Collection) -> None:
    col._backend.upsert_concept(
        pb.Concept(id=1, outline_id="1D", section="bb", title="t", exam_weight=1.0)
    )
    col._backend.upsert_item(
        pb.Item(
            id=10, concept_id=1, level=3, difficulty=0.2, source_ref="seed",
            ai_generated=False, stem="stem", choices=["a", "b"], answer=0,
            explanation="x",
        )
    )


def theta(col: Collection) -> float:
    return col._backend.mastery_query(concept_ids=[1]).entries[0].theta


def main() -> int:
    a, b = new_col(), new_col()
    seed(a)
    seed(b)
    for i in range(10):
        a._backend.record_transfer_review(item_id=10, concept_id=1, correct=(i % 2 == 0), latency_ms=1000)
        b._backend.record_transfer_review(item_id=10, concept_id=1, correct=(i % 3 == 0), latency_ms=1000)

    # Single-field responses are unwrapped by the backend, so this is the
    # repeated reviews container directly.
    log_a = list(a._backend.export_transfer_log())
    log_b = list(b._backend.export_transfer_log())
    assert len(log_a) == 10 and len(log_b) == 10, "expected 10 reviews per device"

    into_b = b._backend.import_transfer_log(reviews=log_a)
    into_a = a._backend.import_transfer_log(reviews=log_b)
    print(f"  into A: added={into_a.added} total={into_a.total}")
    print(f"  into B: added={into_b.added} total={into_b.total}")
    assert (into_a.added, into_a.total) == (10, 20)
    assert (into_b.added, into_b.total) == (10, 20)

    ta, tb = theta(a), theta(b)
    print(f"  theta A={ta:.6f}  theta B={tb:.6f}  (converged: {abs(ta - tb) < 1e-9})")
    assert abs(ta - tb) < 1e-9, "devices did not converge"
    assert a._backend.mastery_query(concept_ids=[1]).entries[0].n_transfer_obs == 20

    again = a._backend.import_transfer_log(reviews=log_b)
    print(f"  re-import A: added={again.added} total={again.total} (idempotent)")
    assert (again.added, again.total) == (0, 20)
    assert abs(theta(a) - ta) < 1e-9

    a.close()
    b.close()
    print("  RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
