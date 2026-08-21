"""Build a study material bundle from the OCR of a real petition file.

Criterion: **Judging the work of others**, 8 C.F.R. §204.5(h)(3)(iv).

## Why this criterion and these exhibits

The source file (`data/Dehuan Liu`) is a real person's immigration case. Most
of its exhibit groups mix public record with private documents -- support
letters, an internal appointment order, a commercial contract carrying a mobile
number, a salary certificate carrying a national ID number. Group C is the one
whose evidence is public throughout: award-committee certificates, an industry
association's own "about" pages, and news coverage in Sohu, China Daily and PR
Newswire. Exhibit C-10 is the single exception (a private email) and is left
out; nothing else in the group needed removing.

That choice is not cosmetic. A participant reads every exhibit closely -- that
is the task -- and 24 of them will do so. Material that is already published is
the only kind this study has any business putting in front of them.

## bbox

Passed through unchanged. The OCR emits a 0-1000 grid, which is the space the
bundle already uses (红线 #8); verified across all 2,286 blocks in this corpus
(x in [0, 999], y in [0, 1000]). No page dimensions are needed and none are
available.

## Snippets are chosen by hand

Each entry below names the block by a phrase that occurs in it. An evidence
card has to be one quotable claim with a box a participant can be shown, and
that is a judgement about the argument, not something to scrape. The script's
job is to resolve the phrase to the block's exact text and box, and to fail
loudly if a phrase stops matching -- silently dropping an exhibit would leave a
sub-argument standing on evidence that is no longer there.
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OCR_ROOT = Path(r"F:/Python-Project/Arbor_CHI_2027/data/Dehuan Liu/OCR/ocr_results_l")
OUT = Path(__file__).resolve().parents[1] / "study_materials" / "judging_v1"

CRITERION = "Judging the Work of Others"
CFR = "8 C.F.R. §204.5(h)(3)(iv)"
CASE_LABEL = "EB-1A · Prof. Dehuan Liu"
FOCUS_ENTITY = "Prof. Dehuan Liu"

# Display ids. The source directories are lower case (c1); the petition itself
# numbers them C-1, and that is what a citation has to say for a participant to
# find the exhibit in front of them.
EXHIBIT_TITLES = {
    "c1": "Certificate of appointment - 13th Tiger Roar Awards Organizing Committee",
    "c2": "China Advertising Association of Commerce - About CAAC",
    "c3": "Sohu - Final review of the 13th Tiger Roar Award",
    "c4": "China Daily - The 2022 Tiger Roar Awards successfully concluded",
    "c5": "PR Newswire - ZEISS Vision wins Silver at the 13th Tiger Roar Awards",
    "c6": "Tsinghua University - Faculty page, Prof. Liping Sun",
    "c7": "Certificate of appointment - Judge, First China Digital Marketing Conference",
    "c8": "The First China Digital Marketing Conference will be held on January 21st",
    "c9": "CAAC - Digital Marketing Committee of China established in Beijing",
    "g5": "Peking University Press - Market Research and Application",
    "d8": "New Rules of Advertising Communication: From AIDMA, AISAS to ISMAS",
}

# (snippet_id, exhibit, page, locating phrase, label, doc_title, doc_subtitle)
SNIPPETS = [
    # -- the competitions themselves --------------------------------------
    ("k1", "c2", 2, "ever first national association",
     "CAAC founded 1981 - first national body",
     "CHINA ADVERTISING ASSOCIATION OF COMMERCE", "About CAAC"),
    ("k2", "c2", 5, "The 11th Council of CAAC was elected",
     "11th Council elected Dec 2021",
     "CHINA ADVERTISING ASSOCIATION OF COMMERCE", "About CAAC"),
    ("k3", "c4", 2, "On August 19th, the 13th Tiger Roar Awards ceremony",
     "13th ceremony, Aug 19, sponsored by CAAC",
     "CHINA DAILY", "The 2022 Tiger Roar Awards Successfully Concluded"),
    ("k4", "c5", 3, "most professionally influential comprehensive award",
     "650+ public jury, 90+ final reviewers",
     "PR NEWSWIRE", "ZEISS Vision Won the Silver Award"),
    ("k5", "c3", 2, "416 shortlisted companies",
     "92 final judges, 416 companies, 1,000+ cases",
     "SOHU", "Final Review of the 13th Tiger Roar Award"),
    ("k6", "c5", 2, "Award Ceremony of",
     "Ceremony held in Beijing, Aug 19, 2022",
     "PR NEWSWIRE", "ZEISS Vision Won the Silver Award"),
    ("k7", "c9", 2, "On Aug. 14, 2015",
     "Digital Marketing Committee founded Aug 2015",
     "CHINA ADVERTISING ASSOCIATION OF COMMERCE", "Digital Marketing Committee established"),
    ("k8", "c9", 5, "NetEase was elected as the Chairman Entity",
     "NetEase chairs; Li Li, CEO of NetEase Media",
     "CHINA ADVERTISING ASSOCIATION OF COMMERCE", "Digital Marketing Committee established"),
    ("k9", "c8", 2, "will be Held on January 21st",
     "First conference held January 21",
     "DIGITAL MARKETING COMMITTEE OF CHINA", "Conference announcement"),

    # -- the petitioner's role in judging ----------------------------------
    ("k10", "c1", 2, "appointed as the Deputy Director",
     "Appointed Deputy Director of the Organizing Committee",
     "TIGER ROAR AWARDS", "Certificate of appointment, Apr. 2022"),
    ("k11", "c1", 2, "Executive President: Xubin Chen",
     "Signed by Executive President Xubin Chen",
     "TIGER ROAR AWARDS", "Certificate of appointment, Apr. 2022"),
    ("k12", "c7", 2, "Judge Dehuan Liu",
     "Named as Judge on the conference certificate",
     "DIGITAL MARKETING COMMITTEE OF CHINA", "Certificate, Beijing, Jan. 2016"),
    ("k13", "c3", 6, "Founder of Tiger Roar Award, sincerely expressed",
     "Xubin Chen, founder, addressed the judges",
     "SOHU", "Final Review of the 13th Tiger Roar Award"),
    ("k14", "c3", 7, "Chairman of the jury, shared breakthroughs",
     "Xiaodong Zheng, Chairman of the Jury",
     "SOHU", "Final Review of the 13th Tiger Roar Award"),
    ("k15", "c3", 5, "92 judges for final review gathered online",
     "92 judges appointed one by one, online",
     "SOHU", "Final Review of the 13th Tiger Roar Award"),

    # -- cross-criterion --------------------------------------------------
    #
    # Real evidence from this filing that belongs to OTHER criteria: a peer's
    # research record, the petitioner's own authorship, his own scholarship.
    # None of it evidences judging the work of others.
    #
    # It is in the pool on purpose. PR-1 discards any candidate tree that hangs
    # fewer than two of these under this criterion, because the distractor node
    # is what C-14 and 红线 #5 are about -- a sub-argument that does not belong,
    # rendered exactly like one that does. With only one such snippet available
    # the filter could never bite, so three are supplied.
    ("k16", "c6", 2, "mainly engages in research on social modernization",
     "Prof. Liping Sun's research record",
     "TSINGHUA UNIVERSITY", "School of Social Science - Faculty"),
    ("k17", "g5", 3, "holds a Ph.D. in Sociology from Peking University",
     "Biography: Vice Dean, PKU Journalism & Communication",
     "PEKING UNIVERSITY PRESS", "Market Research and Application - About the author"),
    ("k18", "d8", 2, "Every business is rooted in information asymmetry",
     "Authored article: from AIDMA and AISAS to ISMAS",
     "PEKING UNIVERSITY", "New Rules of Advertising Communication"),
]

# Snippets that evidence a DIFFERENT criterion. Not shipped to the client --
# this is the answer key for the distractor check (红线 #5), used by the tree
# selection script and never by anything the participant can reach.
#
# k16 (Prof. Liping Sun's faculty page) was listed here until the filed brief
# turned up. The brief uses it INSIDE this criterion -- "Dr. Liping Sun ... also
# participated in the Tiger Roar Awards selection with Dr. Liu" -- as evidence
# of the calibre of the panel he sat on. Calling it off-criterion was my reading,
# and the attorney's reading is the one that counts.
#
# What is left is genuinely off-criterion: a biography evidencing his leading
# role (§(h)(3)(viii)) and one of his own articles evidencing authorship
# (§(h)(3)(vi)). Two, which is exactly PR-1's threshold.
CROSS_CRITERION = {"k17", "k18"}

# Subject/predicate/object per snippet, for the relations panel. Written out
# rather than extracted: a wrong triple here is a wrong claim shown to a
# participant as if the material said it.
RELATIONS = {
    "k1": [("China Advertising Association of Commerce", "founded", "1981"),
           ("China Advertising Association of Commerce", "is", "first national advertising association in China")],
    "k2": [("11th Council of CAAC", "elected", "21 December 2021")],
    "k3": [("13th Tiger Roar Awards", "sponsored by", "China Advertising Association of Commerce"),
           ("13th Tiger Roar Awards ceremony", "held", "19 August, Beijing")],
    "k4": [("13th Tiger Roar Award", "public jury", "650+"),
           ("13th Tiger Roar Award", "final review judges", "90+")],
    "k5": [("13th Tiger Roar Award", "final review judges", "92"),
           ("13th Tiger Roar Award", "shortlisted companies", "416"),
           ("13th Tiger Roar Award", "case works", "over 1,000")],
    "k6": [("13th Tiger Roar Award ceremony", "date", "19 August 2022"),
           ("ZEISS Vision", "won", "Silver, Marketing Case category")],
    "k7": [("Digital Marketing Committee of China", "established", "14 August 2015, Beijing"),
           ("Digital Marketing Committee of China", "under", "China Advertising Association of Commerce")],
    "k8": [("NetEase", "elected", "Chairman Entity"),
           ("Li Li", "is", "CEO of NetEase Media Group")],
    "k9": [("First China Digital Marketing Conference", "held", "21 January")],
    "k10": [(FOCUS_ENTITY, "appointed", "Deputy Director, 13th Tiger Roar Awards Organizing Committee")],
    "k11": [("Xubin Chen", "is", "Executive President")],
    "k12": [(FOCUS_ENTITY, "served as", "Judge, First China Digital Marketing Conference")],
    "k13": [("Xubin Chen", "is", "Founder of Tiger Roar Award")],
    "k14": [("Xiaodong Zheng", "is", "Chairman of the Jury")],
    "k15": [("13th Tiger Roar Award", "final review judges", "92")],
    "k16": [("Liping Sun", "is", "Professor of Sociology, Tsinghua University")],
    "k17": [(FOCUS_ENTITY, "is", "Vice Dean, School of Journalism and Communication, PKU"),
            (FOCUS_ENTITY, "holds", "Ph.D. in Sociology, Peking University")],
    "k18": [(FOCUS_ENTITY, "authored", "New Rules of Advertising Communication")],
}

CJK = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]+")
# LaTeX-ish superscripts the OCR leaves behind: \(13^{\text{th}}\) -> 13th
SUPER = re.compile(r"\\\(\s*(\d+)\s*\^\{?\\?\w*\{?(\w+)\}?\}?\s*\\\)")


def clean(text: str) -> str:
    """Plain English prose, as a participant will read it.

    The corpus is a bilingual filing, so a block often carries the Chinese
    original and its translation in one box. The study runs in English (PR-5),
    and a participant who cannot read the Chinese half would be judging a
    sentence against evidence they can only half see.
    """
    text = SUPER.sub(r"\1\2", text)
    text = text.replace("\\(", "").replace("\\)", "")
    text = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", text)
    # Bare TeX commands the OCR emits for symbols: "ZEISS \times iG".
    text = text.replace("\\times", "x")
    text = re.sub(r"\\[a-zA-Z]+", " ", text)
    text = CJK.sub(" ", text)
    text = re.sub(r"^\s*#+\s*", "", text)
    text = re.sub(r"\s*\|\s*", " ", text)
    text = text.replace("_", " ")
    # The OCR breaks a hyphenated word across a line and leaves the space in:
    # "high- quality", "down- to- earth". A participant comparing a sentence
    # against the excerpt word by word should not have to read around that.
    text = re.sub(r"(\w)- (\w)", r"\1-\2", text)
    # A date whose Chinese half has just been removed leaves its digits
    # stranded at the front: "2021 12 21 The 11th Council was elected ...".
    text = re.sub(r"^(?:\d{1,4}\s+){2,}(?=[A-Za-z])", "", text)
    return " ".join(text.split())


def blocks(exhibit: str, page: int):
    path = OCR_ROOT / exhibit / f"page_{page}.json"
    if not path.exists():
        raise SystemExit(f"no OCR for {exhibit} page {page}")
    return json.loads(path.read_text(encoding="utf-8")).get("text_blocks") or []


def page_count(exhibit: str) -> int:
    return len(glob.glob(str(OCR_ROOT / exhibit / "page_*.json")))


def display(exhibit: str) -> str:
    """c1 -> C-1, matching how the petition numbers its exhibits."""
    m = re.match(r"([a-z]+)(\d+)", exhibit)
    return f"{m.group(1).upper()}-{m.group(2)}"


# The petitioner as the corpus writes him. Both orders appear: Chinese sources
# translate as "Liu Dehuan", the English filing uses "Dehuan Liu".
NAME_FORMS = ("Dehuan Liu", "Liu Dehuan", "LIU Dehuan", "Liu, Dehuan")


def other_mentions(exhibits: set) -> list:
    """Every page in this bundle that names the petitioner.

    Feeds the relations panel's "he is also named here" list, which is a
    navigation aid, not an assessment (C-07). Derived rather than hand-listed:
    a page that mentions him and is missing from this list is a place the
    participant is quietly not told to look.
    """
    out = []
    for ex in sorted(exhibits, key=lambda s: (s[0], int(s[1:]))):
        for path in sorted(glob.glob(str(OCR_ROOT / ex / "page_*.json")),
                           key=lambda p: int(re.search(r"(\d+)", Path(p).name).group(1))):
            page = json.loads(Path(path).read_text(encoding="utf-8"))
            text = page.get("markdown_text") or ""
            if any(form in text for form in NAME_FORMS):
                out.append({"exhibit": display(ex), "page": page["page_number"]})
    return out


def build() -> None:
    snippets, missing = {}, []
    used_exhibits = set()

    for sid, ex, page, phrase, label, doc_title, doc_sub in SNIPPETS:
        hit = None
        for b in blocks(ex, page):
            raw = " ".join((b.get("text_content") or "").split())
            if phrase.lower() in raw.lower():
                hit = b
                break
        if hit is None:
            missing.append(f"{sid}: {ex} p{page} no block containing {phrase!r}")
            continue
        used_exhibits.add(ex)
        snippets[sid] = {
            "snippet_id": sid,
            "exhibit": display(ex),
            "page": page,
            "bbox": list(hit["bbox_list"]),
            "label": label,
            "text": clean(hit.get("text_content") or ""),
            "doc_title": doc_title,
            "doc_subtitle": doc_sub,
        }

    if missing:
        # Loudly: a sub-argument standing on evidence that silently vanished is
        # worse than no bundle.
        raise SystemExit("could not locate:\n  " + "\n  ".join(missing))

    exhibits = [
        {"id": display(ex), "pages": page_count(ex), "title": EXHIBIT_TITLES[ex]}
        for ex in sorted(used_exhibits, key=lambda s: int(s[1:]))
    ]

    OUT.mkdir(parents=True, exist_ok=True)
    write(OUT / "snippets.json", {
        "schema_version": 1,
        "bbox_space": 1000,
        "_comment": ("bbox is normalised to a 1000x1000 space (红线 #8), not pixels. "
                     "Passed through from the OCR, which emits that space natively."),
        "exhibits": exhibits,
        "snippets": snippets,
    })

    mentions = other_mentions(used_exhibits)
    write(OUT / "relations.json", {
        "schema_version": 1,
        "focus_entity": FOCUS_ENTITY,
        "other_mentions": {FOCUS_ENTITY: mentions},
        "relations": {
            sid: [{"subject": s, "predicate": p, "object": o} for s, p, o in triples]
            for sid, triples in RELATIONS.items() if sid in snippets
        },
    })

    write(OUT / "cross_criterion.json", {
        "schema_version": 1,
        "_comment": ("Snippets evidencing a DIFFERENT criterion. Never served to a "
                     "client; read only by the tree selection script (PR-1) and by "
                     "the leak audit (红线 #5)."),
        "snippet_ids": sorted(CROSS_CRITERION & set(snippets)),
    })

    print(f"{len(snippets)} snippets across {len(exhibits)} exhibits, "
          f"{len(mentions)} pages naming the petitioner -> {OUT}")
    for sid, s in snippets.items():
        print(f"  {sid:<4} {s['exhibit']:<5} p{s['page']:<3} {s['text'][:78]}")


def write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build()
