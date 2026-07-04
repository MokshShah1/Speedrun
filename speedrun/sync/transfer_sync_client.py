# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Desktop client for the Speedrun transfer-log sync.

Exports this collection's transfer reviews, pushes them to the transfer-sync
server, pulls the merged log back, and imports it. Import is union-by-guid and
the concept ability is re-derived by replaying the log, so running this repeatedly
(or after offline review) converges without losing or double-counting anything.

Pair it with Anki's built-in sync (which carries cards/notes/revlog -> recall R):
run a normal Anki sync for R, then this for T/G.

  python -m speedrun.sync.transfer_sync_client --col <collection.anki2> --server http://127.0.0.1:8090
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "out", "pylib"))

FIELDS = ("guid", "item_id", "concept_id", "correct", "latency_ms", "ts", "difficulty")


def _request(method: str, url: str, body: bytes | None = None, timeout: float = 30.0) -> dict:
    """Minimal HTTP/1.0 client over a raw socket.

    Deliberately avoids urllib/http.client so we never import `ssl` - Anki's
    bundled Windows python aborts on the OpenSSL applink path when `ssl` loads.
    This transport is localhost plain HTTP, so no TLS is needed anyway.
    """
    if not url.startswith("http://"):
        raise ValueError("only http:// is supported (localhost transport)")
    hostport, _, path = url[len("http://"):].partition("/")
    path = "/" + path
    host, _, port_s = hostport.partition(":")
    port = int(port_s or 80)

    lines = [f"{method} {path} HTTP/1.0", f"Host: {host}", "Connection: close"]
    if body is not None:
        lines += ["Content-Type: application/json", f"Content-Length: {len(body)}"]
    head = ("\r\n".join(lines) + "\r\n\r\n").encode()

    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        sock.sendall(head + (body or b""))
        chunks = []
        while True:
            b = sock.recv(65536)
            if not b:
                break
            chunks.append(b)
    finally:
        sock.close()

    raw = b"".join(chunks)
    header, _, payload = raw.partition(b"\r\n\r\n")
    status = int(header.split(b"\r\n", 1)[0].split()[1])
    if status >= 400:
        raise RuntimeError(f"{method} {url} -> HTTP {status}: {payload[:200]!r}")
    return json.loads(payload or b"{}")


def _post(url: str, obj: dict) -> dict:
    return _request("POST", url, json.dumps(obj).encode())


def _get(url: str) -> dict:
    return _request("GET", url)


def _review_to_dict(r) -> dict:
    return {
        "guid": r.guid, "item_id": r.item_id, "concept_id": r.concept_id,
        "correct": bool(r.correct), "latency_ms": r.latency_ms, "ts": r.ts,
        "difficulty": r.difficulty,
    }


def sync(col_path: str, server: str) -> dict:
    from anki.collection import Collection
    import anki.speedrun_pb2 as pb

    server = server.rstrip("/")
    col = Collection(col_path)
    try:
        local = list(col._backend.export_transfer_log())
        before = len(local)

        # Push local -> server.
        pushed = _post(f"{server}/transfer/push", {"reviews": [_review_to_dict(r) for r in local]})

        # Pull merged log <- server and import (idempotent by guid).
        merged = _get(f"{server}/transfer/pull").get("reviews", [])
        protos = [
            pb.TransferReviewProto(
                guid=r["guid"], item_id=r["item_id"], concept_id=r["concept_id"],
                correct=bool(r["correct"]), latency_ms=r["latency_ms"], ts=r["ts"],
                difficulty=r.get("difficulty", 0.0),
            )
            for r in merged
        ]
        added = col._backend.import_transfer_log(reviews=protos).added
        after = len(list(col._backend.export_transfer_log()))
        return {
            "local_before": before, "pushed_new_to_server": pushed.get("added"),
            "server_total": pushed.get("total"), "imported_new_locally": added,
            "local_after": after,
        }
    finally:
        col.close(downgrade=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sync the Speedrun transfer log via the transfer-sync server.")
    ap.add_argument("--col", required=True, help="path to .anki2 collection")
    ap.add_argument("--server", default="http://127.0.0.1:8090")
    args = ap.parse_args(argv)

    stats = sync(args.col, args.server)
    print("transfer-log sync:")
    for k, v in stats.items():
        print(f"  {k:24s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
