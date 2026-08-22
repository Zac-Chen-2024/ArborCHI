"""One designed document per genre.

`design_exhibits.py` holds the page box, the content loader and the build; this
holds the documents themselves. They are separate because they change for
different reasons: the first when the pipeline changes, this when a document
should look more like the thing it is.

Each genre is a real layout rather than a box of centred lines -- a masthead, a
breadcrumb, a signature block with a rule, a wire service's utility bar, an
end-of-release marker. That matters beyond appearance: locating a passage on a
page that has navigation chrome and a timestamp is a different act from
locating one on a certificate, and a set where every document is set in one
face on one paper flattens the difference the study is measuring.

Multi-page genres take (doc, items, page_no, total, start) and lay out the
slice of the document they were given, with a running head on continuation
pages. Single-page ones take the document alone.
"""
from __future__ import annotations

from typing import Any, Dict

from design_common import esc, flow, page, snip

# --- exhibit divider -------------------------------------------------------

DIVIDER_FONTS = "family=Inter:wght@400;600"
DIVIDER_CSS = """
  body { background:#fcfcfa; color:#1f1f1f; font-family:'Inter',Helvetica,sans-serif;
         display:flex; align-items:center; justify-content:center }
  .tab { text-align:center }
  .tab .n { font-size:15px; letter-spacing:.42em; text-transform:uppercase;
            color:#8c8c86; margin-bottom:26px }
  .tab .id { font-size:72px; font-weight:600; letter-spacing:.12em }
  .tab .rule { width:120px; height:2px; background:#1f1f1f; margin:30px auto 0 }
"""


def divider(doc: Dict[str, Any]) -> str:
    return page(doc["exhibit"], DIVIDER_FONTS, DIVIDER_CSS, f"""
  <div class="tab">
    <div class="n">Exhibit</div>
    <div class="id">{esc(doc["exhibit"])}</div>
    <div class="rule"></div>
  </div>""")


# --- certificate -----------------------------------------------------------

CERT_FONTS = ("family=Cormorant+Garamond:wght@400;600;700"
              "&family=EB+Garamond:wght@400;500;600")
