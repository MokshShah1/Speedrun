# Speedrun (MCAT) — fork of Anki

Speedrun is a fork of [Anki](https://github.com/ankitects/anki) that schedules study on **transfer** (can you *use* a fact on a novel problem) rather than only **recall**. It inherits Anki's FSRS memory engine and adds a per-concept transfer model.

License: GNU AGPL-3.0-or-later (inherited from Anki). Some Anki components are BSD-3-Clause. This fork preserves all upstream license headers.

## Core idea (from the Brainlift / PRD)
- **R** = recall probability (from Anki's FSRS).
- **T** = transfer probability: P(correctly solving a *novel* problem requiring the concept under changed wording/context), modeled per concept via a 1-parameter Elo/IRT update across a difficulty ladder.
- **G = R - T** = the gap ("illusion of mastery"); drives what to study next.
- Three honest scores: Memory (R), Performance (T), Readiness (472-528), each with a range, coverage %, confidence, reasons, and a give-up rule.

## This folder (`speedrun/`)
App-specific assets that ship with the fork, kept separate from upstream Anki code:

- `data/concepts.json` — the AAMC content-outline concept map (the coverage backbone). 31 in-scope content categories across Bio/Biochem, Chem/Phys, Psych/Soc (CARS excluded). `exam_weight` is a tunable uniform-within-section prior to be refined against AAMC's published distributions.
- `data/seed_items.json` — hand-authored transfer items (no AI) spanning ladder levels L0-L5, used for the Wednesday review loop. Same schema the Friday AI generator targets.
- `import_content.py` — loads the concept map + seed items into a collection through the engine RPCs (`upsert_concept` / `upsert_item`). Run after a build: `python speedrun/import_content.py [collection.anki2]`. With no path it creates a throwaway collection and prints a verification summary (concept count, coverage, gap queue).
- `ai/` — the Phase 6 AI transfer-item generation pipeline (provider + checker + leakage scanner + cache + gold-set eval). Fully offline-testable; see `AI.md`.
- `verify_sync.py` — headless two-device sync check against the built backend (`python speedrun/verify_sync.py` after `tools/ninja pylib`). Mirrors `pylib/tests/test_speedrun_sync.py`.
- `ENGINE.md` — the Phase 2 engine: what it does, why it lives in Rust, files touched, and the test/undo proof.
- `AI.md` — the Phase 6 AI pipeline: how items are generated from a named source, the quality bar, the leakage scanner, the 50-item gold set, and how to run it live with an API key.
- `SYNC.md` — the Phase 7 sync model: standard data via Anki's self-hosted server, and the append-only transfer-review log merge (union by guid + deterministic replay).
- `eval/` — Phase 8 evaluation harnesses: calibration (Brier/log-loss/ECE vs baselines), the interleaving ablation experiment (honest null + forgetting effect), and the 20x soak/restart test. See `EVAL.md`.
- `EVAL.md` — calibration results, the interleaving experiment, the soak test, and the documented v0 readiness mapping.

## Engine change (Rust, `rslib`) — implemented

A protobuf `SpeedrunService` (see `proto/anki/speedrun.proto`) exposing:
- `UpsertConcept` / `UpsertItem` — load the concept map and items.
- `RecordTransferReview` — grade a transfer item; updates concept ability via an online Elo/1-PL-IRT step. Transactional and undoable.
- `MasteryQuery(concept_ids) -> {R, T, G, theta, n_transfer_obs, coverage}` for the dashboard.
- `TransferGapQueue(limit) -> [concept_id]` ordered by `exam_weight x G`.
- `ExportTransferLog` / `ImportTransferLog` — append-only transfer-review log sync (union by `guid`, deterministic replay). See `SYNC.md`.

Collection tables: `concept`, `speedrun_item`, `transfer_review`, `concept_state` (theta stored in the collection DB; each carries `usn` for later sync). Created idempotently to avoid touching Anki's schema-version invariants — see `ENGINE.md`.

## Concept tagging convention (for decks)

R (recall) is aggregated to a concept from the FSRS state of the cards that
teach it. Cards are linked to a concept by an Anki **note tag**:

```
speedrun::<AAMC_CODE>      e.g.  speedrun::1D
```

Any premade deck (the project's seed deck is **MileDown**) is brought in scope
by importing its `.apkg` normally, then ensuring its notes carry the matching
`speedrun::<code>` tag. Coverage and the per-concept recall used in `G = R - T`
then read straight from those tagged cards (wired in the desktop phase). This
keeps the deck↔concept mapping in standard Anki tags rather than a bespoke
table, so it survives import/export and sync unchanged.

## Build
See Anki's docs: `docs/development.md` and `docs/windows.md`. In short, on Windows you need Rust (rustup), MSVC Build Tools + Windows SDK, MSYS2 (`git`, `rsync`) on PATH, and N2/Ninja (`bash tools/install-n2`). Then `.\run` from the repo root.
