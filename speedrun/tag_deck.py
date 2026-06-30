# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Auto-tag an imported MCAT deck (e.g. MileDown) with `speedrun::<outline_id>`.

The Speedrun engine aggregates FSRS recall (R) to the concept level by reading
cards tagged `speedrun::<outline_id>` (see rslib `concept_recall`). Pre-made
decks aren't tagged that way, so this maps every note to its best-matching AAMC
content category using the concept map's titles + topic keywords, then applies
the tag.

Matching is keyword-overlap with inverse-document-frequency weighting (a term
that points at one category counts more than one shared by many), plus a bonus
when a full topic phrase appears verbatim. It's deliberately conservative: notes
below `--min-score` are left untagged rather than mis-tagged.

  Dry run (no writes, prints the assignment distribution):
    python speedrun/tag_deck.py --col path/to/collection.anki2 --dry-run
  Apply, limited to the deck:
    python speedrun/tag_deck.py --col ... --search "deck:MileDown*"
  Self-test on a synthetic collection (no external deck needed):
    python speedrun/tag_deck.py --self-test
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "out", "pylib"))

CONCEPTS_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "concepts.json")
TAG_PREFIX = "speedrun::"
DEFAULT_MIN_SCORE = 1.5
PHRASE_BONUS = 2.0

STOPWORDS = {
    "and", "the", "of", "to", "in", "for", "with", "their", "its", "from", "into",
    "structure", "function", "functions", "system", "systems", "processes", "process",
    "principles", "nature", "ways", "main", "within", "between", "intro", "basics",
    "theory", "theories", "vs", "etc", "other", "via",
}
WORD_RE = re.compile(r"[a-z0-9][a-z0-9'\-]+")
TAG_RE = re.compile(r"<[^>]+>")


def _tokens(text: str) -> list[str]:
    return [t for t in WORD_RE.findall(text.lower()) if len(t) >= 3 and t not in STOPWORDS]


def _strip_html(s: str) -> str:
    return TAG_RE.sub(" ", s).replace("&nbsp;", " ")


class ConceptIndex:
    """Keyword/phrase index over the concept map for note->concept scoring."""

    def __init__(self, concepts: list[dict]):
        self.concepts = concepts
        self.phrases: dict[str, list[str]] = {}      # outline_id -> topic phrases
        self.tokens: dict[str, set[str]] = {}        # outline_id -> distinctive tokens
        df: Counter[str] = Counter()                 # token -> #concepts containing it
        per_concept_tokens: dict[str, set[str]] = {}
        for c in concepts:
            cid = c["id"]
            phrases = [p.lower() for p in c.get("topics", [])]
            self.phrases[cid] = phrases
            toks = set(_tokens(c["title"]))
            for p in phrases:
                toks.update(_tokens(p))
            per_concept_tokens[cid] = toks
            for t in toks:
                df[t] += 1
        n = max(len(concepts), 1)
        import math
        self.idf = {t: math.log(1 + n / df_t) for t, df_t in df.items()}
        self.tokens = per_concept_tokens

    def best(self, text: str) -> tuple[str | None, float]:
        text_l = text.lower()
        note_tokens = set(_tokens(text_l))
        best_id, best_score = None, 0.0
        for c in self.concepts:
            cid = c["id"]
            score = sum(self.idf.get(t, 0.0) for t in (note_tokens & self.tokens[cid]))
            for phrase in self.phrases[cid]:
                if len(phrase) >= 6 and phrase in text_l:
                    score += PHRASE_BONUS
            if score > best_score:
                best_id, best_score = cid, score
        return best_id, best_score


