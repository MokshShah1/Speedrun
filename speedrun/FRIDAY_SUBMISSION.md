# Friday submission — AI checked + phone syncs

Friday asks for two things (PRD §12):

1. **AI added & checked** — ladder items generated from a named source, a gold-set
   checker, a held-out eval that **beats a baseline**, a leakage check, and the app
   still scores with **AI off**.
2. **Two-way phone↔desktop sync** — review on phone shows on desktop and reverse,
   offline-then-sync, no lost/doubled reviews; **three scores + give-up rule on the
   phone**.

Proof = eval numbers + baseline + a phone→desktop sync recording.

---

## What's built for Friday

| Requirement | Where | Status |
| --- | --- | --- |
| AI generation from a named source | `speedrun/ai/` (glucagon run in `speedrun/data/glucagon_items_openai.json`) | done |
| Gold-set checker + held-out eval + baseline | `speedrun/ai/run_eval.py` (1.000 vs 0.500) | done |
| Leakage check | `speedrun/ai/leakage.py` | done |
| Scores with AI **off** | engine is AI-independent; mock/cache path | done |
| Transfer-log sync engine | `rslib/src/speedrun/sync.rs` (5 Rust tests) | done |
| Transfer-log transport (server) | `speedrun/sync/transfer_sync_server.py` | done |
| Desktop transfer-log client | `speedrun/sync/transfer_sync_client.py` | done |
| Two-device convergence over HTTP | `speedrun/sync/test_transfer_sync.py` | done |
| AnkiDroid transfer-log wiring | `Anki-Android/.../speedrun/TransferLogSync.kt` + `SyncWorker` hook | code done, rebuild APK |
| Three scores on the phone | `TransferLogSync.logReadiness()` → logcat | code done, rebuild APK |
| Standard R sync (cards/revlog) | Anki's built-in self-hosted sync server | run it |

---

## Part A — headless proofs (record this whole run)

```powershell
cd C:\dev\speedrun-anki
.\speedrun\friday_proof.ps1
```

Prints, in order: the commit hash, the AI held-out eval (**accuracy 1.000 vs
baseline 0.500**), the AI pipeline tests, the Rust sync tests
(merge/converge/idempotent/replay), the two-device transfer-log sync over real
HTTP (**A/B converge to the same log + identical T**), and the pylib convergence
test.

**AI-off proof (this is section 3b of the runner):** two *live* OpenAI runs from
two named sources in two different exam sections — **glucagon** (concept 4,
Bio/Biochem) and **acids/bases/buffers** (concept 15, Chem/Phys) — are checked for
provenance (each item traces to concept + ladder level + named source), then —
**with the AI provider off and the AI package never imported** — they're loaded
into the engine, reviewed, and scored. R/T/G and readiness come straight out of
the Rust engine:

```powershell
out\pyenv\Scripts\python.exe -m speedrun.ai.prove_ai_off
# glucagon: 30/30 ai_generated, L0..L5 x5, traced -> AI off: T=29% Readiness 493 PASS
# buffers : 14/14 ai_generated, traced           -> AI off: T=29% Readiness 493 PASS
```

**Breadth / not overfit:** the checker gated the buffers source *harder* than
glucagon — **14/30 accepted** — rejecting for `level_miscalibrated`, `copies_source`,
`answer_leaks_into_stem`, `answer_out_of_range`, and `catchall_choice` on brand-new
content. A mechanical, content-agnostic bar, not one tuned to glucagon.

---

## Part B — live phone↔desktop sync (the recording)

Two channels sync in parallel:

- **Standard data → recall R:** Anki's own self-hosted sync server (cards, notes,
  revlog). Unchanged upstream.
