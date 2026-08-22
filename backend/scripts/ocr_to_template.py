"""Turn a block-per-page corpus into HTML templates for the render pipeline.

This is a bridge, used once per exhibit set. The replica set in TRY/ was built
by drawing substituted text into the original documents' block rectangles, so
its boxes came from OCR of the source. Rewriting those pages as HTML moves them
onto `render_exhibits.py`, after which the boxes are measured from the DOM and
OCR is out of the loop for good -- for this set and for anything authored later.

What is preserved: the page count, every block's position and reading order,
the block kinds, and the text. The layout is inherited, not re-invented.

One honest limitation: a block's *height* is no longer taken from the source.
The width and top-left are, and the text then flows to whatever height its own
typography gives it. That is the correct behaviour -- the height of the box is
now a fact about the rendered page rather than about a different one -- but a
block whose replacement text is much longer than the original's can run past
where the original ended. `--report` lists the worst offenders.


Why there is a theme per genre
------------------------------

A real file is not uniform. It holds a certificate, a conference programme, a
handful of web pages someone printed from a browser, an association's brochure,
a plain press release -- and they look nothing like each other. Rendering all of
them in one typeface on one paper produces a set that reads as generated, and
worse, it flattens a distinction the study depends on: locating a passage on a
printed web page (navigation chrome, timestamps, grey furniture) is a different
act from locating one on a certificate, and a participant's expectations differ
sharply between them.

So each genre gets its own paper, ink, type pairing and page furniture, and its
own scan level -- a certificate photocopied twice should not carry the same wear
as a page printed from a browser yesterday (spec §6).

The genre of each exhibit is declared in a map, not guessed. It was read off the
documents; a keyword heuristic would get it wrong silently.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

# The source corpus normalises both axes to 0-1000 independently, so a box maps
# to the page by fraction, not by aspect ratio.
NORM = 1000.0

# CSS px. Width 1000 makes x map 1:1 from the normalised space, which makes the
# generated HTML readable when something needs to be checked by hand.
PAGE_W = 1000

# A slip sheet: one line, "Exhibit C-4", nothing else. Every exhibit in this
# corpus opens with one, and they are typed pages rather than documents.
DIVIDER = re.compile(r"^Exhibit\s+[A-Z]{1,3}-\d{1,3}$", re.I)


# --- the themes ------------------------------------------------------------
#
# `fonts` are Google families with the weights actually used, `css` is the
# genre's own styling, `scan` its wear. Everything shares the absolute-position
# machinery in BASE_CSS; a theme only ever changes how the page looks.

THEMES: Dict[str, Dict[str, Any]] = {
    "divider": {
        "scan": "medium",
        "fonts": {"Inter": "wght@400;600"},
        "stack": '"Inter", "Helvetica Neue", Arial, sans-serif',
        "css": """
  body { background:#fcfcfc; color:#2a2a2a }
  .title, .sub_title, .text {
     font-weight:600; letter-spacing:.18em;
    text-transform:uppercase; text-align:center; line-height:1.3 }
""",
    },

    # Photocopied twice, kept in a folder: warm paper, engraved-looking type,
    # a ruled frame.
    "certificate": {
        "scan": "heavy",
        "fonts": {"Cormorant Garamond": "wght@500;600;700", "EB Garamond": "wght@400;500"},
        "stack": '"EB Garamond", "Times New Roman", Georgia, serif',
        "css": """
  body { background:#faf5e9; color:#241f16 }
  body::before { content:""; position:absolute; inset:26px;
                 border:2.5px solid #9b7f45 }
  body::after  { content:""; position:absolute; inset:34px;
                 border:1px solid #b9a273 }
  .title { font-family:"Cormorant Garamond",Georgia,serif; font-weight:700;
            letter-spacing:.15em; text-transform:uppercase;
           text-align:center; line-height:1.28; color:#4a3312 }
  .sub_title { font-family:"Cormorant Garamond",Georgia,serif; font-weight:600;
                letter-spacing:.09em; text-align:center;
               line-height:1.35; color:#6b4d20 }
  .text { text-align:center; line-height:1.6; letter-spacing:.02em }
  .image_caption { font-style:italic; text-align:center; color:#7a6438 }
""",
    },

    # An association's own brochure: institutional blue, a rule under every
    # heading, generous body setting.
    "brochure": {
        "scan": "medium",
        "fonts": {"Source Serif 4": "wght@400;600;700", "Source Sans 3": "wght@400;600"},
        "stack": '"Source Sans 3", "Segoe UI", Helvetica, Arial, sans-serif',
        "css": """
  body { background:#ffffff; color:#1b1b1b }
  .title { font-family:"Source Serif 4",Georgia,serif; font-weight:700;
            color:#123a63; line-height:1.3;
           border-bottom:3px solid #123a63; padding-bottom:9px }
  .sub_title { font-family:"Source Serif 4",Georgia,serif; font-weight:600;
                color:#1f4e79; line-height:1.4 }
  .text { line-height:1.62; text-align:justify }
  .image_caption { color:#5d6b78; text-align:center }
""",
    },

    # Printed from a browser: white, sans, a red section accent, grey furniture.
    "portal": {
        "scan": "light",
        "fonts": {"Noto Sans": "wght@400;500;700"},
        "stack": '"Noto Sans", "Segoe UI", Helvetica, Arial, sans-serif',
        "css": """
  body { background:#ffffff; color:#232323 }
  body::before { content:""; position:absolute; left:0; right:0; top:0;
                 height:7px; background:#c0392b }
  .title { font-weight:700; line-height:1.32; color:#111 }
  .sub_title { font-weight:700; line-height:1.4; color:#1a1a1a }
  .text { line-height:1.72; color:#333 }
  .image_caption { color:#8a8a8a; text-align:center }
""",
    },

    # A business-news site: serif headline over sans body, a hairline masthead.
    "news": {
        "scan": "light",
        "fonts": {"IBM Plex Serif": "wght@500;600", "IBM Plex Sans": "wght@400;500"},
        "stack": '"IBM Plex Sans", "Segoe UI", Helvetica, Arial, sans-serif',
        "css": """
  body { background:#ffffff; color:#1c1c1c }
  body::before { content:""; position:absolute; left:52px; right:52px; top:44px;
                 border-top:1px solid #c9c9c9 }
  .title { font-family:"IBM Plex Serif",Georgia,serif; font-weight:600;
            line-height:1.3; color:#0d0d0d }
  .sub_title { font-family:"IBM Plex Serif",Georgia,serif; font-weight:500;
                line-height:1.42; color:#0b6b3a }
  .text { line-height:1.68; color:#2b2b2b }
  .image_caption { color:#7d7d7d; font-style:italic;
                   text-align:center }
""",
    },

    # A newswire distribution page: utility chrome, tabular feel, federal blue.
    "newswire": {
        "scan": "light",
        "fonts": {"IBM Plex Sans": "wght@400;600", "IBM Plex Mono": "wght@400"},
        "stack": '"IBM Plex Sans", "Segoe UI", Helvetica, Arial, sans-serif',
        "css": """
  body { background:#fcfdfe; color:#1f2933 }
  body::before { content:""; position:absolute; left:0; right:0; top:0;
                 height:34px; background:#eef3f8;
                 border-bottom:1px solid #cfdae4 }
  .title { font-weight:600; color:#00437a; line-height:1.34 }
  .sub_title { font-weight:600; color:#005ea2; line-height:1.42 }
  .text { line-height:1.6; color:#2a3441 }
  .image_caption { font-family:"IBM Plex Mono",monospace;
                   color:#66757f; text-align:center; letter-spacing:.03em }
""",
    },

    # A university department page: serif headings, crimson, a quiet rule.
    "faculty": {
        "scan": "light",
        "fonts": {"Lora": "wght@500;600;700", "Open Sans": "wght@400;600"},
        "stack": '"Open Sans", "Segoe UI", Helvetica, Arial, sans-serif',
        "css": """
  body { background:#fffdfa; color:#242220 }
  body::before { content:""; position:absolute; left:0; right:0; top:0;
                 height:5px; background:#6b1d1d }
  .title { font-family:"Lora",Georgia,serif; font-weight:700;
           color:#6b1d1d; line-height:1.32 }
  .sub_title { font-family:"Lora",Georgia,serif; font-weight:600;
               color:#3f2020; line-height:1.42 }
  .text { line-height:1.68; color:#33302c }
  .image_caption { color:#8b8378; text-align:center }
""",
    },

    # A printed conference programme: cream stock, display serif, rules.
    "programme": {
        "scan": "medium",
        "fonts": {"Cormorant Garamond": "wght@500;600;700", "Inter": "wght@400;500"},
        "stack": '"Inter", "Helvetica Neue", Arial, sans-serif',
        "css": """
  body { background:#f7f3ea; color:#1d2430 }
  body::before { content:""; position:absolute; left:44px; right:44px; top:38px;
                 border-top:3px double #123a5c }
  .title { font-family:"Cormorant Garamond",Georgia,serif; font-weight:700;
            letter-spacing:.05em; text-align:center;
           color:#123a5c; line-height:1.24 }
  .sub_title { font-family:"Cormorant Garamond",Georgia,serif; font-weight:600;
                text-align:center; color:#1d4e77; line-height:1.36 }
  .text { line-height:1.6; text-align:center; color:#28303c }
  .image_caption { letter-spacing:.08em; text-transform:uppercase;
                   color:#6b7683; text-align:center }
""",
    },

    # A press release as a plain typed document: no chrome at all.
    "release": {
        "scan": "light",
        "fonts": {"EB Garamond": "wght@400;600"},
        "stack": '"EB Garamond", "Times New Roman", Georgia, serif',
        "css": """
  body { background:#fdfdfb; color:#151313 }
  .title { font-weight:600; text-align:center; line-height:1.34 }
  .sub_title { font-weight:600; line-height:1.42 }
  .text { line-height:1.58; text-align:justify }
  .image_caption { font-style:italic; text-align:center;
                   color:#6a6560 }
""",
    },
}

# Read off the documents themselves; see the module docstring on why this is a
# declaration and not a heuristic.
GENRES = {
    "c1": "certificate",   # Blue Lantern award, "Presented to ..."
    "c2": "brochure",      # About CDCA -- the association's own profile
    "c3": "portal",        # industry portal article, section path and timestamp
    "c4": "news",          # CNBUSINESSREVIEW.COM, "Source: ..."
    "c5": "newswire",      # release distribution page, "Send a Release"
    "c6": "faculty",       # university department staff page, breadcrumb
    "c7": "programme",     # conference programme cover
    "c8": "release",       # press release body, no page furniture
    "c9": "portal",        # association news page
}
DEFAULT_GENRE = "release"

BASE_CSS = """
  @page { margin: 0 }
  html, body { margin: 0; padding: 0 }
  body {
    width: %(w)dpx; height: %(h)dpx; position: relative; overflow: hidden;
    font-family: %(stack)s; font-size: 15px;
    -webkit-font-smoothing: antialiased;
  }
  .b { position: absolute; box-sizing: border-box; z-index: 1 }
  /* A photograph cannot be fabricated honestly, so its place on the page is
     kept and marked as what it is -- the same choice the replica set made. */
  .image { border: 1px dashed #bdb8ab; background: rgba(0,0,0,.035);
           display: flex; align-items: center; justify-content: center;
           font-size: 12px; letter-spacing: .14em; text-transform: uppercase;
           color: #918c80 }
"""


def exhibit_id(directory: str) -> str:
    """'c1' -> 'C-1'. Anything else is passed through untouched."""
    m = re.fullmatch(r"([a-zA-Z]+)(\d+)", directory)
    return f"{m.group(1).upper()}-{m.group(2)}" if m else directory


def font_link(theme: Dict[str, Any]) -> str:
    families = "&".join(f"family={f.replace(' ', '+')}:{w}"
                        for f, w in theme["fonts"].items())
    return ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2'
            f'?{families}&display=swap">')


def is_divider(blocks: List[Dict[str, Any]]) -> bool:
    texts = [" ".join((b.get("text_content") or "").split()) for b in blocks]
    texts = [t for t in texts if t]
    return len(texts) == 1 and bool(DIVIDER.match(texts[0]))


# How large each kind of block is allowed to get, in CSS px. The size itself is
# fitted to the block's own rectangle; these only bound it, so that a heading in
# a generous box still reads as a heading and one in a cramped box does not
# grow until it collides with what comes after it.
#
# Themes set family, weight, colour, tracking and alignment -- a kind's
# character -- but never its size. Size belongs to the rectangle: the blocks are
# pinned at the source document's coordinates, so a fixed 40px title in a box
# laid out for 24px does not overflow harmlessly, it lands on the next block.
SIZES = {
    "title": (19, 42),
    "sub_title": (15, 29),
    "text": (11, 19),
    "image_caption": (10, 15),
}

# Uppercase set with wide tracking runs far wider than the estimate assumes, so
# these themes get a tighter ceiling on the kinds they track.
SIZE_OVERRIDES = {
    "certificate": {"title": (18, 33), "sub_title": (14, 24)},
    "divider": {"title": (20, 40), "sub_title": (20, 40), "text": (20, 40)},
    "programme": {"title": (19, 36)},
}


def fit_font_size(text: str, box_w: float, box_h: float,
                  lo: float = 11.0, hi: float = 19.0) -> float:
    """Pick a size that puts roughly as much ink in the box as the original had.

    The source gives a block's rectangle and its text but not its type size, so
    the size is recovered from the two: at size s, a line holds about
    box_w / (0.5 * s) characters, and the block needs len(text) / that many
    lines at 1.5 line-height. Solving for s and clamping keeps a dense page
    dense and a sparse one sparse, which is what makes the render still read as
    the same document.

    It only sets the starting point; the box that gets recorded is whatever the
    browser actually lays out.
    """
    n = max(len(text), 1)
    if box_w <= 0 or box_h <= 0:
        return round((lo + hi) / 2, 1)
    # box_h = (n / (box_w / (0.5 s))) * 1.5 s  ->  s = sqrt(box_w box_h / (0.75 n))
    size = (box_w * box_h / (0.75 * n)) ** 0.5
    return round(min(max(size, lo), hi), 1)


def sizes_for(genre: str) -> Dict[str, Any]:
    return {**SIZES, **SIZE_OVERRIDES.get(genre, {})}


def page_html(blocks: List[Dict[str, Any]], *, exhibit: str, page: int,
              title: str, page_h: int, theme: Dict[str, Any], genre: str,
              offline: bool) -> str:
    stack = 'Georgia, "Times New Roman", serif' if offline else theme["stack"]
    sizes = sizes_for(genre)
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{html.escape(title)}</title>",
        "" if offline else font_link(theme),
        "<style>"
        + BASE_CSS % {"w": PAGE_W, "h": page_h, "stack": stack}
        + theme["css"]
        + "</style>",
        "</head><body>",
    ]

    for block in blocks:
        x1, y1, x2, y2 = block["bbox_list"]
        left = x1 / NORM * PAGE_W
        top = y1 / NORM * page_h
        width = (x2 - x1) / NORM * PAGE_W
        height = (y2 - y1) / NORM * page_h
        kind = block["block_type"]
        text = " ".join((block.get("text_content") or "").split())

        style = f"left:{left:.1f}px;top:{top:.1f}px;width:{width:.1f}px"

        if kind == "image":
            # Height is meaningful here and nowhere else: an image block is a
            # reserved area, not text that flows.
            parts.append(
                f'<div class="b image" style="{style};height:{height:.1f}px">'
                f"[ photograph ]</div>")
            continue

        if not text:
            # The source marks regions that hold no text -- a rule, a stray mark,
            # a box the segmenter drew around nothing. Giving one a snippet_id
            # would mint a snippet that can never be highlighted and can never be
            # cited, and V4 would then fail on it forever. Keep it off the page.
            continue

        lo, hi = sizes.get(kind, SIZES["text"])
        style += f";font-size:{fit_font_size(text, width, height, lo, hi)}px"
        # The height the source gave this block. The size above is only an
        # estimate -- it assumes a line-height and an average character width,
        # and every theme has its own -- so the renderer measures the block and
        # shrinks it until it fits. Estimating is for looking right; measuring
        # is for being right, and only the second keeps a block off the one
        # below it.
        fit = f' data-fit-h="{height:.1f}"'

        snippet_id = f"{exhibit}_p{page}_{block['block_id']}"
        parts.append(
            f'<div class="b {html.escape(kind)}" style="{style}"{fit}'
            f' data-snippet-id="{html.escape(snippet_id)}"'
            f' data-snippet-label="{html.escape(kind)}: {html.escape(text[:60])}">'
            f"{html.escape(text)}</div>")

    parts.append("</body></html>")
    return "\n".join(p for p in parts if p) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ocr", required=True, type=Path,
                    help="corpus root, one dir per exhibit")
    ap.add_argument("--out", required=True, type=Path, help="template directory to write")
    ap.add_argument("--aspect", type=float, default=1824 / 1400,
                    help="page height / width of the source pages")
    ap.add_argument("--genres", type=Path,
                    help="JSON map of exhibit dir -> genre; merged over the built-in one")
    ap.add_argument("--offline", action="store_true",
                    help="use local faces instead of Google Fonts")
    ap.add_argument("--report", type=int, default=5,
                    help="how many worst-overflowing blocks to list")
    args = ap.parse_args()

    genres = dict(GENRES)
    if args.genres:
        genres.update(json.loads(args.genres.read_text(encoding="utf-8")))

    page_h = round(PAGE_W * args.aspect)
    args.out.mkdir(parents=True, exist_ok=True)

    exhibits, overflow, empty = [], [], 0
    for directory in sorted(p for p in args.ocr.iterdir() if p.is_dir()):
        pages = sorted(directory.glob("page_*.json"),
                       key=lambda p: int(re.search(r"(\d+)", p.stem).group(1)))
        if not pages:
            continue

        ex = exhibit_id(directory.name)
        genre = genres.get(directory.name, DEFAULT_GENRE)
        theme = THEMES[genre]
        files, doc_title, fonts = [], "", set()

        for page_no, page_path in enumerate(pages, start=1):
            data = json.loads(page_path.read_text(encoding="utf-8"))
            blocks = sorted(data["text_blocks"],
                            key=lambda b: (b["bbox_list"][1], b["bbox_list"][0]))

            # A slip sheet is not the document; it is the tab in front of it.
            page_theme = THEMES["divider"] if is_divider(blocks) else theme
            if not doc_title and page_theme is theme:
                for block in blocks:
                    if block["block_type"] in ("title", "sub_title"):
                        doc_title = " ".join((block.get("text_content") or "").split())
                        break

            name = f"{directory.name}_p{page_no}.html"
            (args.out / name).write_text(
                page_html(blocks, exhibit=ex, page=page_no,
                          title=doc_title or ex, page_h=page_h,
                          theme=page_theme,
                          genre="divider" if page_theme is THEMES["divider"] else genre,
                          offline=args.offline),
                encoding="utf-8")
            # Per page, not per exhibit: a page loads only its own theme's
            # faces, so an exhibit-wide list would flag the slip sheet for not
            # having loaded the certificate's fonts.
            files.append({"html": name, "scan": page_theme["scan"],
                          "fonts": [] if args.offline
                                   else sorted(page_theme["fonts"])})
            fonts.update(() if args.offline else page_theme["fonts"])

            for block in blocks:
                if block["block_type"] != "text":
                    continue
                text = " ".join((block.get("text_content") or "").split())
                if not text:
                    empty += 1
                    continue
                x1, y1, x2, y2 = block["bbox_list"]
                box_w = (x2 - x1) / NORM * PAGE_W
                box_h = (y2 - y1) / NORM * page_h
                lo, hi = sizes_for(genre).get("text", SIZES["text"])
                size = fit_font_size(text, box_w, box_h, lo, hi)
                # Same estimate as the sizer, read the other way: how tall the
                # text wants to be against how tall its original rectangle was.
                want = len(text) / max(box_w / (0.5 * size), 1) * 1.5 * size
                if box_h > 0 and want / box_h > 1.25:
                    overflow.append((want / box_h, ex, page_no,
                                     block["block_id"], text[:50]))

        exhibits.append({
            "id": ex,
            "title": doc_title or ex,
            "genre": genre,
            "fonts": sorted(fonts),          # informational; the check is per page
            "pages": files,
        })

    spec = {
        "bundle": args.out.name,
        # Declared so the renderer fails loudly if a template's CSS height ever
        # drifts from the source page shape it is replicating.
        "page_aspect": round(args.aspect, 4),
        "exhibits": exhibits,
    }
    (args.out / "exhibits.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    total = sum(len(e["pages"]) for e in exhibits)
    print(f"{len(exhibits)} exhibits, {total} pages -> {args.out}")
    for e in exhibits:
        scans = sorted({p["scan"] for p in e["pages"]})
        print(f"  {e['id']:5} {len(e['pages']):2}p  {e['genre']:12} "
              f"scan={'/'.join(scans):13} {e['title'][:42]}")
    print(f"  spec: {args.out / 'exhibits.json'}")
    if empty:
        print(f"  {empty} text blocks in the source carry no text; dropped "
              f"(a snippet with no words cannot be cited or verified)")
    if overflow:
        overflow.sort(reverse=True)
        print(f"\n  {len(overflow)} text blocks want more height than the original "
              f"rectangle gave them; the worst:")
        for ratio, ex, page_no, block_id, text in overflow[:args.report]:
            print(f"    {ratio:4.1f}x  {ex} p{page_no} {block_id}  {text}...")
        print("  the rendered box is still measured, so the boxes are right; "
              "check the CHECK image if a page looks crowded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
