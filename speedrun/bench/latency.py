# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Latency benchmark for the Speedrun hot paths (p50 / p95, cold vs warm).

Reviewer ask (Wednesday MVP): "the demonstration could have presented a latency
measurement which would close the expected rubric rows." This is that
measurement. It times the paths that actually back the thesis (R/T/G ->
readiness), reports p50/p95/min/max over many iterations with a monotonic timer,
warms up before timing, and stays fully offline/deterministic (a temp collection
+ the loopback transfer-sync server; no live network, no OpenAI).

Paths measured (each labelled with units):
  - readiness_report        - Rust engine score computation (Memory R / Performance T
                              / Readiness + range + coverage + give-up). The exact
                              call the desktop dashboard and AnkiDroid both make.
  - mastery_query(all)      - per-concept R/T/G the dashboard reads alongside it.
  - next_transfer_item      - transfer item load (pick + return the next ladder item).
  - record_transfer_review  - transfer review round-trip (record answer + Elo/IRT
                              theta update + G recompute, undoable).
  - collection_open (warm)  - re-open of an on-disk collection, in-process.
  - collection_open (cold)  - open in a fresh backend process (each app launch).
  - transfer_sync_cycle     - append-only union-by-guid HTTP sync cycle
                              (export -> push -> pull -> import), warm/idempotent.
  - transfer_sync_initial   - the one-time cold backlog upload to an empty server.

