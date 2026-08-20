#!/usr/bin/env python
"""
Emit the PLACEHOLDER material bundle at backend/study_materials/case_v1/.

    python scripts/make_placeholder_bundle.py

Why a generator rather than hand-written JSON: the bundle must be reproducible
byte-for-byte, and a script is reviewable in a way that six parallel JSON files
are not. When the real material lands (data/Dehuan Liu, 64 exhibits), this
script is replaced by the OT-01/OT-02 pipeline -- fixed seed, five candidate
trees, the pre-registered selection rule (docs/预注册 PR-1) -- and the output
directory keeps the same shape, so nothing downstream changes.

⚠️ EVERYTHING HERE IS PLACEHOLDER. The case is invented (Northwind / Dr. Wei
Li), it mirrors study-app/src/data/fixtures.ts so the two ends agree during
development, and `manifest.placeholder` is true so any run against it is
identifiable in the logs. No real participant may ever run on this bundle.

The tree and the planted registry carry fields that must NEVER reach the
frontend -- `distractor` on nodes, `planted_id` on sentences. They live here
because the analysis needs them; the API strips them (see materials.py's
public_* functions and the audit that guards it).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "study_materials" / "case_v1"

CRITERION = "Leading or Critical Role"
CFR = "8 C.F.R. §204.5(h)(3)(viii)"

# --- exhibits ---------------------------------------------------------------
EXHIBITS = [
    {"id": "A3", "pages": 2, "title": "ACM SIGMOD - Best Paper Award"},
    {"id": "B1", "pages": 6, "title": "Organisational chart and delegation of authority"},
    {"id": "B2", "pages": 8, "title": "Annual Report 2023"},
    {"id": "C1", "pages": 3, "title": "Letter of recommendation - Marcus Reed"},
    {"id": "C2", "pages": 5, "title": "Internal memorandum - Project Atlas"},
    {"id": "D1", "pages": 4, "title": "Data Infrastructure Review - Vendor of the Year"},
    {"id": "E2", "pages": 4, "title": "VLDB 2023 - Programme committee invitation"},
]

# --- snippets ---------------------------------------------------------------
# bbox is NORMALISED to a 1000x1000 space (红线 #8). Never pixels: the same
# snippet has to land correctly at every zoom level and render width, and the
# page dimensions that pixels would need are not in the OCR output.
SNIPPETS = {
    "c1": dict(ex="B2", page=5, label="Revenue $320M - 1,800 employees",
               text="Global revenue reached $320M in FY2023, with 1,800 employees across eleven offices.",
               bbox=[120, 340, 880, 400]),
    "c2": dict(ex="D1", page=1, label="Data Infrastructure Vendor of the Year",
               text="Northwind Data Systems was named Data Infrastructure Vendor of the Year for 2023.",
               bbox=[110, 220, 890, 275]),
    "c3": dict(ex="D1", page=3, label="13 of the 20 largest retailers in North America",
               text="Its platform serves 13 of the 20 largest retailers in North America.",
               bbox=[110, 500, 870, 552]),
    "c4": dict(ex="B1", page=2, label="Reports to the CTO - 4 teams, 47 people",
               text="The Director of AI Research reports directly to the Chief Technology Officer and oversees four research teams comprising 47 researchers.",
               bbox=[100, 300, 900, 395]),
    "c5": dict(ex="B1", page=4, label="Final approval over a $12M budget",
               text="Final approval authority over the division's $12M annual R&D budget rests with the Director of AI Research.",
               bbox=[100, 415, 900, 490]),
    "c6": dict(ex="C1", page=1, label="Retrieval rebuild cut query latency 60%",
               text="The retrieval infrastructure rebuild that Dr. Li led reduced median query latency by 60% across our platform.",
               bbox=[130, 380, 870, 455]),
    "c7": dict(ex="C2", page=3, label="Led Project Atlas - delivered 2022 Q3",
               text="Project Atlas was initiated and led by Dr. Li, and was delivered in Q3 2022.",
               bbox=[120, 260, 880, 315]),
    "c8": dict(ex="A3", page=1, label="SIGMOD 2022 Best Paper Award",
               text="Best Paper Award presented to Dr. Wei Li et al. for “Efficient Query Processing in Large-Scale Distributed Databases.”",
               bbox=[140, 430, 860, 505]),
    "c9": dict(ex="E2", page=2, label="VLDB 2023 programme committee invitation",
               text="We invite Dr. Wei Li to serve on the Program Committee for VLDB 2023.",
               bbox=[130, 300, 870, 355]),
    # Not attached to any node: the unused-evidence pool (C-06).
    "c10": dict(ex="E2", page=4, label="Conference registration figures",
                text="Registration for the 2023 meeting totalled 2,140 attendees.",
                bbox=[130, 610, 870, 662]),
}

# --- frozen tree ------------------------------------------------------------
# `distractor` marks a node the pre-registration counts as cross-statute noise.
# SERVER-SIDE ONLY -- see the module docstring.
TREE = {
    "tree_variant_id": "placeholder-v0",
    "criterion": CRITERION,
    "arguments": [
        {
            "id": "a1", "index": "①",
            "title": "The organisation has a distinguished reputation",
            "rationale": "Establish the standing of the organisation before the individual role",
            "subs": [
                {"id": "s1", "title": "Scale and market position",
                 "snippet_ids": ["c1", "c2"], "distractor": False},
                {"id": "s2", "title": "Industry recognition and client coverage",
                 "snippet_ids": ["c3"], "distractor": False},
            ],
        },
        {
            "id": "a2", "index": "②",
            "title": "The petitioner performs a leading role within it",
            "rationale": "Argue hierarchical position, decision authority and actual impact",
            "subs": [
                {"id": "s3", "title": "Position in the hierarchy and reporting line",
                 "snippet_ids": ["c4"], "distractor": False},
                {"id": "s4", "title": "Decision and resource authority",
                 "snippet_ids": ["c5"], "distractor": False},
                {"id": "s5", "title": "Quantified impact of the leadership",
                 "snippet_ids": ["c6", "c7"], "distractor": False},
                # Academic honours belong to a different criterion; the frozen
                # tree includes them so the participant has something real to
                # judge. Nothing in the UI marks it.
                {"id": "s6", "title": "Academic honours corroborating professional standing",
                 "snippet_ids": ["c8", "c9"], "distractor": True},
            ],
        },
    ],
}

# --- planted errors ---------------------------------------------------------
# The probe's ground truth (PR-2). SERVER-SIDE ONLY.
#
# `kind` is what is wrong with the sentence, not how wrong: the analysis codes
# severity separately, and baking a severity in here would freeze a judgement
# that has not been made yet.
PLANTED = {
    "schema_version": 1,
    "items": [
        {"planted_id": "p1", "node_id": "s1", "kind": "overstated",
         "note": "claims a figure larger than the exhibit supports"},
        {"planted_id": "p2", "node_id": "s3", "kind": "wrong_exhibit",
         "note": "cites an exhibit that does not contain the claim"},
        {"planted_id": "p3", "node_id": "s5", "kind": "unsupported_causal",
         "note": "asserts a causal link the exhibit only describes as temporal"},
    ],
}

# --- pre-generated node text ------------------------------------------------
# One file per node. `source: "frozen"` on every sentence here; a node the
# participant edits is regenerated live and its sentences carry "live" instead.
PREGEN = {
    "s1": [
        ("Northwind Data Systems is a data-infrastructure firm reporting $320M in revenue and 1,800 employees across eleven offices.",
         ["c1"], "claim", None),
        ("The company was named Data Infrastructure Vendor of the Year for 2023, placing it among the top five vendors worldwide.",
         ["c2"], "evidence", "p1"),
    ],
    "s2": [
        ("Its platform serves 13 of the 20 largest retailers in North America.", ["c3"], "evidence", None),
    ],
    "s3": [
        ("As Director of AI Research at Northwind Data Systems, Dr. Li reported directly to the Chief Technology Officer and oversaw four research teams comprising 47 researchers.",
         ["c4"], "claim", None),
        ("This reporting line is documented in the company's delegation of authority.", ["c5"], "evidence", "p2"),
    ],
    "s4": [
        ("Dr. Li held final approval authority over the division's $12M annual research and development budget.",
         ["c5"], "claim", None),
    ],
    "s5": [
        ("The retrieval infrastructure rebuild that Dr. Li led reduced median query latency by 60% across the platform.",
         ["c6"], "claim", None),
        ("Because of Project Atlas, which Dr. Li initiated and led, the company's Q3 2022 revenue rose.",
         ["c7"], "evidence", "p3"),
    ],
    "s6": [
        ("Dr. Li's SIGMOD 2022 Best Paper Award further underscores his professional standing.", ["c8"], "evidence", None),
        ("He was invited to serve on the VLDB 2023 Program Committee.", ["c9"], "evidence", None),
    ],
}


def cite(snippet_ids):
    return " ".join(
        f"[Exhibit {SNIPPETS[s]['ex']}, p.{SNIPPETS[s]['page']}]" for s in snippet_ids
    )


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    write(OUT / "snippets.json", {
        "schema_version": 1,
        "bbox_space": 1000,
        "_comment": "bbox is normalised to a 1000x1000 space (红线 #8), not pixels.",
        "exhibits": EXHIBITS,
        "snippets": {
            sid: {"snippet_id": sid, "exhibit": s["ex"], "page": s["page"],
                  "bbox": s["bbox"], "label": s["label"], "text": s["text"]}
            for sid, s in SNIPPETS.items()
        },
    })

    write(OUT / "tree.frozen.json", TREE)
    write(OUT / "planted.json", PLANTED)

    for node_id, sentences in PREGEN.items():
        write(OUT / "pregen" / f"{node_id}.json", {
            "schema_version": 1,
            "node_id": node_id,
            "sentences": [
                {
                    "sent_id": f"{node_id}_{i}",
                    "text": f"{text} {cite(snips)}",
                    "snippet_ids": snips,
                    "exhibit_refs": [
                        {"exhibit": SNIPPETS[s]["ex"], "page": SNIPPETS[s]["page"]}
                        for s in snips
                    ],
                    "sentence_type": stype,
                    "source": "frozen",
                    "planted_id": planted,
                }
                for i, (text, snips, stype, planted) in enumerate(sentences)
            ],
        })

    write(OUT / "manifest.json", {
        "schema_version": 1,
        "material_id": "case_v1",
        "placeholder": True,
        "_comment": (
            "PLACEHOLDER. Invented case, generated by "
            "scripts/make_placeholder_bundle.py. No participant may run on this. "
            "Replaced at M5 by the OT pipeline over data/Dehuan Liu."
        ),
        "criterion": CRITERION,
        "cfr": CFR,
        "tree_variant_id": TREE["tree_variant_id"],
        # Pinned generation parameters. Every live-generated sentence in a
        # session must come from exactly these, or two participants are not
        # working with the same system.
        "model": "placeholder",
        "model_params": {"temperature": 0.0, "max_tokens": 800},
        "seed": 0,
        "frozen_at": None,
        "candidate_trees_archived": 0,
        "selection_rule": "docs/预注册_pre-registration.md PR-1",
    })

    files = sorted(str(p.relative_to(OUT)).replace(os.sep, "/")
                   for p in OUT.rglob("*.json"))
    print(f"wrote {len(files)} files to {OUT}")
    for f in files:
        print("  " + f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
