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

- `data/concepts.json` — the AAMC content-outline concept map (the coverage backbone). 28 in-scope content categories across Bio/Biochem, Chem/Phys, Psych/Soc (CARS excluded). `exam_weight` is a tunable uniform-within-section prior to be refined against AAMC's published distributions.
- `data/seed_items.json` — hand-authored transfer items (no AI) spanning ladder levels L0-L5, used for the Wednesday review loop. Same schema the Friday AI generator targets.

## Planned engine change (Rust, `rslib`)
A new protobuf service exposing:
- `MasteryQuery(concept_ids) -> {R, T, G, n_transfer_obs, coverage}` for the dashboard.
- A transfer-gap review queue ordered by `exam_weight x G`.

New collection tables: `concept`, `item`, `transfer_review`, `concept_state` (T/theta stored in the collection DB so it syncs to the phone). See `../PRD` equivalents and the project PRD.

## Build
See Anki's docs: `docs/development.md` and `docs/windows.md`. In short, on Windows you need Rust (rustup), MSVC Build Tools + Windows SDK, MSYS2 (`git`, `rsync`) on PATH, and N2/Ninja (`bash tools/install-n2`). Then `.\run` from the repo root.