CERT_CSS = """
  /* Flex column, so the middle takes the slack. Pinning the signature block to
     the bottom left a hole in the page whenever the citation was short: the
     certificate read as a header and a footer with nothing between them. */
  body { background:#fbf7ec; color:#1c1810;
         font-family:'EB Garamond',Garamond,serif; padding:92px 88px 128px;
         display:flex; flex-direction:column }
  main { flex:1; display:flex; flex-direction:column; justify-content:center;
         position:relative; z-index:2 }
  .frame { position:absolute; inset:42px; border:3px double #8a7444 }
  .frame::after { content:''; position:absolute; inset:9px; border:1px solid #bda971 }
  .guilloche { position:absolute; inset:52px; opacity:.05; pointer-events:none;
               background:repeating-linear-gradient(38deg,#8a7444 0 1px,transparent 1px 9px) }

  header { text-align:center; position:relative; z-index:2 }
  .org { font-family:'Cormorant Garamond',serif; font-size:29px; font-weight:700;
         letter-spacing:.2em; text-transform:uppercase; color:#2b2415 }
  .rule { width:190px; height:1px; background:#8a7444; margin:16px auto 13px }
  .sub { font-size:13px; letter-spacing:.32em; text-transform:uppercase; color:#6d6448 }

  .kicker { text-align:center; font-size:14px; letter-spacing:.3em;
            text-transform:uppercase; color:#6d6448; margin:0 0 18px }
  .award { text-align:center; font-family:'Cormorant Garamond',serif;
           font-size:52px; font-weight:600; line-height:1.16; color:#1a1508;
           letter-spacing:.06em }
  .award .lede { display:block; font-size:20px; letter-spacing:.28em;
                 text-transform:uppercase; color:#6d6448; margin-top:16px }

  .to { text-align:center; font-size:14px; letter-spacing:.24em;
        text-transform:uppercase; color:#6d6448; margin:44px 0 12px }
  .namewrap { text-align:center; margin-bottom:34px }
  .name { font-family:'Cormorant Garamond',serif; font-size:42px; font-weight:700;
          color:#1a1508; border-bottom:1px solid #bda971;
          display:inline-block; padding:0 44px 9px }

  .body { font-size:17px; line-height:2.0; text-align:center; max-width:640px;
          margin:0 auto; color:#2b2415 }

  .meta { display:flex; justify-content:space-between; margin:0 42px;
          position:relative; z-index:3 }
  .sig { min-width:250px }
  .lbl { display:block; font-size:10px; letter-spacing:.22em; text-transform:uppercase;
         color:#8a8064; margin-bottom:8px }
  .sigline { font-family:'Cormorant Garamond',serif; font-size:23px; color:#2b2415;
             border-top:1px solid #8a7444; padding-top:9px }

  .seal { position:absolute; width:138px; height:138px; border-radius:50%;
          border:3px double #9a3b2e; color:#9a3b2e; opacity:.55;
          display:flex; align-items:center; justify-content:center; text-align:center;
          font-size:10px; line-height:1.6; letter-spacing:.13em; text-transform:uppercase;
          padding:14px }
  /* Above the signature block, not across it. A real seal often clips a
     signature, but one sitting on the label makes the label unreadable, and an
     exhibit whose own caption cannot be read is not evidence of much. */
  .seal.a { right:104px; bottom:268px; transform:rotate(-8deg) }
  .seal.b { right:238px; bottom:230px; transform:rotate(7deg) }

  .foot { position:absolute; left:88px; right:88px; bottom:64px; text-align:center;
          font-size:11px; letter-spacing:.1em; color:#8a8064; z-index:2 }
"""


def certificate(doc: Dict[str, Any]) -> str:
    d = doc["content"]
    seals = "".join(f'<div class="seal {c}" data-region="seal">{esc(t)}</div>'
                    for c, t in zip(("a", "b"), d["seals"]))
    return page(d["award"], CERT_FONTS, CERT_CSS, f"""
  <div class="frame"></div><div class="guilloche"></div>

  <header>
    <div class="org">{esc(d["org"])}</div>
    <div class="rule"></div>
    <div class="sub">{esc(d["org_sub"])}</div>
  </header>

  <main>
    <div class="kicker">{esc(d["kicker"])}</div>
    <div class="award">{esc(d["award"])}<span class="lede">{esc(d["theme"])}</span></div>

    <div class="to">Presented to</div>
    <div class="namewrap">{snip(d["ids"]["name"], d["name"], "name")}</div>

    <p class="body">{snip(d["ids"]["body"], d["body"])}</p>
  </main>

  <div class="meta">
    <div class="sig">
      <span class="lbl">Date of Issue</span>
      <span class="sigline">{esc(d["date"])}</span>
    </div>
    <div class="sig" style="text-align:right">
      <span class="lbl">Executive President</span>
      <span class="sigline">{esc(d["signatory"])}</span>
    </div>
  </div>

  {seals}
  <div class="foot" data-region="footer">{esc(d["footer"])}</div>""")


# --- association brochure --------------------------------------------------

BROCHURE_FONTS = ("family=Source+Serif+4:wght@400;600;700"
                  "&family=Source+Sans+3:wght@400;600;700")
