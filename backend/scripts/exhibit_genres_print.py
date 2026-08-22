"""Two genres the earlier sets did not have: a book and a journal paper.

The real filing cites both inside this criterion -- a book the petitioner edited
and a paper he co-wrote -- and they are not in exhibit group C, which is why a
replica built from that folder alone came out missing them. They also look
nothing like the other nine: a book's front matter is a cover, a blurb, four
pages of contents and a colophon, and a paper is a title block over a body in
sections. Neither is a web page and neither is a certificate.

A book's colophon is worth a note. It identifies its subject as precisely as a
name does -- an ISBN, a CIP number and a press address between them name exactly
one book, and that book has one editor-in-chief -- so every number on that page
is substituted, and the audit looks for the originals as fragments.
"""
from __future__ import annotations

from typing import Dict, List

from design_common import esc, page, snip

# --- book ------------------------------------------------------------------

BOOK_FONTS = ("family=Spectral:wght@400;500;600;700"
              "&family=Barlow+Condensed:wght@400;500;600")
BOOK_CSS = """
  body { background:#f6f2e9; color:#1d1b16;
         font-family:'Spectral',Georgia,serif; padding:0 }

  /* cover */
  .cover { height:100%; display:flex; flex-direction:column;
           background:linear-gradient(#1d3a34 0 58%, #f6f2e9 58% 100%) }
  .cover .band { flex:none; padding:96px 84px 0; color:#f3efe4 }
  .cover .series { font-family:'Barlow Condensed',sans-serif; font-size:15px;
                   letter-spacing:.36em; text-transform:uppercase; opacity:.75 }
  .cover h1 { font-size:62px; font-weight:600; line-height:1.1; margin:38px 0 0;
              letter-spacing:.01em }
  .cover .ed { margin-top:44px; font-size:21px; letter-spacing:.05em; opacity:.9 }
  .cover .rest { flex:1; padding:0 84px 84px; display:flex;
                 flex-direction:column; justify-content:flex-end }
  .cover .press { font-family:'Barlow Condensed',sans-serif; font-size:22px;
                  letter-spacing:.2em; text-transform:uppercase; color:#1d3a34;
                  border-top:2px solid #1d3a34; padding-top:16px }

  /* blurb, contents, colophon share the interior page */
  .interior { padding:82px 92px 96px }
  .runhead { font-family:'Barlow Condensed',sans-serif; font-size:12px;
             letter-spacing:.28em; text-transform:uppercase; color:#8a8474;
             border-bottom:1px solid #ded7c6; padding-bottom:12px;
             margin-bottom:34px; display:flex; justify-content:space-between }
  h2 { font-size:25px; font-weight:600; margin-bottom:20px; color:#1d3a34 }
  .p { font-size:15.5px; line-height:1.8; margin-bottom:16px; text-align:justify;
       hyphens:auto }
  .bio { border-left:3px solid #c3b68f; padding-left:18px; font-size:14.5px;
         line-height:1.78; color:#3c3830; margin-bottom:16px }
  .credits { margin-top:26px; font-family:'Barlow Condensed',sans-serif;
             font-size:14px; letter-spacing:.06em; color:#6b6552;
             border-top:1px solid #ded7c6; padding-top:14px;
             display:flex; justify-content:space-between }

  /* contents */
  .toc { column-count:1 }
  .toc .ch { font-weight:600; font-size:16px; margin:18px 0 7px; color:#1d3a34 }
  .toc .sec { display:flex; align-items:baseline; font-size:14px;
              color:#3c3830; margin-bottom:5px }
  .toc .sec .t { white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
  .toc .sec .dots { flex:1; border-bottom:1px dotted #b8b09a; margin:0 8px 4px }
  .toc .sec .pg { font-variant-numeric:tabular-nums; color:#6b6552 }

  /* colophon */
  .colophon { font-size:13px; line-height:1.95; color:#3c3830 }
  .colophon .row { display:flex; gap:14px; border-bottom:1px dotted #ded7c6;
                   padding:6px 0 }
  .colophon .k { font-family:'Barlow Condensed',sans-serif; font-size:12px;
                 letter-spacing:.16em; text-transform:uppercase; color:#8a8474;
                 min-width:190px; flex:none; padding-top:3px }
  .colophon .isbn { margin-top:26px; font-family:'Barlow Condensed',sans-serif;
                    font-size:19px; letter-spacing:.1em; color:#1d3a34;
                    border:2px solid #1d3a34; display:inline-block;
                    padding:10px 18px }
  .foot { position:absolute; left:92px; right:92px; bottom:52px;
          font-family:'Barlow Condensed',sans-serif; font-size:12px;
          letter-spacing:.08em; color:#9a9382;
          display:flex; justify-content:space-between }
"""

