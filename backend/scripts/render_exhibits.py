"""Render exhibits from HTML and measure their bboxes at render time (OT-01/OT-03).

Implements docs/Exhibit渲染管线_技术规格.md. The one idea the whole thing rests on:

    **Rendering is the truth.** A bbox is not recovered afterwards by OCR; it is
    measured from the DOM at the moment the page is drawn. Every geometric step
    after that is recorded as a 3x3 homography, the image goes through
    warpPerspective and the coordinates through perspectiveTransform, and both
    use the same H.

    OCR is for acceptance only, never for producing coordinates.

That inverts the usual order and removes a whole class of error. Coordinates
recovered by OCR are a second measurement of something already known exactly,
and they drift: a character misread, a line merged, a box a few pixels off. Here
the number the highlight uses is the number the browser laid the text out with.

The five rules from the spec, and where each lives:

  R1  getClientRects(), not getBoundingClientRect()   -> `measure`
  R2  geometry and photometry strictly separated      -> `warp` vs `weather`
  R3  keep both quad and axis-aligned box             -> `record`
  R4  normalise to 0-1000, origin top-left            -> NORM
  R5  the homography goes into the manifest           -> `build`

Two things the reference implementation left for here: a union box per snippet
(the spec's §8 -- the viewer highlights one rectangle per snippet, not one per
line), and the acceptance checks V3/V4/V6 wired in so a bad render fails the run
instead of being noticed later.

The spec leaves V1 -- "the box is on the right words" -- to a person looking at
CHECK.png. That does not scale past a page or two, and it is the check that
matters most, so `check_marks` does it mechanically instead. Every page is
rendered a second time with the browser painting each line box in a colour of
its own, and that render goes through the same homography. The coloured pixels
are the paint pass's account of where a line ended up; `bbox_norm` is
getClientRects()'s account carried through the matrix. Two accounts from two
code paths, compared per snippet, on every page.

It has to be that, and not something simpler. Every other check here reads the
same numbers back through the same matrix, so none of them can notice the
numbers being wrong -- measured directly, an ink-coverage test could not tell a
correctly rotated box from one the homography never touched, because a fraction
of a degree still leaves a box sitting on its own text.
"""
from __future__ import annotations

import argparse
import json
import sys
import zlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List

# cv2, numpy and playwright are imported inside the functions that use them.
# The acceptance checks below are pure arithmetic, and scripts/audit.py has to
# be able to run them from an environment that has neither a browser nor
# OpenCV installed -- an import at module scope would make that impossible and
# turn "the checks did not run" into "the checks passed".

# The convention the viewer already uses (红线 #8): a coordinate divided by 1000
# is a fraction of the page, so a highlight holds at any zoom or render width.
NORM = 1000.0

# Colours for the marked render. Saturated, far apart in hue, and never near
# paper or ink, so they survive the warp, the noise and the JPEG and can still
# be told apart. Twelve is more than any page needs at once; snippets that share
# one are separated by being nowhere near each other, and the check pairs a
# colour with the snippet it was assigned rather than guessing from the colour.
MARK_COLOURS = [f"{r},{g},{b}"
                for r in (0, 128, 255) for g in (0, 128, 255) for b in (0, 128, 255)
                if not (r == g == b)]        # 24, greys excluded: paper and ink

# Max rotation, perspective jitter, noise sigma, JPEG quality.
SCAN_LEVELS = {
    "light": (0.25, 0.0015, 3, 92),
    "medium": (0.7, 0.004, 6, 82),
    "heavy": (1.4, 0.008, 11, 70),
}


# ---------------------------------------------------------------------------
# 1. Render, and measure while the browser still knows where everything is
# ---------------------------------------------------------------------------
@contextmanager
def _chromium(browser):
    """Yield a browser: the caller's if it has one, otherwise a throw-away."""
    from playwright.sync_api import sync_playwright

    if browser is not None:
        yield browser
        return
    with sync_playwright() as pw:
        chrome = pw.chromium.launch()
        try:
            yield chrome
        finally:
            chrome.close()



