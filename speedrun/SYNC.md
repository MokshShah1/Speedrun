# Speedrun sync (Phase 7)

Speedrun has to sync two kinds of data between devices (phone ↔ desktop):

| Data                                              | What carries it                    | Mechanism                                                        |
| ------------------------------------------------- | ---------------------------------- | ---------------------------------------------------------------- |
| Cards, notes, revlog (so **R**/FSRS memory state) | Anki's standard collection objects | **Anki's built-in self-hosted sync server** (unchanged upstream) |
| Transfer reviews (so **T**/the gap **G**)         | Speedrun's `transfer_review` table | **append-only log sync** added in this fork                      |

The first is free: FSRS state lives in standard Anki tables, so it rides Anki's
existing sync. The engineering is the second, because the Speedrun tables are
not part of Anki's synced schema.

## Self-hosted server (standard data)

Anki ships a sync server in the backend. Run it against the fork:

```bash
set SYNC_USER1=user:pass        # Windows; export on macOS/Linux
set SYNC_BASE=C:\path\to\server-data
python -m anki.syncserver       # serves on 127.0.0.1:8080 by default
```

Point desktop and phone at `http://<host>:8080/` as a custom sync server. Cards,
notes and review history (and therefore recall **R**) then sync two-way and
offline-then-sync as in stock Anki.

## Transfer-log sync (the new part)

The insight: a concept's learned ability `theta` is **derived**, not primary.
It is a pure replay of that concept's transfer reviews. So we never sync the
derived state — we sync the **append-only review log** and recompute.

- **Identity:** every review carries a globally-unique `guid` (Anki's base91
  random id). The device-local integer `id` is _not_ synced; imported reviews
  get fresh local ids. Two devices can both mint `id = 1` without colliding.
- **Merge = union on `guid`.** Importing a peer's log inserts only the guids you
  do not already have. This is why **10 reviews here + 10 there = 20 after sync,
  and still 20 if you sync again** — the merge is idempotent.
- **Replay = the conflict rule.** After a merge, each affected concept is
  recomputed by replaying its reviews in the canonical `(ts, guid)` order from
  the neutral prior. Both devices hold the same union and sort it identically,
  so they converge to exactly the same `theta` even though Elo updates are
  order-dependent. There is no conflict resolution because there are no
  conflicts — only a deterministic replay of a shared, ordered, append-only log.
- **No incremental drift.** The live record path _also_ derives `theta` by
  replaying the log (not a one-step update), so a device shows the same score
  before and after its first sync.

### RPCs (`proto/anki/speedrun.proto`)

- `ExportTransferLog() -> TransferLog` — this device's full review log (the
  payload a peer imports).
- `ImportTransferLog(TransferLog) -> {added, total}` — union-merge a peer's log
  and replay affected concepts.

### Proof

- Rust (`rslib/src/speedrun/sync.rs`):
  - `two_devices_merge_to_union_and_converge` — 10 + 10 → 20, identical `theta`,
    re-import adds 0.
  - `replay_is_order_independent_of_arrival` — delivering the log reversed yields
    the same ability (canonical sort).
  - `recompute_matches_incremental_record` — replay equals the live path.
- Python end-to-end through the built backend:
  - `pylib/tests/test_speedrun_sync.py` (pytest, runs in the Anki dev env).
  - `speedrun/verify_sync.py` (standalone; run `python speedrun/verify_sync.py`
    after `tools/ninja pylib`). Observed: both devices converge to the same
    `theta`, totals 10/10 → 20/20, re-import `added=0`.

## Still needs hardware / a real run

- The two-device demo on a **real phone** is Phase 5 (AnkiDroid on the shared
  engine). The merge logic and RPCs are proven headlessly here; wiring the phone
  to call `ImportTransferLog`/`ExportTransferLog` alongside Anki's normal sync is
  the remaining integration.
