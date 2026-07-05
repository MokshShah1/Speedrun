# Speedrun evaluation (Phase 8)

Headless evidence that the engine's numbers mean something. Three harnesses live
in `speedrun/eval/`; pure scoring/stats are in `metrics.py` and unit-tested
without the backend (`test_eval.py`).

## 1. Calibration of the transfer model (`calibration.py`)

We have no real student labels offline, so we state a data-generating process:
each concept has a fixed latent ability `true_theta`, and an item of difficulty
`b` is answered correctly with probability `sigmoid(true_theta - b)` (the 1-PL
IRT model the engine assumes). We then drive the **real backend**: at each trial
the model predicts `sigmoid(theta_hat - b)` from its current estimate, we sample
the outcome from the DGP, and the engine updates `theta_hat`.

Predictions are scored against three baselines: always-0.5, the base rate
(predict the global correct fraction), and a **difficulty-only prior** that knows
each item's `b` but never learns `theta` (fixed at the prior 0). The last is the
load-bearing one: because the engine's prediction already conditions on `b`,
beating base-rate is nearly free — so the real test is beating a predictor that
knows difficulty but never learns ability. The converged engine (2nd half, past
cold-start burn-in) must beat it, which isolates the value of the ability-learning.

Observed (`python speedrun/eval/calibration.py`, 2160 trials, base rate 0.526):

| predictor                      | log-loss  | Brier     | ECE       |
| ------------------------------ | --------- | --------- | --------- |
| **engine (full run)**          | **0.573** | **0.194** | **0.024** |
| engine (converged, 2nd half)   | 0.580     | 0.197     | 0.037     |
| baseline difficulty-only prior | 0.608     | 0.210     | —         |
| baseline base-rate             | 0.692     | 0.249     | —         |
| baseline always-0.5            | 0.693     | 0.250     | —         |

The reliability table tracks predicted ≈ observed in every populated bin (e.g.
the 0.2–0.3 bin observes 0.26; the 0.7–0.8 bin observes 0.74), and ECE stays
~0.02–0.04. The script **exits non-zero unless the engine beats all three
baselines on log-loss — including the converged engine vs the difficulty-only
prior**, so it can gate a build.

> "Performance accuracy" and "paraphrase gap" in the PRD are the same machinery:
> accuracy is `1 - Brier`-style scoring above; the paraphrase gap is `R - T`,
> already surfaced by the engine as `G` and shown on the dashboard.

## 1b. Memory-model calibration (`memory_calibration.py`, PRD Step 1)

The memory-side counterpart: it scores Anki's **FSRS** recall on **held-out**
reviews via `evaluate_with_time_series_splits` (train on each card's earlier
reviews, test on later), so "when it says 80% the student recalls ~80%" is proven
out-of-sample on the shipping engine. Reviews are drawn from an **exponential**
forgetting curve (FSRS assumes a *power* curve) so it is a fair test, not a model
grading its own homework. Reports held-out **log-loss** + **reliability RMSE** vs a
base-rate baseline; exits non-zero unless FSRS beats the base rate with small
calibration error. Full description in `MODELS.md` §1.

## 2. Interleaving ablation — 3 builds (`interleaving.py`)

The study-feature experiment, run honestly with the **three builds PRD §8 asks
for**, holding practice **per concept equal** across arms so only the order differs:

- **interleaved** — round-robin `c0..cN` × K → **Speedrun, feature ON** (the gap queue rotates concepts)
- **blocked** — `c0×K, c1×K, ...` → **Speedrun, feature OFF** (the ablation)
- **plain Anki** — same reps in a **concept-agnostic** order → **baseline** (stock Anki spaces cards by memory, blind to a concept-level transfer gap)

Two contrasts fall out: *interleaved − blocked* isolates the feature; *interleaved
− plain Anki* shows the whole app beats the obvious alternative. Run under two
explicit learner models:

| scenario            | interleaved | blocked | plain Anki | vs blocked (95% CI)          | vs plain Anki (95% CI)       |
| ------------------- | ----------- | ------- | ---------- | ---------------------------- | ---------------------------- |
| order-agnostic      | 0.6737      | 0.6737  | 0.6737     | +0.0000 [+0.0000,+0.0000] **NULL** | +0.0000 [+0.0000,+0.0000] **NULL** |
| forgetting (0.04)   | 0.6473      | 0.3607  | 0.6241     | **+0.2866** [+0.2840,+0.2892] | **+0.0232** [+0.0219,+0.0245] |

