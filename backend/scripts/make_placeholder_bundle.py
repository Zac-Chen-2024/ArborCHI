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
PRACTICE_OUT = ROOT / "study_materials" / "practice_v1"

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
# `doc_title` / `doc_subtitle` are what the page header prints; `rel` are the
# factual triples the relations panel shows (C-07). The triples are STATEMENTS
# extracted from the document -- subject / predicate / object -- and carry no
# evaluative field. There is deliberately nowhere here to put "this looks
# weak": the panel states what the document says and the judgement stays with
# the participant.
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


# doc header + factual triples, keyed by snippet id
DOC_META = {'c1': ('NORTHWIND DATA SYSTEMS', 'Annual Report 2023', [['Northwind Data Systems', 'annual revenue', '$320M'], ['Northwind Data Systems', 'employees', '1,800'], ['Northwind Data Systems', 'offices', '11']]),
    'c2': ('DATA INFRASTRUCTURE REVIEW', 'Vendor of the Year - 2023', [['Northwind Data Systems', 'named', 'Data Infrastructure Vendor of the Year'], ['Awarded by', 'is', 'Data Infrastructure Review']]),
    'c3': ('DATA INFRASTRUCTURE REVIEW', 'Market Coverage', [['Northwind Data Systems', 'serves', '13 of the 20 largest North American retailers']]),
    'c4': ('NORTHWIND DATA SYSTEMS', 'Organizational Chart - Research & Development', [['Dr. Wei Li', 'holds title', 'Director of AI Research'], ['AI Research division', 'reports to', 'Marcus Reed - CTO'], ['Dr. Wei Li', 'manages', '4 teams - 47 researchers']]),
    'c5': ('NORTHWIND DATA SYSTEMS', 'Delegation of Authority', [['Dr. Wei Li', 'approval authority over', '$12M annual division budget']]),
    'c6': ('LETTER OF RECOMMENDATION', 'Marcus Reed - Chief Technology Officer', [['Dr. Wei Li', 'led', 'retrieval infrastructure rebuild'], ['That project', 'resulted in', '60% lower median query latency'], ['Recommender', 'is', 'Marcus Reed - CTO']]),
    'c7': ('INTERNAL MEMORANDUM', 'Project Atlas - Delivery Review', [['Dr. Wei Li', 'initiated and led', 'Project Atlas'], ['Project Atlas', 'delivered', '2022 Q3']]),
    'c8': ('ACM SIGMOD', 'Best Paper Award - 2022', [['Dr. Wei Li', 'received', 'SIGMOD 2022 Best Paper Award'], ['Awarded by', 'is', 'ACM SIGMOD']]),
    'c9': ('VLDB 2023', 'Program Committee Invitation', [['Dr. Wei Li', 'invited to serve on', 'VLDB 2023 Program Committee']]),
    'c10': ('VLDB 2023', 'Registration Summary', [['2023 meeting', 'registered attendees', '2,140']])}


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


# ---------------------------------------------------------------------------
# Practice bundle (BE-18)
# ---------------------------------------------------------------------------
#
# A DIFFERENT criterion on purpose. If practice used the real case, the
# participant would arrive at the task having already read the exhibits, and
# the first minutes of the measured phase would be spent on material they know
# -- which is exactly the part of the session where the two conditions differ
# most. Small, too: practice is for learning the controls, not for practising
# the judgement.
#
# It carries NO planted errors. Practice is where someone learns that the
# magnifier exists; discovering a planted error there would teach them the task
# has traps, and they would go into the real one hunting.
PRACTICE_CRITERION = "Original Contributions of Major Significance"
PRACTICE_CFR = "8 C.F.R. §204.5(h)(3)(v)"

PRACTICE_EXHIBITS = [
    {"id": "P1", "pages": 3, "title": "Patent grant - adaptive indexing"},
    {"id": "P2", "pages": 2, "title": "Industry adoption memo"},
]

PRACTICE_SNIPPETS = {
    "q1": dict(ex="P1", page=2, label="Patent granted 2021",
               text="US Patent 11,204,881 was granted in 2021 for an adaptive indexing method.",
               bbox=[120, 300, 880, 360],
               doc=("UNITED STATES PATENT OFFICE", "Grant Notice - 2021")),
    "q2": dict(ex="P2", page=1, label="Adopted by four vendors",
               text="Four independent vendors adopted the indexing method within two years.",
               bbox=[110, 420, 870, 478],
               doc=("INDUSTRY ADOPTION MEMO", "Two-year review")),
}

PRACTICE_TREE = {
    "tree_variant_id": "practice-v0",
    "criterion": PRACTICE_CRITERION,
    "arguments": [{
        "id": "pa1", "index": "①",
        "title": "The contribution is original",
        "rationale": "Establish novelty before significance",
        "subs": [
            {"id": "ps1", "title": "Granted patent", "snippet_ids": ["q1"], "distractor": False},
            {"id": "ps2", "title": "Independent adoption", "snippet_ids": ["q2"], "distractor": False},
        ],
    }],
}

