# Speedrun AI item generation (Phase 6)

The transfer engine needs a steady supply of **transfer items** (novel,
application-and-reasoning questions) per concept and per ladder level. Hand
authoring does not scale, so Speedrun grows items from a **named source** with
an LLM, then refuses to trust the model: every candidate must clear a mechanical
quality bar and a leakage scan before it can be stored.

## Pipeline

```
named source text + concept + level
        │
        ▼
   provider.generate()        ← MockProvider (offline) or OpenAIProvider (live)
        │   raw candidate items
        ▼
   checker.check_item()       ← structural + grounding rules (mechanical)
        │
        ▼
   leakage.scan()             ← verbatim source-copy + near-duplicate detection
        │   accepted items only
        ▼
   generate.generate_items()  ← writes accepted items to an on-disk cache
        │
        ▼
   cli.py → JSON in seed-item schema → import_content.py → engine
```

The whole thing runs **offline with no API key** via the deterministic
`MockProvider`, which is what the tests and the "AI-off" path use. Set
`SPEEDRUN_AI_PROVIDER=openai` and `OPENAI_API_KEY` to switch to a real model;
the prompt instructs the model to use only the source, to test *use* of the
concept on a novel problem, and to never put the answer in the stem.

## Quality bar (`checker.py`)

An item is **rejected** if any rule fails:

- `stem_too_short` — stem under 15 characters
- `too_few_choices` — fewer than 3 options
- `empty_choice` — a blank/whitespace option
- `duplicate_choices` — two options normalise to the same text
- `answer_out_of_range` — answer index is not a valid choice
- `answer_leaks_into_stem` — the correct option text appears in the stem
- `missing_explanation` — no explanation provided
- `off_topic` — the item shares no significant token with the concept/source
- `catchall_choice` — an option is "all/none of the above" (AAMC-atypical, and it
  hides answer-key errors — added after the live glucagon run below)
- `level_miscalibrated` — an L0/L1 (definition/paraphrase) item is written as a
  clinical vignette or runs long, i.e. it's really an application item on the
  wrong rung. This protects the difficulty ladder that `G = R − T` depends on.

## Leakage scanner (`leakage.py`)

- `copies_source` — the stem reproduces an 8+ word verbatim span of the source
  (memorisation, not transfer)
- `near_duplicate` — the stem's token set overlaps an existing item by ≥ 0.80
  Jaccard (deduplicates within a batch and against seed/gold items)

## Gold set + held-out evaluation

`gold/gold_set.json` is **50 hand-labelled items** (25 good, 25 bad, with the
intended failure type recorded for each bad item). `run_eval.py` runs the
checker over the set and compares it to a trivial **accept-all baseline**:

| metric | accept-all baseline | checker |
|---|---|---|
| accuracy | 0.50 | **1.00** |
| precision | — | 1.00 |
| recall | — | 1.00 |

The thresholds are **pre-set and committed** (no post-hoc tuning):
`CUTOFF = 0.25` (checker must beat baseline accuracy by this margin) and
`MIN_ACCURACY = 0.90`. `run_eval.py` exits non-zero if either is missed, so a
regression fails loudly.

## Running it

```bash
# Offline evaluation (no key needed)
python -m speedrun.ai.run_eval

# Offline tests
python -m pytest speedrun/ai/test_ai.py

# Generate items for one concept from a named source (offline mock)
python -m speedrun.ai.cli \
    --concept-id 30 \
    --concept-title "buffers and the Henderson-Hasselbalch equation" \
    --source speedrun/ai/sources/buffers_milestone.txt \
    --source-ref "MileDown GenChem: Buffers" \
    --levels 1 2 3 --n 4 \
    --out speedrun/data/generated_items.json

# Same command, live model:
#   set SPEEDRUN_AI_PROVIDER=openai and OPENAI_API_KEY first
```

Accepted items are written in the same schema as `data/seed_items.json`, so
`import_content.py` loads them into the engine through `upsert_item` with
`ai_generated = true`.

## Files

- `provider.py` — `Provider` protocol, `MockProvider` (offline/deterministic),
  `OpenAIProvider` (live), `get_provider()`
- `checker.py` — mechanical quality rules
- `leakage.py` — source-copy + near-duplicate detection
- `generate.py` — orchestration + on-disk cache (the AI-off replay path)
- `cli.py` — `python -m speedrun.ai.cli` driver, emits seed-schema JSON
- `gold/gold_set.json` — 50 labelled items
- `run_eval.py` — held-out evaluation against the gold set, with hard thresholds
- `sources/` — sample named source texts
- `test_ai.py` — offline test suite (provider, checker, leakage, cache, eval)

## Generation decision (the load-bearing question)

How T items are produced is the most load-bearing choice in the system: if items
are badly formed, `G` is noise, readiness is noise, and the dashboard is fiction.
The committed decision is:

> **T items are AI-generated per concept from a named source, and are only
> trusted after passing the mechanical checker + leakage scan, with a
> hand-labelled gold set as the standing quality anchor.** The gold set is not
> polish — it is the ground truth the automated bar is measured against.

Rejected alternatives: pure hand-authoring (highest quality, does not scale to
the full AAMC outline); pure community-sourcing (uneven quality, licensing).
Both remain usable *inputs* because anything can be fed through the same checker.

## Quality ceiling — live run on the glucagon cluster

Reviewer's ask: pick one concept cluster, run the pipeline end-to-end on a real
model, and learn the actual quality ceiling. We ran **glucagon / blood-glucose
regulation** (concept `1D`), `gpt-4o-mini`, 5 candidates per rung across L0–L5
(30 items → `data/glucagon_items_openai.json`). Findings:

- **Content accuracy is high:** ~29/30 items are factually defensible MCAT
  questions, well grounded in the source, with plausible distractors and no
  verbatim source copying.
- **The model ignores the difficulty ladder:** it wrote clinical-vignette
  *application* questions at **every** rung, including L0/L1 which must be
  definition/paraphrase. Left unchecked this flattens the ladder — and a flat
  ladder makes `T` (and therefore `G`) meaningless.
- **One keyed answer was wrong:** an L2 item marked "all of the above" correct
  while bundling a glucagon action into a list of insulin effects. The original
  mechanical checker has no answer-correctness rule, so it passed.

**What we did about it:** added the `catchall_choice` and `level_miscalibrated`
rules. Re-running the *tightened* checker over the same 30 items now flags **9**:
the 8 miscalibrated L0/L1 vignettes and the 1 catch-all (the same item with the
wrong key). So the raw accept rate is honest at roughly **21/30 (~70%)** for this
cluster once the ladder is enforced — that is the real ceiling.

**Conclusion:** AI generation is viable and productive, but **not safe to feed
`G` unsupervised.** The remaining gaps the mechanical bar still can't close —
answer *correctness* and true difficulty calibration — are exactly why the
gold-set-gated strategy (and per-concept human sign-off before items drive
scores) is the right call, and why the calibration harness fits real `b` from
response data rather than trusting the level prior. Next hardening step: a
second-model "answer-verifier" pass (independent solve + agree) before an item
is eligible to move `G`.

## Still open

- A second-model answer-correctness verifier (independent solve-and-agree) to
  catch wrong keys mechanically.
- Difficulty (`b`) should be learned from response data (calibration harness),
  not taken from the per-level prior.
