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
the outcome from the DGP, and the engine updates `theta_hat`. Predictions are
scored against an always-0.5 baseline and a base-rate baseline.

Observed (`python speedrun/eval/calibration.py`, 2160 trials):

| predictor | log-loss | Brier | ECE |
|---|---|---|---|
| **engine (full run)** | **0.573** | **0.194** | **0.024** |
| baseline always-0.5 | 0.693 | 0.250 | — |
| baseline base-rate | 0.692 | 0.249 | — |

The reliability table shows predicted ≈ observed in every populated bin. The
script **exits non-zero unless the engine beats both baselines on log-loss**, so
it can gate a build.

> "Performance accuracy" and "paraphrase gap" in the PRD are the same machinery:
> accuracy is `1 - Brier`-style scoring above; the paraphrase gap is `R - T`,
> already surfaced by the engine as `G` and shown on the dashboard.

## 2. Interleaving ablation (`interleaving.py`)

The study-feature experiment, run honestly. Practice **per concept is held
equal** across arms; only the order differs:

- **blocked**: `c0 x K`, then `c1 x K`, ...
- **interleaved**: round-robin `c0..cN`, repeated `K` times.

Run under two explicit learner models, letting the data decide:

| scenario | effect (interleaved − blocked) | 95% CI | verdict |
|---|---|---|---|
| order-agnostic (no forgetting) | +0.0000 | [+0.0000, +0.0000] | **NULL** |
| forgetting learner (decay 0.04) | +0.2854 | [+0.2825, +0.2882] | effect |

The null in the order-agnostic case is the point: with equal practice and no
forgetting, order *cannot* matter, so a credible harness must report no effect
there (if it didn't, it would be rigged). Interleaving helps only once a
forgetting mechanism is present — the spacing benefit — and that mechanism is
stated up front, not smuggled into the conclusion. The script asserts both:
order-agnostic must be null **and** forgetting must show an effect.

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

| operation | throughput | per call |
|---|---|---|
| `record_transfer_review` | ~900/s | ~1.1 ms |
| `mastery_query` (all concepts) | ~200/s | ~4.9 ms |
| `readiness_report` | ~230/s | ~4.3 ms |
| `transfer_gap_queue` | ~260/s | ~3.9 ms |
| `export_transfer_log` | ~100/s | ~9.9 ms |
| `import_transfer_log` (1000 rows) | ~20000/s | ~0.05 ms |

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
same way. The confidence interval widens as coverage drops: a small fixed floor
plus a term proportional to the un-observed share of the exam (so an unstudied
exam reports a wide band, not false precision). This linear `T -> score` map is
**v0**; the calibration harness above is the tool that will fit the real mapping
(e.g. isotonic or a logistic link to AAMC scaled scores) when practice-test data
is available.

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
python speedrun/eval/calibration.py
python speedrun/eval/interleaving.py
python speedrun/eval/soak.py
python speedrun/tag_deck.py --self-test
```

## Still open in Phase 8

- Signed APK + installer and the demo video need your machine / device.
- Calibration against real AAMC practice-test scores remains (the calibration
  harness is the tool that will consume that data when it exists).