BROCHURE_CSS = """
  body { background:#fff; color:#1d1d1d;
         font-family:'Source Sans 3',Helvetica,sans-serif; padding:74px 86px 96px }
  .mast { display:flex; align-items:flex-end; gap:22px;
          border-bottom:4px solid #123a63; padding-bottom:18px; margin-bottom:8px }
  .logo { width:74px; height:74px; background:#123a63; color:#fff;
          font-family:'Source Serif 4',Georgia,serif; font-weight:700; font-size:25px;
          letter-spacing:.04em; display:flex; align-items:center;
          justify-content:center; flex:none }
  .mast .nm { font-family:'Source Serif 4',Georgia,serif; font-size:27px;
              font-weight:700; color:#123a63; line-height:1.15 }
  .mast .tag { font-size:12px; letter-spacing:.2em; text-transform:uppercase;
               color:#6f7c89; margin-top:7px }
  .strip { height:5px; background:#c9a227; width:180px; margin-bottom:34px }
  h1 { font-family:'Source Serif 4',Georgia,serif; font-size:34px; font-weight:700;
       color:#0f2c4b; margin-bottom:18px }
  .h2 { font-family:'Source Serif 4',Georgia,serif; font-size:19px; font-weight:700;
        color:#123a63; margin:30px 0 12px; padding-left:13px;
        border-left:4px solid #c9a227 }
  .p { font-size:15px; line-height:1.78; color:#2c2c2c; margin-bottom:15px;
       text-align:justify; hyphens:auto }
  .runhead { display:flex; justify-content:space-between; font-size:11px;
             letter-spacing:.16em; text-transform:uppercase; color:#8c98a4;
             border-bottom:1px solid #dde3e9; padding-bottom:11px; margin-bottom:32px }
  .foot { position:absolute; left:86px; right:86px; bottom:52px;
          border-top:1px solid #dde3e9; padding-top:12px;
          display:flex; justify-content:space-between;
          font-size:11px; color:#8c98a4; letter-spacing:.06em }
"""


def brochure(doc, items, page_no, total, start):
    d = doc["content"]
    head = (f"""
  <div class="mast">
    <div class="logo">{esc(d["mark"])}</div>
    <div>
      <div class="nm">{esc(d["org"])}</div>
      <div class="tag">{esc(d["tagline"])}</div>
    </div>
  </div>
  <div class="strip"></div>
  <h1>{esc(d["title"])}</h1>""" if page_no == 1 else f"""
  <div class="runhead"><span>{esc(d["org"])}</span><span>{esc(d["title"])}</span></div>""")
    return page(d["title"], BROCHURE_FONTS, BROCHURE_CSS, f"""{head}
  {flow(items, doc["exhibit"], start)}
  <div class="foot" data-region="footer"><span>{esc(d["footer"])}</span>
    <span>Page {page_no} of {total}</span></div>""")


# --- web article on an industry portal -------------------------------------

PORTAL_FONTS = "family=Noto+Sans:wght@400;500;700&family=Noto+Serif:wght@600;700"
PORTAL_CSS = """
  body { background:#fff; color:#222; font-family:'Noto Sans',Helvetica,sans-serif }
  .util { height:34px; background:#f4f4f4; border-bottom:1px solid #e3e3e3;
          display:flex; align-items:center; gap:20px; padding:0 60px;
          font-size:11px; color:#8a8a8a }
  .util .r { margin-left:auto }
  .brandbar { border-bottom:3px solid #c0392b; padding:20px 60px 16px;
              display:flex; align-items:baseline; gap:16px }
  .brand { font-family:'Noto Serif',Georgia,serif; font-size:26px; font-weight:700;
           color:#c0392b; letter-spacing:.02em }
  .brand span { color:#333 }
  .nav { display:flex; gap:19px; font-size:13px; color:#555; margin-left:auto }
  .nav b { color:#c0392b; font-weight:500 }
  .wrap { padding:24px 60px 0 }
  .crumb { font-size:12px; color:#9a9a9a; margin-bottom:22px }
  .crumb b { color:#c0392b; font-weight:400 }
  h1 { font-family:'Noto Serif',Georgia,serif; font-size:31px; line-height:1.3;
       color:#131313; margin-bottom:16px }
  .byline { display:flex; gap:18px; font-size:12px; color:#9a9a9a;
            border-bottom:1px solid #eee; padding-bottom:14px; margin-bottom:24px }
  .h2 { font-size:18px; font-weight:700; color:#1a1a1a; margin:26px 0 12px }
  .p { font-size:15px; line-height:1.85; color:#333; margin-bottom:16px }
  .runhead { margin:20px 60px 24px; font-size:11px; letter-spacing:.14em;
             text-transform:uppercase; color:#b0b0b0;
             border-bottom:1px solid #eee; padding-bottom:12px }
  .foot { position:absolute; left:60px; right:60px; bottom:40px;
          border-top:1px solid #eee; padding-top:12px;
          display:flex; justify-content:space-between; font-size:11px; color:#aaa }
"""


