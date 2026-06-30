# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""End-to-end test of Speedrun transfer-log sync across two collections.

Simulates two devices (e.g. phone + desktop) studying offline, then exchanging
their append-only transfer-review logs. The merge is a union on each review's
`guid`, after which both devices replay the shared log and converge to the same
ability. Re-running the exchange is idempotent: "10 + 10 = 20 once"."""

import anki.speedrun_pb2 as pb
from tests.shared import getEmptyCol


def _seed(col):
    col._backend.upsert_concept(
        pb.Concept(id=1, outline_id="1D", section="bb", title="t", exam_weight=1.0)
    )
    col._backend.upsert_item(
        pb.Item(
            id=10,
            concept_id=1,
            level=3,
            difficulty=0.2,
            source_ref="seed",
            ai_generated=False,
            stem="stem",
            choices=["a", "b"],
            answer=0,
            explanation="x",
        )
    )


def _theta(col):
    return col._backend.mastery_query(concept_ids=[1]).entries[0].theta


def test_two_device_transfer_log_sync_converges_and_is_idempotent():
    a = getEmptyCol()
    b = getEmptyCol()
    _seed(a)
    _seed(b)

    # Each "device" studies offline with a different correct/wrong pattern.
    for i in range(10):
        a._backend.record_transfer_review(
            item_id=10, concept_id=1, correct=(i % 2 == 0), latency_ms=1000
        )
        b._backend.record_transfer_review(
            item_id=10, concept_id=1, correct=(i % 3 == 0), latency_ms=1000
        )

    # Single-field responses are unwrapped by the backend, so export returns the
    # repeated reviews container directly (cf. transfer_gap_queue).
    log_a = list(a._backend.export_transfer_log())
    log_b = list(b._backend.export_transfer_log())
    assert len(log_a) == 10
    assert len(log_b) == 10

    # Two-way exchange.
    into_b = b._backend.import_transfer_log(reviews=log_a)
    into_a = a._backend.import_transfer_log(reviews=log_b)
    assert (into_a.added, into_a.total) == (10, 20)
    assert (into_b.added, into_b.total) == (10, 20)

    # Both devices replayed the same union -> identical ability.
    assert abs(_theta(a) - _theta(b)) < 1e-9
    assert a._backend.mastery_query(concept_ids=[1]).entries[0].n_transfer_obs == 20

    # Idempotent: re-importing the same log adds nothing and does not move theta.
    theta_before = _theta(a)
    again = a._backend.import_transfer_log(reviews=log_b)
    assert (again.added, again.total) == (0, 20)
    assert abs(_theta(a) - theta_before) < 1e-9

    a.close()
    b.close()
