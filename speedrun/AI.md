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

## Still needs a key / not done here

- Real held-out eval of *generated* item quality against a human rater needs the
  live provider (`OPENAI_API_KEY`); the offline path proves the plumbing,
  checker, leakage scanner, cache, and gold-set bar.