def portal(doc, items, page_no, total, start):
    d = doc["content"]
    if page_no == 1:
        head = f"""
  <div class="util"><span>{esc(d["util"])}</span><span class="r">Search</span></div>
  <div class="brandbar">
    <div class="brand">{esc(d["brand"])}<span>{esc(d["brand_tail"])}</span></div>
    <div class="nav"><b>{esc(d["section"])}</b>{"".join(
        f"<span>{esc(x)}</span>" for x in d["nav"])}</div>
  </div>
  <div class="wrap">
    <div class="crumb">Home &rsaquo; <b>{esc(d["section"])}</b> &rsaquo; Full Article</div>
    <h1>{esc(d["headline"])}</h1>
    <div class="byline"><span>{esc(d["date"])}</span><span>{esc(d["source"])}</span>
      <span>{esc(d["views"])}</span></div>"""
    else:
        head = f"""
  <div class="runhead">{esc(d["brand"])}{esc(d["brand_tail"])}
    &nbsp;·&nbsp; {esc(d["headline"][:64])}</div>
  <div class="wrap">"""
    return page(d["headline"], PORTAL_FONTS, PORTAL_CSS, f"""{head}
  {flow(items, doc["exhibit"], start)}
  </div>
  <div class="foot" data-region="footer"><span>{esc(d["footer"])}</span><span>{page_no} / {total}</span></div>""")


# --- business news ---------------------------------------------------------

NEWS_FONTS = ("family=IBM+Plex+Serif:wght@400;500;600"
              "&family=IBM+Plex+Sans:wght@400;500;600")
NEWS_CSS = """
  body { background:#fff; color:#1b1b1b;
         font-family:'IBM Plex Sans',Helvetica,sans-serif; padding:56px 78px 90px }
  .mast { text-align:center; border-top:3px solid #111; border-bottom:1px solid #111;
          padding:14px 0 12px; margin-bottom:6px }
  .mast .n { font-family:'IBM Plex Serif',Georgia,serif; font-size:27px;
             font-weight:600; letter-spacing:.22em; text-transform:uppercase }
  .mast .s { font-size:10px; letter-spacing:.3em; text-transform:uppercase;
             color:#7a7a7a; margin-top:8px }
  .rail { display:flex; justify-content:center; gap:24px; font-size:11px;
          letter-spacing:.14em; text-transform:uppercase; color:#8a8a8a;
          border-bottom:1px solid #ddd; padding-bottom:11px; margin-bottom:30px }
  .kicker { font-size:11px; letter-spacing:.22em; text-transform:uppercase;
            color:#0b6b3a; margin-bottom:11px }
  h1 { font-family:'IBM Plex Serif',Georgia,serif; font-size:33px; font-weight:600;
       line-height:1.26; margin-bottom:14px }
  .byline { font-size:12px; color:#8a8a8a; border-bottom:1px solid #eee;
            padding-bottom:13px; margin-bottom:22px }
  .byline b { color:#1b1b1b; font-weight:500 }
  .h2 { font-family:'IBM Plex Serif',Georgia,serif; font-size:18px; font-weight:600;
        color:#0b6b3a; margin:26px 0 11px }
  .p { font-size:14.5px; line-height:1.82; color:#2b2b2b; margin-bottom:15px;
       text-align:justify; hyphens:auto }
  .runhead { font-size:11px; letter-spacing:.16em; text-transform:uppercase;
             color:#a0a0a0; border-bottom:1px solid #eee;
             padding-bottom:12px; margin-bottom:26px }
  .foot { position:absolute; left:78px; right:78px; bottom:44px;
          border-top:1px solid #ddd; padding-top:11px;
          display:flex; justify-content:space-between; font-size:11px; color:#9a9a9a }
"""