The null in the order-agnostic case is the point: with equal practice and no
forgetting, order _cannot_ matter, so a credible harness must report no effect on
**both** contrasts (else it's rigged). With forgetting, interleaving beats both its
own blocked ablation **and** the concept-agnostic stock-Anki order — so the gain is
the interleaving itself, not just "being Speedrun." Notably plain Anki (0.624) sits
between blocked (0.361) and interleaved (0.647): stock Anki's mixed order already
avoids the worst of blocking, and deliberate interleaving adds more on top. The
script asserts both scenarios on both contrasts.

## 2b. Paraphrase test — T is not a copy of R (`paraphrase.py`, PRD 7d)

Proves Performance (T) carries signal beyond Memory (R). Two archetypes with
**decoupled** latent abilities are run through the **real engine**:

| archetype    | R (recall) | T (engine) | true T | G = R−T | \|T−true\| | \|T−R\| |
| ------------ | ---------- | ---------- | ------ | ------- | ---------- | ------- |
| memorizer    | 0.975      | 0.236      | 0.213  | +0.739  | 0.054      | 0.739   |
| understander | 0.950      | 0.736      | 0.734  | +0.214  | 0.078      | 0.214   |

The engine **recovers the true transfer ability** (|T−true| < 0.08 both), and for
the memorizer T lands **0.74 away from R** — if T merely copied R it would sit on
top of it. The gap is **conditional on the student** (Δ = 0.52 between archetypes),
so R−T is a real "illusion of mastery" signal (SPOV 2), largest exactly for the
student who memorized the wording — not an artifact of the memory model.

## 3. Soak / restart test (`soak.py`)

Twenty simulated app sessions against one on-disk collection. Each session
opens the file, records 25 transfer reviews, exercises undo, exchanges a
synthetic peer sync log (twice, to check idempotency), reads the dashboard, and
closes (a process restart). After every reopen it asserts:

- the review log persisted across the restart (exact expected count),
- `sum(n_transfer_obs) == total reviews` (replay stays consistent),
- re-importing a peer log adds nothing (idempotent sync),
- readiness/mastery values are finite and within their bands.

Observed: **PASS — 20 sessions, 580 reviews durable**, no panics or invariant
breaks. This is the graceful-restart half of the "20x crash test"; the ungraceful
mid-write kill is covered separately below.

## 4. Hard-kill crash recovery (`crash_kill.py`)

The soak test restarts cleanly; this one does not. A child process opens the
collection, commits `K = 40` transfer reviews, prints a `READY` marker, then keeps
writing in a tight loop. The parent **hard-kills** it (`TerminateProcess` /
`SIGKILL` — no `finally`, no flush, no `close()`), reopens the file, and asserts:

- the collection opens — no corruption, no stuck SQLite lock,
- every committed review survived (`count >= K`); SQLite's WAL drops only the
  single transaction that was in flight at kill time,
- `sum(n_transfer_obs) == total` still holds after recovery,
- readiness stays in band, and
- the collection is **still writable** afterwards (a fresh review increments the
  count), proving recovery is complete, not just readable.

Observed (`python speedrun/eval/crash_kill.py`): child killed at ~359 committed
reviews, **all durable, invariants intact, writable after crash — PASS**. Per-op
transactions plus WAL mean a crash costs at most the one unfinished answer.

## 5. Engine benchmark (`bench.py`, the `make bench` target)

Times the hot paths through the real backend so an accidental `O(n^2)` can't slip
in unnoticed. Representative run (30 concepts, 6-rung ladder each):

| operation                         | throughput | per call |
| --------------------------------- | ---------- | -------- |
| `record_transfer_review`          | ~900/s     | ~1.1 ms  |
| `mastery_query` (all concepts)    | ~200/s     | ~4.9 ms  |
| `readiness_report`                | ~230/s     | ~4.3 ms  |
| `transfer_gap_queue`              | ~260/s     | ~3.9 ms  |
| `export_transfer_log`             | ~100/s     | ~9.9 ms  |
| `import_transfer_log` (1000 rows) | ~20000/s   | ~0.05 ms |

The script enforces soft floors (record ≥ 100/s, dashboard ≥ 20/s) and exits
non-zero below them, so it gates a build. Recording is a few hundred µs of real
work plus a transaction; the dashboard recomputes every concept's `R`/`T` from
scratch — fast enough that a human-paced session never waits.

## 6. Deck auto-tagger (`../tag_deck.py`)

Pre-made decks (MileDown, AnKing) aren't tagged `speedrun::<outline_id>`, so the
engine can't aggregate their FSRS recall into concept-level `R`. This script maps
each note to its best AAMC category by IDF-weighted keyword overlap with the
concept map's titles + topics, plus a bonus for verbatim topic phrases, and is
conservative (notes under `--min-score` stay untagged rather than mis-tagged).
`--dry-run` prints the assignment distribution before writing; `--self-test`
builds a synthetic 6-note MileDown deck and verifies every note lands on the
right category (Michaelis–Menten → `1A`, glycolysis → `1D`, action potential →
`3A`, Henderson–Hasselbalch → `5A`, operant conditioning → `7C`, Ohm's law →
`4C`) — **PASS**.

## Readiness mapping (v0, documented)

The readiness score is intentionally explicit so it can be replaced once real
calibration data exists. From `rslib/src/speedrun/mod.rs`:

```
readiness = scale_score(performance, 472, 528)
          = 472 + round((528 - 472) * clamp(performance, 0, 1))
```

where `performance` is the exam-weight-weighted mean transfer `T` across in-scope
concepts, and per-section scores map the section's weighted `T` onto 118..132 the
same way. As of concept-map **v0.2.0** those `exam_weight`s are no longer a
uniform prior: each is derived from AAMC's published per-section Foundational-
Concept distributions (Bio/Biochem FC1 55% / FC2 20% / FC3 25%; Chem/Phys FC4 40%
/ FC5 60%; Psych/Soc FC6 25% / FC7 35% / FC8 20% / FC9 15% / FC10 5%), split
uniformly across the content categories inside each FC (AAMC does not publish
per-category counts). See the `weighting` block in `speedrun/data/concepts.json`
for the exact method and source URLs.

The confidence interval widens as coverage drops: a small fixed floor plus a term
proportional to the un-observed share of the exam (so an unstudied exam reports a
wide band, not false precision). This linear `T -> score` map is **v0**; the
calibration harness above is the tool that will fit the real mapping (e.g.
isotonic or a logistic link to AAMC scaled scores) when practice-test data is
available.

## Running everything

A `speedrun/Makefile` wires the harnesses into targets (uses MSYS2 `make` on
Windows; the Python entrypoints below are equivalent):

```bash
make -C speedrun test        # pure unit tests (no backend)
make -C speedrun bench       # engine perf benchmark (`make bench`)
make -C speedrun crash       # hard-kill crash recovery
make -C speedrun eval        # calibration + interleaving + soak
make -C speedrun tag-test    # deck auto-tagger self-test

# or directly:
python -m pytest speedrun/eval/test_eval.py   # pure unit tests (no backend)
python speedrun/eval/bench.py                 # needs tools/ninja pylib first
python speedrun/eval/crash_kill.py            # needs tools/ninja pylib first
python speedrun/eval/calibration.py           # transfer (T) calibration
python speedrun/eval/memory_calibration.py    # memory (R / FSRS) calibration, held-out
python speedrun/eval/paraphrase.py            # T is not a copy of R (PRD 7d)
python speedrun/eval/interleaving.py          # study-feature ablation, 3 builds (PRD 8)
python speedrun/eval/soak.py
python speedrun/tag_deck.py --self-test
```

## Still open in Phase 8

- Signed APK + installer and the demo video need your machine / device.
- **Weights: done.** Concept/section `exam_weight`s are calibrated to AAMC's
  published Foundational-Concept distributions (concept-map v0.2.0); the
  derivation and source URLs live in `speedrun/data/concepts.json`.
- **Readiness scale map: still v0 (by choice).** Fitting the `T -> scaled-score`
  link to real AAMC practice-test concordance data remains — that data is
  proprietary and unavailable offline, so the linear map is kept explicit rather
  than fit to data we don't have. The calibration harness above is the tool that
  will consume it when it exists.
