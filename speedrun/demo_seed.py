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

# One real, UNANSWERED application question per demo concept. next_transfer_item
# only serves items with no transfer review yet, so once the seeded reviews cover
# the whole ladder the reviewer would have nothing to show; these keep the Transfer
# Reviewer populated with authentic questions (level 2 = single-concept application).
FRESH_QUESTIONS: dict[str, tuple[str, list[str], int, str]] = {
    "1A": ("A noncompetitive inhibitor binds an enzyme's allosteric site. How are Vmax and Km affected?",
           ["Vmax decreases, Km unchanged", "Vmax unchanged, Km increases", "Both increase", "Both decrease"], 0,
           "Noncompetitive inhibition lowers Vmax; Km is unchanged since active-site affinity is unaffected."),
    "1B": ("A point mutation changes codon UUA to UUG (both encode leucine). This is best described as:",
           ["A silent mutation", "A missense mutation", "A nonsense mutation", "A frameshift"], 0,
           "Both codons specify leucine, so the protein is unchanged - a silent (synonymous) mutation."),
    "1C": ("In a Hardy-Weinberg population the recessive allele frequency q = 0.3. What fraction are carriers?",
           ["0.09", "0.21", "0.42", "0.49"], 2, "Heterozygotes = 2pq = 2(0.7)(0.3) = 0.42."),
    "1D": ("During prolonged fasting, which hormone predominates and what does it promote?",
           ["Insulin; glycogen synthesis", "Glucagon; gluconeogenesis and glycogenolysis",
            "Insulin; lipogenesis", "Glucagon; glycolysis"], 1,
           "Fasting raises glucagon, driving gluconeogenesis and glycogenolysis to keep blood glucose up."),
    "2A": ("A cell is placed in a hypertonic solution. Water will:",
           ["Enter the cell, causing lysis", "Leave the cell, causing it to shrink",
            "Not move", "Enter via active transport"], 1,
           "Water moves osmotically toward higher solute, so it leaves the cell (crenation)."),
    "3A": ("During the rising phase of an action potential, which ion movement dominates?",
           ["K+ efflux", "Na+ influx", "Cl- influx", "Ca2+ efflux"], 1,
           "Depolarization is driven by voltage-gated Na+ channels opening and Na+ rushing in."),
    "4A": ("A 2 kg block accelerates at 3 m/s^2. The net force on it is:",
           ["1.5 N", "5 N", "6 N", "0.67 N"], 2, "F = ma = 2 x 3 = 6 N."),
    "4C": ("Resistors of 4 ohm and 12 ohm are wired in parallel. The equivalent resistance is:",
           ["16 ohm", "8 ohm", "3 ohm", "48 ohm"], 2, "1/R = 1/4 + 1/12 = 1/3, so R = 3 ohm."),
    "5A": ("A buffer has pKa 4.7. To hold pH at 4.7, the ratio [A-]/[HA] should be:",
           ["10:1", "1:1", "1:10", "2:1"], 1, "By Henderson-Hasselbalch, pH = pKa when [A-] = [HA] (1:1)."),
    "5B": ("Which molecule has the highest boiling point?",
           ["CH4", "H2O", "H2S", "CO2"], 1, "Water's hydrogen bonding gives it the highest boiling point here."),
    "5D": ("Which functional group is most readily reduced to an alcohol by NaBH4?",
           ["Carboxylic acid", "Ketone", "Alkane", "Ether"], 1,
           "A ketone is reduced to a secondary alcohol; alkanes and ethers are unreactive to NaBH4."),
    "5E": ("A reaction has +delta_H and +delta_S. It is spontaneous:",
           ["At all temperatures", "At high temperatures", "At low temperatures", "Never"], 1,
           "delta_G = delta_H - T*delta_S < 0 only when T is large."),
    "6B": ("Grouping a phone number into chunks improves recall mainly by:",
           ["Increasing sensory memory", "Using grouping to fit working memory's ~7-item limit",
            "Slowing long-term forgetting", "Reducing proactive interference"], 1,
           "Chunking packs more into the limited capacity of working memory."),
    "6C": ("The James-Lange theory of emotion proposes that:",
           ["Emotion precedes physiological arousal", "Physiological arousal precedes and causes the emotion",
            "Arousal and emotion are independent", "Cognitive appraisal alone causes emotion"], 1,
           "James-Lange: the felt emotion follows from bodily/physiological responses."),
    "7A": ("A behavior increases after an aversive stimulus is removed. This is:",
           ["Positive reinforcement", "Negative reinforcement", "Positive punishment", "Negative punishment"], 1,
           "Removing an aversive stimulus to increase a behavior is negative reinforcement."),
    "7C": ("Under the elaboration likelihood model, the central route persuades via:",
           ["Source attractiveness", "Careful evaluation of argument quality", "Peripheral cues", "Mere repetition"], 1,
           "The central route depends on thoughtful processing of argument quality."),
    "8A": ("Bandura's self-efficacy refers to:",
           ["Global self-worth", "Belief in one's ability to succeed at a specific task",
            "Identification with a group", "The ideal self"], 1,
           "Self-efficacy is a task-specific belief in one's own capability."),
    "8B": ("Attributing a stranger's rudeness to their personality rather than their situation is:",
           ["Self-serving bias", "Fundamental attribution error", "Just-world hypothesis", "In-group bias"], 1,
           "Overweighting disposition over situation for others is the fundamental attribution error."),
    "9A": ("A hospital's enduring roles, rules, and hierarchy that persist regardless of staff exemplify:",
           ["A social institution", "A primary group", "A dyad", "Role strain"], 0,
           "Enduring structured patterns that organize social life are social institutions."),
    "10A": ("Residents of a poor neighborhood have less access to fresh food and clinics. This illustrates:",
            ["Meritocracy", "Spatial inequality and health disparity", "Social mobility", "Cultural capital"], 1,
            "Unequal resource access tied to place is spatial inequality driving health disparities."),
}


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def add_fresh_items(col: Collection, code_to_id: dict[str, int], base_id: int = 5000) -> int:
    """Upsert one real, unanswered application question per demo concept."""
    added = 0
    for code, (stem, choices, ans, expl) in FRESH_QUESTIONS.items():
        cid = code_to_id.get(code)
        if cid is None:
            continue
        col._backend.upsert_item(
            pb.Item(
                id=base_id + added, concept_id=cid, level=2, difficulty=-0.2,
                source_ref="demo (practice)", ai_generated=False, stem=stem,
                choices=list(choices), answer=ans, explanation=expl,
            )
        )
        added += 1
    return added


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

    # Leave one real, UNANSWERED question per concept so the Transfer Reviewer
    # always has something to serve (it skips already-answered items).
    add_fresh_items(col, code_to_id)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        path, temp = args[0], False
    else:
        fd, path = tempfile.mkstemp(suffix=".anki2")
        os.close(fd)
        os.unlink(path)
        temp = True

    fresh_only = "--fresh-only" in sys.argv
    col = Collection(path)
    try:
        if fresh_only:
            # Only add the unanswered practice questions (idempotent upserts);
            # leaves existing reviews/cards untouched. Fixes an over-seeded
            # collection where every ladder item was already answered.
            code_to_id = import_concepts(col)
            added = add_fresh_items(col, code_to_id)
            resp = col._backend.next_transfer_item(concept_id=0)
            print(f"Added {added} fresh unanswered questions.")
            print(f"Transfer Reviewer has an item to serve: {resp.found}"
                  + (f" (concept {resp.concept_id}, L{resp.item.level})" if resp.found else ""))
            return 0
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