def news(doc, items, page_no, total, start):
    d = doc["content"]
    head = (f"""
  <div class="mast"><div class="n">{esc(d["masthead"])}</div>
    <div class="s">{esc(d["tagline"])}</div></div>
  <div class="rail">{"".join(f"<span>{esc(x)}</span>" for x in d["rail"])}</div>
  <div class="kicker">{esc(d["section"])}</div>
  <h1>{esc(d["headline"])}</h1>
  <div class="byline">{esc(d["source"])} &nbsp;·&nbsp; <b>{esc(d["date"])}</b></div>"""
            if page_no == 1 else f"""
  <div class="runhead">{esc(d["masthead"])} &nbsp;·&nbsp; {esc(d["date"])}</div>""")
    return page(d["headline"], NEWS_FONTS, NEWS_CSS, f"""{head}
  {flow(items, doc["exhibit"], start)}
  <div class="foot" data-region="footer"><span>{esc(d["footer"])}</span>
    <span>Page {page_no} of {total}</span></div>""")


# --- newswire distribution page --------------------------------------------

WIRE_FONTS = "family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400"
WIRE_CSS = """
  body { background:#fff; color:#1f2933;
         font-family:'IBM Plex Sans',Helvetica,sans-serif }
  .util { height:32px; background:#eef3f8; border-bottom:1px solid #cfdae4;
          display:flex; align-items:center; gap:18px; padding:0 56px;
          font-size:11px; color:#5b6b7b }
  .head { padding:18px 56px 14px; border-bottom:2px solid #005ea2;
          display:flex; align-items:center }
  .wm { font-size:23px; font-weight:600; color:#00437a; letter-spacing:-.01em }
  .wm i { font-style:normal; color:#0d8bd9 }
  .nav { margin-left:auto; display:flex; gap:17px; font-size:12px; color:#54606d }
  .tabs { padding:11px 56px; background:#f7fafc; border-bottom:1px solid #e2e9f0;
          display:flex; gap:16px; font-size:11px; color:#7b8794 }
  .wrap { padding:26px 56px 0 }
  h1 { font-size:26px; font-weight:600; color:#00437a; line-height:1.34;
       margin-bottom:14px }
  .meta { display:flex; gap:16px; align-items:center; font-size:12px; color:#7b8794;
          border-bottom:1px solid #e2e9f0; padding-bottom:14px; margin-bottom:20px }
  .meta .co { font-weight:600; color:#1f2933 }
  .h2 { font-size:17px; font-weight:600; color:#005ea2; margin:24px 0 11px }
  .p { font-size:14.5px; line-height:1.8; color:#2a3441; margin-bottom:15px }
  .boiler { margin-top:26px; border-left:3px solid #cfdae4; padding:4px 0 4px 16px;
            font-family:'IBM Plex Mono',monospace; font-size:11.5px; line-height:1.7;
            color:#66757f }
  .runhead { margin:20px 56px 22px; font-size:11px; letter-spacing:.14em;
             text-transform:uppercase; color:#9aa7b4;
             border-bottom:1px solid #e2e9f0; padding-bottom:12px }
  .foot { position:absolute; left:56px; right:56px; bottom:38px;
          border-top:1px solid #e2e9f0; padding-top:11px;
          display:flex; justify-content:space-between; font-size:11px; color:#9aa7b4 }
"""


