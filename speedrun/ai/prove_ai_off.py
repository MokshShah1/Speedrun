# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Proof that AI-generated items feed the engine and the app scores with AI OFF.

Two Friday requirements meet here (PRD 6.4):
  1. Traceability - every AI item traces to a concept + ladder level + named source.
  2. "The app still scores with AI off" - the scoring path is the Rust engine; no
     model is called to compute R/T/G or readiness.

This loads a *live* OpenAI run (default speedrun/data/glucagon_items_openai.json),
checks provenance, then - with the AI provider explicitly OFF and the AI package
never imported - imports those items, records graded transfer reviews, and reads
the three scores back out of the engine.

Run: python -m speedrun.ai.prove_ai_off [items.json ...]   (needs out/pylib built)
     defaults to both the glucagon and buffers live runs when present.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "out", "pylib"))
DATA = os.path.join(REPO, "speedrun", "data")


def prove(path: str) -> int:
    # AI is OFF for everything below. (The scoring path never calls a model
    # anyway - we don't even import speedrun.ai here - but make it explicit.)
    os.environ["SPEEDRUN_AI_PROVIDER"] = ""

    import anki.speedrun_pb2 as pb
    from anki.collection import Collection

    from speedrun.import_content import import_concepts

    with open(path, encoding="utf-8") as f:
        items = json.load(f)

    # 1. Provenance: every AI item traces to concept + level + named source.
    by_level: dict[int, int] = {}
    missing: list[int] = []
    for k, it in enumerate(items):
        traced = (
            it.get("ai_generated") is True
            and isinstance(it.get("concept_id"), int)
            and isinstance(it.get("level"), int)
            and bool(it.get("source_ref"))
            and bool(it.get("stem"))
            and bool(it.get("choices"))
            and isinstance(it.get("answer"), int)
        )
        if not traced:
            missing.append(k)
        by_level[it["level"]] = by_level.get(it["level"], 0) + 1

    sources = sorted({it.get("source_ref", "") for it in items})
    concept_ids = sorted({int(it["concept_id"]) for it in items})
    print(f"AI item provenance (live OpenAI run - {os.path.basename(path)}):")
    print(f"  items            : {len(items)}")
    print(f"  ai_generated=true: {sum(1 for it in items if it.get('ai_generated'))}/{len(items)}")
    print(f"  concept id(s)    : {concept_ids}")
    print(f"  named source(s)  : {sources}")
    print("  by ladder level  : " + ", ".join(f"L{lv}={by_level[lv]}" for lv in sorted(by_level)))
    if missing:
        print(f"  FAIL: {len(missing)} item(s) missing provenance at indices {missing}")
        return 1

    # 2. Score with AI OFF: import the concept map + these AI items, review, read
    #    R/T/G and readiness straight from the engine.
    fd, col_path = tempfile.mkstemp(suffix=".anki2")
    os.close(fd)
    os.unlink(col_path)
    col = Collection(col_path)
    try:
        import_concepts(col)  # numeric ids by outline order; AI items use id 4
        for i, it in enumerate(items, start=1):
            col._backend.upsert_item(
                pb.Item(
                    id=i,
                    concept_id=int(it["concept_id"]),
                    level=int(it["level"]),
                    difficulty=float(it.get("b", 0.0)),
                    source_ref=it.get("source_ref", ""),
                    ai_generated=True,
                    stem=it["stem"],
                    choices=list(it["choices"]),
                    answer=int(it["answer"]),
                    explanation=it.get("explanation", ""),
                )
            )
        # Realistic answering: lower rungs land, upper rungs miss (the "can recall,
        # can't yet transfer" pattern) - so T is meaningfully below 100%.
        graded = 0
        for i, it in enumerate(items, start=1):
            col._backend.record_transfer_review(
                item_id=i,
                concept_id=int(it["concept_id"]),
                correct=int(it["level"]) <= 2,
                latency_ms=4000,
            )
            graded += 1

        mastery = col._backend.mastery_query(concept_ids=concept_ids)
        report = col._backend.readiness_report()

        provider = os.environ.get("SPEEDRUN_AI_PROVIDER", "") or "(off)"
        print(f"\nScored with AI provider = {provider}; {graded} transfer reviews on AI items:")
        for e in mastery.entries:
            gap = e.recall - e.transfer
            print(
                f"  concept {e.concept_id}: R={e.recall * 100:4.0f}%  "
                f"T={e.transfer * 100:4.0f}%  G={gap * 100:+4.0f}%  (n={e.n_transfer_obs})"
            )
        print(
            f"  Readiness: {report.readiness} "
            f"({report.readiness_low}-{report.readiness_high}, 472-528)  "
            f"coverage={report.coverage * 100:.0f}%"
        )

        assert 472 <= report.readiness <= 528, report.readiness
        assert any(e.n_transfer_obs > 0 for e in mastery.entries), "no transfer signal"
        print("\n  RESULT: PASS - AI-generated items drive T; the engine scores with AI OFF")
        return 0
    finally:
        col.close()
        os.unlink(col_path)


def main() -> int:
    args = sys.argv[1:]
    if not args:
        args = [
            os.path.join(DATA, name)
            for name in ("glucagon_items_openai.json", "buffers_items_openai.json")
            if os.path.exists(os.path.join(DATA, name))
        ]
    rc = 0
    for i, path in enumerate(args):
        if i:
            print()
        rc |= prove(path)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
