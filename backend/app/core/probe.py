"""
Probe item sampling (BE-13). The algorithm is pre-registered -- see
docs/预注册_pre-registration.md PR-2. Do not change it without adding an entry
there; it is the definition of the dependent measure's sampling frame.

    candidate pool   every sentence in the FINAL text that carries a citation
    target           14 items, permitted range 12-15
    mandatory        every surviving planted sentence
    fill             stratified random by sub-argument: each stratum gets at
                     least 1, the rest in proportion to its share of the pool,
                     floor first, remainder handed out in sub-argument order
    overflow         more than 15 surviving planted -> sample 15 from the
                     planted alone, no filler
    underflow        pool below 12 -> take all of it
    ceiling          planted must be <= 60% of the items; over that, planted are
                     dropped at random rather than filler being added

That last rule is the one worth restating. If nearly every sentence a
participant is asked about turns out to have a problem, they notice, and from
then on they are answering a different question -- "is this one of the trick
ones" rather than "does this evidence hold this claim up". Their hit rate goes
up for a reason that has nothing to do with the interface being tested. Adding
filler instead of dropping planted would not fix it, because that changes the
item count rather than the ratio.

Reproducibility: the RNG is seeded from the participant's token, so the same
session always draws the same items and the draw can be recomputed years later
from the archive alone. It is a *derived* seed, not the token itself, so the
seed can be published in a pre-registration without publishing a credential.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any, Dict, List, Optional

from .alignment import align_to_baseline
from .sentences import CITE_RE, split_sentences
from .study_config import probe_config


def seed_for(token: str, session_id: str) -> int:
    """Deterministic seed. Derived, so it can be published; the token cannot."""
    digest = hashlib.sha256(f"probe:{token}:{session_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def build_candidate_pool(
    final_text: str,
    baseline_sentences: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Sentences of the final text that carry a citation, with provenance.

    Sentences without a citation are excluded by PR-2, which also removes the
    section headings -- there is nothing to ask about a heading, and "does the
    cited evidence support this?" has no answer when nothing is cited.
    """
    sentences = split_sentences(final_text)
    aligned = align_to_baseline(sentences, baseline_sentences)
    pool: List[Dict[str, Any]] = []
    for index, (text, record) in enumerate(zip(sentences, aligned)):
        if not CITE_RE.search(text):
            continue
        pool.append({**record, "text": text, "position": index})
    return pool


def _stratified_fill(
    candidates: List[Dict[str, Any]],
    need: int,
    rng: random.Random,
) -> List[Dict[str, Any]]:
    """Draw `need` items, spreading them across sub-arguments (PR-2).

    Every stratum gets one before any gets two: a probe that happened to draw
    all its items from one sub-argument would tell us about that paragraph
    rather than about the participant.
    """
    if need <= 0 or not candidates:
        return []

    strata: Dict[Optional[str], List[Dict[str, Any]]] = {}
    for item in candidates:
        strata.setdefault(item.get("subargument_id"), []).append(item)

    # Sub-argument order, so the remainder is handed out deterministically.
    keys = sorted(strata, key=lambda k: (k is None, k or ""))
    for key in keys:
        rng.shuffle(strata[key])

    if need >= len(candidates):
        return list(candidates)

    total = len(candidates)
    quota: Dict[Optional[str], int] = {}
    # One each first, capped by what the stratum actually has.
    for key in keys:
        quota[key] = 1 if len(strata[key]) else 0
    remaining = need - sum(quota.values())

    if remaining < 0:
        # More strata than items wanted: keep the first `need` strata in order.
        picked: List[Dict[str, Any]] = []
        for key in keys:
            if len(picked) >= need:
                break
            picked.append(strata[key][0])
        return picked

    # Proportional share of what is left, floored.
    shares: Dict[Optional[str], int] = {}
    for key in keys:
        share = int(remaining * len(strata[key]) / total)
        shares[key] = min(share, len(strata[key]) - quota[key])
    handed_out = sum(shares.values())

    # Remainder, one at a time in sub-argument order (PR-2 says "向下取整后
    # 余数按分论点顺序补").
    leftover = remaining - handed_out
    while leftover > 0:
        progressed = False
        for key in keys:
            if leftover == 0:
                break
            if quota[key] + shares[key] < len(strata[key]):
                shares[key] += 1
                leftover -= 1
                progressed = True
        if not progressed:
            break

    picked = []
    for key in keys:
        picked.extend(strata[key][: quota[key] + shares[key]])
    return picked


def select_items(
    final_text: str,
    baseline_sentences: List[Dict[str, Any]],
    *,
    token: str,
    session_id: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Draw the probe items. Returns {items, stats} -- see PR-2.

    `items` carry `planted_id` for the analysis; the API strips it before the
    participant's browser sees them.
    """
    cfg = config or probe_config()
    target = int(cfg["target_items"])
    minimum = int(cfg["min_items"])
    maximum = int(cfg["max_items"])
    max_planted_ratio = float(cfg["max_planted_ratio"])

    rng = random.Random(seed_for(token, session_id))
    pool = build_candidate_pool(final_text, baseline_sentences)

    planted = [s for s in pool if s.get("planted_id")]
    filler = [s for s in pool if not s.get("planted_id")]

    stats = {
        "pool": len(pool),
        "planted_surviving": len(planted),
        "dropped_planted_for_ratio": 0,
        "rule": "target",
    }

    if len(pool) < minimum:
        # Underflow: take everything. Fewer items is a smaller measurement, not
        # a broken one; inventing items would be worse.
        items = list(pool)
        stats["rule"] = "underflow"
    elif len(planted) > maximum:
        # Overflow: the planted alone exceed the cap, so the probe is drawn
        # from them and no filler is added.
        items = rng.sample(planted, maximum)
        stats["rule"] = "planted_overflow"
    else:
        chosen_planted = list(planted)
        # Ceiling on the planted share -- see the module docstring for why this
        # drops planted rather than adding filler.
        allowed = int(target * max_planted_ratio)
        if len(chosen_planted) > allowed and len(filler) >= target - allowed:
            stats["dropped_planted_for_ratio"] = len(chosen_planted) - allowed
            chosen_planted = rng.sample(chosen_planted, allowed)
            stats["rule"] = "planted_ratio_capped"

        need = target - len(chosen_planted)
        items = chosen_planted + _stratified_fill(filler, need, rng)

        # Trim or top up into the permitted band.
        if len(items) > maximum:
            items = items[:maximum]
        if len(items) < minimum:
            extra = [s for s in pool if s not in items]
            rng.shuffle(extra)
            items.extend(extra[: minimum - len(items)])

    # Presentation order is random and planted items are interleaved, so a
    # participant cannot learn the shape of the sample from its ordering.
    rng.shuffle(items)

    for i, item in enumerate(items):
        item["probe_index"] = i

    stats["items"] = len(items)
    stats["planted_in_items"] = sum(1 for i in items if i.get("planted_id"))
    stats["planted_ratio"] = (
        round(stats["planted_in_items"] / len(items), 4) if items else 0.0
    )
    return {"items": items, "stats": stats}


def public_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """One probe item as the participant receives it.

    `planted_id` is removed -- it is the answer. So is `similarity`, which
    would hint that this sentence was edited, and `source`, which would say
    whether it was machine-written.
    """
    return {
        "probe_index": item["probe_index"],
        "sent_id": item.get("sent_id"),
        "text": item["text"],
        "citations": CITE_RE.findall(item["text"]),
    }


__all__ = ["seed_for", "build_candidate_pool", "select_items", "public_item"]