def newswire(doc, items, page_no, total, start):
    d = doc["content"]
    if page_no == 1:
        head = f"""
  <div class="util">{"".join(f"<span>{esc(x)}</span>" for x in d["util"])}</div>
  <div class="head"><div class="wm">{esc(d["wire"])}<i>{esc(d["wire_tail"])}</i></div>
    <div class="nav">{"".join(f"<span>{esc(x)}</span>" for x in d["nav"])}</div></div>
  <div class="tabs">{"".join(f"<span>{esc(x)}</span>" for x in d["tabs"])}</div>
  <div class="wrap">
    <h1>{esc(d["headline"])}</h1>
    <div class="meta"><span class="co">{esc(d["company"])}</span>
      <span>{esc(d["date"])}</span><span>{esc(d["views"])}</span></div>"""
    else:
        head = f"""
  <div class="runhead">{esc(d["wire"])}{esc(d["wire_tail"])}
    &nbsp;·&nbsp; {esc(d["company"])}</div>
  <div class="wrap">"""
    tail = f'<div class="boiler">{esc(d["boiler"])}</div>' if page_no == total else ""
    return page(d["headline"], WIRE_FONTS, WIRE_CSS, f"""{head}
  {flow(items, doc["exhibit"], start)}
  {tail}
  </div>
  <div class="foot" data-region="footer"><span>{esc(d["footer"])}</span><span>{page_no} / {total}</span></div>""")


# --- university faculty page -----------------------------------------------

FACULTY_FONTS = "family=Lora:wght@500;600;700&family=Open+Sans:wght@400;600"
FACULTY_CSS = """
  body { background:#fffdfa; color:#242220;
         font-family:'Open Sans',Helvetica,sans-serif }
  .top { background:#6b1d1d; color:#fff; padding:20px 62px;
         display:flex; align-items:center; gap:18px }
  .crest { width:52px; height:52px; border-radius:50%; border:2px solid #fff;
           display:flex; align-items:center; justify-content:center;
           font-family:'Lora',Georgia,serif; font-size:18px; font-weight:700;
           color:#fff; flex:none }
  .top .u { font-family:'Lora',Georgia,serif; font-size:22px; font-weight:600 }
  .top .s { font-size:12px; opacity:.82; margin-top:3px; letter-spacing:.04em }
  .nav { background:#4e1515; color:#e8d5d5; padding:10px 62px;
         display:flex; gap:22px; font-size:12px }
  .wrap { padding:22px 62px 0 }
  .crumb { font-size:12px; color:#9a8f8f; margin-bottom:24px }
  .hero { display:flex; gap:28px; margin-bottom:26px; align-items:flex-start }
  .portrait { width:168px; height:214px; flex:none; color:#b7a9a9 }
  h1 { font-family:'Lora',Georgia,serif; font-size:30px; font-weight:700;
       color:#6b1d1d; margin-bottom:9px }
  .role { font-size:14px; color:#5c534e; line-height:1.65;
          border-left:3px solid #d8c4c4; padding-left:14px }
  .h2 { font-family:'Lora',Georgia,serif; font-size:18px; font-weight:600;
        color:#3f2020; margin:26px 0 11px;
        border-bottom:1px solid #ecdede; padding-bottom:7px }
  .p { font-size:14.5px; line-height:1.82; color:#33302c; margin-bottom:15px;
       text-align:justify; hyphens:auto }
  .runhead { margin:20px 62px 22px; font-size:11px; letter-spacing:.14em;
             text-transform:uppercase; color:#b0a3a3;
             border-bottom:1px solid #ecdede; padding-bottom:12px }
  .foot { position:absolute; left:62px; right:62px; bottom:40px;
          border-top:1px solid #ecdede; padding-top:12px;
          display:flex; justify-content:space-between; font-size:11px; color:#b0a3a3 }
"""


