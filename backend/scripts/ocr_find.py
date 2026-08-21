"""Locate OCR text blocks by phrase, for hand-picking bundle snippets.

The bundle's snippets are chosen by a person, not scraped: an evidence card
has to be one quotable claim with a box a participant can be shown. This just
answers "which block, on which page, with what box, contains this phrase".

bbox comes through unchanged -- the OCR already emits a 0-1000 grid, which is
the space the bundle uses (红线 #8). Verified across all 2,286 blocks in this
corpus: x in [0, 999], y in [0, 1000].
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

ROOT = r"F:/Python-Project/Arbor_CHI_2027/data/Dehuan Liu/OCR/ocr_results_l"


def blocks(exhibit: str):
    pages = glob.glob(os.path.join(ROOT, exhibit, "page_*.json"))
    pages.sort(key=lambda p: int(re.search(r"(\d+)", os.path.basename(p)).group(1)))
    for path in pages:
        page = json.load(open(path, encoding="utf-8"))
        for b in page.get("text_blocks") or []:
            yield page["page_number"], b


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exhibits", help="comma-separated, e.g. c1,c3,c4")
    ap.add_argument("phrase", nargs="?", default="", help="case-insensitive substring")
    ap.add_argument("--max-chars", type=int, default=260)
    args = ap.parse_args()

    needle = args.phrase.lower()
    for ex in args.exhibits.split(","):
        for page, b in blocks(ex.strip()):
            text = " ".join((b.get("text_content") or "").split())
            if needle and needle not in text.lower():
                continue
            if len(text) < 12:
                continue
            print(f"{ex}\tp{page}\t{b['bbox_list']}\t{text[:args.max_chars]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