def measure(html: Path, out_png: Path, width: int, scale: int,
            browser=None) -> Dict[str, Any]:
    """Draw the page and take every [data-snippet-id] rectangle off the DOM.

    R1: one record per LINE. A snippet that wraps has no single honest
    rectangle -- one box spanning every line includes the whitespace between
    them and the empty right-hand end of the last line, which highlights badly
    and, worse, blurs the adjacency that `mislocation` plants depend on.

    The measurement goes through a Range, not the element. `Element.getClientRects`
    is per-line only for INLINE elements; on a block -- which is what a `<p>` or
    `<h1>` carrying data-snippet-id is -- it returns one rect for the whole
    border box, i.e. exactly the big rectangle R1 forbids, silently. A Range over
    the element's contents returns one rect per line box in both cases.

    Nested inlines (`<em>`, `<strong>`) split a line into several rects, so rects
    that sit on the same baseline are merged: the result is one rect per visual
    line, hugging the text, with the last short line no wider than its words.
    """
    from playwright.sync_api import TimeoutError as PWTimeout

    # A set is dozens of pages; launching Chromium per page costs more than
    # rendering them. `browser` is passed in when a whole set is being built.
    with _chromium(browser) as chrome:
        page = chrome.new_page(
            viewport={"width": width, "height": 1400}, device_scale_factor=scale
        )
        # Wait for the document, then for the network, then for the fonts --
        # in that order, and forgivingly. Waiting on "load" alone means one slow
        # font stylesheet can hang the whole set on a 30s timeout; waiting on
        # `document.fonts.ready` is what actually matters, because webfonts
        # change line breaking and measuring before they land measures a layout
        # nobody will ever see. If a face genuinely never arrives, the per-page
        # font check reports it by name rather than the build dying here.
        page.goto(html.resolve().as_uri(), wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except PWTimeout:
            pass
        try:
            page.evaluate("() => document.fonts.ready")
        except Exception:
            pass

        # Make the viewport the document's own height before anything is
        # measured. A full-page screenshot is the taller of the two, so a
        # document shorter than the viewport gets a strip of blank paper below
        # it -- and, worse, y is then normalised against a page taller than the
        # one that was laid out, so every box sits slightly high. Resizing also
        # settles any height-relative CSS before the rects are read.
        # body, not documentElement: the latter's scrollHeight is clamped
        # to the viewport, so it can never report a shorter page.
        doc_h = page.evaluate(
            "() => Math.ceil(Math.max(document.body.scrollHeight,"
            "                         document.body.offsetHeight))")

        # How far the citable text runs past the type area.
        #
        # A designed page has a fixed height and hides what will not fit, which
        # is how a paragraph disappears without anyone noticing: the citation
        # still resolves, the box is still correct, and the words are simply not
        # on the sheet. Nobody can answer a question about a passage that was
        # cropped off the bottom.
        #
        # Measured against the type area rather than by comparing scrollHeight
        # with clientHeight, which looks like the obvious test and is not one:
        # `overflow:hidden` makes a box unscrollable, and Chromium then reports
        # the two as equal however far the content runs past the edge. That
        # version of this check sat here reporting zero while a paragraph ran
        # under the footer and off the page.
        overflow = page.evaluate("""() => {
            const b = document.body, cs = getComputedStyle(b)
            const r = b.getBoundingClientRect()
            const floor = r.top + b.clientHeight - parseFloat(cs.paddingBottom)
            let worst = 0
            document.querySelectorAll('[data-snippet-id]').forEach((el) => {
                worst = Math.max(worst, el.getBoundingClientRect().bottom - floor)
            })
            return Math.round(worst)
        }""")
        if doc_h and doc_h != page.viewport_size["height"]:
            page.set_viewport_size({"width": width, "height": int(doc_h)})
            page.wait_for_timeout(50)

        # Shrink anything taller than the rectangle its source document gave it.
        #
        # Blocks are pinned at the source's coordinates and re-typeset in a new
        # face, so a block that comes out taller than its original does not
        # overflow into empty space -- it lands on the block below. The template
        # sizes each block by estimate; this is where the estimate is checked
        # against what the browser actually did, which is the only measurement
        # that counts.
        crowded = page.evaluate("""() => {
            const MIN = 9          // below this a page stops being readable
            const out = []
            document.querySelectorAll('[data-fit-h]').forEach((el) => {
                const max = parseFloat(el.dataset.fitH)
                if (!(max > 0)) return
                const start = parseFloat(getComputedStyle(el).fontSize)
                let size = start
                while (el.getBoundingClientRect().height > max && size > MIN) {
                    size = Math.max(MIN, size - 0.5)
                    el.style.fontSize = size + 'px'
                }
                if (size < start) {
                    out.push({snippet_id: el.dataset.snippetId || '?',
                              from: start, to: size,
                              floored: size <= MIN &&
                                       el.getBoundingClientRect().height > max})
                }
            })
            return out
        }""")

        box = page.evaluate("""() => {
            const r = document.body.getBoundingClientRect()
            return {x: r.x + scrollX, y: r.y + scrollY,
                    width: r.width, height: r.height}
        }""")

        rects = page.evaluate("""() => {
            // Two rects belong to the same visual line when they overlap
            // vertically by more than half the shorter one. Superscripts and
            // different font sizes on one line have different heights, so a
            // shared-top test is not enough.
            const sameLine = (a, b) => {
                const overlap = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
                return overlap > 0.5 * Math.min(a.height, b.height)
            }

            const out = []
            document.querySelectorAll('[data-snippet-id]').forEach((el) => {
                const id = el.dataset.snippetId
                const text = el.textContent.replace(/\\s+/g, ' ').trim()
                const label = el.dataset.snippetLabel || ''
                const cs = getComputedStyle(el)
                // Its own line-height, so the R1 check below compares a box to
                // the element that produced it rather than to other snippets.
                const lh = parseFloat(cs.lineHeight) ||
                           parseFloat(cs.fontSize) * 1.2

                const range = document.createRange()
                range.selectNodeContents(el)
                let rects = Array.from(range.getClientRects())
                    .filter((r) => r.width >= 1 && r.height >= 1)
                // No text (a figure, a seal): fall back to the element's own box.
                if (!rects.length) {
                    rects = Array.from(el.getClientRects())
                        .filter((r) => r.width >= 1 && r.height >= 1)
                }
                rects.sort((a, b) => a.top - b.top || a.left - b.left)

                const lines = []
                for (const r of rects) {
                    const last = lines[lines.length - 1]
                    if (last && sameLine(last, r)) {
                        last.top = Math.min(last.top, r.top)
                        last.bottom = Math.max(last.bottom, r.bottom)
                        last.left = Math.min(last.left, r.left)
                        last.right = Math.max(last.right, r.right)
                        last.height = last.bottom - last.top
                    } else {
                        lines.push({top: r.top, bottom: r.bottom,
                                    left: r.left, right: r.right, height: r.height})
                    }
                }

                lines.forEach((r, line) => out.push({
                    snippet_id: id, line, text, label, line_height: lh,
                    x: r.left + scrollX, y: r.top + scrollY,
                    w: r.right - r.left, h: r.bottom - r.top,
                }))
            })
            return out
        }""")
        # Reserved areas that hold no text (a photograph's place on the page).
        # They carry no snippet_id and never reach the participant, but the
        # collision check below needs them: text landing on a photograph is a
        # layout failure exactly like text landing on text.
        regions = page.evaluate("""() => {
            // Reserved areas and page furniture: a photograph's place on the
            // page, a footer, a seal. None of them are citable, and none of
            // them may have text printed across them.
            return [...document.querySelectorAll('.image, [data-region]')]
                .map((el) => {
                    const r = el.getBoundingClientRect()
                    return {kind: el.dataset.region || 'image',
                            x: r.x + scrollX, y: r.y + scrollY,
                            w: r.width, h: r.height}
                })
        }""")

        doc_title = page.title()
        # Did anything end up in a fallback face? The spec says to wait for the
        # webfonts; it does not say how to tell that the wait worked, and a
        # missing face is invisible -- the page still renders, in other metrics,
        # with other line breaks, and the boxes measured off it are perfectly
        # self-consistent, so nothing downstream can notice.
        #
        # The question has to be asked per element, not per declared family.
        # Browsers load a face only when something actually uses it, so a family
        # declared for image captions on a page with no captions never loads and
        # never should. What matters is whether the face THIS element asked for
        # is available.
        missing_fonts = page.evaluate(r"""() => {
            const generic = /^(serif|sans-serif|monospace|cursive|fantasy|system-ui|ui-\w+)$/i
            const missing = new Set()
            document.querySelectorAll('[data-snippet-id]').forEach((el) => {
                const cs = getComputedStyle(el)
                const first = cs.fontFamily.split(',')[0].trim()
                                .replace(/^["']|["']$/g, '')
                if (!first || generic.test(first)) return
                const want = `${cs.fontStyle} ${cs.fontWeight} `
                           + `${parseFloat(cs.fontSize)}px "${first}"`
                if (!document.fonts.check(want)) missing.add(first)
            })
            return [...missing]
        }""")

        # Photograph the body's own rectangle, not the whole document.
        #
        # `full_page` captures the documentElement, and a child's top margin can
        # escape the body and make the document taller than the page -- a 20px
        # margin on a running head did exactly that, so every continuation sheet
        # came out 1314px tall against a 1294px design and the aspect check
        # rejected the lot. Clipping to the body makes the image the page by
        # construction, whatever a template does with its margins.
        page.screenshot(path=str(out_png), clip=box)

        # A second render in which the browser paints each line box in a colour
        # of its own, so the finished page can be asked where its own text is.
        #
        # This is the witness for V1. Everything else in this file traces the
        # SAME numbers through the same matrix, so it cannot notice the numbers
        # being wrong -- an ink-coverage check, for instance, cannot tell a
        # correctly rotated box from one that never got rotated at all, because
        # a 0.7 degree error still leaves the box on its words. The highlights
        # below come from the paint pass rather than from getClientRects(), so
        # comparing them against the manifest compares two independent accounts
        # of where a line is, and a disagreement is a real defect.
        marks = page.evaluate("""() => {
            if (!window.CSS || !CSS.highlights) return null
            const style = document.createElement('style')
            // Strip the page down to greys first. The marked render is an
            // instrument, not an exhibit: the only saturated colour on it
            // should be the marks. A theme is free to choose any colour, and
            // one of them will eventually land near a palette entry after the
            // warp and the JPEG -- the portal's red rule did, and was read as a
            // snippet spanning the whole page.
            //
            // Only paint properties are touched. Nothing here can move a line,
            // which matters because the rects were measured before this ran.
            style.textContent =
                '*, *::before, *::after { background-image: none !important;' +
                // transparent, NOT white: a decorative overlay -- a certificate's
                // frame, a watermark -- is an absolutely positioned element, and
                // positioned elements paint above in-flow content. Painting one
                // white turns it into a sheet over the page, and the marks under
                // it vanish. Which is how this was found: the certificate's
                // frame hid every line that did not carry its own z-index.
                ' background-color: transparent !important;' +
                ' border-color: #ddd !important; color: #333 !important;' +
                ' box-shadow: none !important; text-shadow: none !important;' +
                ' filter: none !important }' +
                'body { background-color: #fff !important }'
            const out = []
            let i = 0
            document.querySelectorAll('[data-snippet-id]').forEach((el) => {
                const range = document.createRange()
                range.selectNodeContents(el)
                // One hue per line is not possible -- a Highlight covers a Range,
                // and the paint pass decides where its lines fall. That is the
                // point: the split into lines is the browser's, not ours.
                const name = 'm' + i
                CSS.highlights.set(name, new Highlight(range))
                const rgb = MARKS[i % MARKS.length]
                // Appended after the reset above, so these win on order.
                style.textContent += `::highlight(${name}){`
                                   + `background-color:rgb(${rgb}) !important;`
                                   + `color:rgb(${rgb}) !important}`
                out.push({snippet_id: el.dataset.snippetId, rgb})
                i += 1
            })
            document.head.appendChild(style)
            return out
        }""".replace("MARKS", json.dumps(MARK_COLOURS)))

        marked_png = None
        if marks is not None:
            marked_png = out_png.with_name(out_png.stem + ".marked.png")
            page.screenshot(path=str(marked_png), clip=box)

        page.close()

    # Everything measured is in page coordinates; the image starts at the clip
    # origin, so the two only agree once that origin is taken off.
    ox, oy = box["x"], box["y"]

    fragments = []
    for r in rects:
        x, y = (r["x"] - ox) * scale, (r["y"] - oy) * scale
        w, h = r["w"] * scale, r["h"] * scale
        fragments.append({
            "snippet_id": r["snippet_id"],
            "line": r["line"],
            "text": r["text"],
            "label": r["label"],
            "height": h,
            "line_height": r["line_height"] * scale,
            "quad": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
        })
    boxes = []
    for r in regions:
        x, y = (r["x"] - ox) * scale, (r["y"] - oy) * scale
        w, h = r["w"] * scale, r["h"] * scale
        boxes.append({"kind": r["kind"],
                      "quad": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]})

    return {"fragments": fragments, "regions": boxes, "doc_title": doc_title,
            "fonts_missing": sorted(missing_fonts), "crowded": crowded,
            "overflow": overflow,
            "marks": marks, "marked_png": marked_png}


