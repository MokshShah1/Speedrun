# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Command-line driver for AI transfer-item generation.

Generates items for one concept from a named source file across a ladder of
levels, runs every candidate through the checker and leakage scanner, and
writes the accepted items as JSON in the same schema as ``data/seed_items.json``
(so ``import_content.py`` can load them straight into the engine).

Offline by default (MockProvider). Set SPEEDRUN_AI_PROVIDER=openai and
OPENAI_API_KEY to use a real model.

    python -m speedrun.ai.cli \\
        --concept-id 30 --concept-title "buffers and the Henderson-Hasselbalch equation" \\
        --source speedrun/ai/sources/buffers_milestone.txt \\
        --source-ref "MileDown GenChem: Buffers" \\
        --levels 1 2 3 --n 4 --out speedrun/data/generated_items.json
"""

from __future__ import annotations

import argparse
import json
import sys

from . import generate


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate AI transfer items for a concept.")
    p.add_argument("--concept-id", type=int, required=True)
    p.add_argument("--concept-title", required=True)
    p.add_argument("--source", required=True, help="path to the named source text")
    p.add_argument("--source-ref", required=True, help="human-readable citation")
    p.add_argument("--levels", type=int, nargs="+", default=[1, 2, 3])
    p.add_argument("--n", type=int, default=4, help="candidates requested per level")
    p.add_argument("--out", default=None, help="write accepted items to this JSON file")
    p.add_argument("--provider", default=None, help="mock (default) or openai")
    p.add_argument("--no-cache", action="store_true")
    args = p.parse_args(argv)

    with open(args.source, encoding="utf-8") as f:
        source_text = f.read()

    accepted: list[dict] = []
    total_requested = 0
    total_rejected = 0
    for level in args.levels:
        report = generate.generate_items(
            concept_id=args.concept_id,
            concept_title=args.concept_title,
            source_ref=args.source_ref,
            source_text=source_text,
            level=level,
            n=args.n,
            provider_name=args.provider,
            existing=accepted,
            use_cache=not args.no_cache,
        )
        total_requested += report.requested
        total_rejected += len(report.rejected)
        accepted.extend(report.accepted)
        tag = " (cache)" if report.from_cache else ""
        print(f"  L{level}: accepted {len(report.accepted)}/{report.requested}{tag}")
        for r in report.rejected:
            print(f"      rejected: {', '.join(r['reasons'])}")

    print(f"Total accepted: {len(accepted)} (requested {total_requested}, "
          f"rejected {total_rejected})")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(accepted, f, indent=2)
        print(f"Wrote {len(accepted)} items to {args.out}")
    return 0 if accepted else 1


if __name__ == "__main__":
    sys.exit(main())
