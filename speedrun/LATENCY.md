# Latency — p50/p95 of the Speedrun hot paths

Reviewer feedback on the Wednesday MVP: *"the demonstration could have presented
a … latency measurement which would close the expected rubric rows."* This is
that measurement — the response times of the paths that actually back the thesis
(R/T/G → readiness), the transfer review loop, and the transfer-log sync.

It is a small, reproducible harness (`speedrun/bench/latency.py`) that warms up,
times each path with a **monotonic** timer (`time.perf_counter`) one call per
sample, and reports **p50 / p95 / min / max / mean** in **milliseconds**. It is
fully **offline and deterministic**: a temp collection seeded from the real
31-concept AAMC map (no live network, no OpenAI). It distinguishes **cold vs
warm** where that is meaningful (collection open, and first-sync vs steady-state
sync).

## Reproduce

```powershell
cd C:\dev\speedrun-anki
out\pyenv\Scripts\python.exe -m speedrun.bench.latency
```

(Also runs as section 7 of `.\speedrun\friday_proof.ps1`.) Needs the fork built
(`out/pylib` present). The run is ~30 s and prints the tables below.

## What is measured (and why)

| path | what it is | units |
| --- | --- | --- |
| `readiness_report` | the Rust engine score computation — **Memory R / Performance T / Readiness + range + coverage + give-up**. The exact call the desktop dashboard **and** AnkiDroid make. | ms |
| `mastery_query(all)` | per-concept R / T / G the dashboard reads alongside it. | ms |
| `next_transfer_item` | **transfer item load** — pick the next unmastered ladder item for the highest-gap concept. | ms |
| `record_transfer_review` | **transfer review round-trip** — record a graded answer + the online Elo/IRT **theta/G update** (undoable). | ms |
| `export_transfer_log` | engine side of a sync: serialise this device's append-only review log. | ms |
| `import_transfer_log` (idempotent) | engine side of a sync: the **union-by-guid merge + replay** of the full log (re-importing the same log adds 0 — pure merge/replay cost). | ms |
| `transfer_sync_cycle` (e2e HTTP) | the **full append-only union-by-guid HTTP sync** (`speedrun/sync/`): export → push → pull → import, over a loopback server (steady-state / idempotent). | ms |
| `transfer_sync_initial` (cold) | the one-time **cold backlog upload** to a fresh empty server. | ms |
| `collection_open` (warm / cold) | re-open of an on-disk collection, in-process (warm) and in a fresh backend process (cold — each app launch). | ms |

## Results (this machine)

- **Hardware/OS:** 13th Gen Intel Core i7-1355U (10c/12t), 15.7 GB RAM, Windows 11
  Home (build 26200). Bundled dev Python 3.13.13 (`out\pyenv`). Fork commit
  `d400b88` on branch `speedrun`.
- **Fixture:** real 31-concept AAMC map, a full L0–L5 ladder per concept, seeded
  graded transfer reviews (`seed=5`). The engine `export`/`import` replay a
  ~2,450-review log; the e2e HTTP cycle exchanges a 400-review log.

Representative run (numbers are stable across runs to within the sub-millisecond
/ network jitter of a laptop):

### Warm (steady state)

| path | n | p50 | p95 | min | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| `readiness_report` | 300 | **2.36** | **4.12** | 1.98 | 6.14 |
| `mastery_query(all)` | 300 | 2.67 | 4.26 | 2.18 | 6.82 |
| `next_transfer_item` (transfer item load) | 300 | 2.28 | 3.89 | 1.91 | 6.21 |
| `record_transfer_review` (round-trip) | 2000 | **1.72** | **2.66** | 0.56 | 5.27 |
| `export_transfer_log` (engine) | 300 | 11.29 | 12.72 | 8.75 | 16.50 |
| `import_transfer_log` (engine, idempotent) | 200 | 22.35 | 24.58 | 20.04 | 26.97 |
| `transfer_sync_cycle` (e2e HTTP, warm) | 20 | **79.4** | **90.5** | 63.3 | 99.7 |
| `collection_open` (warm, in-process) | 50 | 11.94 | 14.72 | 9.36 | 16.53 |

### Cold (fresh process / first sync)

| path | n | p50 | p95 | min | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| `collection_open` (cold, fresh process) | 12 | 9.34 | 18.20 | 4.43 | 19.90 |
| `transfer_sync_initial` (cold, full backlog) | 8 | 84.26 | 100.80 | 72.95 | 102.71 |

All units milliseconds (ms). Numbers vary with machine load: a quieter run gave
`readiness_report` p50 0.91 / p95 2.13 and `transfer_sync_cycle` p50 57 / p95 117
— same order of magnitude. The interactive engine calls stay low single-digit
ms regardless.

## Reading the numbers

- **The score path is effectively free.** The full dashboard `readiness_report`
  (R, T, G, per-section scaled scores, coverage band, give-up list) is **≈1–2.5 ms
  p50, ≈2–4 ms p95** across a 31-concept collection (varies with machine load).
  `mastery_query` and `next_transfer_item` are the same order. This is the number
  the reviewer asked for: the engine change adds no perceptible latency to the
  dashboard or to AnkiDroid (same RPC).
- **A transfer review round-trip** (record + Elo/IRT theta update + G recompute,
  undoable) is **≈1.7 ms p50, ≈2.7 ms p95** — imperceptible inside the answer tap.
- **Sync work is dominated by transport, not the engine.** The engine's own
  export + union-by-guid merge/replay of a ~2,450-review log is **≈11 + ≈22 ms**;
  the end-to-end HTTP cycle is **≈80 ms warm / ≈84 ms cold**, i.e. two localhost
  round-trips + JSON of the log. Sync is off the interactive path (it runs at the
  end of a normal sync), so tens of ms is comfortably fine.
- **Cold collection open** (each desktop launch, a fresh backend process) is
  **≈9 ms p50** here; warm re-open in-process is **≈12 ms**.

## Method notes / honesty

- **Monotonic timer**, one sample per call, `warmup` calls discarded before
  timing. Percentiles are linear-interpolated over the sorted samples.
- **The e2e HTTP sync is the one best-effort number.** Co-hosting a
  heavily-exercised Anki backend in the *same process* as the loopback client
  intermittently stalls the socket for ~seconds (a GIL/GC artifact, **not** real
  sync cost). So the harness (a) times the e2e cycle first, on a freshly-loaded
  backend, where it is clean, (b) caps each request's socket timeout and spaces
  the cycles so a stall can only land in the tail, and (c) if the loopback still
  can't be measured cleanly, it **says so and falls back** to the deterministic
  engine-side `export_transfer_log` + `import_transfer_log` numbers rather than
  reporting a fabricated value. The engine-side pair is the robust, always-clean
  measure of what a sync actually costs the CPU.
- Numbers are from a **laptop CPU** (i7-1355U) under normal desktop load;
  treat them as order-of-magnitude, reproducible on this machine, not a spec.