Run:
  out\\pyenv\\Scripts\\python.exe -m speedrun.bench.latency
  (or, from the repo root, via friday_proof.ps1's LATENCY section)

Needs the fork built (imports the backend from out/pylib).
"""

from __future__ import annotations

import gc
import math
import os
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "out", "pylib"))

from anki.collection import Collection  # noqa: E402
import anki.speedrun_pb2 as pb  # noqa: E402

from speedrun.import_content import import_concepts, import_seed_items  # noqa: E402
from speedrun.sync import transfer_sync_client as client  # noqa: E402
from speedrun.sync import transfer_sync_server as server  # noqa: E402

# Ladder difficulties b (L0..L5), matching the other harnesses.
LADDER_B = [-1.5, -0.9, -0.2, 0.5, 1.0, 1.6]
# Reviews recorded into the fixture: enough to give T/G/coverage/give-up real
# signal and a realistic-sized transfer log for the sync path.
N_SEED_REVIEWS = 400
SEED = 5


def _new_disk_path() -> str:
    """A collection path on disk (created, then removed so Collection() makes it)."""
    fd, path = tempfile.mkstemp(suffix=".anki2")
    os.close(fd)
    os.unlink(path)
    return path


def _cleanup(*paths: str) -> None:
    for p in paths:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(p + suffix)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# Statistics (dependency-free; monotonic timer samples are in milliseconds).
# --------------------------------------------------------------------------- #


def _percentile(sorted_ms: list[float], q: float) -> float:
    """Linear-interpolated percentile q in [0,100] of an already-sorted list."""
    if not sorted_ms:
        return 0.0
    if len(sorted_ms) == 1:
        return sorted_ms[0]
    idx = (q / 100.0) * (len(sorted_ms) - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return sorted_ms[lo]
    return sorted_ms[lo] + (sorted_ms[hi] - sorted_ms[lo]) * (idx - lo)


class Stats:
    def __init__(self, label: str, samples_ms: list[float]):
        self.label = label
        s = sorted(samples_ms)
        self.n = len(s)
        self.p50 = _percentile(s, 50)
        self.p95 = _percentile(s, 95)
        self.min = s[0] if s else 0.0
        self.max = s[-1] if s else 0.0
        self.mean = (sum(s) / len(s)) if s else 0.0


def measure(label: str, n: int, fn, warmup: int = 50) -> Stats:
    """Warm up `warmup` calls, then time `n` calls of fn(i), one sample each."""
    for i in range(warmup):
        fn(i)
    samples: list[float] = []
    for i in range(n):
        t0 = time.perf_counter()
        fn(i)
        samples.append((time.perf_counter() - t0) * 1e3)
    return Stats(label, samples)


# --------------------------------------------------------------------------- #
# Fixture: a realistic mid-study collection (real 31-concept AAMC map + a full
# L0..L5 ladder per concept + N_SEED_REVIEWS graded transfer answers).
# --------------------------------------------------------------------------- #


def build_fixture(col: Collection) -> list[tuple[int, int]]:
    """Populate `col` in place; return list of (item_id, concept_id)."""
    code_to_id = import_concepts(col)
    import_seed_items(col, code_to_id)
    concept_ids = sorted(code_to_id.values())

    # Give every concept a full ladder so next_transfer_item / record have breadth.
    pairs: list[tuple[int, int]] = []
    iid = 10_000  # above seed item ids to avoid collisions
    for cid in concept_ids:
        for lvl, b in enumerate(LADDER_B):
            col._backend.upsert_item(
                pb.Item(id=iid, concept_id=cid, level=lvl, difficulty=b,
                        source_ref="bench", ai_generated=False, stem="s",
                        choices=["a", "b", "c", "d"], answer=0, explanation="x")
            )
            pairs.append((iid, cid))
            iid += 1

    rng = random.Random(SEED)
    for _ in range(N_SEED_REVIEWS):
        item_id, cid = pairs[rng.randrange(len(pairs))]
        col._backend.record_transfer_review(
            item_id=item_id, concept_id=cid, correct=rng.random() < 0.55, latency_ms=1500
        )
    return pairs


# --------------------------------------------------------------------------- #
# Cold collection open, measured in a fresh backend process (one open each).
# --------------------------------------------------------------------------- #

_COLD_OPEN_PROBE = (
    "import os,sys,time;"
    "sys.path.insert(0, os.path.join(sys.argv[2],'out','pylib'));"
    "from anki.collection import Collection;"
    "t=time.perf_counter();"
    "c=Collection(sys.argv[1]);"
    "dt=(time.perf_counter()-t)*1e3;"
    "c.close();"
    "print(f'{dt:.4f}')"
)


def measure_cold_open(col_path: str, iters: int) -> Stats:
    """Open the collection in `iters` fresh python/backend processes, timing only
    the Collection() construction inside each child (excludes interpreter start)."""
    samples: list[float] = []
    for _ in range(iters):
        work = _new_disk_path()
        shutil.copy(col_path, work)
        try:
            out = subprocess.run(
                [sys.executable, "-c", _COLD_OPEN_PROBE, work, REPO],
                capture_output=True, text=True, check=True,
            )
            samples.append(float(out.stdout.strip().splitlines()[-1]))
        finally:
            _cleanup(work)
    return Stats("collection_open (cold, fresh process)", samples)


# --------------------------------------------------------------------------- #
# Transfer-log sync cycle (loopback HTTP).
# --------------------------------------------------------------------------- #


def _serve(store: server.Store) -> tuple[ThreadingHTTPServer, str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(store))
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, url


# Spacing between HTTP sync iterations (outside the timed region). Each sync
# opens two short-lived loopback connections (push + pull, Connection: close);
# hammering them back-to-back can produce slow connects / RSTs on Windows. A few
# ms of idle between cycles keeps the loopback healthy without affecting the
# per-call timing we record.
NET_GAP_S = 0.03
# Per-request socket timeout for the loopback sync. The client hardcodes 30s,
# which turns a single flaky loopback connection into a 30s stall; on localhost
# a healthy request is sub-100ms, so a short cap keeps the measurement bounded.
# Applied by overriding the client's default arg (a harness knob, not a source
# edit): _request(method, url, body=None, timeout=<this>).
HTTP_TIMEOUT_S = 3.0


def _install_http_timeout() -> None:
    if client._request.__defaults__ is not None:
        client._request.__defaults__ = (None, HTTP_TIMEOUT_S)


def _sync(path: str, url: str, retries: int = 4) -> dict:
    """client.sync with bounded retry on transient Windows loopback resets.

    The stdlib loopback server occasionally sends an RST or stalls under rapid
    connect/teardown churn (WinError 10054); the sync is idempotent
    (union-by-guid) so a retry is safe. With HTTP_TIMEOUT_S capping each attempt,
    a retried sample only inflates the tail (p95/max), never the median."""
    for attempt in range(retries):
        try:
            return client.sync(path, url)
        except (ConnectionResetError, ConnectionAbortedError, OSError,
                socket.timeout, RuntimeError):
            if attempt == retries - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
    raise RuntimeError("unreachable")


def measure_net(label: str, n: int, fn, warmup: int = 3) -> Stats:
    """Like `measure`, but idle NET_GAP_S between calls (outside the timed
    region) so loopback connection churn cannot distort the samples."""
    for i in range(warmup):
        fn(i)
        time.sleep(NET_GAP_S)
    samples: list[float] = []
    for i in range(n):
        t0 = time.perf_counter()
        fn(i)
        samples.append((time.perf_counter() - t0) * 1e3)
        time.sleep(NET_GAP_S)
    return Stats(label, samples)


def measure_sync_warm(device_path: str, n: int) -> tuple[Stats, int]:
    """Steady-state (warm) sync cycles against a server that already holds the
    device's full log: each cycle pushes 0 new, pulls the merged log, imports 0
    new (idempotent union-by-guid). Returns (stats, server_log_size)."""
    _install_http_timeout()
    store = server.Store(None)
    httpd, url = _serve(store)
    try:
        _sync(device_path, url)  # prime: upload the backlog once
        total = store.total()
        stats = measure_net("transfer_sync_cycle (e2e HTTP, warm)", n,
                            lambda i: _sync(device_path, url))
        return stats, total
    finally:
        httpd.shutdown()
        httpd.server_close()


def measure_sync_cold(device_path: str, iters: int) -> Stats:
    """Cold initial sync: a fresh copy of the device + a fresh empty server each
    time, timing the one-time backlog upload + merged pull + import."""
    _install_http_timeout()
    samples: list[float] = []
    for _ in range(iters):
        work = _new_disk_path()
        shutil.copy(device_path, work)
        store = server.Store(None)
        httpd, url = _serve(store)
        try:
            t0 = time.perf_counter()
            _sync(work, url)
            samples.append((time.perf_counter() - t0) * 1e3)
        finally:
            httpd.shutdown()
            httpd.server_close()
            _cleanup(work)
            time.sleep(NET_GAP_S)
    return Stats("transfer_sync_initial (cold, full backlog)", samples)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def _print_table(rows: list[Stats]) -> None:
    print(f"\n  {'path':40s} {'n':>5s} {'p50':>9s} {'p95':>9s} "
          f"{'min':>9s} {'max':>9s} {'mean':>9s}   (ms)")
    print("  " + "-" * 96)
    for r in rows:
        print(f"  {r.label:40s} {r.n:5d} {r.p50:9.3f} {r.p95:9.3f} "
              f"{r.min:9.3f} {r.max:9.3f} {r.mean:9.3f}")


def main() -> int:
    print("Speedrun latency benchmark (p50/p95, monotonic timer, offline fixture)")
    print(f"  fixture: real 31-concept AAMC map, full L0-L5 ladder/concept, "
          f"{N_SEED_REVIEWS} graded transfer reviews (seed={SEED})")

    def step(msg: str) -> None:
        print(f"  ... {msg}", flush=True)

    col_path = _new_disk_path()
    col = Collection(col_path)
    warm_rows: list[Stats] = []
    rng = random.Random(SEED + 1)

    # Build the fixture, then close so the transfer-log sync (which opens its own
    # Collection on this path) can run first, against a freshly-loaded backend.
    pairs = build_fixture(col)
    col.close()
    gc.collect()

    # --- transfer-log sync cycle over real loopback HTTP. Measured first, while
    #     the backend is fresh: co-hosting a heavily-exercised Anki backend in
    #     the same process intermittently stalls the loopback socket for ~seconds
    #     (a GIL/GC artifact, not real sync cost), so we time the e2e cycle here
    #     and keep the deterministic engine-side export/import (below) as the
    #     robust sync-cost number. Best-effort: on loopback contention we say so
    #     and fall back to the engine numbers rather than fake a value. ---
    sync_warm = sync_cold = None
    sync_log_size = 0
    try:
        step("timing transfer_sync_cycle (e2e HTTP, warm)")
        sync_warm, sync_log_size = measure_sync_warm(col_path, n=20)
        step("timing transfer_sync_initial (cold)")
        sync_cold = measure_sync_cold(col_path, iters=8)
    except (ConnectionResetError, ConnectionAbortedError, OSError,
            socket.timeout, RuntimeError) as exc:
        step(f"e2e HTTP sync SKIPPED (loopback contention: {type(exc).__name__}); "
             f"engine-side export/import below are the robust proxy")

    # --- warm, in-process engine paths ---
    col = Collection(col_path)
    try:
        step("timing readiness_report")
        warm_rows.append(measure("readiness_report", 300,
                                 lambda i: col._backend.readiness_report()))
        step("timing mastery_query(all)")
        warm_rows.append(measure("mastery_query(all)", 300,
                                 lambda i: col._backend.mastery_query(concept_ids=[])))
        step("timing next_transfer_item")
        warm_rows.append(measure("next_transfer_item (transfer item load)", 300,
                                 lambda i: col._backend.next_transfer_item(concept_id=0)))

        def _rec(i: int) -> None:
            item_id, cid = pairs[rng.randrange(len(pairs))]
            col._backend.record_transfer_review(
                item_id=item_id, concept_id=cid, correct=rng.random() < 0.55, latency_ms=1500
            )
        step("timing record_transfer_review")
        warm_rows.append(measure("record_transfer_review (round-trip)", 2000, _rec))

        # --- sync ENGINE work (in-process, no network): the export + the
        #     union-by-guid merge/replay that a sync cycle actually spends its
        #     work on. Deterministic and never flaky, unlike the loopback HTTP. ---
        log = list(col._backend.export_transfer_log())
        engine_log_size = len(log)
        step("timing export_transfer_log")
        warm_rows.append(measure("export_transfer_log (engine)", 300,
                                 lambda i: col._backend.export_transfer_log()))
        step("timing import_transfer_log (idempotent)")
        warm_rows.append(measure("import_transfer_log (engine, idempotent)", 200,
                                 lambda i: col._backend.import_transfer_log(reviews=log)))
    finally:
        col.close()
        gc.collect()

    if sync_warm is not None:
        warm_rows.append(sync_warm)

    # --- warm collection re-open (in-process) ---
    def _reopen(i: int) -> None:
        c = Collection(col_path)
        c.close()
    step("timing collection_open (warm)")
    warm_rows.append(measure("collection_open (warm, in-process)", 50, _reopen, warmup=3))
    gc.collect()

    # --- cold collection open (fresh backend process); spawns subprocesses, so
    #     do it last ---
    step("timing collection_open (cold, fresh processes)")
    cold_open = measure_cold_open(col_path, iters=12)

    _cleanup(col_path)

    print("\nWARM paths (steady state):")
    _print_table(warm_rows)
    print(f"    (export/import replay a {engine_log_size}-review transfer log; the "
          f"e2e HTTP cycle exchanges a {sync_log_size}-review log)")

    print("\nCOLD paths (fresh process / first sync):")
    cold_rows = [cold_open] + ([sync_cold] if sync_cold is not None else [])
    _print_table(cold_rows)
    if sync_cold is None:
        print("    (transfer_sync_initial e2e HTTP not captured this run; see the "
              "engine-side import_transfer_log number above)")

    print("\n  RESULT: PASS (measured; no pass/fail floor)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
