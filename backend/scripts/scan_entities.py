"""Inventory everything in a source corpus that must not survive into a replica.

Why this exists. The first replica covered eleven exhibits and its substitution
table was written by hand, from reading them. That worked and does not scale:
the full filing is sixty-four exhibits over three hundred and thirty-four pages,
and among them are an employment certificate carrying a national identity
number, a research agreement with its contract number, a salary page, a
telephone and an address for a university office, and letters signed by named
people who are not the petitioner. A hand-written list is a list of what someone
remembered, and one number missed there is one real identity number published.

So the table is not written from memory. This reads every page and reports what
is in it, in categories, with counts and the exhibits each appears in. What
comes out is a worklist: every item either gets a replacement or is explicitly
recorded as safe to keep, and nothing is passed over by not having been noticed.

It reports; it changes nothing. `fabricate_material.py` does the substituting
and refuses to finish while any original is still in its own output.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

# Numbers that identify a person or a document. Written as patterns rather than
# a list because they cannot be enumerated: the point of a national identity
# number is that it is unique, so it is never in a table you already have.
PATTERNS: List[Tuple[str, re.Pattern]] = [
    # 18-digit mainland identity number, or the 15-digit older form.
    ("identity number", re.compile(r"\b\d{17}[\dXx]\b|\b\d{15}\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("url", re.compile(r"\bhttps?://[^\s)>\"]+|\bwww\.[\w.-]+\.[a-z]{2,}\b", re.I)),
    ("telephone", re.compile(r"\b(?:\+?86[- ]?)?(?:0\d{2,3}[- ]?)?\d{7,8}\b")),
    # Reference numbers: a contract, a document, an ISBN, a certificate.
    ("reference number", re.compile(
        r"\b(?:[A-Z]{2,6}[- ]?){1,3}\d{3,}(?:[- ]?\d+)*\b|\bISBN[\s\d-]{10,}")),
    ("money", re.compile(r"[¥$€]\s?\d[\d,]{2,}(?:\.\d+)?|\b\d[\d,]{4,}\s?(?:CNY|RMB|USD|yuan)\b", re.I)),
    ("postcode-ish", re.compile(r"\b\d{6}\b")),
]

# A run of capitalised words: people, organisations, publications, places.
NAME = re.compile(r"\b([A-Z][\w’'.-]*(?:\s+(?:of|for|and|the|de|van|&)\s+)?"
                  r"(?:\s*[A-Z][\w’'.-]*){0,5})")

# Words that start a sentence and mean nothing on their own. Kept short on
# purpose: it is better to review a common word than to hide a surname behind a
# stop list that was never checked.
STOP = {
    "The", "This", "That", "These", "Those", "There", "Their", "They", "It",
    "In", "On", "At", "As", "For", "From", "With", "Without", "Of", "And",
    "But", "Or", "If", "When", "While", "After", "Before", "During", "By",
    "To", "We", "Our", "You", "Your", "He", "She", "His", "Her", "I", "A", "An",
    "All", "Any", "Both", "Each", "Every", "Some", "Such", "No", "Not", "Now",
    "Here", "How", "What", "Which", "Who", "Why", "Since", "Through", "Under",
    "Over", "Between", "Among", "Also", "However", "Therefore", "Thus",
    "Moreover", "Furthermore", "Meanwhile", "According", "Based", "Following",
    "Page", "Home", "Search", "Menu", "Login", "Next", "Previous", "More",
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December", "Monday", "Tuesday",
    "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
}

CJK = re.compile(r"[一-鿿]{2,}")


def pages_of(root: Path, exhibit: str):
    for path in sorted((root / exhibit).glob("page_*.json"),
                       key=lambda p: int(re.search(r"(\d+)", p.stem).group(1))):
        data = json.loads(path.read_text(encoding="utf-8"))
        text = [data.get("markdown_text") or ""]
        for block in data.get("text_blocks") or []:
            text.append(block.get("text_content") or "")
        yield path.stem, "\n".join(text)


def scan(root: Path) -> Dict[str, Dict[str, set]]:
    found: Dict[str, Dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for exhibit in sorted(p.name for p in root.iterdir() if p.is_dir()):
        for _, text in pages_of(root, exhibit):
            for label, pattern in PATTERNS:
                for hit in pattern.findall(text):
                    hit = hit if isinstance(hit, str) else hit[0]
                    if hit.strip():
                        found[label][hit.strip()].add(exhibit)
            for hit in NAME.findall(text):
                hit = " ".join(hit.split())
                if len(hit) < 4 or hit.split()[0] in STOP:
                    continue
                found["name"][hit].add(exhibit)
            for hit in CJK.findall(text):
                found["chinese"][hit].add(exhibit)
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, type=Path, help="corpus root")
    ap.add_argument("--out", type=Path, help="write the full worklist as JSON")
    ap.add_argument("--covered", type=Path,
                    help="an existing substitutions.json; its originals are "
                         "reported as already handled rather than outstanding")
    ap.add_argument("--top", type=int, default=25, help="how many to print per category")
    args = ap.parse_args()

    covered: set = set()
    if args.covered:
        blob = json.loads(args.covered.read_text(encoding="utf-8"))
        reps = blob.get("replacements", blob)
        pairs = reps.items() if isinstance(reps, dict) else [
            (r.get("from") or r.get("original"), r.get("to")) for r in reps]
        covered = {a for a, _ in pairs}

    found = scan(args.src)
    lowered = {c.lower() for c in covered}

    print(f"{'category':18}{'total':>7}{'covered':>9}{'outstanding':>13}")
    worklist: Dict[str, List] = {}
    for label in [p[0] for p in PATTERNS] + ["name", "chinese"]:
        items = found.get(label, {})
        out = {k: sorted(v) for k, v in items.items()
               if k.lower() not in lowered
               and not any(k.lower() in c for c in lowered)}
        worklist[label] = [{"text": k, "exhibits": v} for k, v in
                           sorted(out.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
        print(f"{label:18}{len(items):7}{len(items) - len(out):9}{len(out):13}")

    for label in ("identity number", "email", "telephone", "reference number", "money"):
        rows = worklist.get(label) or []
        if not rows:
            continue
        print(f"\n-- {label} ({len(rows)} outstanding) " + "-" * 30)
        for row in rows[:args.top]:
            where = ",".join(row["exhibits"][:6])
            print(f"   {row['text'][:56]:58} {where}")

    rows = worklist.get("name") or []
    print(f"\n-- name ({len(rows)} outstanding, most widespread first) " + "-" * 12)
    for row in rows[:args.top]:
        print(f"   {len(row['exhibits']):3}x  {row['text'][:52]:54} "
              f"{','.join(row['exhibits'][:8])}")

    if args.out:
        args.out.write_text(json.dumps(worklist, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        print(f"\nfull worklist -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