SECTION_RE = None  # set on first use, keeps the import list short


def _toc(items: List[Dict[str, str]]) -> str:
    """Contents, as a book sets them: chapters in bold, sections with leaders
    and a right-aligned folio.

    The source keeps a whole contents page in one block, chapter and section
    runs and page numbers together, because that is what a segmenter does with
    a page of leader dots. Set that as a paragraph and it reads as a wall; split
    on the folios and it reads as contents.
    """
    import re

    global SECTION_RE
    if SECTION_RE is None:
        SECTION_RE = re.compile(r"(.+?)[\s.]*\((\d+)\)")

    out = []
    for item in items:
        text = item["text"]
        entries = SECTION_RE.findall(text)
        if not entries:
            out.append(f'<div class="ch">{esc(text)}</div>')
            continue
        for label, folio in entries:
            label = label.strip(" .·—-")
            if not label:
                continue
            if label.lower().startswith("chapter"):
                out.append(f'<div class="ch">{esc(label)}'
                           f'<span class="pg"> {esc(folio)}</span></div>')
            else:
                out.append(f'<div class="sec"><span class="t">{esc(label)}</span>'
                           f'<span class="dots"></span>'
                           f'<span class="pg">{esc(folio)}</span></div>')
    return "\n  ".join(out)


def _colophon(items: List[Dict[str, str]], doc) -> str:
    """The publication data page, as a book prints it: labelled rows."""
    rows, isbn, loose = [], "", []
    for item in items:
        text = item["text"]
        if "ISBN" in text and not isbn:
            isbn = text
            continue
        if ":" in text and len(text.split(":", 1)[0]) < 44:
            key, value = text.split(":", 1)
            rows.append(f'<div class="row"><div class="k">{esc(key.strip())}</div>'
                        f'<div>{esc(value.strip())}</div></div>')
        else:
            loose.append(text)
    body = "\n  ".join(rows)
    tail = "".join(f'<div class="row"><div class="k"></div><div>{esc(t)}</div></div>'
                   for t in loose)
    return f'{body}{tail}<div class="isbn">{esc(isbn)}</div>' if isbn else body + tail


def book(doc, items, page_no, total, start, full_chrome=False):
    d = doc["content"]
    kind = doc.get("page_kind", "body")
    slug = doc["exhibit"].lower().replace("-", "")

    if kind == "cover":
        return page(d["title"], BOOK_FONTS, BOOK_CSS, f"""
  <div class="cover">
    <div class="band">
      <div class="series">{esc(d["series"])}</div>
      <h1>{snip(f"{slug}_title", d["title"])}</h1>
      <div class="ed">{snip(f"{slug}_editor", d["editor"])}</div>
    </div>
    <div class="rest"><div class="press">{esc(d["press"])}</div></div>
  </div>""")

    head = f"""
  <div class="interior">
    <div class="runhead"><span>{esc(d["title"])}</span>
      <span>{esc(d["press"])}</span></div>"""
    foot = (f'<div class="foot"><span>{esc(d["press"])}</span>'
            f'<span>{page_no} / {total}</span></div>')

    if kind == "contents":
        inner = f'<h2>Contents</h2><div class="toc">{_toc(items)}</div>'
    elif kind == "colophon":
        inner = (f'<h2>Cataloguing in Publication</h2>'
                 f'<div class="colophon">{_colophon(items, doc)}</div>')
    else:                                   # the blurb page
        parts, n = [], start
        for i, item in enumerate(items):
            cls = "bio" if i == 1 else "p"
            parts.append(snip(f"{slug}_s{n}", item["text"], cls, "p"))
            n += 1
        inner = f'<h2>{esc(d["title"])}</h2>' + "\n  ".join(parts)

    return page(d["title"], BOOK_FONTS, BOOK_CSS, f"{head}\n  {inner}\n  </div>\n  {foot}")


