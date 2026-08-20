"""
Evidence coverage overview (Doc/01 M13 #2, plan 2.3.2).

Pure reporting -- states facts about the current structure, offers no
scores or recommendations (the paper's "no automatic judgement" principle):

    * snippets not referenced by any SubArgument (project-wide, per exhibit)
    * SubArguments backed by 0 or 1 snippet
    * per Standard: which extraction evidence layers
      (claim / proof / significance / context) have no assigned snippet

Everything is computed from legal_arguments.json + the extraction snippet
source; nothing is persisted.
"""

from collections import defaultdict
from typing import Any, Dict, List

LAYERS = ("claim", "proof", "significance", "context")


def compute_coverage(legal_args: Dict[str, Any], snippets: List[Dict[str, Any]]) -> Dict[str, Any]:
    arguments = legal_args.get("arguments", []) or []
    sub_arguments = legal_args.get("sub_arguments", []) or []

    by_id = {s.get("snippet_id"): s for s in snippets if s.get("snippet_id")}
    arg_by_id = {a.get("id"): a for a in arguments}

    assigned: set = set()
    per_standard: Dict[str, Dict[str, Any]] = {}

    def std_entry(key: str) -> Dict[str, Any]:
        if key not in per_standard:
            per_standard[key] = {
                "standard_key": key,
                "argument_count": 0,
                "subargument_count": 0,
                "snippet_count": 0,
                "single_evidence_subarguments": [],
                "empty_subarguments": [],
                "layer_counts": {layer: 0 for layer in LAYERS},
                "layer_gaps": [],
                "_snippet_ids": set(),
            }
        return per_standard[key]

    for a in arguments:
        e = std_entry(a.get("standard_key") or "unknown")
        e["argument_count"] += 1

    for sa in sub_arguments:
        arg = arg_by_id.get(sa.get("argument_id"))
        key = (arg or {}).get("standard_key") or "unknown"
        e = std_entry(key)
        e["subargument_count"] += 1
        ids = [sid for sid in (sa.get("snippet_ids") or []) if sid]
        assigned.update(ids)
        e["_snippet_ids"].update(ids)
        brief = {"id": sa.get("id"), "title": sa.get("title", ""), "argument_id": sa.get("argument_id"), "snippet_count": len(ids)}
        if len(ids) == 0:
            e["empty_subarguments"].append(brief)
        elif len(ids) == 1:
            e["single_evidence_subarguments"].append(brief)

    for e in per_standard.values():
        for sid in e["_snippet_ids"]:
            s = by_id.get(sid)
            layer = (s or {}).get("evidence_layer")
            if layer in e["layer_counts"]:
                e["layer_counts"][layer] += 1
        e["snippet_count"] = len(e["_snippet_ids"])
        e["layer_gaps"] = [layer for layer in LAYERS if e["layer_counts"][layer] == 0]
        del e["_snippet_ids"]

    unassigned = []
    by_exhibit: Dict[str, int] = defaultdict(int)
    for s in snippets:
        sid = s.get("snippet_id")
        if not sid or sid in assigned:
            continue
        exhibit = s.get("exhibit_id", "")
        by_exhibit[exhibit] += 1
        text = s.get("text", "") or ""
        unassigned.append({
            "snippet_id": sid,
            "exhibit_id": exhibit,
            "page": s.get("page"),
            "evidence_type": s.get("evidence_type"),
            "evidence_layer": s.get("evidence_layer"),
            "is_applicant_achievement": s.get("is_applicant_achievement"),
            "text": text[:160] + ("..." if len(text) > 160 else ""),
        })

    return {
        "totals": {
            "snippets": len(by_id),
            "assigned_snippets": len(assigned & set(by_id)),
            "unassigned_snippets": len(unassigned),
            "arguments": len(arguments),
            "sub_arguments": len(sub_arguments),
        },
        "unassigned_by_exhibit": dict(sorted(by_exhibit.items())),
        "unassigned_snippets": unassigned,
        "standards": sorted(per_standard.values(), key=lambda e: e["standard_key"]),
    }
