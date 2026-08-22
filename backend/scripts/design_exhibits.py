"""Author exhibit pages as designed documents, not as boxes of text.

The difference from `ocr_to_template.py`: that one inherits a source document's
block rectangles and pours text into absolutely positioned divs. It reproduces a
page's skeleton -- where things sat -- and nothing else. A certificate came out
as centred lines on cream paper with no frame, no seal and no signature rule; a
university page as grey text with no crest and no breadcrumb. Right in outline,
obviously generated up close.

Here each genre is a designed document: flow layout, a running head, the
furniture the genre actually has, and a typographic hierarchy of its own
(`exhibit_genres.py`). The citable passages carry `data-snippet-id` and
`render_exhibits.py` measures them off the DOM as before, so the boxes stay
exact and no OCR is involved anywhere.

Three consequences worth stating plainly.

Page geometry is no longer inherited, so a document runs to as many pages as its
own setting needs. That is the right way round -- a page count copied from a
different typesetting never meant anything -- but page numbers here do not line
up with the earlier set, and the two are not interchangeable.

Because the layout flows, blocks cannot collide by construction. The renderer's
collision check stays on anyway: it costs nothing, and a guarantee that rests on
an argument is not one.

And the text is the replica set's, minus the residue left where a bilingual
source had its Chinese stripped. Nothing in it is real: every person,
organisation, award, publication and figure was substituted.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from design_common import (  # noqa: E402
    PAGE_H,
    PAGE_W,
    count_paras,
    load_blocks,
    load_pages,
    norm,
    paginate,
)
from exhibit_genres import FLOWING as WEB_GENRES  # noqa: E402
from exhibit_genres import SINGLE, divider  # noqa: E402
from exhibit_genres_print import PRINT_GENRES  # noqa: E402

# A book and a paper are laid out by `exhibit_genres_print`; everything that is
# a web page or an office document by `exhibit_genres`. Same call signature, so
# the build does not care which a document is.
FLOWING = {**WEB_GENRES, **PRINT_GENRES}

# How much text a page of each genre holds, in characters, for the first sheet
# and for the ones after it. Set by building the set and lowering whatever the
# renderer reported as cropped -- 2300 on a portal continuation page put 20px
# past the bottom edge, so it is 2100 now.
#
# The numbers differ by genre because the chrome does: a wire page spends a
# third of the sheet on its utility bar, tabs and headline block, a brochure
# almost none. They differ between first and later pages because a continuation
# page carries a running head where the first carries a masthead.
BUDGET = {
    "brochure": (3700, 4000),
    "portal": (3400, 3700),
    "news": (3350, 3650),
    "newswire": (3200, 3600),
    "faculty": (3400, 3900),
    "release": (3500, 3800),
}

# The documents. Everything a designed page needs that a flat list of text
# blocks cannot say: which line is the masthead, which is the signatory, what
# the seal legend reads. The body text itself is loaded from the replica set.
DOCS: List[Dict[str, Any]] = [
    {
        "exhibit": "C-1", "genre": "certificate", "scan": "heavy",
        "title": "Certificate of appointment, 9th Blue Lantern Awards",
        "content": {
            "org": "China Digital Commerce Association",
            "org_sub": "Blue Lantern Awards Organizing Committee",
            "kicker": "This is to certify the appointment of",
            "award": "Blue Lantern",
            "theme": "Starting a New Journey",
            "name": "Mr. Ruiheng Fang",
            "body": ("This is to certify that you are appointed as the Deputy "
                     "Director of the 9th Blue Lantern Awards Organizing Committee."),
            "signatory": "Zhiyuan Tan",
            "date": "October 2023",
            "seals": ["China Digital Commerce Association 1100000287431",
                      "Blue Lantern Awards Organizing Committee"],
            "footer": "Certificate No. BL-2023-0431 · Beijing, China",
            "ids": {"name": "c1_name", "body": "c1_appointment"},
        },
    },
    {
        "exhibit": "C-2", "genre": "brochure", "scan": "medium",
        "title": "About CDCA — association profile",
        "content": {
            "mark": "CDCA",
            "org": "China Digital Commerce Association",
            "tagline": "Founded 1981 · Beijing",
            "title": "About CDCA",
            "footer": "China Digital Commerce Association · cdca.org.cn",
        },
    },
    {
        "exhibit": "C-3", "genre": "portal", "scan": "light",
        "title": "Final Review of the 9th Blue Lantern Award",
        "content": {
            "util": "Sign in · Subscribe · Submit a case",
            "brand": "Qingzhou", "brand_tail": "Digital",
            "section": "Review",
            "nav": ["Case", "Process", "Industry", "Awards"],
            "headline": "Final Review of the 9th Blue Lantern Award Ended Successfully",
            "date": "Sep. 13, 2023 16:24",
            "source": "Source: Qingzhou Digital",
            "views": "Read 4,120",
            "footer": "qingzhoudigital.com · © 2023",
        },
    },
    {
        "exhibit": "C-4", "genre": "news", "scan": "light",
        "title": "The 2023 Blue Lantern Awards Successfully Concluded",
        "content": {
            "masthead": "CN Business Review",
            "tagline": "Brands · Marketing · Digital Commerce",
            "rail": ["Companies", "Marketing", "Technology", "Opinion", "Data"],
            "section": "Marketing",
            "headline": ("The 2023 Blue Lantern Awards Successfully Concluded, "
                         "with Cangyu Achieving Great Results Again"),
            "source": "Source: Eastport",
            "date": "September 2023",
            "footer": "cnbusinessreview.com",
        },
    },
    {
        "exhibit": "C-5", "genre": "newswire", "scan": "light",
        "title": "LUMEN Optics Won the Silver Award — Newswire Asia",
        "content": {
            "util": ["Languages", "Register", "Log in", "Send a Release",
                     "Media Monitoring"],
            "wire": "Newswire", "wire_tail": "Asia",
            "nav": ["Product & Service", "News Center", "Resource Library",
                    "Contact Us"],
            "tabs": ["Overview", "Latest News", "Special Topic", "Industry",
                     "Region", "Headline News", "Multimedia", "Listed Company"],
            "headline": ("LUMEN Optics Won the Silver Award in the Marketing Case "
                         "Category of the 9th Blue Lantern Awards"),
            "company": "LUMEN Optics",
            "date": "Sep. 15, 2023 15:54",
            "views": "View 2,585",
            "boiler": ("About Newswire Asia — Newswire Asia distributes company "
                       "announcements to media, analysts and industry databases "
                       "across the region. Releases are published as submitted."),
            "footer": "newswireasia.com",
        },
    },
    {
        "exhibit": "C-6", "genre": "faculty", "scan": "light",
        "title": "Jianwen Xu — School of Social Science, Jinling University",
        "content": {
            "crest": "JU",
            "university": "Jinling University",
            "school": "School of Social Science",
            "nav": ["About", "Faculty", "Research", "Programmes", "News"],
            "crumb": "Home › Faculty › Full-time Faculty › Full Article",
            "name": "Jianwen Xu",
            "role": ("Professor at the Department of Sociology, Jinling University, "
                     "and PhD supervisor"),
            "footer": "sociology.jinling.edu.cn",
        },
    },
    {
        "exhibit": "C-7", "genre": "programme", "scan": "medium",
        "title": "The First China Smart Retail Conference",
        "content": {
            "convener": "Convened by",
            "org": "Smart Retail Committee of China",
            "title": "The First China Smart Retail Conference",
            "subtitle": "& China Smart Retail Commendation Conference",
            "role_label": "Judge",
            "judge": "Ruiheng Fang",
            "venue": "Beijing, China · March 2018",
            "ids": {"judge": "c7_judge"},
        },
    },
    {
        "exhibit": "C-8", "genre": "release", "scan": "light",
        "title": "The First China Smart Retail Conference will be Held on March 18th",
        "content": {
            "org": "Smart Retail Committee of China",
            "contact_line": "press@smartretail.org.cn",
            "tagline": "China Digital Commerce Association",
            "headline": ("The First China Smart Retail Conference will be Held "
                         "on March 18th"),
            "dateline": "Beijing · March 2018",
            "contact": ("Smart Retail Committee of China\n"
                        "press@smartretail.org.cn"),
            "footer": "Smart Retail Committee of China",
        },
    },
    {
        "exhibit": "G-5", "genre": "book", "scan": "medium",
        "title": "Market Study and Practice — Nanhu University Press",
        "content": {
            "series": "Twenty-First Century Communication Studies Series",
            "title": "Market Study and Practice",
            "editor": "Ruiheng Fang, Editor-in-Chief",
            "press": "Nanhu University Press",
        },
    },
    {
        "exhibit": "D-8", "genre": "paper", "scan": "light",
        "title": "New Rules of Advertising Communication",
        "content": {
            "journal": "Journal of Communication Studies",
            "issue": "Vol. 34, No. 2",
            "title": ("New Rules of Advertising Communication: "
                      "From AIDMA, AISAS to IRMAP"),
            "short_title": "New Rules of Advertising Communication",
            "authors": "Ruiheng Fang, Yanting Qiu",
            "affiliation": "School of Journalism & Communication, Nanhu University",
            "footer": "Journal of Communication Studies",
        },
    },
    {
        "exhibit": "C-9", "genre": "portal", "scan": "light",
        "title": "Smart Retail Committee Was Established in Beijing",
        "content": {
            "util": "Sign in · Membership · Contact",
            "brand": "CDCA", "brand_tail": " News",
            "section": "Committees",
            "nav": ["About", "Members", "Events", "Notices"],
            "headline": ("Smart Retail Committee of China Digital Commerce "
                         "Association Was Established in Beijing"),
            "date": "Jul. 30, 2018",
            "source": "Source: CDCA",
            "views": "Read 1,864",
            "footer": "cdca.org.cn · © 2018",
        },
    },
]


# What each sheet of a book is. Detected from the sheet rather than declared,
# because the source is what says where the contents end and the colophon
# begins, and a hand-written table would go stale the moment a page moved.
def page_kind(genre: str, index: int, items) -> str:
    if genre == "paper":
        return "front" if index == 0 else "body"
    if genre != "book":
        return "body"
    if index == 0:
        return "cover"
    import re

    text = " ".join(i["text"] for i in items)
    if "CIP" in text or "Cataloging" in text or "Cataloguing" in text:
        return "colophon"
    # Contents are recognised by their folios, not by the first line. A sheet
    # in the middle of a contents run opens with the running head, so testing
    # the top of the page put the second half of the table through as prose.
    if len(re.findall(r"\(\d{1,4}\)", text)) >= 3:
        return "contents"
    return "blurb"


def mirror_pages(doc, pages) -> list:
    """One designed sheet per source sheet.

    The alternative -- reflowing a document into as many pages as its own
    setting needs -- gives a tidier book and a different filing. A replica whose
    exhibit runs to four sheets where the original ran to twelve is not a
    replica of it, and page counts are part of what a reader of the real thing
    sees.
    """
    # The source's first sheet is the slip sheet, which the build already emits
    # as a divider; its text is filtered out, so what is left here is an empty
    # page that would render as a blank one.
    pages = pages[1:]

    if doc["genre"] in SINGLE:
        return [SINGLE[doc["genre"]](doc)]

    render = FLOWING[doc["genre"]]
    total, sheets, start = len(pages), [], 1
    for n, items in enumerate(pages):
        doc["page_kind"] = page_kind(doc["genre"], n, items)
        sheets.append(render(doc, items, n + 1, total, start, True))
        start += count_paras(items)
    return sheets


def build(out: Path, ocr: Path, only: str | None, mirror: bool = False) -> int:
    out.mkdir(parents=True, exist_ok=True)
    exhibits = []

    for doc in DOCS:
        if only and doc["exhibit"] != only:
            continue
        slug = doc["exhibit"].lower().replace("-", "")
        pages = []

        # Every exhibit opens with its slip sheet, as the filing does.
        name = f"{slug}_p1.html"
        (out / name).write_text(divider(doc), encoding="utf-8")
        pages.append({"html": name, "scan": "medium"})

        if mirror:
            # Only a page printed from a browser gets the web filters.
            web = doc["genre"] in ("portal", "news", "newswire", "faculty")
            sheets = mirror_pages(doc, load_pages(ocr, doc["exhibit"], web))
        elif doc["genre"] in SINGLE:
            sheets = [SINGLE[doc["genre"]](doc)]
        else:
            items = load_blocks(ocr, doc["exhibit"])
            # A heading that repeats what the page's own design already says.
            # The masthead prints the headline and the hero prints the name, so
            # the same words arriving again as a section heading read as a
            # stutter -- and worse, they would be two citable places for one
            # sentence.
            shown = {norm(doc["content"].get(k, "")) for k in
                     ("headline", "name", "title")} - {""}
            items = [i for i in items
                     if not (i["kind"] == "head" and norm(i["text"]) in shown)]
            spread = paginate(items, *BUDGET[doc["genre"]])
            render = FLOWING[doc["genre"]]
            sheets, start = [], 1
            for n, slice_ in enumerate(spread, start=1):
                sheets.append(render(doc, slice_, n, len(spread), start))
                start += count_paras(slice_)

        for n, sheet in enumerate(sheets, start=2):
            name = f"{slug}_p{n}.html"
            (out / name).write_text(sheet, encoding="utf-8")
            pages.append({"html": name, "scan": doc["scan"]})

        exhibits.append({"id": doc["exhibit"], "title": doc["title"],
                         "genre": doc["genre"], "pages": pages})
        print(f"  {doc['exhibit']:5} {doc['genre']:12} {len(pages):2}p  "
              f"{doc['title'][:52]}")

    spec = {"bundle": out.name,
            "page_aspect": round(PAGE_H / PAGE_W, 4),
            "exhibits": exhibits}
    (out / "exhibits.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total = sum(len(e["pages"]) for e in exhibits)
    print(f"{len(exhibits)} exhibits, {total} pages -> {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path, help="template directory")
    ap.add_argument("--ocr", required=True, type=Path,
                    help="replica corpus the body text comes from")
    ap.add_argument("--only", help="build a single exhibit, e.g. C-1")
    ap.add_argument("--mirror", action="store_true",
                    help="one designed sheet per source sheet, rather than "
                         "reflowing the text into as many pages as it needs")
    args = ap.parse_args()
    return build(args.out, args.ocr, args.only, args.mirror)


if __name__ == "__main__":
    sys.exit(main())
