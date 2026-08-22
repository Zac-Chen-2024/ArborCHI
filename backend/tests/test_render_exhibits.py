"""Acceptance checks of the exhibit render pipeline (spec §7).

These test the checks, not the renderer: a gate nobody has watched fail is not
known to be a gate. Rendering itself needs a browser and is exercised by running
the script; what has to hold under CI is that a bad manifest is rejected.

The R1 case is the one that matters most. Measuring block elements instead of
line boxes produces a manifest that passes every other check -- coordinates in
range, every snippet present, no answer-key fields -- while the boxes are wrong
in exactly the way the spec's R1 exists to prevent. It went unnoticed in the
reference implementation, so it gets a test.
"""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "render_exhibits.py"


def _load():
    spec = importlib.util.spec_from_file_location("render_exhibits", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


render = _load()


def frag(height, line_height, snippet_id="s1", line=0):
    return {"snippet_id": snippet_id, "line": line,
            "height": height, "line_height": line_height}


def manifest(snippets):
    return {"exhibit": "A3", "page": 1, "snippets": snippets}


def snip(snippet_id="s1", bbox=(10, 10, 200, 40)):
    return {"snippet_id": snippet_id, "bbox_norm": list(bbox),
            "lines": [{"line": 0, "quad_norm": [[10, 10], [200, 10],
                                                [200, 40], [10, 40]]}]}


# --- R1: one line box is one line tall -------------------------------------

def test_r1_accepts_a_line_box():
    assert check_ok(render.check_lines([frag(28, 24)]))


def test_r1_accepts_a_tall_glyph():
    """Room for a cap-height overshoot or a small inline image."""
    assert check_ok(render.check_lines([frag(41, 24)]))


def test_r1_rejects_a_block_box():
    """Three lines measured as one -- the bug this check exists for."""
    problems = render.check_lines([frag(72, 24)])
    assert len(problems) == 1
    assert "block box, not a line" in problems[0]


def test_r1_names_the_snippet_and_line():
    problems = render.check_lines([frag(72, 24, snippet_id="snip_c3_role", line=2)])
    assert "snip_c3_role" in problems[0] and "line 2" in problems[0]


def test_r1_tolerates_a_missing_line_height():
    """An element with no text yields line_height 0; it must not divide-by-zero
    or fire, because its box legitimately is not a line."""
    assert check_ok(render.check_lines([frag(500, 0)]))


# --- V3: coordinates in range and the right way round ----------------------

@pytest.mark.parametrize("bbox", [
    (-1, 10, 200, 40),      # off the left edge
    (10, 10, 1001, 40),     # past the right edge
    (200, 10, 10, 40),      # x reversed
    (10, 40, 200, 10),      # y reversed
    (10, 10, 10, 40),       # zero width
])
def test_v3_rejects_bad_boxes(bbox):
    problems = render.check(manifest([snip(bbox=bbox)]), {"s1"})
    assert any(p.startswith("V3") for p in problems)


def test_v3_accepts_the_full_page():
    assert check_ok(render.check(manifest([snip(bbox=(0, 0, 1000, 1000))]), {"s1"}))


# --- V4: everything the template declared actually rendered ----------------

def test_v4_flags_a_snippet_that_never_drew():
    problems = render.check(manifest([snip("s1")]), {"s1", "s2"})
    assert problems == ["V4 s2: declared in the template but not measured"]


def test_v4_ignores_extra_measured_snippets():
    """Rendering more than declared is not an error; missing one is."""
    assert check_ok(render.check(manifest([snip("s1"), snip("s2")]), {"s1"}))


# --- V6: the answer key is not in a render artefact ------------------------

@pytest.mark.parametrize("field", ["planted_id", "distractor", "text_clean"])
def test_v6_catches_a_leaked_answer_key_field(field):
    leaked = snip()
    leaked[field] = "whatever"
    problems = render.check(manifest([leaked]), {"s1"})
    assert any(p.startswith("V6") for p in problems)


def test_v6_catches_it_nested_anywhere():
    leaked = snip()
    leaked["lines"][0]["planted_id"] = "p3"
    assert any(p.startswith("V6") for p in render.check(manifest([leaked]), {"s1"}))


def test_clean_manifest_passes_everything():
    assert check_ok(render.check(manifest([snip("s1"), snip("s2")]), {"s1", "s2"}))


def check_ok(problems):
    assert problems == [], problems
    return True


# --- collisions: nothing is printed on top of anything else ----------------
#
# Blocks are pinned at the source document's coordinates and re-typeset, so a
# block that comes out taller than the rectangle it was given lands on the one
# below. This is the check for it, and it is the reason it exists: the first
# themed render put eleven blocks on top of each other across 49 pages, and
# every one of those pages looked plausible on its own.

def laid_out(*boxes):
    return {"exhibit": "C-9", "page": 2, "regions": [],
            "snippets": [snip(f"s{i}", bbox=b) for i, b in enumerate(boxes)]}


def test_neighbours_that_do_not_touch_are_fine():
    assert check_ok(render.check_layout(laid_out((0, 0, 500, 100),
                                                 (0, 110, 500, 200))))


def test_a_descender_brushing_the_next_line_is_fine():
    """Boxes touch constantly; only real coverage is a defect."""
    assert check_ok(render.check_layout(laid_out((0, 0, 500, 100),
                                                 (0, 96, 500, 200))))


def test_a_block_printed_over_the_next_one_is_caught():
    problems = render.check_layout(laid_out((0, 0, 500, 200), (0, 100, 500, 300)))
    assert len(problems) == 1
    assert "printed on top of" in problems[0]


def test_a_swallowed_block_is_caught():
    """The 100%-overlap case: one block entirely inside another."""
    problems = render.check_layout(laid_out((0, 0, 500, 400), (100, 100, 300, 200)))
    assert "100%" in problems[0]


def test_text_landing_on_a_photograph_is_caught():
    page = laid_out((0, 0, 500, 300))
    page["regions"] = [{"kind": "image", "bbox_norm": [0, 150, 500, 600]}]
    problems = render.check_layout(page)
    assert len(problems) == 1 and "[image]" in problems[0]


def test_the_page_is_named_in_the_message():
    problems = render.check_layout(laid_out((0, 0, 500, 200), (0, 100, 500, 300)))
    assert "C-9 p2" in problems[0]


def test_a_page_with_no_regions_key_still_checks():
    """Manifests written before regions existed must not crash the audit."""
    page = laid_out((0, 0, 500, 200), (0, 100, 500, 300))
    del page["regions"]
    assert len(render.check_layout(page)) == 1


# --- V1: the page is asked where its own text is ---------------------------
#
# The only check here that is not reading its own numbers back. Everything else
# traces the same coordinates through the same matrix, so none of it can notice
# the coordinates being wrong; measured directly, an ink-coverage test cannot
# even tell a correctly rotated box from one the homography never touched.
#
# These use a painted image built by hand, so what the check does is visible
# without a browser.

np = pytest.importorskip("numpy", reason="V1 verification is image arithmetic")


def painted(*blobs, size=(200, 400)):
    """A white page with a solid rectangle of each given colour."""
    img = np.full((size[0], size[1], 3), 250, np.uint8)
    for rgb, (x1, y1, x2, y2) in blobs:
        r, g, b = (int(v) for v in rgb.split(","))
        img[y1:y2, x1:x2] = (b, g, r)          # the array is BGR
    return img


def marked_manifest(snippets):
    h, w = 200, 400
    return {
        "exhibit": "C-4", "page": 2, "snippets": [
            {"snippet_id": sid,
             "bbox_norm": [x1 / w * 1000, y1 / h * 1000,
                           x2 / w * 1000, y2 / h * 1000],
             "lines": []}
            for sid, (x1, y1, x2, y2) in snippets
        ],
    }


RED, GREEN = render.MARK_COLOURS[0], render.MARK_COLOURS[1]


def test_v1_passes_when_the_paint_is_where_the_manifest_says():
    box = (40, 60, 300, 90)
    problems = render.check_marks(
        marked_manifest([("s1", box)]), painted((RED, box)),
        [{"snippet_id": "s1", "rgb": RED}])
    assert check_ok(problems)


def test_v1_records_the_drift_it_measured():
    box = (40, 60, 300, 90)
    manifest = marked_manifest([("s1", box)])
    render.check_marks(manifest, painted((RED, box)),
                       [{"snippet_id": "s1", "rgb": RED}])
    assert manifest["v1_max_drift_px"] <= 1


def test_v1_catches_a_box_off_by_a_line():
    manifest = marked_manifest([("s1", (40, 60, 300, 90))])
    image = painted((RED, (40, 100, 300, 130)))       # the text is 40px lower
    problems = render.check_marks(manifest, image,
                                  [{"snippet_id": "s1", "rgb": RED}])
    assert len(problems) == 1 and "40px out" in problems[0]


def test_v1_catches_a_box_that_is_the_wrong_width():
    manifest = marked_manifest([("s1", (40, 60, 300, 90))])
    problems = render.check_marks(manifest, painted((RED, (40, 60, 200, 90))),
                                  [{"snippet_id": "s1", "rgb": RED}])
    assert len(problems) == 1


def test_v1_catches_a_snippet_that_was_never_painted():
    """A snippet the render never drew: the strongest form of missing."""
    manifest = marked_manifest([("s1", (40, 60, 300, 90))])
    problems = render.check_marks(manifest, painted((GREEN, (40, 60, 300, 90))),
                                  [{"snippet_id": "s1", "rgb": RED}])
    assert len(problems) == 1 and "no such pixels" in problems[0]


def test_v1_tolerates_antialiasing_at_the_edges():
    """Chroma subsampling smears a pixel or two; that is not a defect."""
    manifest = marked_manifest([("s1", (40, 60, 300, 90))])
    problems = render.check_marks(manifest, painted((RED, (42, 61, 298, 92))),
                                  [{"snippet_id": "s1", "rgb": RED}])
    assert check_ok(problems)


def test_v1_compares_shared_colours_as_a_group():
    """More snippets than colours means two share one; the check then compares
    everything wearing that colour against every pixel of it."""
    a, b = (20, 20, 120, 50), (20, 120, 120, 150)
    manifest = marked_manifest([("s1", a), ("s2", b)])
    problems = render.check_marks(
        manifest, painted((RED, a), (RED, b)),
        [{"snippet_id": "s1", "rgb": RED}, {"snippet_id": "s2", "rgb": RED}])
    assert check_ok(problems)


def test_v1_names_the_page_and_the_snippet():
    manifest = marked_manifest([("C-4_p2_p2_b7", (40, 60, 300, 90))])
    problems = render.check_marks(manifest, painted((RED, (40, 120, 300, 150))),
                                  [{"snippet_id": "C-4_p2_p2_b7", "rgb": RED}])
    assert "C-4 p2" in problems[0] and "C-4_p2_p2_b7" in problems[0]


# --- the V1 tolerance is a fraction of a line, not a fixed distance --------
#
# The error worth catching is a box on the wrong line, so the allowance has to
# scale with the line: a page set in 11px type and one set in 40px display type
# do not deserve the same slack, and a fixed pixel budget is either too tight
# for the second or useless on the first.

def with_lines(sid, box, line_h):
    h, w = 200, 400
    x1, y1, x2, y2 = box
    return {"snippet_id": sid,
            "bbox_norm": [x1 / w * 1000, y1 / h * 1000, x2 / w * 1000, y2 / h * 1000],
            "lines": [{"line": 0, "quad_norm": [[0, 0], [10, 0],
                                                [10, line_h / h * 1000],
                                                [0, line_h / h * 1000]]}]}


def page_of(snippet):
    return {"exhibit": "C-4", "page": 2, "snippets": [snippet]}


def test_small_type_gets_a_tight_tolerance():
    """12px lines: a 6px slip is most of a line and must not pass."""
    manifest = page_of(with_lines("s1", (40, 60, 300, 72), line_h=12))
    problems = render.check_marks(manifest, painted((RED, (40, 68, 300, 80))),
                                  [{"snippet_id": "s1", "rgb": RED}])
    assert manifest["v1_tolerance_px"] == 6
    assert len(problems) == 1


def test_display_type_gets_a_wider_one():
    """60px lines: the same 8px slip is a fifth of a line and is antialiasing."""
    manifest = page_of(with_lines("s1", (40, 40, 300, 100), line_h=60))
    problems = render.check_marks(manifest, painted((RED, (40, 48, 300, 108))),
                                  [{"snippet_id": "s1", "rgb": RED}])
    assert manifest["v1_tolerance_px"] == 20
    assert check_ok(problems)


def test_display_type_still_catches_a_whole_line():
    manifest = page_of(with_lines("s1", (40, 40, 300, 100), line_h=60))
    problems = render.check_marks(manifest, painted((RED, (40, 128, 300, 188))),
                                  [{"snippet_id": "s1", "rgb": RED}])
    assert len(problems) == 1 and "tolerance of 20px" in problems[0]


def test_a_page_with_no_line_boxes_falls_back():
    """Nothing to scale against; the floor applies rather than a crash."""
    manifest = page_of({"snippet_id": "s1", "bbox_norm": [100, 300, 750, 450],
                        "lines": []})
    render.check_marks(manifest, painted((RED, (40, 60, 300, 90))),
                       [{"snippet_id": "s1", "rgb": RED}])
    assert manifest["v1_tolerance_px"] == 10
