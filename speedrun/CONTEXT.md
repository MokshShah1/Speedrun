# Speedrun — full project context (START HERE)

This is the single entry point for the **Speedrun** project. Read this first, then
follow the links. It exists so any agent (Claude Code, Cursor, etc.) has every
piece of context for the work.

---

## 1. What this is

**Speedrun is an MCAT study app built *within* Anki** — a real fork of the Anki
source that modifies its core (Rust `rslib`, protobuf API, Qt desktop, and the
Android backend), **not** an add-on or a separate app sitting on top of Anki.
Running the fork launches Anki itself, rebuilt from modified source, with the
Speedrun engine baked into the core.

It's an assignment project. The assignment: build a desktop + mobile study app on
Anki, make an engine-level change, add a score model and a study-feature
experiment, and prove it.

## 2. The thesis (product SPOVs)

FSRS already solves **memory** (recall). The unsolved, valuable work is the two
bridges: **memory → performance** and **performance → readiness**. So Speedrun
optimizes **transfer**, not recall. Five SPOVs (see the brainlift doc):

1. Schedule reps on whether you can **use** a fact, not whether you can recall it.
2. A student's weakest topic is the one they get right by **memorizing the wording**.
3. The student is the least reliable sensor — **don't trust the grade button**.
4. Studying one topic at a time (blocked) feels efficient and makes you worse (**interleaving**).
5. An AI question is worthless until a machine has re-solved it and agreed — **a raw generated item never touches the score**.

## 3. Core engine model (the important part)

- **Concept** is the unit (mapped 1:1 to the AAMC content outline), not the card.
- **R (recall)** = FSRS retrievability, aggregated from cards tagged
  `speedrun::<outline_id>`. Inherited, not rebuilt.
- **T (transfer)** = probability of solving a *novel* problem needing the concept.
  Modeled with a 1-PL IRT / Elo update from graded transfer answers.
- **Ladder L0–L5**: definition → paraphrase → single-concept application → novel
  application → multi-concept reasoning → full passage. T is measured along this
  difficulty gradient, not at one point.
- **G = R − T** = the "illusion of mastery" gap. Drives what to study next, feeds
  the performance model, and is the headline dashboard number. High R + low T =
  top priority. If R is low, build R first.
- **Three scores**: Memory (R), Performance (T), Readiness (472–528 scaled from
  exam-weighted T, with a confidence band that widens as coverage drops), plus a
  **give-up rule** (stop flogging a concept past threshold).

## 4. Where the code lives

Two locations:

- **The fork (all code):** `C:\dev\speedrun-anki` — git branch **`speedrun`**.
- **Assignment + brainlift:** `C:\Users\moksh\Downloads\AAI\Speedrun`
  (`brainlift/` has `build_brainlift_docx.py` → `MCAT-Brainlift.docx`; `PRD.md`).

Inside the fork:

| area | path | what |
|---|---|---|
| Rust engine | `rslib/src/speedrun/` | `mod.rs` (T/G/Elo math), `service.rs` (RPCs), `recall.rs` (R from FSRS), `sync.rs`, `undo.rs` |
| Rust storage | `rslib/src/storage/speedrun/` | `tables.sql` + `mod.rs` (idempotent tables) |
| API | `proto/anki/speedrun.proto` | `SpeedrunService` RPCs |
| Desktop UI | `qt/aqt/speedrun.py`, `qt/aqt/transfer_reviewer.py` | Tools ▸ Speedrun Dashboard + Transfer Review |
| Py tests | `pylib/tests/test_speedrun*.py` | end-to-end backend tests |
| Module | `speedrun/` | data, AI pipeline, eval harnesses, android kit, scripts, docs |

The `speedrun/` module:

- `data/` — `concepts.json` (AAMC concept map), `seed_items.json`, `glucagon_items_openai.json`
- `ai/` — `provider.py`, `checker.py`, `leakage.py`, `generate.py`, `cli.py`, `run_eval.py`, `gold/gold_set.json`, `sources/`
- `eval/` — `bench.py`, `crash_kill.py`, `calibration.py`, `interleaving.py`, `soak.py`, `metrics.py`, `test_eval.py`
- `android/` — `ANDROID.md`, `build_speedrun_backend.ps1`, `SpeedrunBackendTest.kt`
- scripts — `import_content.py`, `tag_deck.py`, `verify_sync.py`
- docs — `README.md`, `ENGINE.md`, `AI.md`, `SYNC.md`, `EVAL.md`, `Makefile`, this file

## 5. Deep-dive docs (read as needed)

- `speedrun/README.md` — module overview + RPC list
- `speedrun/ENGINE.md` — T/G/Elo rationale + files touched (Phase 2/4)
- `speedrun/AI.md` — item-generation pipeline, checker rules, **the glucagon quality-ceiling run**, generation decision (Phase 6)
- `speedrun/SYNC.md` — append-only transfer-review log sync, conflict-free replay (Phase 7)
- `speedrun/EVAL.md` — calibration, interleaving ablation, soak, bench, crash test (Phase 8)
- `speedrun/android/ANDROID.md` — turn-key AnkiDroid build kit (Phase 5)
- `PRD.md` (assignment folder) — full product requirements

## 6. Build / run / test

Anki's interface is the **`justfile`** (run `just --list`). Do not call `./ninja`
or `./run` directly.

