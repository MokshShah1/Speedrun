# Speedrun — final submission & verification guide

**Exam:** MCAT (472–528; four sections 118–132; CARS excluded — no memorizable content).
**What it is:** a fork of Anki whose Rust engine adds a per-concept **transfer**
model on top of FSRS **recall**, surfaced as three honest scores (Memory R,
Performance T, Readiness) on a desktop app and an Android companion that share the
one engine and sync.

This doc exists so you can **verify what's built without hunting**. Every claim
below points to the file and the one command that re-runs it.

## Verify everything with one command

```powershell
.\speedrun\sunday_proof.ps1      # runs ALL headless proofs, prints a PASS/FAIL summary
```

It runs, in order: the AI gold-set eval + baseline, AI pipeline/leakage tests,
AI-off scoring, memory calibration, transfer calibration, the paraphrase test, the
3-build study ablation, the Rust engine + sync tests, two-device HTTP sync, crash
recovery, soak, benchmark, latency, and the coverage tagger — each exits non-zero
on regression. (Build the fork once first so `out/pylib` exists: `just run`.)

Three proofs need a human and are recorded, not scripted: the **demo video**, the
**live phone↔desktop sync**, and the **clean-machine installer run** (below).

---

## What changed since the MVP (Wednesday → Sunday)

| Area | Wednesday (MVP) | Now (Sunday) |
| --- | --- | --- |
| AI | none (no model calls) | generate-from-named-source → **checker + leakage gate** → gold-set eval that **beats a baseline**; still scores with AI **off** |
| Scores | memory + a rough score | **three** scores (R, T, Readiness) each with a **range**, coverage, reasons, give-up, and a **whole-score abstention** rule |
| Mobile | reviews same deck | **two-way sync** (phone↔desktop), offline-then-sync, three scores computed **on-device** |
| Models | — | memory **and** transfer **calibrated** on held-out data; **paraphrase test** proves T isn't a copy of R |
| Study feature | — | interleaving ablation across **3 builds** (feature on/off/plain Anki), equal practice |
| Weights | uniform prior | **AAMC-calibrated** exam weights (concept map v0.2.0) |
| Packaging | clean build | desktop **MSI installer**, Android APK, latency + benchmark reports |

---

## Rubric map (Section 11 grading areas)

### Rust change and how it fits Anki (20%)
- **Code:** `rslib/src/speedrun/` (mod/service/recall/sync/undo), `proto/anki/speedrun.proto`.
- **Why Rust + files touched + merge risk:** `speedrun/ENGINE.md`.
- **Proof:** `cargo test -p anki --lib speedrun::` — engine math, **undo restores state** (no corruption), gap-queue ordering, sync merge/replay. Ships to phone via the same backend `.aar`.

### Score accuracy and honest uncertainty (20%)
- **Model descriptions (one page each + give-up rule):** `speedrun/MODELS.md`.
- **Memory (R) calibrated, held-out:** `speedrun/eval/memory_calibration.py` → log-loss **0.637** vs base-rate 0.648, reliability RMSE **0.085**. PASS.
- **Performance (T) calibrated:** `speedrun/eval/calibration.py` → log-loss **0.573** / Brier **0.194** / ECE **0.024**, beats the load-bearing **difficulty-only prior** (0.608). PASS.
- **T is not a copy of R (paraphrase, 7d):** `speedrun/eval/paraphrase.py` → memorizer **|T−R| = 0.74**, engine recovers true transfer within 0.05, gap conditional on the student. PASS.
- **Readiness = range, not one number; abstention:** `qt/aqt/speedrun.py` + `MODELS.md §3`. Band widens as coverage drops; **no score below 50 graded transfer reviews / 25% coverage** (stated, tunable).

### Study feature on learning science (15%)
- **Interleaving ablation, 3 builds, equal practice:** `speedrun/eval/interleaving.py`, `EVAL.md §2`. Forgetting learner: interleaved **0.647** > plain Anki **0.624** > blocked **0.361**; honest **null** under an order-agnostic learner (harness not rigged).

