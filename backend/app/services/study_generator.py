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
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..core import materials

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

    NOT WIRED UP YET. The provider is deliberately unchosen (the LLM decision is
    still open), and the prompt asset lands with the real bundle at M5. Until
    then this raises, and `assemble` is called with an injected generator in
    tests -- which is enough to prove the frozen/live decision path, the
    stamping and 红线 #1, all of which are what M1 has to demonstrate.
    """
    manifest = materials.load_bundle(material_id)["manifest"]
    raise GenerationError(
        f"live generation is not configured yet (node {node_id}, "
        f"model={manifest.get('model')!r}); see M5"
    )


__all__ = ["GenerationError", "NODE_STATES", "node_is_changed", "assemble",
           "generate_live_sentences"]