def faculty(doc, items, page_no, total, start):
    d = doc["content"]
    if page_no == 1:
        head = f"""
  <div class="top"><div class="crest">{esc(d["crest"])}</div>
    <div><div class="u">{esc(d["university"])}</div>
      <div class="s">{esc(d["school"])}</div></div></div>
  <div class="nav">{"".join(f"<span>{esc(x)}</span>" for x in d["nav"])}</div>
  <div class="wrap">
    <div class="crumb">{esc(d["crumb"])}</div>
    <div class="hero">
      <div class="portrait ph">Photograph</div>
      <div><h1>{esc(d["name"])}</h1>
        <div class="role">{esc(d["role"])}</div></div>
    </div>"""
    else:
        head = f"""
  <div class="runhead">{esc(d["university"])} &nbsp;·&nbsp; {esc(d["name"])}</div>
  <div class="wrap">"""
    return page(d["name"], FACULTY_FONTS, FACULTY_CSS, f"""{head}
  {flow(items, doc["exhibit"], start)}
  </div>
  <div class="foot" data-region="footer"><span>{esc(d["footer"])}</span><span>{page_no} / {total}</span></div>""")


# --- conference programme --------------------------------------------------

PROG_FONTS = "family=Cormorant+Garamond:wght@500;600;700&family=Inter:wght@400;500;600"
PROG_CSS = """
  body { background:#f7f3ea; color:#1d2430; font-family:'Inter',Helvetica,sans-serif;
         padding:92px 88px 96px; display:flex; flex-direction:column }
  .edge { position:absolute; left:46px; right:46px; top:44px; bottom:44px;
          border-top:3px double #123a5c; border-bottom:3px double #123a5c }
  header { text-align:center; position:relative; z-index:2 }
  .org { font-size:12px; letter-spacing:.34em; text-transform:uppercase;
         color:#5b6a7c }
  .orgname { font-family:'Cormorant Garamond',serif; font-size:25px; font-weight:600;
             color:#123a5c; margin-top:10px; letter-spacing:.06em }
  main { flex:1; display:flex; flex-direction:column; justify-content:center;
         text-align:center; position:relative; z-index:2 }
  h1 { font-family:'Cormorant Garamond',serif; font-size:50px; font-weight:700;
       line-height:1.16; color:#123a5c; letter-spacing:.03em }
  .amp { display:block; font-size:22px; font-weight:500; letter-spacing:.16em;
         text-transform:uppercase; color:#5b6a7c; margin-top:18px }
  .panel { margin:46px auto 0; border:1px solid #c3cedb; background:#fdfbf6;
           padding:26px 40px; display:inline-flex; align-items:center; gap:26px }
  .panel .ph { width:104px; height:130px; color:#9aa7b4 }
  .panel .lbl { font-size:11px; letter-spacing:.24em; text-transform:uppercase;
                color:#7c8794; margin-bottom:8px }
  .panel .nm { font-family:'Cormorant Garamond',serif; font-size:32px;
               font-weight:700; color:#123a5c }
  .venue { text-align:center; font-size:13px; letter-spacing:.2em;
           text-transform:uppercase; color:#5b6a7c; position:relative; z-index:2 }
  .venue .rule { width:110px; height:1px; background:#123a5c; margin:0 auto 18px }
"""


def programme(doc: Dict[str, Any]) -> str:
    d = doc["content"]
    return page(d["title"], PROG_FONTS, PROG_CSS, f"""
  <div class="edge"></div>
  <header><div class="org">{esc(d["convener"])}</div>
    <div class="orgname">{esc(d["org"])}</div></header>
  <main>
    <h1>{esc(d["title"])}<span class="amp">{esc(d["subtitle"])}</span></h1>
    <div class="panel">
      <div class="ph">Photograph</div>
      <div><div class="lbl">{esc(d["role_label"])}</div>
        {snip(d["ids"]["judge"], d["judge"], "nm")}</div>
    </div>
  </main>
  <div class="venue"><div class="rule"></div>{esc(d["venue"])}</div>""")


# --- press release ---------------------------------------------------------

