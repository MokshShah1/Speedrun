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
breaks. This is the headless half of the "20x crash test"; a hard mid-write kill
is not yet covered.

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

```bash
python -m pytest speedrun/eval/test_eval.py   # pure unit tests (no backend)
python speedrun/eval/calibration.py           # needs tools/ninja pylib first
python speedrun/eval/interleaving.py
python speedrun/eval/soak.py                   # needs tools/ninja pylib first
```

## Still open in Phase 8

- `make bench` target, signed APK + installer, and the demo video need the build
  tooling / your machine.
- A hard-kill crash test (process killed mid-write) and calibration against real
  AAMC practice-test scores remain.
