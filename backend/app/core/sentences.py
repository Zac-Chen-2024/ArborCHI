"""
Sentence segmentation -- one algorithm, mirrored in study-app/src/lib/sentences.ts.

Why this is its own module and not a one-line regex split. Petition prose is
dense with abbreviations, and a naive split on `[.!?]\\s` cuts every one of
them:

    "Dr. Li reported to the CTO [Exhibit B1, p.2]. He led four teams."
    naive  -> 3 "sentences", the first being "Dr."
    here   -> 2

That miscount is not cosmetic. The probe samples 12-15 sentences from the
participant's final text and asks about each one (BE-13); a fragment like "Dr."
as a probe item is unanswerable, and the sampling denominator is wrong. Sentence
ids also anchor the edit lineage (红线 #2), so a boundary that moves between two
runs breaks provenance.

**The frontend must produce the identical segmentation.** The live log records
sent_ids computed in the browser; the offline analysis recomputes them here. If
the two disagreed, the reconstruction would silently fail to line up with what
was logged. Both implementations are kept in step by
tests/test_sentences.py and the shared fixture list it uses -- change one,
change both, and re-run.

Approach: mask citation brackets (which contain "p.2" and would otherwise be
cut), then accept a boundary only where terminal punctuation is followed by
whitespace and an opening character, and the token before the punctuation is
neither a known abbreviation nor a single initial.
"""

from __future__ import annotations

import re
from typing import List

# Citation brackets are opaque during segmentation: "[Exhibit B1, p.2]" holds a
# period that is not a sentence end.
CITE_RE = re.compile(r"\[Exhibit\s+[^\]]+\]")
_MASK = "\x00CITE\x00"

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

# A boundary candidate: terminal punctuation, optional closing quotes/brackets,
# whitespace, then something that can start a sentence.
_BOUNDARY = re.compile(r'([.!?]+)(["\'’”)\]]*)(\s+)(?=[A-Z“"\'([‘])')

# The word immediately before the punctuation.
_LAST_WORD = re.compile(r"([A-Za-zÀ-ɏ]+)\.?$")


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


def split_sentences(text: str) -> List[str]:
    """Split `text` into sentences. Returns [] for blank input."""
    if not text or not text.strip():
        return []

    masked = CITE_RE.sub(_MASK, text)
    cites = CITE_RE.findall(text)

    pieces: List[str] = []
    start = 0
    for m in _BOUNDARY.finditer(masked):
        end_of_sentence = m.end(2)
        if _is_abbreviation(masked[start:m.end(1)]):
            continue
        pieces.append(masked[start:end_of_sentence])
        start = m.end(3)
    pieces.append(masked[start:])

    # Unmask in order: the placeholders were substituted left to right.
    out: List[str] = []
    i = 0
    for piece in pieces:
        while _MASK in piece:
            piece = piece.replace(_MASK, cites[i], 1)
            i += 1
        piece = piece.strip()
        if piece:
            out.append(piece)
    return out


def count_sentences(text: str) -> int:
    return len(split_sentences(text))


def count_citations(text: str) -> int:
    return len(CITE_RE.findall(text))


__all__ = ["CITE_RE", "ABBREVIATIONS", "split_sentences", "count_sentences",
           "count_citations"]