def check_lines(fragments: List[Dict[str, Any]]) -> List[str]:
    """R1, mechanically: a line box is one line tall.

    This is the check that would have caught measuring blocks instead of lines.
    A box holding n lines comes out about n times its element's own line-height,
    and comparing each box to the element that produced it means a 60px title and
    a 10px footnote are both judged correctly. 1.8 leaves room for a tall glyph
    or an inline image without admitting a two-line box.
    """
    problems = []
    for frag in fragments:
        limit = frag["line_height"] * 1.8
        if limit > 0 and frag["height"] > limit:
            problems.append(
                f"R1 {frag['snippet_id']} line {frag['line']}: box is "
                f"{frag['height']:.0f}px against a line-height of "
                f"{frag['line_height']:.0f}px -- this is a block box, not a line")
    return problems


# ---------------------------------------------------------------------------
# 2. Geometry. Everything here goes into H; nothing else may.
# ---------------------------------------------------------------------------

def h_rotate(deg: float, w: int, h: int):
    import cv2
    import numpy as np
    m = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return np.vstack([m, [0, 0, 1]]).astype(np.float64)


def h_perspective(w: int, h: int, jitter: float, rng):
    """Small corner jitter: paper not lying flat, or a photo taken by hand."""
    import cv2
    import numpy as np
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    d = jitter * min(w, h)
    dst = src + rng.uniform(-d, d, src.shape).astype(np.float32)
    return cv2.getPerspectiveTransform(src, dst).astype(np.float64)


