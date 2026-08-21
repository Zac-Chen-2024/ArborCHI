"""
Letter assembly for condition C (BE-08, 红线 #1/#3).

The rule, from 开发手册 §4.3: a node the participant left alone reads its text
from `pregen/`; a node they renamed, re-parented or created is generated live.
Every sentence is stamped `source: "frozen" | "live"` and the two are visually
identical in the UI (红线 #3) -- the distinction exists for the analysis, which
asks whether people verify machine-written text differently depending on where
it came from. If the interface ever showed the difference, that question would
be answering itself.

**The server decides which is which.** The client sends the node states it has;
this module compares them against `tree.frozen.json` and reaches its own
conclusion. A client-supplied "I changed this" flag would be a claim about the
independent variable, made by the thing being measured.

What counts as changed, and why each one:

    title differs        the text argues a different point
    parent differs       the text sits under a different claim
    snippet set differs  the text cites different evidence
    node is new          there is nothing pre-generated to read

Merely accepting a proposed node is NOT a change: the participant endorsed what
was there, so the frozen text still describes it. Re-ordering is not a change
either -- position does not alter what a paragraph says.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..core import materials
from ..core.sentences import split_sentences
from .llm_client import call_llm_text

logger = logging.getLogger(__name__)

# Node states the client may report. `removed` nodes contribute no text.
NODE_STATES = ("proposed", "accepted", "edited", "removed")


class GenerationError(Exception):
    pass


def node_is_changed(
    node_id: str,
    submitted: Dict[str, Any],
    frozen: Dict[str, Dict[str, Any]],
) -> Tuple[bool, Optional[str]]:
    """(changed, reason). `reason` is logged and returned to the analysis."""
    original = frozen.get(node_id)
    if original is None:
        return True, "new_node"
    if (submitted.get("title") or "").strip() != (original.get("title") or "").strip():
        return True, "renamed"
    if submitted.get("parent_id") and submitted["parent_id"] != original.get("parent_id"):
        return True, "reparented"
    if set(submitted.get("snippet_ids") or []) != set(original.get("snippet_ids") or []):
        return True, "evidence_changed"
    return False, None


def assemble(
    node_states: Dict[str, Dict[str, Any]],
    *,
    material_id: str = "case_v1",
    generate_live: Optional[Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Build the letter. Returns {text, sentences, stats}.

    `generate_live` is injected so the decision path can be exercised without a
    network call; the default raises rather than silently substituting frozen
    text for a node that was changed, because that substitution would look like
    a successful generation while quietly falsifying `source`.
    """
    frozen = materials.frozen_nodes(material_id)
    tree = materials.load_bundle(material_id)["tree"]

    sentences: List[Dict[str, Any]] = []
    parts: List[str] = []
    counts = {"frozen": 0, "live": 0, "nodes_changed": 0, "nodes_total": 0}

    # Walk the tree's own order so paragraphs follow the argument structure
    # rather than whatever order the client happened to serialise.
    for arg in tree["arguments"]:
        heading_written = False
        for sub in arg["subs"]:
            node_id = sub["id"]
            submitted = node_states.get(node_id)
            if submitted is None or submitted.get("state") == "removed":
                continue

            counts["nodes_total"] += 1
            changed, reason = node_is_changed(node_id, submitted, frozen)

            if changed:
                counts["nodes_changed"] += 1
                if generate_live is None:
                    raise GenerationError(
                        f"node {node_id} was changed ({reason}) but no live "
                        f"generator is configured"
                    )
                node_sentences = generate_live(node_id, submitted)
                for s in node_sentences:
                    s["source"] = "live"
                    s["change_reason"] = reason
                    # A live sentence is new prose; nothing planted survives
                    # into it, and claiming otherwise would corrupt the probe.
                    s["planted_id"] = None
                counts["live"] += len(node_sentences)
            else:
                node_sentences = materials.pregen_sentences(node_id, material_id) or []
                counts["frozen"] += len(node_sentences)

            if not node_sentences:
                continue

            if not heading_written:
                parts.append(f"{arg['index']} {arg['title']}")
                heading_written = True

            for position, s in enumerate(node_sentences):
                s["subargument_id"] = node_id
                s["argument_id"] = arg["id"]
                s["position"] = len(sentences)
                s["position_in_node"] = position
                sentences.append(s)

            parts.append(" ".join(s["text"] for s in node_sentences))

    text = "\n\n".join(parts)
    return {"text": text, "sentences": sentences, "stats": counts}


# Parses "[Exhibit B2, p.5]" / "[Exhibit B2 p. 5]" back out of generated prose.
_CITE_PARTS = re.compile(r"\[Exhibit\s+([A-Za-z0-9\-]+)\s*,?\s*p\.?\s*(\d+)\s*\]")

_SYSTEM = """You are drafting one paragraph of an EB-1A petition letter.

Rules, all of them hard:
- Write only about the sub-argument you are given. Do not introduce other topics.
- Every factual claim must be supported by one of the supplied evidence excerpts
  and must carry its citation in the form [Exhibit B2, p.5] at the end of the
  sentence that makes the claim.
- Never state a fact the excerpts do not contain. Do not round, extrapolate or
  strengthen a number. If an excerpt says a team did something, do not write
  that the petitioner did it.
- Do not invent exhibit numbers or page numbers. Use only those supplied.
- Formal legal-brief register. No headings, no bullet points, no preamble, no
  closing remark. Output the paragraph and nothing else.
- 2 to 4 sentences."""


