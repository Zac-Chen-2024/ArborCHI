"""The substitution table, and the two ways it can go wrong.

One is obvious and has an audit: an original survives. The other has no audit
and cannot have one, because what it produces is not an original -- the table
rewriting the inside of an ordinary word. "NIO" turned every "opinion" into
"opiAurelian" and "Sage" turned every "passage" into "pasThornwood" across three
hundred pages, and every check in the pipeline reported the corpus clean,
correctly: no real name was left in it. Only reading the prose showed it.

So these tests are mostly about words that must NOT change.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fabricate_material.py"


def _load():
    spec = importlib.util.spec_from_file_location("fabricate_material", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fabricate_material"] = module
    spec.loader.exec_module(module)
    return module


fab = _load()


# --- ordinary words are not names ------------------------------------------

@pytest.mark.parametrize("text", [
    "in my opinion the union was junior",
    "this passage carried the message",
    "the Renminbi is the currency",
    "a companion of the minion",
    "the seasoning was sage and thyme",
    "an opinionated pioneer",
])
def test_prose_is_left_alone(text):
    assert fab.substitute(text) == text


# --- names are replaced, in every spelling the corpus uses -----------------

@pytest.mark.parametrize("original,gone", [
    ("Peking University", "Peking"),
    ("Professor Dehuan Liu", "Dehuan"),
    ("PENGUang University", "PENGU"),        # how an OCR read the logo
    ("iQIYI Science & Technology", "iQIYI"),
    ("NIO Inc.", "NIO"),
    ("Sage Publishing", "Sage"),
    ("Umeng+ product page", "Umeng"),
    ("visit pku.edu.cn", "pku"),
    ("Tsinghua University", "Tsinghua"),
    ("Harvard University", "Harvard"),
])
def test_the_original_does_not_survive(original, gone):
    assert gone.lower() not in fab.substitute(original).lower()


def test_a_longer_name_wins_over_a_shorter_one():
    """'Umeng+' and 'Umeng' are both entries. Applied shortest-first the plus
    would be left hanging off a replacement that no longer means anything."""
    assert fab.substitute("Umeng+") == "Datalink+"


def test_case_is_followed_not_imposed():
    """An all-capitals match gets an all-capitals replacement. The corpus writes
    the same organisation both ways and a case-sensitive pass replaced one."""
    assert fab.substitute("NIO Inc.").startswith("AURELIA")
    assert fab.substitute("Nio Inc.").startswith("Aurelia")


def test_a_bare_given_name_is_reached():
    """Five exhibits say 'Professor Dehuan' with no surname, 126 times. A table
    of full names alone leaves the given name standing in all of them."""
    assert "Dehuan" not in fab.substitute("Professor Dehuan spoke")


# --- the boundary rule itself ----------------------------------------------

def test_a_boundary_is_only_added_where_one_can_exist():
    """A trailing anchor after a non-word character never matches, so anchoring
    both ends unconditionally would silently disable exactly the entries added
    because they end in punctuation."""
    assert fab._bounded("Umeng+").endswith(r"\+")
    assert fab._bounded("Umeng").endswith(")")


def test_the_anchor_is_not_a_word_boundary():
    r"""Deliberately not \b.

    A word boundary is defined against Unicode word characters, and CJK are
    word characters, so there is no boundary between the last ideograph of a
    Chinese name and the first letter of its romanisation. The corpus is
    bilingual and writes them adjacently; four names survived on that alone.
    """
    joined = "广告协会CAAC"
    assert fab.substitute(joined) != joined


def test_the_pattern_can_actually_match():
    """A guard against the anchor arriving as something other than an anchor --
    a literal control character, say -- which makes every pattern unmatchable
    and every corpus look clean."""
    import re
    assert re.search(fab._bounded("Dehuan"), "Professor Dehuan Liu")


# --- the OCR runs words together, and a name can be either half ------------
#
# The corpus is bilingual and line-broken, and its text is full of seams: a
# name against the Chinese it translates, a name against the next word, a name
# against the previous one. Four real names survived on nothing but that.

@pytest.mark.parametrize("text,gone", [
    ("Abbreviation: CAACDate of foundation", "CAAC"),      # name, then a word
    ("About PR NewswirePR Newswire, a company", "PR News"),  # word, then a name
    ("Gang ChenShaoyang Lu", "Gang Chen"),                 # two names, no space
])
def test_a_run_together_name_is_still_reached(text, gone):
    assert gone.lower() not in fab.substitute(text).lower()


def test_the_seam_rule_does_not_reopen_the_middle_of_a_word():
    """The seam is allowed only where the name itself starts with a capital.
    Without that condition it is exactly the rule that made 'opinion' into
    'opiAurelian'."""
    assert fab.substitute("in my opinion, a companion") == "in my opinion, a companion"


def test_the_lookahead_is_scoped_against_ignorecase():
    """The patterns compile IGNORECASE, and under that flag [a-z] matches
    capitals too -- so an unscoped 'not followed by lower-case' rejected
    everything and was identical to the rule it replaced."""
    assert "(?-i:" in fab._bounded("CAAC")
