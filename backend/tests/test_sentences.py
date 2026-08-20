"""
Sentence segmentation, and the guarantee that the browser agrees with it.

The fixture file is the contract. The Python side is checked here; the
TypeScript side is checked against the same file by the study-app's own test
(scripts/check_sentences.mjs, run in CI), so a change to one implementation
that is not mirrored in the other fails the build rather than silently
producing two different segmentations of the same draft.
"""
import json
from pathlib import Path

import pytest

from app.core.sentences import count_citations, count_sentences, split_sentences

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "sentences.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize(
    "case", FIXTURES["cases"], ids=[c["why"][:40] for c in FIXTURES["cases"]]
)
def test_split_matches_the_shared_contract(case):
    assert split_sentences(case["text"]) == case["expect"]


def test_abbreviations_do_not_inflate_the_count():
    """The count feeds probe sampling (BE-13): 12-15 items are drawn from the
    final text, so an inflated count changes what the participant is asked."""
    text = "Dr. Li joined Northwind Inc. in 2019. He led four teams."
    assert count_sentences(text) == 2


def test_citation_counting_is_independent_of_segmentation():
    text = "A [Exhibit B1, p.2] and B [Exhibit C1, p.1; Exhibit C2, p.3] end."
    assert count_citations(text) == 2
    assert count_sentences(text) == 1