def _node_snippets(
    submitted: Dict[str, Any], material_id: str
) -> List[Dict[str, Any]]:
    """The evidence this node is allowed to cite, in the participant's order."""
    pool = materials.public_snippets(material_id).get("snippets") or {}
    out = []
    for sid in submitted.get("snippet_ids") or []:
        snip = pool.get(sid)
        if snip:
            out.append(snip)
    return out


def _build_prompt(
    node_id: str, submitted: Dict[str, Any], material_id: str,
) -> Tuple[str, List[Dict[str, Any]]]:
    bundle = materials.load_bundle(material_id)
    criterion = bundle["manifest"].get("criterion", "")
    snippets = _node_snippets(submitted, material_id)

    parent_title = ""
    for arg in bundle["tree"]["arguments"]:
        if arg["id"] == submitted.get("parent_id"):
            parent_title = arg["title"]
            break

    lines = [
        f"Criterion: {criterion}",
        f"Argument: {parent_title}" if parent_title else "",
        f"Sub-argument to draft: {submitted.get('title', node_id)}",
        "",
        "Evidence excerpts available (cite by exhibit and page exactly as shown):",
    ]
    for snip in snippets:
        lines.append(
            f"- [Exhibit {snip['exhibit']}, p.{snip['page']}] {snip['text']}"
        )
    if not snippets:
        # A node the participant stripped of evidence. Saying so beats letting
        # the model fill the gap from its own knowledge, which is exactly the
        # failure the planted-error measure would then be unable to distinguish.
        lines.append("- (none)")
    return "\n".join(line for line in lines if line != ""), snippets


def _sentences_from_text(
    node_id: str, text: str, snippets: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Turn generated prose into the same sentence records frozen text produces.

    Citations are parsed back out of the prose rather than asked for as
    structured ids: the model is reliable at repeating "[Exhibit B2, p.5]" that
    it was shown, and unreliable at inventing our internal snippet ids. Mapping
    (exhibit, page) -> snippet_id here means a hallucinated exhibit yields an
    empty snippet_ids list -- visible in the data -- instead of a plausible id
    pointing at the wrong excerpt.

    The splitter is the shared one (core/sentences.py), so a live sentence and a
    frozen sentence are divided by identical rules. 红线 #3 is about more than
    styling: if the two were segmented differently, sent_id lineage across an
    edit would mean different things depending on which kind of sentence it was.
    """
    by_ref = {(s["exhibit"], int(s["page"])): s["snippet_id"] for s in snippets}
    records: List[Dict[str, Any]] = []
    for i, sent in enumerate(split_sentences(text)):
        refs, ids = [], []
        for exhibit, page in _CITE_PARTS.findall(sent):
            ref = {"exhibit": exhibit, "page": int(page)}
            if ref not in refs:
                refs.append(ref)
            sid = by_ref.get((exhibit, int(page)))
            if sid and sid not in ids:
                ids.append(sid)
        records.append({
            "sent_id": f"{node_id}_{i}",
            "text": sent,
            "snippet_ids": ids,
            "exhibit_refs": refs,
            # Frozen text distinguishes claim/evidence sentences by hand. Live
            # text gets the same key with a value that says it was not judged,
            # rather than a guess that would be silently mixed into any
            # analysis grouping by sentence_type.
            "sentence_type": "unclassified",
        })
    return records


async def generate_live_sentences(
    node_id: str,
    submitted: Dict[str, Any],
    *,
    material_id: str = "case_v1",
) -> List[Dict[str, Any]]:
    """Generate one node's text with the LLM.

    Model and parameters come from the bundle manifest, not from settings: two
    participants must be working with the same system, and a deploy that
    changed the default model between them would otherwise go unrecorded.

    Reasoning models expose neither temperature nor seed, so this call is not
    replayable. That is recorded in the manifest's `reproducibility` field and
    is why only frozen text is used for anything the two conditions are
    compared on -- live text exists because a participant who restructures the
    tree must see their change reflected, not because it is measurable.
    """
    manifest = materials.load_bundle(material_id)["manifest"]
    params = manifest.get("model_params") or {}
    prompt, snippets = _build_prompt(node_id, submitted, material_id)

    try:
        text = await call_llm_text(
            prompt,
            system_prompt=_SYSTEM,
            provider=manifest.get("provider"),
            model=manifest.get("model"),
            max_tokens=params.get("max_output_tokens", 800),
            reasoning_effort=params.get("reasoning_effort"),
            caller="study_generator.live",
        )
    except Exception as e:                      # provider/config/network alike
        # Deliberately widened: assemble()'s contract is that a failure here
        # becomes a 503 the moderator can act on. Letting a provider exception
        # escape would surface as a 500 that reads like a bug in the study
        # platform rather than a missing key or a rate limit.
        raise GenerationError(f"live generation failed for {node_id}: {e}") from e

    text = (text or "").strip()
    if not text:
        raise GenerationError(f"live generation returned nothing for {node_id}")

    records = _sentences_from_text(node_id, text, snippets)
    if not records:
        raise GenerationError(f"live generation produced no sentences for {node_id}")
    return records


__all__ = ["GenerationError", "NODE_STATES", "node_is_changed", "assemble",
           "generate_live_sentences"]
