# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Hard-kill crash-recovery test.

The soak test proves graceful restarts; this proves an *ungraceful* one. A child
process opens the collection, commits K transfer reviews, prints a READY marker,
then keeps writing in a tight loop. The parent hard-kills it (TerminateProcess /
SIGKILL - no cleanup, no flush), reopens the collection, and asserts:

- the collection opens (no corruption / no stuck lock),
- every committed review survived (count >= K) - SQLite/WAL drops only the
  single in-flight transaction,
- invariants hold (sum of per-concept obs == total reviews; readiness in band),
- the collection is still writable afterwards (recovery is complete).

Run:  python speedrun/eval/crash_kill.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "out", "pylib"))

N_CONCEPTS = 5
LADDER_B = [-1.5, -0.9, -0.2, 0.5, 1.0, 1.6]
COMMIT_BEFORE_READY = 40


def _open(path):
    from anki.collection import Collection
    return Collection(path)


def _items(cid: int) -> list[int]:
    base = (cid - 1) * len(LADDER_B)
    return [base + k + 1 for k in range(len(LADDER_B))]


def child(path: str) -> int:
    """Commit COMMIT_BEFORE_READY reviews, announce READY, then write forever."""
    import anki.speedrun_pb2 as pb  # noqa: F401  (kept for parity / future use)

    col = _open(path)
    n = 0
    while n < COMMIT_BEFORE_READY:
        cid = (n % N_CONCEPTS) + 1
        item_id = _items(cid)[n % len(LADDER_B)]
        col._backend.record_transfer_review(item_id=item_id, concept_id=cid, correct=bool(n % 2), latency_ms=900)
        n += 1
    # Force a WAL checkpoint so the committed reviews are durable on disk.
    try:
        col._backend.checkpoint()  # type: ignore[attr-defined]
    except Exception:
        pass
    print(f"READY committed={n}", flush=True)
    # Keep writing so a transaction is likely in flight when we are killed.
    while True:
        cid = (n % N_CONCEPTS) + 1
        item_id = _items(cid)[n % len(LADDER_B)]
        col._backend.record_transfer_review(item_id=item_id, concept_id=cid, correct=bool(n % 2), latency_ms=900)
        n += 1
    return 0  # unreachable


def seed(path: str) -> None:
    import anki.speedrun_pb2 as pb
    col = _open(path)
    iid = 1
    for cid in range(1, N_CONCEPTS + 1):
        col._backend.upsert_concept(
            pb.Concept(id=cid, outline_id=f"C{cid}", section="bb", title="t", exam_weight=1.0)
        )
        for lvl, b in enumerate(LADDER_B):
            col._backend.upsert_item(
                pb.Item(id=iid, concept_id=cid, level=lvl, difficulty=b, source_ref="s",
                        ai_generated=False, stem="s", choices=["a", "b"], answer=0, explanation="x")
            )
            iid += 1
    col.close(downgrade=False)


def total_reviews(col) -> int:
    return len(list(col._backend.export_transfer_log()))


def parent() -> int:
    fd, path = tempfile.mkstemp(suffix=".anki2")
    os.close(fd)
    os.unlink(path)
    try:
        seed(path)

        # Spawn the writer child.
        proc = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--child", path],
            stdout=subprocess.PIPE, text=True,
        )
        ready = False
        assert proc.stdout is not None
        for line in proc.stdout:
            if line.startswith("READY"):
                ready = True
                break
        if not ready:
            proc.kill()
            print("  child never reached READY"); return 1

        # Let it get mid-write, then hard-kill (no cleanup).
        time.sleep(0.3)
        proc.kill()
        proc.wait(timeout=10)
        print(f"  child hard-killed (exit {proc.returncode}); reopening...")
        time.sleep(0.3)

        # Reopen and verify recovery.
        col = _open(path)
        total = total_reviews(col)
        assert total >= COMMIT_BEFORE_READY, f"lost data: {total} < {COMMIT_BEFORE_READY}"
        m = col._backend.mastery_query(concept_ids=[])
        obs_sum = sum(e.n_transfer_obs for e in m.entries)
        assert obs_sum == total, f"obs sum {obs_sum} != total {total}"
        r = col._backend.readiness_report()
        assert 472 <= r.readiness <= 528

        # Still writable after recovery?
        col._backend.record_transfer_review(item_id=1, concept_id=1, correct=True, latency_ms=900)
        assert total_reviews(col) == total + 1
        col.close(downgrade=False)

        print(f"  recovered: {total} committed reviews durable, invariants hold, writable after crash")
        print("  RESULT: PASS")
        return 0
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(path + suffix)
            except OSError:
                pass


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--child":
        return child(sys.argv[2])
    return parent()


if __name__ == "__main__":
    sys.exit(main())
