"""
Sentence segmentation -- one algorithm, mirrored in study-app/src/lib/sentences.ts.

Why this is its own module and not a one-line regex split. Petition prose is
dense with abbreviations and citations, and a naive split on `[.!?]\\s` gets
both wrong:

    "Dr. Li reported to the CTO [Exhibit B1, p.2]. He led four teams."
    naive  -> 3 "sentences", the first being "Dr."
    here   -> 2

    "Northwind reported $320M. [Exhibit B2, p.5] The company was named..."
    naive  -> splits inside the citation at "p.5"
    here   -> 2, with the citation kept on the sentence it supports

Neither miscount is cosmetic. The probe samples 12-15 SENTENCES from the
participant's final text and asks about each one (BE-13, PR-2): a fragment like
"Dr." is unanswerable as a probe item, and a letter that segments into one
sentence has no probe at all. Sentence ids also anchor the edit lineage
(红线 #2), so a boundary that moves between two runs breaks provenance.

**The frontend must produce the identical segmentation.** The live log records
sent_ids computed in the browser; the offline analysis recomputes them here. A
divergence raises nothing -- it just yields a reconstruction that does not line
up with the log, discovered during analysis when the sessions are gone. The two
are kept in step by tests/fixtures/sentences.json, checked from Python by
tests/test_sentences.py and from TypeScript by study-app's `npm test`, both in
CI.

Approach: a boundary is terminal punctuation, optional closing quotes, any
citations trailing the sentence, then whitespace, then something that can start
a sentence -- provided the token before the punctuation is neither a known
abbreviation nor a single initial.

Citations are matched inline rather than masked out first. An earlier version
substituted a sentinel string for each citation and restored them afterwards;
that worked, but it put a non-printable character into the source of both
implementations, and git then treated the files as binary -- no diff, no
review. Matching citations where they stand is simpler and leaves no sentinel
for the two languages to disagree about.
"""

from __future__ import annotations

import re
from typing import List

# "[Exhibit B1, p.2]", including multi-citation brackets like
# "[Exhibit B1, p.2; Exhibit C1, p.1]".
CITE_RE = re.compile(r"\[Exhibit\s+[^\]]+\]")

# Tokens that end in a period without ending a sentence. Lower-cased, no dot.
ABBREVIATIONS = frozenset({
    # titles
    "dr", "mr", "mrs", "ms", "prof", "sr", "jr", "st", "hon", "rev",
    # organisations
    "inc", "ltd", "co", "corp", "llc", "plc", "dept", "univ", "assn", "bros",
    # references
    "no", "nos", "fig", "figs", "ex", "p", "pp", "para", "paras", "vol", "ch",
    "art", "sec", "cf", "al", "ed", "eds", "trans", "supra", "id",
    # latin / common
    "eg", "ie", "etc", "vs", "v", "approx", "est", "min", "max", "ca", "viz",
    "resp", "cir", "app",
})

# Groups: 1 punctuation, 2 closing quotes/brackets, 3 trailing citations,
# 4 the whitespace separating this sentence from the next.
# Triple-quoted so the pattern can hold both quote characters literally.
_BOUNDARY = re.compile(
    r'''([.!?]+)(["'’”)\]]*)((?:\s*\[Exhibit\s+[^\]]+\])*)(\s+)'''
    r'''(?=[A-Z“"'(‘])'''
)

# The word immediately before the punctuation.
_LAST_WORD = re.compile(r"(\w*[A-Za-zÀ-ɏ]+)\.?$")


def _is_abbreviation(prefix: str) -> bool:
    """True if `prefix` (text up to and including the period) ends in a token
    that does not end a sentence."""
    m = _LAST_WORD.search(prefix.rstrip("."))
    if not m:
        return False
    word = m.group(1)
    if len(word) == 1 and word.isupper():
        # A single capital is an initial: "Dr. W. Li" must not split at "W."
        return True
    return word.lower() in ABBREVIATIONS


# A blank line is a hard boundary. Headings carry no terminal punctuation --
# "① The organisation has a distinguished reputation" -- so without this the
# heading glues onto the first sentence of its section and the pair becomes one
# probe item beginning with a heading. Paragraph breaks end sentences in prose
# too, so this is not a special case for headings.
_BLOCK = re.compile(r"\n\s*\n")


def split_sentences(text: str) -> List[str]:
    """Split `text` into sentences. Returns [] for blank input."""
    if not text or not text.strip():
        return []
    blocks = _BLOCK.split(text)
    if len(blocks) > 1:
        return [s for block in blocks for s in split_sentences(block)]
    return _split_block(text)


def _split_block(text: str) -> List[str]:
    out: List[str] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        if _is_abbreviation(text[start:m.end(1)]):
            continue
        # The sentence runs through its trailing citations (group 3). A citation
        # after the full stop belongs to the claim it supports -- which is what
        # a reader would say, and what the probe needs when it shows one
        # sentence and asks whether its evidence holds it up.
        piece = text[start:m.end(3)].strip()
        if piece:
            out.append(piece)
        start = m.end(4)

    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def count_sentences(text: str) -> int:
    return len(split_sentences(text))


def count_citations(text: str) -> int:
    return len(CITE_RE.findall(text))


__all__ = ["CITE_RE", "ABBREVIATIONS", "split_sentences", "count_sentences",
           "count_citations"]
