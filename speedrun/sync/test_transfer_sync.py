# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Two-device end-to-end test of the transfer-log sync, over real HTTP.

Spins up the transfer-sync server on an ephemeral port and drives two separate
on-disk collections (device A, device B) through the desktop client against it.
Proves the Friday sync requirements without a phone:

- two-way propagation (A's reviews reach B and B's reach A),
- convergence (both devices end with the same log and the same per-concept T),
- no lost / double-counted reviews (union-by-guid),
- offline-then-sync (review offline, then a later sync propagates it once),
- idempotency (re-syncing imports nothing new).

Run: python -m speedrun.sync.test_transfer_sync   (needs out/pylib built)
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "out", "pylib"))

from speedrun.sync import transfer_sync_client as client  # noqa: E402
from speedrun.sync import transfer_sync_server as server  # noqa: E402

LADDER_B = [-1.5, -0.9, -0.2, 0.5, 1.0, 1.6]
N_CONCEPTS = 4


def _new_col_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".anki2")
    os.close(fd)
    os.unlink(path)
    return path


def _seed(path: str) -> None:
    from anki.collection import Collection
    import anki.speedrun_pb2 as pb
    col = Collection(path)
    iid = 1
    for cid in range(1, N_CONCEPTS + 1):
        col._backend.upsert_concept(pb.Concept(id=cid, outline_id=f"C{cid}", section="bb", title="t", exam_weight=1.0))
        for lvl, b in enumerate(LADDER_B):
            col._backend.upsert_item(pb.Item(id=iid, concept_id=cid, level=lvl, difficulty=b,
                                             source_ref="s", ai_generated=False, stem="s",
                                             choices=["a", "b"], answer=0, explanation="x"))
            iid += 1
    col.close(downgrade=False)


def _record(path: str, n: int, start: int, correct) -> None:
    from anki.collection import Collection
    col = Collection(path)
    for k in range(n):
        i = start + k
        cid = (i % N_CONCEPTS) + 1
        item_id = (cid - 1) * len(LADDER_B) + (i % len(LADDER_B)) + 1
        col._backend.record_transfer_review(item_id=item_id, concept_id=cid, correct=correct(i), latency_ms=900)
    col.close(downgrade=False)


def _thetas_and_total(path: str):
    from anki.collection import Collection
    col = Collection(path)
    try:
        m = col._backend.mastery_query(concept_ids=[])
        thetas = {e.concept_id: round(e.theta, 6) for e in m.entries}
        total = len(list(col._backend.export_transfer_log()))
        return thetas, total
    finally:
        col.close(downgrade=False)


def _cleanup(*paths: str) -> None:
    for p in paths:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(p + suffix)
            except OSError:
                pass


def main() -> int:
    store = server.Store(None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(store))
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    pathA, pathB = _new_col_path(), _new_col_path()
    try:
        _seed(pathA)
        _seed(pathB)

        # A reviews 5, syncs up.
        _record(pathA, 5, 0, lambda i: i % 2 == 0)
        sA1 = client.sync(pathA, url)
        assert sA1["pushed_new_to_server"] == 5 and sA1["server_total"] == 5, sA1

        # B reviews 4 (offline until now), syncs: pushes its own, pulls A's.
        _record(pathB, 4, 100, lambda i: i % 3 == 0)
        sB1 = client.sync(pathB, url)
        assert sB1["pushed_new_to_server"] == 4 and sB1["server_total"] == 9 and sB1["local_after"] == 9, sB1

        # A syncs again: pulls B's 4, converges.
        sA2 = client.sync(pathA, url)
        assert sA2["imported_new_locally"] == 4 and sA2["local_after"] == 9, sA2

        # Convergence: identical log size and per-concept transfer T.
        tA, totA = _thetas_and_total(pathA)
        tB, totB = _thetas_and_total(pathB)
        assert totA == totB == 9, (totA, totB)
        assert tA == tB, (tA, tB)

        # Idempotency: re-sync A imports nothing new, no double count.
        sA3 = client.sync(pathA, url)
        assert sA3["imported_new_locally"] == 0 and sA3["local_after"] == 9, sA3

        # Offline-then-sync: A reviews 2 offline, then a later sync propagates them once.
        _record(pathA, 2, 200, lambda i: True)
        sA4 = client.sync(pathA, url)
        assert sA4["pushed_new_to_server"] == 2 and sA4["server_total"] == 11, sA4
        sB2 = client.sync(pathB, url)
        assert sB2["imported_new_locally"] == 2 and sB2["local_after"] == 11, sB2

        # Final convergence after the offline round.
        tA, totA = _thetas_and_total(pathA)
        tB, totB = _thetas_and_total(pathB)
        assert totA == totB == 11 and tA == tB, (totA, totB, tA, tB)

        print(f"  A/B converged: {totA} reviews each, identical per-concept T across {len(tA)} concepts")
        print("  RESULT: PASS")
        return 0
    except AssertionError as e:
        print("  FAIL:", e)
        return 1
    finally:
        httpd.shutdown()
        _cleanup(pathA, pathB)


if __name__ == "__main__":
    raise SystemExit(main())