```
just run                     # build + launch the forked desktop app
just check                   # format + full build & checks (do before "done")
cargo test -p anki --lib speedrun::   # Rust engine tests (test profile enables tokio)
just test-py                 # Python backend tests

# Speedrun harnesses (MSYS2 make on Windows: C:\msys64\usr\bin\make.exe):
make -C speedrun bench       # engine perf benchmark (`make bench`)
make -C speedrun crash       # hard-kill crash recovery
make -C speedrun eval        # calibration + interleaving + soak
make -C speedrun tag-test    # deck auto-tagger self-test
python -m pytest speedrun/ai/test_eval.py speedrun/ai/test_ai.py -q

# AI item generation (offline mock by default):
python -m speedrun.ai.cli --concept-id N --concept-title "..." --source <file> --source-ref "..." --levels 0 1 2 3 4 5 --n 5 --out <json>
#   live: set $env:SPEEDRUN_AI_PROVIDER="openai" and $env:OPENAI_API_KEY first

# Content import + deck tagging:
python speedrun/import_content.py [--demo]
python speedrun/tag_deck.py --col <collection.anki2> --dry-run   # then drop --dry-run to apply
```

Note: Python harnesses import the built pylib from `out/pylib`, so build the fork
(`just run` once) before running backend-driven scripts.

## 7. Status (as of latest commit `a857338`)

**Done (built, tested, committed on `speedrun`):**
- Phase 0 env; Phase 1 fork builds + `build_flavor()` + `.version` = `26.05-speedrun`
- Phase 2 engine (T, G, Elo, mastery query, transfer-gap queue) + undo wiring
- Phase 3 content (concept map, L0–L5 seed items, importer)
- Phase 4 G made real (R from FSRS) + desktop Dashboard + Transfer Review UI
- Phase 6 AI pipeline (generator → checker → leakage → cache → gold set/eval) + **live glucagon run + checker hardening**
- Phase 7 sync (append-only review log, union-by-guid, deterministic replay)
- Phase 8 headless proof: calibration (beats baselines), interleaving ablation, soak, `make bench`, hard-kill crash test, deck tagger
- Phase 5 **prep**: turn-key Android build kit (needs a device to execute)

**Remaining (needs a machine/device/data — not codeable headless):**
- Android on-device: install Android Studio + NDK `29.0.14206865` + SDK 36, run
  `speedrun/android/build_speedrun_backend.ps1`, wire AnkiDroid `local_backend=true`,
  run on emulator/phone, import MileDown, **screen-record** a review (shared-engine proof).
- Shippable artifacts: signed APK + desktop installer, demo video.
- Real calibration: feed actual AAMC practice-test scores into the calibration harness.

## 8. Key decisions (committed)

- **Mobile = Android only**, using **Anki's built-in sync** (self-hosted server) for
  standard data; transfer reviews sync via the append-only log.
- **Seed deck = MileDown** (MCAT Anki deck).
- **Give-up rule** uses default thresholds (explicit, tunable).
- **T-item generation = AI-generated per concept, gold-set gated** (checker +
  leakage + human gold set as ground truth). Never trust the raw model.

## 9. Reviewer feedback + our response (context for SPOV 5)

The brainlift reviewer praised R/T/G and SPOV 3 (anchoring on machine-graded T; G =
"the size of the student's lie"), but flagged the **one gap**: the doc never said
**how T items are generated**, calling it the most load-bearing question (bad items
→ G noise → readiness fiction). Response: ran the pipeline **end-to-end on the
glucagon/blood-glucose cluster** live. Finding = the quality ceiling: content
accurate, but the model **flattened the difficulty ladder** (vignettes at every
rung) and **mis-keyed one "all of the above" answer**. Fix: added `catchall_choice`
+ `level_miscalibrated` checker rules (tightened checker now flags 9/30, ~70% real
accept rate) and added **SPOV 5**. See `AI.md` for the full writeup.

## 10. Conventions & gotchas

- **Tagging:** cards belong to a concept via the tag `speedrun::<outline_id>` (e.g.
  `speedrun::1D`). This is how R aggregates to the concept.
- **Schema:** never bump Anki's core schema version; Speedrun tables are created
  idempotently (`CREATE TABLE IF NOT EXISTS`) with defensive column backfills.
- **Undo:** Speedrun mutations use `transact` + `Op::Custom` + `UndoableChange::Speedrun`.
- **Commits:** phase-scoped, descriptive; commit messages via a temp file + `git commit -F`.
  Only commit when asked.
- **Shell:** this is **Windows PowerShell** — chain with `;`, not `&&`. MSYS2 tools
  (`git`, `rsync`, `make`) live at `C:\msys64\usr\bin`.
- **Toolchain (pinned):** Rust **1.92.0**, MSVC 14.44, NDK **29.0.14206865**, SDK 36,
  N2/Ninja. `cargo` uses `~/.cargo/config.toml` with `check-revoke = false` (corp SSL).
- **Secrets:** never write API keys to files or commits. The AI live path reads
  `OPENAI_API_KEY` from the environment only.

## 11. History / more context

The full agent transcript of how this was built (decisions, errors, fixes) is at:
`C:\Users\moksh\.cursor\projects\c-Users-moksh-Downloads-AAI-Speedrun\agent-transcripts\16daa53a-50a4-4b5c-b30a-2284e11e3a6a\16daa53a-50a4-4b5c-b30a-2284e11e3a6a.jsonl`
Search it for a keyword before reading; it's large.
