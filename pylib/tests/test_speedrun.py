# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""End-to-end test of the Speedrun transfer engine through the Python backend.

Exercises the full proto -> Rust -> SQLite path: seed a concept and an item,
record a graded transfer review, confirm the concept's ability/transfer rise,
then undo and confirm the collection is restored (no leftover rows)."""

import anki.speedrun_pb2 as pb
from tests.shared import getEmptyCol


def test_transfer_engine_record_query_and_undo():
    col = getEmptyCol()

    col._backend.upsert_concept(
        pb.Concept(
            id=1,
            outline_id="1D",
            section="bb",
            title="Bioenergetics and metabolism",
            exam_weight=0.5,
        )
    )
    col._backend.upsert_item(
        pb.Item(
            id=10,
            concept_id=1,
            level=3,
            difficulty=0.0,
            source_ref="Lehninger Ch. 14",
            ai_generated=False,
        )
    )

    before = col._backend.mastery_query(concept_ids=[1])
    assert len(before.entries) == 1
    assert before.entries[0].n_transfer_obs == 0
    assert abs(before.entries[0].theta) < 1e-9
    assert before.coverage == 0.0

    col._backend.record_transfer_review(
        item_id=10, concept_id=1, correct=True, latency_ms=4200
    )

    after = col._backend.mastery_query(concept_ids=[1])
    assert after.entries[0].n_transfer_obs == 1
    assert after.entries[0].theta > 0.0
    assert after.entries[0].transfer > before.entries[0].transfer
    assert after.coverage > 0.0

    # The transfer-gap queue should surface the concept we have data for.
    assert 1 in list(col._backend.transfer_gap_queue(limit=0))

    # Undo must fully restore the prior state and remove the review row.
    col.undo()
    undone = col._backend.mastery_query(concept_ids=[1])
    assert undone.entries[0].n_transfer_obs == 0
    assert abs(undone.entries[0].theta) < 1e-9
    assert undone.coverage == 0.0

    col.close()
