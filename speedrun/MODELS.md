# Speedrun model descriptions

One page each for the three models the app reports — **Memory (R)**, **Performance
(T)**, and **Readiness** — plus the **give-up / abstention rule**. All three come
out of the shared Rust engine (`rslib/src/speedrun/`), so desktop and phone show
the identical computation. Every claim below is backed by a harness in
`speedrun/eval/` that re-runs and gates a build.

---

## 1. Memory model — R (recall)

**What it answers:** *Can the student recall this fact right now?*

**How it works.** R is **Anki's built-in FSRS retrievability** — the probability
the student remembers a card at this moment. Speedrun does **not** re-implement
memory; it *inherits* FSRS and aggregates card-level R to the **concept** level by
averaging over the cards tagged `speedrun::<outline_id>` (`rslib/src/speedrun/recall.rs`).
So R is FSRS, unchanged, viewed per AAMC concept.

**Why inherit, not rebuild.** FSRS is already a well-validated memory model;
rebuilding it would be strictly worse and would duplicate a moving target. The
novel work in Speedrun is the *bridges* off memory (T and readiness), not memory
itself.

**Calibration (held-out).** `speedrun/eval/memory_calibration.py` scores the real
FSRS model through the backend, trained on each card's **earlier** reviews and
tested on its **later** ones (`evaluate_with_time_series_splits`) — so the numbers
are out-of-sample. To avoid a model grading its own homework, reviews are drawn
from a plain **exponential** forgetting curve (FSRS assumes a *power* curve), a
deliberately different family. Reported: held-out **log-loss** and **reliability
RMSE** ("predicted − observed", binned) against a base-rate baseline; the script
exits non-zero unless FSRS beats the base rate with small calibration error.

**Give-up:** none needed at the memory layer — once a card has any review, FSRS
has an estimate. Abstention lives at the readiness layer (§3).

---

## 2. Performance model — T (transfer)

**What it answers:** *Can the student answer a new, exam-style question that uses
this fact — not the memorized card?*

**How it works.** Per concept, a one-parameter (**1-PL IRT / Elo**) latent ability
`theta`, updated online after each graded transfer item:

```
theta += K · (correct − P),   where P = σ(theta − b),  K = 0.3
```

`b` is the item's difficulty, **frozen at authoring** so the scale stays stable;
only `theta` learns. The concept's headline transfer is `T = σ(theta − 0.5)` at a
representative difficulty. Items span a **difficulty ladder L0–L5** (definition →
paraphrase → single-concept application → novel application → multi-concept
reasoning → full passage), so T is measured along a gradient, not at one point.
(`rslib/src/speedrun/mod.rs`, `service.rs`.)

**Calibration (held-out).** `speedrun/eval/calibration.py` drives the **real
engine** under a stated 1-PL data-generating process (2160 trials): the model
predicts `σ(theta_hat − b)`, an outcome is sampled, the engine updates. Scored
against three baselines:

| predictor                      | log-loss  | Brier     | ECE       |
| ------------------------------ | --------- | --------- | --------- |
| **engine (full run)**          | **0.573** | **0.194** | **0.024** |
| difficulty-only prior          | 0.608     | 0.210     | —         |
| base-rate                      | 0.692     | 0.249     | —         |
| always-0.5                     | 0.693     | 0.250     | —         |

The load-bearing gate: the converged engine beats the **difficulty-only prior**
(knows `b`, never learns `theta`), proving the ability-learning adds signal beyond
just knowing item difficulty. Reliability bins track observed frequencies.

**Not a copy of memory (paraphrase test, PRD 7d).**
`speedrun/eval/paraphrase.py` gives two archetypes decoupled abilities. For a
**memorizer** (recalls wording, can't transfer): R = 0.98, T = 0.24 — the engine
recovers the *true* transfer within 0.05 and lands **0.74 away from R**, so T is
not R in disguise. The R−T gap is **conditional**: 0.74 for the memorizer vs 0.21
for a true understander (Δ = 0.52). If T merely copied R, both gaps would be ~0.

**Give-up (per concept).** A concept with **≥ 8 graded transfer observations** and
**T < 0.35** is flagged for de-prioritization (`GIVE_UP_MIN_OBS`,
`GIVE_UP_TRANSFER` in `mod.rs`) — "lots of attempts, still not clicking," surfaced
on the dashboard so the student stops flogging it.

---

## 3. Readiness model — projected score

**What it answers:** *What would the student score today, and how sure are we?*

**How it works.** Readiness maps exam-weighted transfer onto the MCAT scale:

```
readiness = scale_score(performance, 472, 528) = 472 + round(56 · clamp(performance, 0, 1))
performance = Σ_i (exam_weight_i · T_i) / Σ_i exam_weight_i   over in-scope concepts
```

Per-section scores map the section's weighted T onto **118–132** the same way. The
`exam_weight`s are **calibrated to AAMC's published per-section Foundational-
Concept distributions** (concept map v0.2.0; see `data/concepts.json` and EVAL.md).

**Range (confidence), not one number.** The band widens as coverage falls:

```
half_width = round(56 · 0.08)  +  round(56 · 0.5 · (1 − coverage))
coverage   = Σ_i (exam_weight_i · covered_i)          # weighted share observed
```

A small floor of irreducible uncertainty plus a term proportional to the
**un-observed** share of the exam — so an unstudied exam reports a wide band, not
false precision. This linear `T → score` map is **v0**, explicitly documented as
awaiting real AAMC practice-test concordance data (which is proprietary); the
calibration harness is the tool that will fit the real link when that data exists.

**What the display always carries** (the honesty rule): the point estimate, the
range, coverage %, a low/med/high confidence signal (via the band width), the
last-updated time, plain-language **reasons** (coverage, an *illusion-of-mastery*
flag when memory exceeds performance by > 10 pts, the largest weighted gap to
study next), and the give-up list.

### Give-up / abstention rule (whole-score) — **the app refuses to guess**

The app shows **no projected score** until it has enough evidence. The stated,
tunable line (`SCORE_MIN_REVIEWS`, `SCORE_MIN_COVERAGE` in `qt/aqt/speedrun.py`):

> **No readiness score until the student has ≥ 50 graded transfer reviews AND
> ≥ 25% exam coverage.**

Below either threshold the dashboard renders **"No score yet"** with exactly what
is missing (e.g. "you have 29 reviews at 11% coverage — answer 21 more transfer
items to unlock an honest projection") and still shows Memory, Performance,
coverage, and the highest-gap concept so the student knows what to do next.
**Rationale:** below ~25% coverage the exam-weighted extrapolation is dominated by
topics we have never observed, and below ~50 reviews the per-concept Elo estimates
are too noisy to project a scaled score honestly. A confident number without that
evidence is "a guess in a nice font," which the rubric (and we) treat as a fail.

---

## Re-running the evidence

```bash
python speedrun/eval/memory_calibration.py   # R calibrated (held-out log-loss + reliability)
python speedrun/eval/calibration.py          # T calibrated (beats difficulty-only prior)
python speedrun/eval/paraphrase.py           # T is not a copy of R (PRD 7d)
python speedrun/eval/interleaving.py         # study-feature ablation, 3 builds (PRD 8)
```

Each script exits non-zero on regression, so they gate a build.