# --- journal paper ---------------------------------------------------------

PAPER_FONTS = ("family=Crimson+Pro:wght@400;600;700"
               "&family=Archivo:wght@400;500;600")
PAPER_CSS = """
  body { background:#fdfdfc; color:#161616;
         font-family:'Crimson Pro',Georgia,serif; padding:74px 96px 92px }
  .journal { display:flex; align-items:baseline; font-family:'Archivo',sans-serif;
             font-size:11px; letter-spacing:.2em; text-transform:uppercase;
             color:#7c7c78; border-bottom:2px solid #16324f;
             padding-bottom:12px; margin-bottom:34px }
  .journal .r { margin-left:auto; letter-spacing:.1em }
  h1 { font-size:31px; font-weight:700; line-height:1.28; margin-bottom:16px;
       color:#16324f; max-width:820px }
  .authors { font-size:17px; margin-bottom:5px }
  .affil { font-family:'Archivo',sans-serif; font-size:12px; color:#6c6c68;
           letter-spacing:.04em; border-bottom:1px solid #e4e4e0;
           padding-bottom:18px; margin-bottom:24px }
  .h2 { font-family:'Archivo',sans-serif; font-size:14px; font-weight:600;
        letter-spacing:.1em; text-transform:uppercase; color:#16324f;
        margin:26px 0 12px }
  .p { font-size:16px; line-height:1.76; margin-bottom:15px; text-align:justify;
       hyphens:auto }
  .runhead { font-family:'Archivo',sans-serif; font-size:11px; letter-spacing:.18em;
             text-transform:uppercase; color:#9a9a95;
             border-bottom:1px solid #e4e4e0; padding-bottom:12px;
             margin-bottom:28px; display:flex; justify-content:space-between }
  .foot { position:absolute; left:96px; right:96px; bottom:46px;
          font-family:'Archivo',sans-serif; font-size:11px; color:#9a9a95;
          display:flex; justify-content:space-between }
"""


def paper(doc, items, page_no, total, start, full_chrome=False):
    d = doc["content"]
    slug = doc["exhibit"].lower().replace("-", "")

    if doc.get("page_kind") == "front":
        head = f"""
  <div class="journal"><span>{esc(d["journal"])}</span>
    <span class="r">{esc(d["issue"])}</span></div>
  <h1>{snip(f"{slug}_title", d["title"])}</h1>
  <div class="authors">{snip(f"{slug}_authors", d["authors"])}</div>
  <div class="affil">{esc(d["affiliation"])}</div>"""
        items = items[3:]          # title, authors and affiliation are set above
    else:
        head = f"""
  <div class="runhead"><span>{esc(d["journal"])}</span>
    <span>{esc(d["short_title"])}</span></div>"""

    parts, n = [], start
    for item in items:
        if item["kind"] == "head":
            parts.append(f'<h2 class="h2">{esc(item["text"])}</h2>')
        else:
            parts.append(snip(f"{slug}_s{n}", item["text"], "p", "p"))
            n += 1

    return page(d["title"], PAPER_FONTS, PAPER_CSS, f"""{head}
  {"".join(parts)}
  <div class="foot"><span>{esc(d["footer"])}</span>
    <span>{page_no} / {total}</span></div>""")


PRINT_GENRES = {"book": book, "paper": paper}
