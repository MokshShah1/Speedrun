# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Seed a *video-ready* collection: real R > T gap, coverage past the abstention
line, readiness with a range.

The plain `--demo` import only touches ~3 concepts (below the 25% coverage / 50
review abstention line, so the dashboard correctly shows "No score yet"). For the
demo recording we want the dashboard to actually render the three scores with a
believable "illusion of mastery" gap. This seeds:

  * the full 31-concept AAMC map (weighted),
  * for 10 concepts across all three sections: a 6-rung item ladder, three cards
    tagged `speedrun::<code>` with an FSRS memory_state (high recall R), and a
    batch of graded transfer reviews with a per-concept ability tuned BELOW recall
    (so T < R and G = R - T is a positive gap).

Result: coverage ~32% (> 25%), > 50 transfer reviews (> 50), and R > T > 0, so the
dashboard shows a real projected score with a range instead of abstaining.

Usage:
    python speedrun/demo_seed.py "C:\\Users\\<you>\\AppData\\Roaming\\Anki2\\User 1\\collection.anki2"
    python speedrun/demo_seed.py            # throwaway temp collection (prints a preview)

Run with desktop Anki CLOSED (the collection must be unlocked).
"""

from __future__ import annotations

import math
import os
import random
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "out", "pylib"))
sys.path.insert(0, os.path.join(REPO, "speedrun"))

import anki.speedrun_pb2 as pb  # noqa: E402
from anki.collection import Collection  # noqa: E402  (import first: initializes the anki pkg)
from anki.cards_pb2 import FsrsMemoryState as FSRSMemoryState  # noqa: E402

from import_content import import_concepts, print_readiness  # noqa: E402

LADDER_B = [-1.5, -0.9, -0.2, 0.5, 1.0, 1.6]
# ~20 content categories spanning all three sections (~65% coverage). High enough
# that the covered concepts' recall dominates the headline Memory number, so the
# aggregate gap G = R - T stays positive (the illusion of mastery) instead of being
# inverted by unstudied concepts (whose transfer sits at the prior ~0.38 while
# their recall is 0).
DEMO_CODES = [
    "1A", "1B", "1C", "1D", "2A", "3A",              # Bio/Biochem
    "4A", "4C", "5A", "5B", "5D", "5E",              # Chem/Phys
    "6B", "6C", "7A", "7C", "8A", "8B", "9A", "10A",  # Psych/Soc
]
DAY = 86400


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def seed(col: Collection, seed_val: int = 7) -> None:
    rng = random.Random(seed_val)
    code_to_id = import_concepts(col)
    model = col.models.by_name("Basic")
    did = col.decks.id("Speedrun Demo")
    now = int(time.time())

    iid = 1
    for code in DEMO_CODES:
        cid = code_to_id[code]

        # 1) Item ladder for this concept (what transfer reviews are graded on).
        concept_items: list[tuple[int, float]] = []
        for lvl, b in enumerate(LADDER_B):
            col._backend.upsert_item(
                pb.Item(
                    id=iid, concept_id=cid, level=lvl, difficulty=b, source_ref="demo",
                    ai_generated=False, stem=f"{code} transfer item L{lvl}",
                    choices=["a", "b", "c", "d"], answer=0, explanation="x",
                )
            )
            concept_items.append((iid, b))
            iid += 1

        # 2) Memory: three tagged cards with a real FSRS memory_state => recall R.
        #    High, slightly varied stability + a recent last review => R ~0.85-0.97.
        for k in range(3):
            note = col.new_note(model)
            note["Front"] = f"{code} fact {k}"
            note["Back"] = "answer"
            note.tags = [f"speedrun::{code}"]
            col.add_note(note, did)
            card = note.cards()[0]
            card.memory_state = FSRSMemoryState(
                stability=rng.uniform(25.0, 70.0), difficulty=rng.uniform(4.0, 7.0)
            )
            card.last_review_time = now - rng.randint(1, 6) * DAY
            card.type = 2  # review
            card.queue = 2  # review
            col.update_cards([card])

        # 3) Performance: graded transfer reviews with a per-concept ability tuned
        #    BELOW recall, so T lands under R (a positive illusion-of-mastery gap).
        ability = rng.uniform(-0.4, 1.0)
        for _ in range(2):  # two passes over the ladder => 12 reviews/concept
            for item_id, b in concept_items:
                correct = rng.random() < sigmoid(ability - b)
                col._backend.record_transfer_review(
                    item_id=item_id, concept_id=cid, correct=correct,
                    latency_ms=rng.randint(3000, 16000),
                )


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        path, temp = args[0], False
    else:
        fd, path = tempfile.mkstemp(suffix=".anki2")
        os.close(fd)
        os.unlink(path)
        temp = True

    col = Collection(path)
    try:
        seed(col)
        r = col._backend.readiness_report()
        n = len(list(col._backend.export_transfer_log()))
        print(f"Seeded demo collection: {n} transfer reviews, "
              f"{len(DEMO_CODES)} concepts with cards+items.")
        print_readiness(col)
        gate = "SHOWS SCORE" if (n >= 50 and r.coverage >= 0.25) else "STILL ABSTAINS"
        print(f"\n  abstention gate: {gate}  (need >=50 reviews & >=25% coverage)")
    finally:
        col.close()
        if temp:
            os.unlink(path)
            print(f"(temp collection {path} removed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
