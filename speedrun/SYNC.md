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

### Transport (the wire between devices)

The RPCs move a log in/out of one backend; a tiny transport moves it between
devices. It reuses the same union-by-guid, replay model, so it inherits the
idempotency and offline-safety.

- **Server** (`speedrun/sync/transfer_sync_server.py`): stdlib HTTP, holds one
  append-only union-by-guid log. `POST /transfer/push` merges a device's log;
  `GET /transfer/pull` returns the merged log; `GET /health`. Persists to JSON.
- **Desktop client** (`speedrun/sync/transfer_sync_client.py`): opens the
  collection, `ExportTransferLog` → push, pull → `ImportTransferLog`. Uses raw
  sockets (no `urllib`/`ssl`) because Anki's bundled Windows python aborts on the
  OpenSSL applink path when `ssl` loads; the transport is localhost cleartext.
- **Phone** (`Anki-Android/.../speedrun/TransferLogSync.kt`): the same
  export→push→pull→import, called from `SyncWorker` at the end of every normal
  sync so the transfer log rides along with Anki's sync. `HttpURLConnection` +
  `org.json` only (no new dependency). `10.0.2.2:8090` reaches the desktop from
  the emulator. Best-effort: never throws, so it can't break Anki's own sync.

### Proof

- Rust (`rslib/src/speedrun/sync.rs`):
  - `two_devices_merge_to_union_and_converge` — 10 + 10 → 20, identical `theta`,
    re-import adds 0.
  - `replay_is_order_independent_of_arrival` — delivering the log reversed yields
    the same ability (canonical sort).
  - `recompute_matches_incremental_record` — replay equals the live path.
  - `converges_when_item_missing_locally` — difficulty travels in the record, so a
    device that lacks the item still converges.
- Python end-to-end through the built backend:
  - `pylib/tests/test_speedrun_sync.py` (pytest, runs in the Anki dev env).
  - `speedrun/sync/test_transfer_sync.py` — **two devices over real HTTP**: spins
    up the transfer-sync server, drives two on-disk collections through the
    desktop client, and asserts two-way propagation, convergence (identical T),
    idempotency, and offline-then-sync. Observed: both converge to 11 reviews with
    identical per-concept T.
  - `speedrun/verify_sync.py` (standalone RPC-level check).

### On-device scores

The shared Rust engine computes the three scores on the phone.
`TransferLogSync.logReadiness()` logs `ReadinessReport` (Memory R / Performance T
/ Readiness + range + give-up count) to logcat after each sync — the phone-side
proof for "three scores + give-up rule on the phone".

See `FRIDAY_SUBMISSION.md` for the end-to-end run + recording playbook.