def make_h(level: str, w: int, h: int, rng):
    """The page's geometry, as one matrix. Nothing else may move a pixel."""
    max_deg, jitter, _, _ = SCAN_LEVELS[level]
    return h_perspective(w, h, jitter, rng) @ h_rotate(rng.uniform(-max_deg, max_deg), w, h)


def apply_h(img, matrix):
    import cv2
    h, w = img.shape[:2]
    return cv2.warpPerspective(
        img, matrix, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(252, 250, 246),
    )


def warp(img, level: str, rng) -> tuple:
    """Apply the geometric layer. Returns (image, H) -- the same H the points use."""
    matrix = make_h(level, img.shape[1], img.shape[0], rng)
    return apply_h(img, matrix), matrix


def weather(img, level: str, rng):
    """The photometric layer: paper tone, uneven light, sensor noise, focus,
    compression. R2 -- none of it moves a pixel, so no coordinate changes and
    none of it has to be reasoned about when checking a box."""
    import cv2
    import numpy as np
    _, _, noise, quality = SCAN_LEVELS[level]
    h, w = img.shape[:2]

    yy, xx = np.mgrid[0:h, 0:w]
    vignette = 1.0 - 0.10 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    out = (img.astype(np.float32) * vignette[..., None]).clip(0, 255)
    out = (out * np.array([0.985, 0.995, 1.0], dtype=np.float32)).clip(0, 255).astype(np.uint8)

    out = (out.astype(np.int16)
           + rng.normal(0, noise, out.shape).astype(np.int16)).clip(0, 255).astype(np.uint8)
    out = cv2.GaussianBlur(out, (3, 3), 0.5)

    ok, enc = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return cv2.imdecode(enc, cv2.IMREAD_COLOR) if ok else out


def transform(matrix, quad: List[List[float]]) -> List[List[float]]:
    import cv2
    import numpy as np
    pts = np.array(quad, dtype=np.float64).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(pts, matrix).reshape(-1, 2).tolist()


def aabb(quads: List[List[List[float]]]) -> List[float]:
    import numpy as np
    pts = np.array([p for q in quads for p in q])
    return [float(pts[:, 0].min()), float(pts[:, 1].min()),
            float(pts[:, 0].max()), float(pts[:, 1].max())]


# ---------------------------------------------------------------------------
# 3. Acceptance (spec §7). V3, V4 and V6 run here; V1 is CHECK.png, by eye.
# ---------------------------------------------------------------------------

ANSWER_KEY_FIELDS = ("planted_id", "distractor", "source_says", "text_clean")