- **Transfer reviews → T / G:** the Speedrun transfer-log server (not part of
  Anki's synced schema, so it rides its own channel). On the phone this fires
  automatically at the end of every normal sync (`SyncWorker` → `TransferLogSync`).

### One-time: rebuild the phone app with the wiring

The Speedrun backend `.aar` and the AnkiDroid APK were already built. After adding
`TransferLogSync.kt` + the `SyncWorker` hook, rebuild + reinstall the debug app:

```powershell
cd C:\dev\ankidroid\Anki-Android
.\gradlew :AnkiDroid:assemblePlayDebug        # or your existing variant
adb install -r AnkiDroid\build\outputs\apk\play\debug\AnkiDroid-play-debug.apk
```

(Cleartext HTTP to the emulator host is already allowed —
`network_security_config.xml` has `cleartextTrafficPermitted="true"`.)

### 1. Start both servers on the desktop

```powershell
# Terminal 1 — standard Anki sync (cards/revlog → R). Bundled python + pylib.
cd C:\dev\speedrun-anki
$env:PYTHONPATH = "out\pylib"
$env:SYNC_USER1 = "speedrun:test"
$env:SYNC_BASE  = "C:\dev\speedrun-anki\out\syncserver-data"
out\pyenv\Scripts\python.exe -m anki.syncserver          # 127.0.0.1:8080

# Terminal 2 — transfer-log server (T/G). Persist so it survives restarts.
cd C:\dev\speedrun-anki
out\pyenv\Scripts\python.exe -m speedrun.sync.transfer_sync_server `
  --port 8090 --data out\transfer-log.json
```

### 2. Point desktop + phone at the standard server

- **Desktop Anki:** Preferences → Syncing → self-hosted sync server →
  `http://127.0.0.1:8080/`. Sync once to upload the MileDown collection.
- **Emulator AnkiDroid:** Settings → Advanced → Custom sync server →
  `http://10.0.2.2:8080/` (10.0.2.2 = the emulator's alias for the host).
  Log in as `speedrun` / `test`, sync down.

### 3. phone → desktop (record)

1. On the phone, review a few cards **and** answer a few transfer items.
2. Tap **Sync** on the phone. logcat shows the transfer-log push + the on-device
   scores (Part C).
3. On the desktop, **Sync**, then run the desktop transfer-log client (desktop
   Anki must be **closed** so the collection isn't locked):

```powershell
out\pyenv\Scripts\python.exe -m speedrun.sync.transfer_sync_client `
  --col "$env:APPDATA\Anki2\User 1\collection.anki2" --server http://127.0.0.1:8090
```

Open the desktop **Speedrun dashboard** → the phone's reviews are reflected in R,
T and G.

### 4. desktop → phone (reverse)

Review on the desktop, sync + run the client, then tap **Sync** on the phone —
the counts appear there too.

### 5. offline-then-sync

Turn the emulator to airplane mode, review, then reconnect and **Sync**. Because
the log is append-only and merged union-by-guid, nothing is lost or double-counted
(the headless proof in Part A demonstrates exactly this).

---

## Part C — three scores + give-up on the phone (on-device)

The shared Rust engine computes the scores **on the phone**. After each sync,
`TransferLogSync.logReadiness()` logs them. Show it live:

```powershell
adb logcat -s AnkiDroid:* | findstr /C:"Speedrun scores"
```

Expected line:

```
Speedrun scores (on device): Memory(R)=0.72 Performance(T)=0.55 Readiness=508 [498..518] coverage=0.41 giveUpConcepts=2
```

(Optional, more rigorous: the host-JVM `SpeedrunBackendTest.kt` template asserts
the same RPCs on the backend `.aar`.)

---

## Clips to record

1. **AI proof** — `friday_proof.ps1` top to bottom (eval 1.000 vs 0.500, all tests
   green), then the AI-off regeneration.
2. **phone → desktop** — review on the emulator, sync, dashboard on desktop updates.
3. **desktop → phone** — reverse direction.
4. **offline-then-sync** — airplane mode, review, reconnect, sync, no double count.
5. **on-device scores** — the logcat `Speedrun scores` line on the phone.

## Part D — distributable installer + clean install (reviewer ask)

The Wednesday reviewer asked for a **clean-machine installer run**. We now build a
real, self-contained **Windows MSI** from this fork and prove it installs/runs off
the dev source tree. Full detail + reproduction steps in **`speedrun/INSTALLER.md`**.

- **Artifact:** `out\installer\dist\anki-26.5-win-x64.msi` (**≈607 MB**, Briefcase/WiX
  bundle with embedded Python 3.13 + Qt6/WebEngine and the forked `anki`/`aqt`), built
  from wheels `out\wheels\anki-26.5-cp310-abi3-win_amd64.whl` (12.05 MB) +
  `aqt-26.5-py3-none-any.whl` (4.44 MB).
- **Build:** `tools\ninja wheels`, then two `qt\tools\build_installer.py --version 26.5
  {build,package}` calls (corp-proxy TLS handled via `UV_NATIVE_TLS` + a
  Windows-cert-store PEM; no verification disabled).
- **Tier reached: B.** The wheels install into a brand-new isolated `venv`
  (empty `PYTHONPATH`, not `out\pyenv`); from there the forked **Rust engine RPC**
  (`readiness_report`) runs, the Speedrun UI modules load from `site-packages`, and
  the GUI boots (**process→profile-ready ≈2.3 s**, then closed). The MSI's own
  self-contained `Anki.exe` payload also boots with **zero external Python**.
- **Not done:** a true **Tier A** run on a separate clean Windows VM (none available
  here — not fabricated). `INSTALLER.md §4` lists the exact steps a grader runs on a
  fresh box.

---

## Part E — latency measurement (reviewer ask)

The Wednesday reviewer also asked for a **latency measurement**. `speedrun/bench/latency.py`
times the hot paths that back the thesis (p50/p95, monotonic timer, warmed up,
fully offline over a temp collection seeded from the real 31-concept AAMC map).
Full table + method in **`speedrun/LATENCY.md`**; also runs as section 7 of
`friday_proof.ps1`.

```powershell
out\pyenv\Scripts\python.exe -m speedrun.bench.latency
```

Verified on this machine (i7-1355U, Win11) — interactive engine paths are low
single-digit ms:

| path | p50 | p95 |
| --- | ---: | ---: |
| `readiness_report` (the dashboard + AnkiDroid score RPC) | **2.4 ms** | **4.1 ms** |
| `record_transfer_review` (record + Elo/IRT θ/G update, undoable) | **1.7 ms** | **2.7 ms** |
| `next_transfer_item` (transfer item load) | 2.3 ms | 3.9 ms |
| engine sync export + union-by-guid merge/replay (2,450-review log) | 11 / 22 ms | — |
| full e2e HTTP transfer-log sync cycle (off the interactive path) | 79 ms | 91 ms |
| collection open (cold / warm) | 9 / 12 ms | — |

Takeaway: the engine change adds **no perceptible latency** to the dashboard or
the phone (same RPC); sync cost is transport, not engine, and runs off the
interactive path.

---

## Honest caveats

- The transfer-log rides a **separate lightweight channel** from Anki's sync
  (the `transfer_review` table isn't in Anki's synced schema); both are two-way,
  idempotent, and offline-safe. Standard reviews (R) use Anki's sync unchanged.
- Readiness is a heuristic mapping with a wide range, stated as unvalidated until
  Sunday's calibration against real practice-test data.
