"""The page box, the content loader, and the two helpers every genre uses.

Split out from `design_exhibits.py` so that `exhibit_genres.py` can import them
without importing the build. Three things live here and nowhere else: how big a
page is, what counts as a citable passage, and how a document's text is turned
into pages.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Dict, List

PAGE_W, PAGE_H = 1000, 1294        # CSS px, near enough to A4 at 96 dpi

RESET = """
  @page { size: %(w)dpx %(h)dpx; margin: 0 }
  * { box-sizing: border-box; margin: 0; padding: 0 }
  /* flow-root so a first child's top margin stays inside the page instead of
     collapsing out through the body and making the document taller than the
     sheet. The renderer clips to the body and would survive it either way, but
     a page whose own box is honest is easier to reason about. */
  body { width: %(w)dpx; height: %(h)dpx; position: relative; overflow: hidden;
         display: flow-root;
         -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility }
  p { orphans: 2; widows: 2 }
  /* A photograph cannot be fabricated honestly. Its place on the page is kept
     and marked as what it is, which is also what the real filing's exhibits do
     when an image is withheld. */
  .ph { border: 1px dashed currentColor; opacity: .45;
        display: flex; align-items: center; justify-content: center;
        font-size: 11px; letter-spacing: .18em; text-transform: uppercase }
"""


def esc(text: str) -> str:
    return html.escape(text or "")


def snip(sid: str, text: str, cls: str = "", tag: str = "span") -> str:
    """A citable passage.

    Only these carry an id. A page's furniture -- a masthead, a breadcrumb, a
    page number -- is not evidence, and a snippet nobody could cite is a box
    that can never be checked against anything.
    """
    klass = f' class="{cls}"' if cls else ""
    return f"<{tag}{klass} data-snippet-id=\"{esc(sid)}\">{esc(text)}</{tag}>"


def page(title: str, fonts: str, css: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{esc(title)}</title>
<link href="https://fonts.googleapis.com/css2?{fonts}&display=swap" rel="stylesheet">
<style>{RESET % {"w": PAGE_W, "h": PAGE_H}}{css}</style>
</head>
<body>
{body}
</body>
</html>
"""


# --- content ---------------------------------------------------------------

MIN_WORDS = 5
EXHIBIT_SLIP = re.compile(r"Exhibit\s+[A-Z]{1,3}-\d{1,3}", re.I)


def readable(text: str) -> bool:
    """Enough words to be prose.

    The replica set was made by substituting a bilingual source, and where a
    passage was Chinese the substitution left a residue: "1981 2005 9", a run of
    lone quotation marks. Poured into an absolutely positioned box those went
    unnoticed. Set as a paragraph in a designed document they are the first
    thing the eye lands on, and they are not text and not evidence, so they do
    not go on a page.
    """
    words = [w for w in text.split() if len(w) > 1 and any(c.isalpha() for c in w)]
    return len(words) >= MIN_WORDS


def is_chrome(text: str) -> bool:
    """A page's own furniture, captured as if it were text.

    The source pages were web pages printed to PDF, so the corpus holds their
    navigation, their section rails and their browser tab titles as ordinary
    blocks: "Languages Register Log in Send a Release Media Monitoring", or a
    headline with the whole site menu run onto the end of it. Poured into the
    original block rectangles those landed where the nav bar had been and looked
    like a nav bar. Set as body copy under a designed masthead they read as
    nonsense, and worse, they are citable -- a participant could be asked to
    verify a sentence that is really a menu.

    The designed page supplies its own chrome, so the captured chrome goes.
    """
    if "_" in text or "|" in text or "›" in text:
        return True
    words = text.split()
    # Prose ends in a full stop. A run of words that never does, at this length,
    # is a menu: real sentences this long are not built without punctuation.
    return len(words) >= 6 and not text.rstrip().endswith((".", "!", "?", "”"))


def norm(text: str) -> str:
    """For comparing two pieces of text as the same words."""
    return " ".join((text or "").lower().split()).strip(" .,:;—-")


def tidy(text: str) -> str:
    """Leading rules and stray marks the capture left on a heading."""
    return text.lstrip("|·—- ").strip()


