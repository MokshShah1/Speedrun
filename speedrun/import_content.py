# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Load the Speedrun concept map and seed transfer items into a collection.

Usage:
    python speedrun/import_content.py [path/to/collection.anki2]

With no path a throwaway collection is created so the import can be verified in
isolation. Concepts are keyed by their AAMC outline code (e.g. "1D"); each is
assigned a stable numeric id by file order, and seed items are linked back to
their concept by that code.

The script bootstraps sys.path to the built `anki` package in out/pylib, so it
can be run directly after a normal build.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO_ROOT, "speedrun", "data")
sys.path.insert(0, os.path.join(REPO_ROOT, "out", "pylib"))

import anki.speedrun_pb2 as pb  # noqa: E402
from anki.collection import Collection  # noqa: E402


def load_json(name: str) -> dict:
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def import_concepts(col: Collection) -> dict[str, int]:
    """Upsert every concept; return a map from AAMC code -> numeric id."""
    data = load_json("concepts.json")
    section_short = {s["id"]: s["short"] for s in data["sections"]}
    code_to_id: dict[str, int] = {}
    for i, c in enumerate(data["concepts"], start=1):
        code = c["id"]
        code_to_id[code] = i
        col._backend.upsert_concept(
            pb.Concept(
                id=i,
                outline_id=code,
                section=section_short.get(c["section"], c["section"]),
                title=c["title"],
                exam_weight=float(c["exam_weight"]),
            )
        )
    return code_to_id


def import_seed_items(col: Collection, code_to_id: dict[str, int]) -> int:
    data = load_json("seed_items.json")
    count = 0
    for i, item in enumerate(data["items"], start=1):
        concept_code = item["concept_id"]
        if concept_code not in code_to_id:
            print(f"  warning: item {item['id']} references unknown concept "
                  f"{concept_code}, skipping")
            continue
        col._backend.upsert_item(
            pb.Item(
                id=i,
                concept_id=code_to_id[concept_code],
                level=int(item["level"]),
                difficulty=float(item["b"]),
                source_ref=item.get("source_ref", ""),
                ai_generated=bool(item.get("ai_generated", False)),
            )
        )
        count += 1
    return count


def run_demo_reviews(col: Collection) -> None:
    """Record a few graded transfer answers so the dashboard has signal."""
    data = load_json("seed_items.json")
    # Answer the first eight items: lower ladder levels correct, harder ones
    # missed - the realistic "can recall, can't yet transfer" pattern.
    for i, item in enumerate(data["items"][:8], start=1):
        correct = int(item["level"]) <= 2
        col._backend.record_transfer_review(
            item_id=i, concept_id=1, correct=correct, latency_ms=5000
        )


def print_readiness(col: Collection) -> None:
    r = col._backend.readiness_report()
    print()
    print(f"  Readiness: {r.readiness}  ({r.readiness_low}-{r.readiness_high}, "
          f"472-528 scale)")
    print(f"  Memory (R):      {r.memory*100:5.1f}%")
    print(f"  Performance (T): {r.performance*100:5.1f}%")
    print(f"  Coverage:        {r.coverage*100:5.1f}%")
    for s in r.sections:
        print(f"    {s.section:<14} score {s.score} ({s.score_low}-{s.score_high}) "
              f"M={s.memory*100:.0f}% T={s.performance*100:.0f}%")
    print("  Reasons:")
    for reason in r.reasons:
        print(f"    - {reason}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    demo = "--demo" in sys.argv
    if args:
        path = args[0]
        created_temp = False
    else:
        fd, path = tempfile.mkstemp(suffix=".anki2")
        os.close(fd)
        os.unlink(path)
        created_temp = True

    col = Collection(path)
    try:
        code_to_id = import_concepts(col)
        n_items = import_seed_items(col, code_to_id)

        mastery = col._backend.mastery_query(concept_ids=[])
        print(f"Imported {len(code_to_id)} concepts and {n_items} seed items.")
        print(f"mastery_query returned {len(mastery.entries)} concept rows; "
              f"coverage={mastery.coverage:.3f}")
        queue = list(col._backend.transfer_gap_queue(limit=5))
        print(f"transfer-gap queue (top 5 concept ids): {queue}")
        assert len(mastery.entries) == len(code_to_id)

        if demo:
            run_demo_reviews(col)
            print_readiness(col)
    finally:
        col.close()
        if created_temp:
            os.unlink(path)
            print(f"(verification collection {path} removed)")


if __name__ == "__main__":
    main()
