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
