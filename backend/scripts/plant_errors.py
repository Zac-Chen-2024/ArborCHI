"""Plant the errors a participant is asked to find (docs/植入错误设计_v1_draft.md).

Hand-authored, one entry per planted error, applied to the pregenerated text.
Each entry names the exact substring to replace, so a rewrite of the underlying
sentence makes the script fail rather than silently plant nothing.

Distribution follows the design document:

  * every top-level argument carries at least 2      -- otherwise a stratified
    probe sample can draw a whole layer with no planted sentence in it
  * at most 1 per sub-argument                       -- two in one paragraph cue
    each other
  * at least 1 under the distractor node             -- C-14 needs something to
    be found in the node that does not belong
  * 5 distinct kinds                                 -- a probe made only of
    "wrong exhibit number" measures reference-checking, not evidence evaluation

`unsupported_causal` is the deliberate control: finding it needs comprehension,
not lookup, and the interface is supposed to be no help at all. If condition C
beats B on that kind too, the difference is coming from somewhere other than
"easier to check".

**Still requires review by the user or an immigration attorney.** Whether each
of these reads as an error to someone who drafts EB-1A petitions for a living
is not a judgement this script can make.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MATERIAL = "judging_v1"
BUNDLE = Path(__file__).resolve().parents[1] / "study_materials" / MATERIAL

# (planted_id, node_id, sent_id, kind, find, replace, note, source_says)
PLANTS = [
    ("p1", "s1", "s1_0", "wrong_exhibit",
     "[Exhibit C-1, p.2]", "[Exhibit C-3, p.2]",
     "cites the Sohu review article instead of the appointment certificate",
     "C-1 p.2 is the certificate carrying the appointment; C-3 p.2 is a news "
     "report on the final review and does not mention the appointment"),

    ("p2", "s2", "s2_1", "unsupported_causal",
     "This designation supports the conclusion that the appointment involved "
     "formal executive oversight.",
     "Because Xubin Chen signed as Executive President, the petitioner's "
     "appointment carried executive oversight of the award.",
     "asserts a causal link the exhibit does not support",
     "C-1 p.2 records only the line 'Executive President: Xubin Chen'. It says "
     "nothing about what the petitioner's appointment carried"),

    ("p3", "s11", "s11_0", "overstated",
     "more than 650 public jurors", "more than 1,650 public jurors",
     "inflates the public jury roughly 2.5x",
     "C-5 p.3 says '650+ public jury'"),

    ("p4", "s14", "s14_0", "wrong_entity",
     "Mr. Xiaodong Zheng served as Chairman of the jury",
     "the petitioner served as Chairman of the jury",
     "attributes to the petitioner a role the exhibit gives to another person",
     "C-3 p.7 names Mr. Xiaodong Zheng as Chairman of the jury, serving in that "
     "post for the second time"),

    ("p5", "s21", "s21_0", "stale_qualifier",
     "is described as the first national association of the advertising industry",
     "is the sole national association of the advertising industry",
     "swaps 'first' for 'sole', a qualifier the exhibit does not use",
     "C-2 p.2 says 'the ever first national association of advertising industry'"),

    # Under the distractor node: evidence for a different criterion entirely,
    # rendered exactly like the rest.
    ("p6", "s24", "s24_1", "overstated",
     "more than 40 papers", "more than 200 papers",
     "inflates the publication count fivefold",
     "G-5 p.3 says 'He has published over 40 papers'"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report without writing")
    args = ap.parse_args()

    tree = json.loads((BUNDLE / "tree.frozen.json").read_text(encoding="utf-8"))
    parent_of, distractor = {}, {}
    for arg in tree["arguments"]:
        for sub in arg["subs"]:
            parent_of[sub["id"]] = arg["id"]
            distractor[sub["id"]] = sub["distractor"]

    items, failures = [], []
    for pid, node, sent_id, kind, find, repl, note, source_says in PLANTS:
        path = BUNDLE / "pregen" / f"{node}.json"
        if not path.exists():
            failures.append(f"{pid}: no pregen for {node}")
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        target = next((s for s in doc["sentences"] if s["sent_id"] == sent_id), None)
        if target is None:
            failures.append(f"{pid}: {node} has no {sent_id}")
            continue
        if find not in target["text"]:
            # Loudly. A plant that silently does nothing leaves a probe item
            # whose answer key says "error" over a sentence that is correct.
            failures.append(f"{pid}: {sent_id} does not contain {find!r}")
            continue

        if not args.check:
            target["text"] = target["text"].replace(find, repl, 1)
            target["planted_id"] = pid
            path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")

        items.append({
            "planted_id": pid,
            "node_id": node,
            "sent_id": sent_id,
            "kind": kind,
            "note": note,
            # What the exhibit actually says, for the analysis and for whoever
            # reviews these. Never served to a client (红线 #5).
            "source_says": source_says,
            "in_distractor_node": distractor.get(node, False),
            "argument_id": parent_of.get(node),
        })

    if failures:
        raise SystemExit("planting failed:\n  " + "\n  ".join(failures))

    per_argument: dict = {}
    for it in items:
        per_argument.setdefault(it["argument_id"], []).append(it["planted_id"])
    nodes = [it["node_id"] for it in items]
    problems = []
    if len(nodes) != len(set(nodes)):
        problems.append("more than one plant in the same sub-argument")
    thin = [a for a, ps in per_argument.items() if len(ps) < 2]
    if thin:
        problems.append(f"arguments with fewer than 2 plants: {thin}")
    if not any(it["in_distractor_node"] for it in items):
        problems.append("no plant under the distractor node")
    if len({it["kind"] for it in items}) < 5:
        problems.append("fewer than 5 distinct kinds")
    if problems:
        raise SystemExit("distribution rules violated:\n  " + "\n  ".join(problems))

    if not args.check:
        (BUNDLE / "planted.json").write_text(json.dumps({
            "schema_version": 1,
            "_comment": ("Answer key. Never served to a client -- materials.public_* "
                         "strips planted_id (红线 #5). Awaiting review by an "
                         "immigration attorney before any real session."),
            "reviewed_by_attorney": False,
            "items": items,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for it in items:
        mark = " [distractor node]" if it["in_distractor_node"] else ""
        print(f"  {it['planted_id']}  {it['kind']:<19} {it['sent_id']:<7} "
              f"{it['argument_id']}{mark}")
    print(f"\n{len(items)} planted across {len(per_argument)} arguments, "
          f"{len({i['kind'] for i in items})} kinds"
          f"{' (check only, nothing written)' if args.check else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
