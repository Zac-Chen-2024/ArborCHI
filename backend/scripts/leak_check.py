"""Run the substitution over a whole corpus and report what would survive.

The build loop for a replica is: add replacements, see what is still there, add
more. Doing that by rebuilding the images each time costs minutes a round and
nothing is learned from the pictures. This does the text half only, in a second,
against every page of the source.

What it looks for is a token list rather than the substitution table's own keys,
and that distinction is the point. The table's keys are what someone thought to
write down; the token list is what must not survive however it is spelled. They
are not the same, and the gap between them is where a leak lives:

  * "Dehuan Liu" is in the table. "Professor Dehuan" is how five exhibits refer
    to him, a hundred and twenty-six times, and replacing the full name leaves
    the given name standing in every one of them.
  * "Peking University" is in the table. The OCR read the same words off a logo
    as "PENGUang University", "PENGuang University" and "PENGueng University" --
    a hundred and thirty-six occurrences that no exact table will ever hold.

So the tokens are fragments: a surname on its own, a distinctive syllable of an
organisation, a domain without its suffix. A fragment matches every spelling
that contains it, and a fragment that never appears costs nothing.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Dict, List

HERE = Path(__file__).resolve().parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def pages(src: Path):
    for exhibit in sorted(p.name for p in src.iterdir() if p.is_dir()):
        for path in sorted((src / exhibit).glob("page_*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            text = [data.get("markdown_text") or ""]
            for block in data.get("text_blocks") or []:
                text.append(block.get("text_content") or "")
            yield exhibit, path.stem, "\n".join(text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--tokens", required=True, type=Path,
                    help="JSON list of fragments that must not survive")
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()

    fab = load("fabricate_material")
    pii = load("scrub_pii")
    tokens = json.loads(args.tokens.read_text(encoding="utf-8"))
    # Anchored at a word start, open at the end. A fragment is meant to catch
    # every spelling that begins with it -- "PENGU" has to find "PENGUang" --
    # but a bare substring test finds "NIO" inside "opinion" and "Sage" inside
    # "passage", and a checker that reports a hundred and twenty phantom leaks
    # is one nobody reads.
    matchers = [(t, re.compile(r"\b" + re.escape(t), re.I)) for t in tokens]

    # A watch list that cannot fire is worse than no watch list, because it
    # reports a clean corpus. This one silently could not: the anchor above
    # arrived as a literal backspace character, so every pattern demanded a
    # control code before the name and nothing ever matched. It said "nothing
    # survives" over three hundred and thirty-four pages of a corpus that at
    # that moment still had every name in it.
    canary = "Dehuan"
    if not re.compile(r"\b" + canary).search(f"Professor {canary} Liu"):
        raise SystemExit("leak_check: the matcher cannot match; refusing to report")

    survived: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    residual: List[str] = []
    seen: Dict[str, str] = {}
    pages_seen = 0

    for exhibit, _, text in pages(args.src):
        pages_seen += 1
        out = pii.scrub(fab.substitute(text), seen)
        for token, matcher in matchers:
            n = len(matcher.findall(out))
            if n:
                survived[token][exhibit] += n
        for label, hit in pii.residuals(out, set(seen.values())):
            residual.append(f"{exhibit}: {label} {hit}")

    print(f"pages scanned      : {pages_seen}")
    print(f"tokens watched     : {len(tokens)}")
    print(f"tokens surviving   : {len(survived)}")
    print(f"identifiers left   : {len(residual)}")

    if residual:
        print("\n-- identifiers that got through " + "-" * 28)
        for line in residual[:args.top]:
            print("   " + line)

    if survived:
        print("\n-- names that got through, most first " + "-" * 22)
        ranked = sorted(survived.items(), key=lambda kv: -sum(kv[1].values()))
        for token, where in ranked[:args.top]:
            total = sum(where.values())
            print(f"   {total:5}x  {token[:34]:36} "
                  f"{','.join(sorted(where)[:8])}")
        if len(ranked) > args.top:
            print(f"   ... and {len(ranked) - args.top} more")
    else:
        print("\nnothing on the watch list survives")
    return 1 if (survived or residual) else 0


if __name__ == "__main__":
    sys.exit(main())
