# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Transfer-log sync endpoint (the channel Anki's own sync does NOT carry).

Anki's built-in self-hosted sync server moves cards/notes/revlog (so recall R),
but the Speedrun `transfer_review` table is not part of Anki's synced schema.
This tiny stdlib server carries *only* that log between devices.

Model: an append-only log, merged **union-by-guid**. Because each transfer review
has a globally-unique guid and the concept's ability is *derived* by replaying the
log in canonical order, merging is idempotent (re-pushing changes nothing) and
order-independent — so two-way sync, offline-then-sync, and repeated syncs can
never lose or double-count a review.

Endpoints:
  GET  /health              -> {"ok": true, "total": N}
  GET  /transfer/pull       -> {"reviews": [ {guid,item_id,concept_id,correct,latency_ms,ts}, ... ]}
  POST /transfer/push       body {"reviews": [...]} -> {"added": k, "total": N}

Run:
  python -m speedrun.sync.transfer_sync_server --port 8090 --data server-xfer.json
"""

from __future__ import annotations

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FIELDS = ("guid", "item_id", "concept_id", "correct", "latency_ms", "ts", "difficulty")


class Store:
    """Thread-safe append-only union-by-guid log with JSON persistence."""

    def __init__(self, path: str | None):
        self.path = path
        self._lock = threading.Lock()
        self._by_guid: dict[str, dict] = {}
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for r in json.load(f).get("reviews", []):
                    self._by_guid[r["guid"]] = r

    def merge(self, reviews: list[dict]) -> int:
        added = 0
        with self._lock:
            for r in reviews:
                guid = r.get("guid")
                if not guid or guid in self._by_guid:
                    continue
                self._by_guid[guid] = {k: r.get(k) for k in FIELDS}
                added += 1
            if added and self.path:
                self._flush()
        return added

    def all(self) -> list[dict]:
        with self._lock:
            # Canonical order (ts, guid) so every device replays identically.
            return sorted(self._by_guid.values(), key=lambda r: (r["ts"], r["guid"]))

    def total(self) -> int:
        with self._lock:
            return len(self._by_guid)

    def _flush(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"reviews": list(self._by_guid.values())}, f)
        os.replace(tmp, self.path)


def make_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, obj: dict) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                self._send(200, {"ok": True, "total": store.total()})
            elif self.path == "/transfer/pull":
                self._send(200, {"reviews": store.all()})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path != "/transfer/push":
                self._send(404, {"error": "not found"})
                return
            try:
                n = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(n) or b"{}")
                reviews = payload.get("reviews", [])
                added = store.merge(reviews)
                self._send(200, {"added": added, "total": store.total()})
            except (ValueError, KeyError, TypeError) as exc:
                self._send(400, {"error": str(exc)})

        def log_message(self, *_args):  # keep the console quiet
            pass

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Speedrun transfer-log sync server.")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--data", default=None, help="JSON file to persist the merged log")
    args = ap.parse_args(argv)

    store = Store(args.data)
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(store))
    print(f"transfer-sync server on http://{args.host}:{args.port}  (total={store.total()})")
    print("  GET /health   GET /transfer/pull   POST /transfer/push")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
