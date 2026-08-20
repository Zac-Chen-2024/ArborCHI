"""
Sentence alignment -- mirrored in study-app/src/lib/textEdit.ts (PR-3).

Dice coefficient over character bigrams, thresholds 0.92 and 0.35. Both numbers
are pre-registered and carried over unchanged from the product line's
`utils/sentenceDiff.ts`; they were not tuned for this study.

    = 1.00   same        untouched
    >= 0.92  edited      the same sentence, reworded
    >= 0.35  rewritten   the same slot, substantially different prose
    <  0.35  new         a sentence that was not there before

Two callers, and they must agree:

* The browser aligns on every edit to keep `sent_id` lineage alive in the log
  (红线 #2).
* The server aligns the FINAL text against the initial snapshot to work out
  which planted sentences survived, because that set is what the probe must
  include (PR-2). The client's lineage cannot be trusted for this -- it lives
  in a log the participant's browser produced, and a dropped batch would
  silently shrink the planted set.

Recomputing server-side also means a session whose log is incomplete still
yields a correct probe.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

STRONG = 0.92
WEAK = 0.35


def _bigrams(text: str) -> Counter:
    norm = " ".join(text.lower().split())
    return Counter(norm[i:i + 2] for i in range(len(norm) - 1))


def similarity(a: str, b: str) -> float:
    """Dice coefficient over character bigrams: 0 (nothing shared) .. 1."""
    if a == b:
        return 1.0
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    shared = sum((A & B).values())
    return (2 * shared) / (sum(A.values()) + sum(B.values()))


def classify(score: float) -> str:
    if score >= 1.0:
        return "same"
    if score >= STRONG:
        return "edited"
    if score >= WEAK:
        return "rewritten"
    return "new"


def best_match(
    text: str,
    candidates: List[Dict[str, Any]],
    *,
    key: str = "text",
) -> Tuple[Optional[Dict[str, Any]], float]:
    """The candidate `text` most resembles, and the score."""
    best: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for candidate in candidates:
        score = similarity(candidate.get(key, ""), text)
        if score > best_score:
            best, best_score = candidate, score
    return best, best_score


def align_to_baseline(
    final_sentences: List[str],
    baseline: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Attach each final sentence to the baseline sentence it descends from.

    Returns one record per FINAL sentence:

        text            as submitted
        sent_id         inherited, or None if the sentence is new
        planted_id      inherited -- this is what the probe needs
        subargument_id  inherited, for the stratified sample
        source          inherited (frozen|live)
        match           same | edited | rewritten | new
        similarity      the score, kept so a borderline call is auditable

    A baseline sentence claimed by two final sentences is a split: both inherit,
    because both descend from it and both may still carry the planted error.
    Over-inclusion is the safe direction here -- a planted sentence missed by
    the probe is a hole in the measurement, while one asked about twice is
    caught by the de-duplication in probe.py.
    """
    out: List[Dict[str, Any]] = []
    for text in final_sentences:
        match, score = best_match(text, baseline)
        kind = classify(score)
        if match is None or kind == "new":
            out.append({
                "text": text, "sent_id": None, "planted_id": None,
                "subargument_id": None, "source": None,
                "match": "new", "similarity": round(score, 4),
            })
            continue
        out.append({
            "text": text,
            "sent_id": match.get("sent_id"),
            "planted_id": match.get("planted_id"),
            "subargument_id": match.get("subargument_id"),
            "source": match.get("source"),
            "match": kind,
            "similarity": round(score, 4),
        })
    return out


__all__ = ["STRONG", "WEAK", "similarity", "classify", "best_match",
           "align_to_baseline"]