def load_blocks(ocr: Path, exhibit: str) -> List[Dict[str, str]]:
    """Every readable block of one exhibit in reading order, without the slip
    sheet or the translator's stamp."""
    folder = ocr / exhibit.lower().replace("-", "")
    out: List[Dict[str, str]] = []
    # A web page printed to PDF repeats its own title and header on every sheet,
    # so the corpus holds the same sentence eight times. Once is a document;
    # eight times is an artefact of how it was captured.
    seen = set()
    for path in sorted(folder.glob("page_*.json"),
                       key=lambda p: int(re.search(r"(\d+)", p.stem).group(1))):
        data = json.loads(path.read_text(encoding="utf-8"))
        for block in sorted(data["text_blocks"],
                            key=lambda b: (b["bbox_list"][1], b["bbox_list"][0])):
            text = tidy(" ".join((block.get("text_content") or "").split()))
            if not text or text == "Translation" or EXHIBIT_SLIP.fullmatch(text):
                continue
            key = text.lower()[:90]
            if key in seen:
                continue
            seen.add(key)
            if block["block_type"] in ("title", "sub_title"):
                if not is_chrome(text):
                    out.append({"kind": "head", "text": text})
            elif readable(text) and not is_chrome(text):
                out.append({"kind": "para", "text": text})
    return out


def load_pages(ocr: Path, exhibit: str, web: bool = True) -> List[List[Dict[str, str]]]:
    """The same cleaning as `load_blocks`, but keeping the source's pages.

    Used when a set mirrors a filing sheet for sheet rather than reflowing it.
    A page whose every block was chrome comes back empty and is still a page:
    that is what a printed web page looks like when the sheet caught the header
    and a photograph and little else, and dropping it would make the replica
    shorter than the thing it replicates.

    `web` is what a source page IS, and it decides two filters that only make
    sense for one kind of document. Both were written for pages printed from a
    browser and both destroy a book:

      * the chrome filter drops a run of words that never reaches a full stop,
        because on a web page that is a menu. In a book it is the contents and
        the colophon -- "Chapter 7 Brand research (157)", "Responsible editor:
        ..." -- and dropping them left the contents pages blank.
      * the de-duplicator drops a passage the corpus has seen before, because a
        printed web page repeats its header on every sheet. A book's two
        contents sheets are near-identical in the source and both are real.
    """
    folder = ocr / exhibit.lower().replace("-", "")
    seen: set = set()
    pages: List[List[Dict[str, str]]] = []
    for path in sorted(folder.glob("page_*.json"),
                       key=lambda p: int(re.search(r"(\d+)", p.stem).group(1))):
        data = json.loads(path.read_text(encoding="utf-8"))
        items: List[Dict[str, str]] = []
        for block in sorted(data["text_blocks"],
                            key=lambda b: (b["bbox_list"][1], b["bbox_list"][0])):
            text = tidy(" ".join((block.get("text_content") or "").split()))
            if not text or text == "Translation" or EXHIBIT_SLIP.fullmatch(text):
                continue
            key = text.lower()[:90]
            if web:
                if key in seen:
                    continue
                seen.add(key)
            if block["block_type"] in ("title", "sub_title"):
                if not (web and is_chrome(text)):
                    items.append({"kind": "head", "text": text})
            elif not web or (readable(text) and not is_chrome(text)):
                items.append({"kind": "para", "text": text})
        pages.append(items)
    return pages


def paginate(items: List[Dict[str, str]], first: int,
             rest: int | None = None) -> List[List[Dict[str, str]]]:
    """Split a flow of headings and paragraphs into pages by how much text each
    holds.

    Approximate on purpose. The renderer refuses a page whose content is clipped,
    so a budget that is too generous fails the build instead of quietly losing a
    paragraph off the bottom of the page -- which is the failure that matters,
    because a citation into a paragraph nobody can see is unanswerable.
    """
    pages: List[List[Dict[str, str]]] = []
    current: List[Dict[str, str]] = []
    used = 0
    for item in items:
        budget = first if not pages else (rest if rest is not None else first)
        cost = len(item["text"]) + (160 if item["kind"] == "head" else 40)
        if current and used + cost > budget:
            pages.append(current)
            current, used = [], 0
        current.append(item)
        used += cost
    if current:
        pages.append(current)
    return pages


def flow(items: List[Dict[str, str]], exhibit: str, start: int) -> str:
    """Headings and citable paragraphs as HTML.

    Numbering runs across the whole document rather than per page, so a snippet
    id keeps meaning the same passage when the text repaginates.
    """
    parts: List[str] = []
    n = start
    for item in items:
        if item["kind"] == "head":
            parts.append(f'<h2 class="h2">{esc(item["text"])}</h2>')
        else:
            slug = exhibit.lower().replace("-", "")
            parts.append(snip(f"{slug}_s{n}", item["text"], "p", "p"))
            n += 1
    return "\n  ".join(parts)


def count_paras(items: List[Dict[str, str]]) -> int:
    return sum(1 for i in items if i["kind"] == "para")