### AI checking and safety (15%)
- **What/why/skipped + pipeline:** `speedrun/AI.md`.
- **Every output traces to a named source:** `speedrun/ai/` provenance + `prove_ai_off.py`.
- **Held-out eval + cutoff, beats a baseline:** `speedrun/ai/run_eval.py` → checker **1.000** vs accept-all **0.500** on a 50-item gold set; pre-committed cutoffs (Δ≥0.25, acc≥0.90).
- **Leakage check:** `speedrun/ai/leakage.py` (verbatim + near-duplicate), exercised in `speedrun/ai/test_ai.py`.
- **Still scores with AI off:** `speedrun/ai/prove_ai_off.py` (engine never imports the AI package). PASS.

### Fair tests others can re-run (12%)
- One command: `speedrun/sunday_proof.ps1`. Pure stats unit-tested without the backend: `speedrun/eval/test_eval.py`. Every harness gates (non-zero on regression).

### Desktop + phone share one engine, with working sync (10%)
- **Sync model + conflict rule:** `speedrun/SYNC.md`.
- **Two-device convergence (7b):** `speedrun/sync/test_transfer_sync.py`, `pylib/tests/test_speedrun_sync.py`. Append-only, **union-by-guid**, deterministic replay ⇒ offline-then-sync loses/doubles nothing.
- **On-device scores (phone):** AnkiDroid `TransferLogSync` logs R/T/Readiness from the shared engine (see the live recording).

### Useful product and clean UX (8%)
- Desktop **Dashboard** (`qt/aqt/speedrun.py`) + **Transfer Reviewer** (`qt/aqt/transfer_reviewer.py`); AnkiDroid companion.

---

## Section 7 challenges

| # | Challenge | Where |
| --- | --- | --- |
| 7a | Rust change + 3 Rust tests + 1 Python test + undo/no-corruption | `rslib/src/speedrun/`, `ENGINE.md`, `pylib/tests/test_speedrun.py` |
| 7b | Offline sync test (no lost/doubled; conflict rule) | `SYNC.md`, `sync/test_transfer_sync.py` |
| 7c | Coverage map (abstain below the line) | dashboard coverage + `tag_deck.py --self-test` |
| 7d | Paraphrase test (report the R−T gap) | `eval/paraphrase.py` |
| 7e | Leakage check (clean) | `ai/leakage.py`, `ai/test_ai.py` |
| 7f | AI card check on a 50-item gold set, cutoff before results | `ai/run_eval.py`, `ai/gold/gold_set.json` |
| 7g | Crash + offline tests, zero corruption | `eval/crash_kill.py`, `eval/soak.py` |
| 7h | One-command benchmark (p50/p95/worst) | `eval/bench.py`, `LATENCY.md` |

---

## Section 12 hand-in

- **GitHub repo** (public AGPL fork, exam stated, both-app build, architecture, Rust note, files touched): this repo; `README.md`, `ENGINE.md`, `android/ANDROID.md`.
- **Model descriptions:** `speedrun/MODELS.md`.
- **Demo video (3–5 min):** shot list in `speedrun/DEMO_SCRIPT.md` — review session, Rust change in action, phone→desktop sync, three scores with ranges (+ abstention), AI features, test results.
- **Brainlift:** assignment folder (`brainlift/`, `PRD.md`).
- **Installer + clean run:** `speedrun/INSTALLER.md` (Tier-B MSI; the clean-VM Tier-A run is the one item deliberately left — noted honestly).

---

## Honest caveats (we report these on purpose)
- **Readiness scale map is v0.** The `T → 472–528` link is linear and explicit; fitting it to real AAMC practice-test concordance needs proprietary data we don't have offline. The calibration harness is the tool that will consume it.
- **Tier-A installer** (a separate clean Windows VM) not executed here; `INSTALLER.md §4` lists the exact steps a grader runs on a fresh box. Tier-B (isolated venv + self-contained MSI boot) is proven.
- The transfer-review log rides a **separate lightweight channel** from Anki's own sync; both are two-way, idempotent, and offline-safe.