def load_index() -> ConceptIndex:
    with open(CONCEPTS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return ConceptIndex(data["concepts"])


def note_text(note) -> str:
    return _strip_html(" ".join(note.fields))


def tag_collection(col, index: ConceptIndex, search: str, min_score: float, dry_run: bool) -> dict:
    nids = col.find_notes(search) if search else col.find_notes("")
    assigned: Counter[str] = Counter()
    unmatched = 0
    changed = 0
    examples: dict[str, str] = {}
    for nid in nids:
        note = col.get_note(nid)
        cid, score = index.best(note_text(note))
        if cid is None or score < min_score:
            unmatched += 1
            continue
        assigned[cid] += 1
        tag = f"{TAG_PREFIX}{cid}"
        examples.setdefault(cid, note_text(note)[:60].strip())
        if tag not in note.tags:
            note.add_tag(tag)
            if not dry_run:
                col.update_note(note)
            changed += 1
    return {
        "total": len(nids), "assigned": sum(assigned.values()), "unmatched": unmatched,
        "changed": changed, "by_concept": dict(assigned), "examples": examples,
    }


def _print_report(stats: dict, dry_run: bool) -> None:
    print(f"  notes scanned : {stats['total']}")
    print(f"  matched       : {stats['assigned']}  (unmatched: {stats['unmatched']})")
    print(f"  tags {'would change' if dry_run else 'changed'} : {stats['changed']}")
    print("  distribution  :")
    for cid, n in sorted(stats["by_concept"].items(), key=lambda kv: (-kv[1], kv[0])):
        ex = stats["examples"].get(cid, "")
        print(f"    {TAG_PREFIX}{cid:<4} {n:>5}   e.g. {ex!r}")


def self_test() -> int:
    """Build a synthetic collection of MCAT-flavoured notes and verify tagging."""
    from anki.collection import Collection

    cases = [
        ("Enzyme kinetics", "What does the Michaelis-Menten constant Km describe?", "1A"),
        ("Glycolysis", "Net ATP yield of glycolysis per glucose?", "1D"),
        ("Action potential", "What ion drives depolarization of the neuron membrane?", "3A"),
        ("Acids and bases", "Henderson-Hasselbalch relates pH, pKa and what ratio?", "5A"),
        ("Operant conditioning", "Define negative reinforcement in operant conditioning.", "7C"),
        ("Circuits", "Ohm's law relates voltage, current and what?", "4C"),
    ]
    fd, path = tempfile.mkstemp(suffix=".anki2")
    os.close(fd)
    os.unlink(path)
    try:
        col = Collection(path)
        model = col.models.by_name("Basic")
        deck_id = col.decks.id("MileDown")
        for front, back, _ in cases:
            note = col.new_note(model)
            note.fields[0] = front
            note.fields[1] = back
            col.add_note(note, deck_id)

        index = load_index()
        stats = tag_collection(col, index, search="deck:MileDown", min_score=DEFAULT_MIN_SCORE, dry_run=False)
        _print_report(stats, dry_run=False)

        # Verify each crafted note received its expected tag.
        expected = defaultdict(int)
        for _, _, cid in cases:
            expected[cid] += 1
        ok = True
        for nid in col.find_notes("deck:MileDown"):
            tags = [t for t in col.get_note(nid).tags if t.startswith(TAG_PREFIX)]
            if not tags:
                ok = False
        got = stats["by_concept"]
        for cid, want in expected.items():
            if got.get(cid, 0) < want:
                print(f"  MISS: expected >={want} for {cid}, got {got.get(cid,0)}")
                ok = False
        col.close(downgrade=False)
        print("  RESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(path + suffix)
            except OSError:
                pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Tag an MCAT deck with speedrun::<outline_id>.")
    ap.add_argument("--col", help="path to .anki2 collection")
    ap.add_argument("--search", default="", help="Anki search to limit notes (e.g. 'deck:MileDown*')")
    ap.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    ap.add_argument("--dry-run", action="store_true", help="report only; do not write tags")
    ap.add_argument("--self-test", action="store_true", help="run on a synthetic collection")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.col:
        ap.error("--col is required unless --self-test")

    from anki.collection import Collection
    col = Collection(args.col)
    try:
        index = load_index()
        stats = tag_collection(col, index, args.search, args.min_score, args.dry_run)
        print(f"Speedrun deck tagging ({'DRY RUN' if args.dry_run else 'APPLY'})")
        _print_report(stats, args.dry_run)
    finally:
        col.close(downgrade=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