def _overlap(a: List[float], b: List[float]) -> float:
    """Shared area as a fraction of the smaller box. 0 when they do not touch."""
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    areas = ((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    smaller = min(areas)
    return ((x2 - x1) * (y2 - y1) / smaller) if smaller > 0 else 0.0


# A little contact is normal -- a descender reaching into the line below, a
# heading's box brushing the rule under it. A quarter of the smaller box is not.
COLLISION = 0.25


def check_layout(manifest: Dict[str, Any]) -> List[str]:
    """Nothing may be printed on top of anything else.

    The blocks are pinned at the source document's coordinates but re-typeset,
    so a block that ends up taller than the rectangle it was given does not
    overflow into empty space -- it lands on whatever comes next. On a set this
    size that cannot be caught by looking; a heading that has swallowed the line
    beneath it is still perfectly legible in isolation, and the CHECK image
    shows two boxes that each look right.
    """
    problems = []
    items = ([(s["snippet_id"], s["bbox_norm"]) for s in manifest["snippets"]]
             + [(f"[{r['kind']}]", r["bbox_norm"]) for r in manifest.get("regions", [])])

    for i, (name_a, box_a) in enumerate(items):
        for name_b, box_b in items[i + 1:]:
            share = _overlap(box_a, box_b)
            if share > COLLISION:
                problems.append(
                    f"layout {manifest['exhibit']} p{manifest['page']}: "
                    f"{name_a} and {name_b} overlap by {share:.0%} of the smaller "
                    f"-- one is printed on top of the other")
    return problems


def check_marks(manifest: Dict[str, Any], marked, marks) -> List[str]:
    """Ask the finished page where its own text is, and see if it agrees.

    The second render paints every line box in a colour of its own, then goes
    through the same warp as the exhibit. So the coloured pixels are the paint
    pass's account of where a line ended up, and `bbox_norm` is
    getClientRects()'s account carried through the homography. Two accounts,
    two code paths, one number: if they agree the box really is on the words.

    This is the one check with that property. Every other check in this file
    reads the same numbers back, so none of them can notice the numbers being
    wrong -- measured directly, an ink-coverage test cannot even distinguish a
    correctly rotated box from one the homography never touched, because a
    fraction of a degree still leaves a box sitting on its own text.
    """
    import cv2
    import numpy as np

    h, w = marked.shape[:2]
    problems = []
    worst = 0.0

    # The tolerance is a fraction of a line, not a fixed number of pixels. The
    # error that matters is a box on the wrong line, so the gate should scale
    # with the thing it is measured against: a page set in 11px type and one set
    # in 40px display type do not deserve the same allowance. Measured across
    # this set the true disagreement runs to 6.5px on lines around 40px tall --
    # antialiasing, cubic resampling and the chroma smear at every edge -- so a
    # third of a line leaves real margin while staying far below the ~1.45 lines
    # that being off by one costs.
    heights = [max(q[1] for q in line["quad_norm"]) - min(q[1] for q in line["quad_norm"])
               for s in manifest["snippets"] for line in s["lines"]]
    line_px = (sorted(heights)[len(heights) // 2] / NORM * h) if heights else 30.0
    tolerance = max(6.0, line_px / 3)

    # Sideways gets more room than up and down, for a reason worth writing out.
    #
    # On a justified line `getClientRects()` returns the LINE BOX, which runs to
    # the measure, while the paint stops at the last glyph -- the difference is
    # the space justification pushed to the end of the line. Measured here: 12px
    # on a 1685px column, and nothing at all on the last line of a paragraph,
    # which is not justified. That is typography, not a misplaced box.
    #
    # The error this check exists to catch is a box on the wrong line, and that
    # is vertical, so the vertical tolerance stays at a third of a line. A
    # horizontal error that matters -- the wrong column, the wrong paragraph --
    # is far larger than half a line height.
    tol = (line_px / 2, tolerance, line_px / 2, tolerance)

    # Snippets are grouped by colour: a page with more snippets than the palette
    # has colours reuses them, and then the honest comparison is the union of
    # everything wearing that colour against every pixel of it.
    by_colour: Dict[str, List[Dict[str, Any]]] = {}
    index = {s["snippet_id"]: s for s in manifest["snippets"]}
    for mark in marks:
        snippet = index.get(mark["snippet_id"])
        if snippet:
            by_colour.setdefault(mark["rgb"], []).append(snippet)

    pixels = marked.reshape(-1, 3).astype(np.int16)
    for rgb, snippets in by_colour.items():
        r, g, b = (int(v) for v in rgb.split(","))
        near = (np.abs(pixels - np.array([b, g, r], np.int16)).max(axis=1) < 40)
        mask = near.reshape(h, w).astype(np.uint8)
        # Chroma subsampling smears a few pixels at every edge; drop specks so
        # they cannot stretch the bounding box.
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        found = np.argwhere(mask > 0)

        names = ", ".join(s["snippet_id"] for s in snippets)
        if not found.size:
            problems.append(
                f"V1 {manifest['exhibit']} p{manifest['page']}: {names} was "
                f"painted rgb({rgb}) but no such pixels are on the page")
            continue

        painted = [found[:, 1].min(), found[:, 0].min(),
                   found[:, 1].max(), found[:, 0].max()]
        claimed = [min(s["bbox_norm"][0] for s in snippets) / NORM * w,
                   min(s["bbox_norm"][1] for s in snippets) / NORM * h,
                   max(s["bbox_norm"][2] for s in snippets) / NORM * w,
                   max(s["bbox_norm"][3] for s in snippets) / NORM * h]

        gaps = [abs(p - c) for p, c in zip(painted, claimed)]
        drift = max(gaps)
        worst = max(worst, drift)
        over = max(g - t for g, t in zip(gaps, tol))
        if over > 0:
            problems.append(
                f"V1 {manifest['exhibit']} p{manifest['page']}: {names} is "
                f"recorded at {[round(c) for c in claimed]} but the page paints "
                f"it at {[int(v) for v in painted]} -- {drift:.0f}px out, "
                f"{over:.0f}px past what a line of {line_px:.0f}px allows")

    # Recorded in the artefact, so "V1 passed" is a number someone can read off
    # the manifest rather than a claim in a commit message.
    manifest["v1_max_drift_px"] = round(worst, 1)
    manifest["v1_tolerance_px"] = round(tolerance, 1)
    manifest["v1_tolerance_x_px"] = round(line_px / 2, 1)
    return problems


def check(manifest: Dict[str, Any], expected_ids: set) -> List[str]:
    problems = []

    # V3: every box inside the page, and the right way round.
    for snip in manifest["snippets"]:
        x1, y1, x2, y2 = snip["bbox_norm"]
        if not (0 <= x1 < x2 <= NORM and 0 <= y1 < y2 <= NORM):
            problems.append(f"V3 {snip['snippet_id']}: bbox outside 0-1000 or inverted: "
                            f"{[round(v, 1) for v in snip['bbox_norm']]}")

    # V4: everything the template promised actually rendered. A snippet that
    # silently failed to draw would leave an argument citing nothing.
    got = {s["snippet_id"] for s in manifest["snippets"]}
    for missing in sorted(expected_ids - got):
        problems.append(f"V4 {missing}: declared in the template but not measured")

    # V6: the answer key is not in a render artefact. It never should be -- this
    # pipeline does not read planted.json -- which is exactly why it is worth
    # asserting: the check costs nothing and catches a future careless join.
    blob = json.dumps(manifest, ensure_ascii=False)
    for field in ANSWER_KEY_FIELDS:
        if field in blob:
            problems.append(f"V6: {field!r} appears in the render manifest")

    return problems


# ---------------------------------------------------------------------------
# 4. One page, end to end
# ---------------------------------------------------------------------------

def build_page(html: Path, out_dir: Path, exhibit: str, page: int,
               level: str, seed: int, width: int, scale: int,
               browser=None, drop_clean: bool = False) -> tuple:
    import cv2
    import numpy as np
    pages_dir = out_dir / "pages" / exhibit
    man_dir = out_dir / "exhibits" / exhibit
    pages_dir.mkdir(parents=True, exist_ok=True)
    man_dir.mkdir(parents=True, exist_ok=True)

    clean_png = man_dir / f"{page}.clean.png"
    measured = measure(html, clean_png, width, scale, browser)

    img = cv2.imread(str(clean_png))
    if img is None:
        raise SystemExit(f"nothing rendered for {exhibit} p{page}")
    h, w = img.shape[:2]

    rng = np.random.default_rng(seed)
    warped, matrix = warp(img, level, rng)
    scanned = weather(warped, level, rng)

    out_jpg = pages_dir / f"{page}.jpg"
    cv2.imwrite(str(out_jpg), scanned, [cv2.IMWRITE_JPEG_QUALITY, 88])

    # The marked render goes through the SAME matrix -- not a fresh one drawn
    # from the same seed, the same object. Re-deriving it would make the check
    # agree with itself by construction, which is the failure mode this whole
    # detour exists to avoid.
    marked = None
    if measured.get("marked_png"):
        raw = cv2.imread(str(measured["marked_png"]))
        if raw is not None:
            marked = weather(apply_h(raw, matrix), level, np.random.default_rng(seed))
            if not drop_clean:
                cv2.imwrite(str(man_dir / f"{page}.marked.png"), marked)
        if drop_clean:
            measured["marked_png"].unlink(missing_ok=True)

    # Line fragments first, then one union box per snippet: the viewer highlights
    # a snippet, the analysis reasons about its lines (spec §8).
    by_id: Dict[str, List[Dict[str, Any]]] = {}
    for frag in measured["fragments"]:
        moved = transform(matrix, frag["quad"])
        by_id.setdefault(frag["snippet_id"], []).append({
            "line": frag["line"],
            "text": frag["text"],
            "label": frag["label"],
            "quad_px": moved,
        })

    def norm_quad(quad):
        return [[x / w * NORM, y / h * NORM] for x, y in quad]

    snippets = []
    for snippet_id, frags in by_id.items():
        frags.sort(key=lambda f: f["line"])
        union = aabb([f["quad_px"] for f in frags])
        snippets.append({
            "snippet_id": snippet_id,
            "exhibit": exhibit,
            "page": page,
            "text": frags[0]["text"],
            "label": frags[0]["label"],
            # The union of every line, for the highlight the viewer draws.
            "bbox_norm": [union[0] / w * NORM, union[1] / h * NORM,
                          union[2] / w * NORM, union[3] / h * NORM],
            # Per line, exact after rotation, for adjacency and for analysis.
            "lines": [{"line": f["line"], "quad_norm": norm_quad(f["quad_px"])}
                      for f in frags],
        })

    regions = []
    for region in measured["regions"]:
        rq = transform(matrix, region["quad"])
        box = aabb([rq])
        regions.append({
            "kind": region["kind"],
            "bbox_norm": [box[0] / w * NORM, box[1] / h * NORM,
                          box[2] / w * NORM, box[3] / h * NORM],
        })

    manifest = {
        "schema_version": 1,
        "exhibit": exhibit,
        "page": page,
        "doc_title": measured["doc_title"],
        "fonts_missing": measured["fonts_missing"],
        "page_px": [w, h],
        "scan_level": level,
        "seed": seed,
        # R5. Not for reproduction -- for diagnosis. When a box looks wrong,
        # having H is the difference between "the render is off" and "the
        # transform is off", which are fixed in different places.
        "homography": matrix.tolist(),
        "coordinate_convention": "normalized 0-1000, origin top-left",
        "provenance": "rendered-from-html; bbox measured from DOM, never OCR'd",
        "snippets": sorted(snippets, key=lambda s: s["snippet_id"]),
        "regions": regions,
        # Which colour each snippet was painted in the marked render. Kept so
        # that V1 can be re-checked against <page>.marked.png later without
        # re-rendering, and so a failure can be looked at rather than guessed at.
        "v1_marks": measured.get("marks") or [],
    }
    # The boxes drawn back onto the scanned page. The spec makes this V1 and
    # says a person has to look at it. `check_marks` now answers the same
    # question mechanically, on every page, by asking the render where its own
    # text is -- so this image is no longer the only thing standing between a
    # wrong coordinate and a study; it is for reading a page that looks odd.
    #
    # Drawn on the file that will be served, re-read from disk, not on the array
    # it came from. The participant sees the JPEG; verifying against the pixels
    # that existed before compression verifies something nobody will ever look
    # at. Outside the strokes this image is now byte-identical to the page, so
    # "the boxes are in the right place" is a statement about the exhibit rather
    # than about an intermediate.
    overlay = cv2.imread(str(out_jpg))
    for snip in manifest["snippets"]:
        for line in snip["lines"]:
            pts = np.array([[x / NORM * w, y / NORM * h] for x, y in line["quad_norm"]],
                           np.int32)
            cv2.polylines(overlay, [pts], True, (0, 0, 255), 2)
        x1, y1, x2, y2 = snip["bbox_norm"]
        cv2.rectangle(overlay, (int(x1 / NORM * w), int(y1 / NORM * h)),
                      (int(x2 / NORM * w), int(y2 / NORM * h)), (255, 128, 0), 1)
    # PNG: a verification image should not itself be lossy. Re-compressing it
    # would put artefacts around exactly the thin coloured lines being judged.
    cv2.imwrite(str(man_dir / f"{page}.CHECK.png"), overlay)

    if drop_clean:
        clean_png.unlink(missing_ok=True)

    # R1 is judged on the layout, before the warp: line-height is a typographic
    # quantity, and comparing against it is cleaner than after a perspective.
    floored = [c for c in measured["crowded"] if c["floored"]]
    if floored:
        # Not a failure: the box recorded is still exactly where the words are.
        # It does mean this block's replacement text is too long for the space
        # the source document had, which is worth knowing when a page looks
        # cramped.
        print(f"    {exhibit} p{page}: {len(floored)} block(s) hit the minimum "
              f"size and still overflow their source rectangle")

    problems = check_lines(measured["fragments"]) + check_layout(manifest)

    if measured.get("overflow", 0) > 2:
        problems.append(
            f"overflow {exhibit} p{page}: citable text runs {measured['overflow']}px "
            f"past the type area and is cropped -- give this genre a smaller "
            f"page budget")

    if marked is not None and measured.get("marks") is not None:
        # An empty list is a page with nothing citable on it -- an exhibit slip
        # sheet. That is verified, and trivially so; it is not unverifiable.
        problems += check_marks(manifest, marked, measured["marks"])
    else:
        # Never silently: a check that did not run must not look like one that
        # passed. CSS.highlights needs Chromium 105 or newer.
        manifest["v1_max_drift_px"] = None
        print(f"    {exhibit} p{page}: V1 not verified -- this browser has no "
              f"CSS Custom Highlight API, so the page could not be asked where "
              f"its own text is")

    # Written last, so the file carries what the checks found. Writing it before
    # them put v1_max_drift_px on the object and not in the artefact, which is
    # the worst of both: the number existed and nobody could read it.
    (man_dir / f"{page}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return manifest, problems


def declared_ids(html: Path) -> set:
    text = html.read_text(encoding="utf-8")
    import re
    return set(re.findall(r'data-snippet-id\s*=\s*"([^"]+)"', text))


# ---------------------------------------------------------------------------
# 5. A whole set, and the two files the rest of the repo actually reads
# ---------------------------------------------------------------------------

def build_set(spec_path: Path, out_dir: Path, scale: int,
              drop_clean: bool = False) -> int:
    """Render every page named by a spec and emit a bundle.

    A spec is one file listing the exhibits and their pages:

        {"exhibits": [
          {"id": "C-1", "title": "...", "scan": "light",
           "pages": ["c1_p1.html", "c1_p2.html"]}
        ]}

    Scan level is per exhibit rather than per bundle, because a real file has
    documents from different sources: a memo printed yesterday should not carry
    the same wear as a certificate photocopied three times (spec §6).
    """
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    root = spec_path.parent

    exhibits, snippets, sizes = [], {}, {}
    problems: List[str] = []

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw, _closing(pw.chromium.launch()) as chrome:
        _render_all(spec, root, out_dir, scale, chrome,
                    exhibits, snippets, sizes, problems, drop_clean)

    if problems:
        raise SystemExit("acceptance failed:\n  " + "\n  ".join(problems))

    return _write_bundle(out_dir, scale, exhibits, snippets, sizes)


@contextmanager
def _closing(browser):
    try:
        yield browser
    finally:
        browser.close()


def _render_all(spec, root, out_dir, scale, chrome,
                exhibits, snippets, sizes, problems, drop_clean) -> None:
    for ex in spec["exhibits"]:
        exhibit_id = ex["id"]
        pages = []
        for page_no, entry in enumerate(ex["pages"], start=1):
            # A page is either a filename or {"html": ..., "scan": ...}. The
            # second form exists because wear belongs to the page, not the
            # exhibit: an exhibit's slip sheet and the document behind it did
            # not come off the same machine.
            if isinstance(entry, str):
                entry = {"html": entry}
            level = entry.get("scan") or ex.get("scan", "medium")
            html = root / entry["html"]
            # Seed from the exhibit and page, so a page re-renders identically
            # and no two pages share a skew. crc32, not hash(): PYTHONHASHSEED
            # randomises string hashing per process, which would make the seed
            # recorded in the manifest a number that reproduces nothing.
            seed = (zlib.crc32(f"{exhibit_id}:{page_no}".encode()) % 10_000
                    if ex.get("seed") is None else ex["seed"] + page_no)
            manifest, page_problems = build_page(
                html, out_dir, exhibit_id, page_no, level, seed,
                ex.get("width", 1000), scale, chrome, drop_clean)
            problems += page_problems
            problems += check(manifest, declared_ids(html))
            for family in manifest["fonts_missing"]:
                problems.append(
                    f"font {exhibit_id} p{page_no}: text asks for {family!r} but "
                    f"the face is not available, so it was laid out in a fallback")

            w, h = manifest["page_px"]
            pages.append({"page": page_no, "w": w, "h": h})
            want = spec.get("page_aspect")
            if want and abs(h / w - want) > 0.01:
                problems.append(
                    f"aspect {exhibit_id} p{page_no}: rendered {h / w:.3f}, "
                    f"spec says {want:.3f} -- the template's page box drifted")
            for snip in manifest["snippets"]:
                x1, y1, x2, y2 = snip["bbox_norm"]
                snippets[snip["snippet_id"]] = {
                    "snippet_id": snip["snippet_id"],
                    "exhibit": exhibit_id,
                    "page": page_no,
                    # Rounded to whole units of a 1000-space: a third of a
                    # pixel of a highlight, and it keeps the file diffable.
                    "bbox": [round(x1), round(y1), round(x2), round(y2)],
                    "label": snip["label"] or snip["text"][:60],
                    "text": snip["text"],
                    "doc_title": manifest["doc_title"],
                }
            print(f"  {exhibit_id} p{page_no}: {len(manifest['snippets'])} snippets, "
                  f"{sum(len(s['lines']) for s in manifest['snippets'])} line boxes, "
                  f"scan={level}")

        exhibits.append({"id": exhibit_id, "pages": len(pages),
                         "title": ex.get("title", exhibit_id)})
        sizes[exhibit_id] = {"pages": pages}


def _write_bundle(out_dir: Path, scale: int, exhibits, snippets, sizes) -> int:
    """The two files the rest of the repo reads."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "snippets.json").write_text(json.dumps({
        "schema_version": 1,
        "bbox_space": 1000,
        # The other bundles say the boxes came from OCR. These did not, and the
        # difference matters to anyone debugging a highlight: there is no
        # recognition step here that could have misread anything.
        "_comment": ("bbox is normalised to a 1000x1000 space (red line #8), not "
                     "pixels. Measured from the DOM at render time, not OCR'd: "
                     "per-page homography and line boxes are in exhibits/<EX>/<page>.json."),
        "exhibits": exhibits,
        "snippets": snippets,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    index = out_dir / "pages" / "index.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({
        "schema_version": 1,
        "target_width": 1000 * scale,
        "exhibits": sizes,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    total_pages = sum(e["pages"] for e in exhibits)
    print(f"\n{len(exhibits)} exhibits, {total_pages} pages, {len(snippets)} snippets "
          f"-> {out_dir}")
    print("  no OCR anywhere in this path; every box came off the DOM")
    print(f"  check by eye: {out_dir / 'exhibits'}/*/*.CHECK.png")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--spec", type=Path, help="a whole exhibit set")
    src.add_argument("--html", type=Path, help="a single page")
    ap.add_argument("--out", required=True, type=Path, help="bundle directory")
    ap.add_argument("--exhibit", help="with --html")
    ap.add_argument("--page", type=int, default=1, help="with --html")
    ap.add_argument("--scan", default="medium", choices=list(SCAN_LEVELS))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--width", type=int, default=1000, help="CSS px")
    ap.add_argument("--scale", type=int, default=2, help="deviceScaleFactor")
    ap.add_argument("--drop-clean", action="store_true",
                    help="delete each page's unwarped render after warping")
    args = ap.parse_args()

    if args.spec:
        return build_set(args.spec, args.out, args.scale, args.drop_clean)

    if not args.exhibit:
        ap.error("--html needs --exhibit")

    manifest, problems = build_page(args.html, args.out, args.exhibit, args.page,
                                    args.scan, args.seed, args.width, args.scale,
                                    None, args.drop_clean)
    problems += check(manifest, declared_ids(args.html))
    if problems:
        raise SystemExit("acceptance failed:\n  " + "\n  ".join(problems))

    lines = sum(len(s["lines"]) for s in manifest["snippets"])
    print(f"{args.exhibit} p{args.page}: {len(manifest['snippets'])} snippets, "
          f"{lines} line boxes, {manifest['page_px'][0]}x{manifest['page_px'][1]}px, "
          f"scan={args.scan}")
    print(f"  check by eye: exhibits/{args.exhibit}/{args.page}.CHECK.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