RELEASE_FONTS = "family=EB+Garamond:wght@400;500;600&family=Inter:wght@400;500;600"
RELEASE_CSS = """
  body { background:#fdfdfb; color:#151313;
         font-family:'EB Garamond',Garamond,serif; padding:72px 92px 96px }
  .letter { display:flex; align-items:baseline; border-bottom:2px solid #1b2b3a;
            padding-bottom:14px; margin-bottom:9px }
  .letter .n { font-size:23px; font-weight:600; letter-spacing:.06em; color:#1b2b3a }
  .letter .c { margin-left:auto; font-family:'Inter',sans-serif; font-size:11px;
               letter-spacing:.1em; color:#7a7a72 }
  .tagline { font-family:'Inter',sans-serif; font-size:10px; letter-spacing:.3em;
             text-transform:uppercase; color:#8a8a80; margin-bottom:44px }
  .flag { font-family:'Inter',sans-serif; font-size:11px; font-weight:600;
          letter-spacing:.28em; text-transform:uppercase; color:#9a3b2e;
          margin-bottom:18px }
  h1 { font-size:30px; font-weight:600; line-height:1.3; margin-bottom:20px;
       max-width:760px }
  .dateline { font-family:'Inter',sans-serif; font-size:12px; letter-spacing:.06em;
              color:#6a6560; border-bottom:1px solid #e6e3dc;
              padding-bottom:14px; margin-bottom:24px }
  .h2 { font-size:19px; font-weight:600; margin:24px 0 11px }
  .p { font-size:16px; line-height:1.78; margin-bottom:15px; text-align:justify;
       hyphens:auto }
  .end { text-align:center; letter-spacing:.5em; color:#9a938a; margin:30px 0 26px }
  .contact { border-top:1px solid #e6e3dc; padding-top:16px;
             font-family:'Inter',sans-serif; font-size:12px; line-height:1.8;
             color:#5a554e }
  .contact b { display:block; font-size:10px; letter-spacing:.22em;
               text-transform:uppercase; color:#8a8a80; margin-bottom:7px }
  .runhead { font-family:'Inter',sans-serif; font-size:11px; letter-spacing:.16em;
             text-transform:uppercase; color:#a8a49c;
             border-bottom:1px solid #e6e3dc; padding-bottom:12px; margin-bottom:26px }
  .foot { position:absolute; left:92px; right:92px; bottom:46px;
          font-family:'Inter',sans-serif; font-size:11px; color:#a8a49c;
          display:flex; justify-content:space-between }
"""


def release(doc, items, page_no, total, start):
    d = doc["content"]
    if page_no == 1:
        head = f"""
  <div class="letter"><span class="n">{esc(d["org"])}</span>
    <span class="c">{esc(d["contact_line"])}</span></div>
  <div class="tagline">{esc(d["tagline"])}</div>
  <div class="flag">For Immediate Release</div>
  <h1>{esc(d["headline"])}</h1>
  <div class="dateline">{esc(d["dateline"])}</div>"""
    else:
        head = f"""
  <div class="runhead">{esc(d["org"])} &nbsp;·&nbsp; {esc(d["headline"][:60])}</div>"""
    tail = (f"""
  <div class="end">###</div>
  <div class="contact"><b>Media Contact</b>{esc(d["contact"])}</div>"""
            if page_no == total else "")
    return page(d["headline"], RELEASE_FONTS, RELEASE_CSS, f"""{head}
  {flow(items, doc["exhibit"], start)}{tail}
  <div class="foot" data-region="footer"><span>{esc(d["footer"])}</span>
    <span>Page {page_no} of {total}</span></div>""")


# Genres whose text flows across as many pages as it needs, and the two that
# are a single designed sheet.
FLOWING = {"brochure": brochure, "portal": portal, "news": news,
           "newswire": newswire, "faculty": faculty, "release": release}
SINGLE = {"certificate": certificate, "programme": programme}