PRACTICE_PREGEN = {
    "ps1": [("US Patent 11,204,881 was granted in 2021 for an adaptive indexing method.",
             ["q1"], "evidence", None)],
    "ps2": [("Four independent vendors adopted the method within two years of the grant.",
             ["q2"], "evidence", None)],
}


def write_practice() -> None:
    write(PRACTICE_OUT / "snippets.json", {
        "schema_version": 1,
        "bbox_space": 1000,
        "exhibits": PRACTICE_EXHIBITS,
        "snippets": {
            sid: {"snippet_id": sid, "exhibit": s["ex"], "page": s["page"],
                  "bbox": s["bbox"], "label": s["label"], "text": s["text"],
                  "doc_title": s["doc"][0], "doc_subtitle": s["doc"][1]}
            for sid, s in PRACTICE_SNIPPETS.items()
        },
    })
    write(PRACTICE_OUT / "relations.json", {
        "schema_version": 1,
        "focus_entity": "Dr. Wei Li",
        "relations": {
            "q1": [{"subject": "US Patent 11,204,881", "predicate": "granted",
                    "object": "2021"}],
            "q2": [{"subject": "Indexing method", "predicate": "adopted by",
                    "object": "four independent vendors"}],
        },
        "other_mentions": {"Dr. Wei Li": [{"exhibit": "P1", "page": 2}]},
    })
    write(PRACTICE_OUT / "tree.frozen.json", PRACTICE_TREE)
    # Empty, not absent: the loader expects the file, and "no planted errors"
    # is a statement the bundle should make rather than leave to inference.
    write(PRACTICE_OUT / "planted.json", {"schema_version": 1, "items": []})

    for node_id, sentences in PRACTICE_PREGEN.items():
        write(PRACTICE_OUT / "pregen" / f"{node_id}.json", {
            "schema_version": 1,
            "node_id": node_id,
            "sentences": [{
                "sent_id": f"{node_id}_{i}",
                "text": f"{text} " + " ".join(
                    f"[Exhibit {PRACTICE_SNIPPETS[s]['ex']}, p.{PRACTICE_SNIPPETS[s]['page']}]"
                    for s in snips),
                "snippet_ids": snips,
                "exhibit_refs": [{"exhibit": PRACTICE_SNIPPETS[s]["ex"],
                                  "page": PRACTICE_SNIPPETS[s]["page"]} for s in snips],
                "sentence_type": stype,
                "source": "frozen",
                "planted_id": planted,
            } for i, (text, snips, stype, planted) in enumerate(sentences)],
        })

    write(PRACTICE_OUT / "manifest.json", {
        "schema_version": 1,
        "material_id": "practice_v1",
        "placeholder": True,
        "practice": True,
        "_comment": "Practice bundle (BE-18): a different criterion, no planted errors.",
        "criterion": PRACTICE_CRITERION,
        "cfr": PRACTICE_CFR,
        "tree_variant_id": PRACTICE_TREE["tree_variant_id"],
        "model": "placeholder",
        "model_params": {"temperature": 0.0, "max_tokens": 400},
        "seed": 0,
        "frozen_at": None,
    })


def main() -> int:
    write(OUT / "snippets.json", {
        "schema_version": 1,
        "bbox_space": 1000,
        "_comment": "bbox is normalised to a 1000x1000 space (红线 #8), not pixels.",
        "exhibits": EXHIBITS,
        "snippets": {
            sid: {"snippet_id": sid, "exhibit": s["ex"], "page": s["page"],
                  "bbox": s["bbox"], "label": s["label"], "text": s["text"],
                  "doc_title": DOC_META[sid][0], "doc_subtitle": DOC_META[sid][1]}
            for sid, s in SNIPPETS.items()
        },
    })

    # relations.json: facts only. C-07 forbids any warning or evaluative state,
    # and the way to make that hold is to have no field it could live in.
    write(OUT / "relations.json", {
        "schema_version": 1,
        "focus_entity": "Dr. Wei Li",
        "relations": {sid: [{"subject": a, "predicate": p, "object": o}
                            for a, p, o in DOC_META[sid][2]]
                      for sid in SNIPPETS},
        "other_mentions": {
            "Dr. Wei Li": [
                {"exhibit": "A3", "page": 1}, {"exhibit": "C1", "page": 1},
                {"exhibit": "C2", "page": 3}, {"exhibit": "E2", "page": 2},
            ],
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

    write_practice()

    for out in (OUT, PRACTICE_OUT):
        files = sorted(str(p.relative_to(out)).replace(os.sep, "/")
                       for p in out.rglob("*.json"))
        print(f"wrote {len(files)} files to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
