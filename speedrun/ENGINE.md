# Speedrun transfer engine (Phase 2)

This document explains the engine change, **why it lives in Rust**, and the
exact files touched, as required by the build rubric.

## What it does

Upstream Anki schedules on **recall R** (the FSRS probability you remember a
card). Speedrun adds **transfer T** — the probability you can solve a _novel_
problem that requires a concept under changed wording/context — and the
headline quantity **G = R − T** (the "illusion of mastery" gap).

The engine adds, per **concept** (the AAMC outline node, not a card):

- a one-parameter (Elo / 1-PL IRT) ability `theta`, updated online from graded
  transfer items: `theta += K · (correct − P(correct))`, where
  `P(correct) = σ(theta − b)` and `b` is the (frozen) item difficulty;
- a `MasteryQuery` returning R, T, G, observation count and weighted exam
  **coverage**;
- a `TransferGapQueue` that orders concepts by `exam_weight · G` (highest-value
  gaps first) — this single query is the study-next ranker, the score-model
  input, and the basis for the interleaving experiment.

## Why this belongs in Rust (`rslib`), not Python/JS

1. **One source of truth for desktop _and_ mobile.** AnkiDroid and the desktop
   GUI both call the same `rslib` backend over protobuf. Implementing T/G in
   Rust means the phone gets the identical engine for free; implementing it in
   PyQt or the TS frontend would not exist on Android at all.
2. **It must be transactional and undoable.** Recording a review mutates two
   tables (`transfer_review`, `concept_state`). Anki's `transact` +
   `UndoableChange` machinery lives in Rust; doing the write here gives us
   atomic rollback and real undo/redo, and guarantees we cannot half-write and
   corrupt the collection.
3. **It rides the existing sync/IPC boundary.** Adding a proto service is the
   sanctioned extension point; the Python and TS RPC stubs are generated, so
   there is no hand-maintained dispatch to drift.
4. **Hot path.** The gap queue and mastery query run on every review/dashboard
   refresh; keeping them in compiled Rust over SQLite avoids a Python round-trip
   per concept.

## Design choices / trade-offs

- **Lazy table creation instead of a schema-version bump.** The four tables are
  created with `CREATE TABLE IF NOT EXISTS` on first use rather than by
  incrementing Anki's `col.ver` and joining the upgrade chain. The schema
  version is entangled with download/upgrade/downgrade/export and a guard test;
  staying out of it means adding the engine **cannot break opening, upgrading,
  or exporting an existing collection**. Each table carries a `usn` column so it
  can be wired into sync later (Phase 7) without a migration.
- **Item difficulty `b` is frozen after authoring** (PRD risk mitigation); only
  the learner ability `theta` updates, so the scale stays stable.
- **R (`r_cache`) is a stored field, default 0** until FSRS aggregation is wired
  in Phase 4; the G math and all queries already consume it.

## Tests (proof)

- Rust (`rslib/src/speedrun/`): 5 unit/integration tests —
  - `correct_answer_raises_ability_wrong_lowers_it`
  - `transfer_probability_is_monotonic_in_ability_and_difficulty`
  - `gap_captures_recall_minus_transfer`
  - `review_updates_mastery_and_undo_restores_it` (records a review, checks
    theta/obs/coverage rise, then **undoes** and asserts full restoration — the
    no-corruption / undo proof)
  - `queue_orders_by_weighted_gap`
- Python (`pylib/tests/test_speedrun.py`): one end-to-end test driving the
  generated backend RPCs (`upsert_concept`, `upsert_item`,
  `record_transfer_review`, `mastery_query`, `transfer_gap_queue`) and
  `col.undo()`.

## Files touched

New:

- `proto/anki/speedrun.proto` — `SpeedrunService` (5 RPCs) + messages.
- `rslib/src/speedrun/mod.rs` — domain types + transfer math (σ, T, Elo, G).
- `rslib/src/speedrun/service.rs` — `impl SpeedrunService for Collection`.
- `rslib/src/speedrun/undo.rs` — `UndoableSpeedrunChange` + undoable helpers.
- `rslib/src/storage/speedrun/mod.rs` — CRUD over the four tables.
- `rslib/src/storage/speedrun/tables.sql` — idempotent table DDL.
- `pylib/tests/test_speedrun.py` — Python end-to-end test.

Edited:

- `rslib/src/lib.rs` — `pub mod speedrun;`.
- `rslib/src/storage/mod.rs` — `mod speedrun;`.
- `rslib/proto/src/lib.rs` — `protobuf!(speedrun, "speedrun");`.
- `rslib/proto/python.rs` — add `import anki.speedrun_pb2` to generated stub.
- `rslib/src/undo/changes.rs` — `UndoableChange::Speedrun` variant, dispatch,
  `From` impl.
- `rslib/src/undo/mod.rs` — `StateChanges` match arm for the new variant.

Generated (by the build, not hand-edited): `descriptors.bin`,
`OUT_DIR/backend.rs`, `out/pylib/anki/_backend_generated.py`,
`out/pylib/anki/speedrun_pb2.py`.
