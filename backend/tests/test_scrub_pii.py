"""The shape-based scrubber, which is the part of the replica that has to be right.

A substitution table can be reviewed by reading it. This cannot: it is supposed
to catch numbers nobody wrote down, so the only way to know it works is to give
it numbers and check what comes back. The corpus it was built for holds one
national identity number, thirteen e-mail addresses and thirty-odd telephone
numbers, and getting any one of them wrong publishes it.
"""
import importlib.util
import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "scrub_pii.py"


def _load():
    spec = importlib.util.spec_from_file_location("scrub_pii", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pii = _load()

ID_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]


def id_checksum_ok(number: str) -> bool:
    total = sum(int(c) * w for c, w in zip(number[:17], ID_WEIGHTS))
    return "10X98765432"[total % 11] == number[17].upper()


# --- nothing identifying survives -----------------------------------------

@pytest.mark.parametrize("text", [
    "证件号:110108196603291919",
    "ID 11010819660329191X",
    "write to liudehuan@vip.sina.com",
    "Tel.: 010- 62753436",
    "mobile 13901234567",
    "call +86 13812345678",
    "Address: http://www.pup.cn",
    "see www.pku.edu.cn for details",
    "Standard Book number: ISBN 978- 7- 301- 10091- 2",
])
def test_the_original_is_gone(text):
    assert pii.scrub(text) != text
    numbers = re.findall(r"\d{7,}", text)
    for original in numbers:
        assert original not in pii.scrub(text)


def test_a_year_is_left_alone():
    """Replacing every number would change what a document says without
    protecting anyone. A date is not an identifier."""
    assert pii.scrub("published in 2006, page 143, 25% growth") == (
        "published in 2006, page 143, 25% growth")


# --- the same original always gives the same stand-in ----------------------

def test_one_address_is_one_person():
    """The petitioner's mailbox appears in six exhibits. Six different
    stand-ins would read as six different people, and an exhibit saying 'write
    to the address above' would stop making sense."""
    a = pii.scrub("contact liudehuan@vip.sina.com")
    b = pii.scrub("or liudehuan@vip.sina.com, either way")
    assert a.split()[-1] == b.split()[1].rstrip(",")


def test_it_does_not_depend_on_process_state():
    """Two builds of the same corpus must agree. `hash()` is randomised per
    process, which would make them differ."""
    assert pii.replacement("id18", "110108196603291919") == \
        pii.replacement("id18", "110108196603291919")


def test_different_originals_get_different_stand_ins():
    assert pii.replacement("email", "a@x.com") != pii.replacement("email", "b@x.com")


# --- the stand-ins are well-formed ----------------------------------------
#
# An identity number that fails its own checksum reads as fake to anyone who
# looks it over, and looking exhibits over closely is exactly what the study
# asks people to do.

def test_the_identity_number_passes_its_own_checksum():
    assert id_checksum_ok(pii.replacement("id18", "110108196603291919"))


def test_the_identity_number_keeps_nothing_of_the_original():
    original = "110108196603291919"
    new = pii.replacement("id18", original)
    assert len(new) == 18
    assert new[:6] != original[:6]          # not the same region
    assert new[6:10] != original[6:10]      # not the same year of birth


def test_the_isbn_passes_its_check_digit():
    out = pii.replacement("isbn", "ISBN 978- 7- 301- 10091- 2")
    digits = [int(c) for c in out if c.isdigit()]
    assert len(digits) == 13
    assert sum(d * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits)) % 10 == 0


def test_a_landline_keeps_its_trunk_prefix():
    """'010-' says Beijing landline. A stand-in that turns it into '845-' is
    not a telephone number any more."""
    assert pii.scrub("Tel.: 010- 62753436").startswith("Tel.: 01")


def test_a_mobile_keeps_its_country_code():
    out = pii.scrub("call +86 13812345678")
    assert out.startswith("call +86 1")
    assert "13812345678" not in out


def test_a_mobile_is_still_a_mobile():
    out = pii.scrub("mobile 13901234567").split()[-1]
    assert re.fullmatch(r"1[3-9]\d{9}", out)


def test_a_url_keeps_its_scheme_and_loses_its_path():
    """The path goes with the host. A slug is not decoration: one in this
    corpus names two companies and a sum."""
    out = pii.scrub("see https://example.org/faculty/profile for more")
    assert out.startswith("see https://") and out.endswith(" for more")
    assert "example.org" not in out and "faculty" not in out


# --- the audit can see what the substitution missed ------------------------

def test_residuals_finds_an_untouched_number():
    assert pii.residuals("id 110108196603291919", set())


def test_residuals_accepts_our_own_stand_ins():
    seen = {}
    text = pii.scrub("Tel.: 010- 62753436 and 110108196603291919", seen)
    assert pii.residuals(text, set(seen.values())) == []


def test_residuals_accepts_a_fragment_of_our_own():
    """The telephone rule matches a subscriber number on its own as well as a
    whole '010-84258203'. Compared for equality a stand-in reads as a leak, and
    an audit that cries wolf is one people learn to wave through."""
    seen = {}
    text = pii.scrub("Tel.: 010- 62753436", seen)
    assert pii.residuals(text, set(seen.values())) == []


def test_a_partial_replacement_would_be_caught():
    """The failure mode worth guarding: eight digits of an eleven-digit mobile
    replaced, three of the original's left standing. It looks handled."""
    assert pii.residuals("139" + "01234567", set())


# --- a URL path that lost its host -----------------------------------------
#
# The OCR breaks a long link across a line, so the slug is left loose in the
# text. It is still a sentence: one in this corpus reads
# "baidus-iqiyi-video-service-raises-1-53-billion/", which names two companies
# and a sum -- in lower case, inside hyphens, past every name rule there is.

def test_a_loose_slug_is_replaced():
    out = pii.scrub("see baidus-iqiyi-video-service-raises-1-53-billion/ for more")
    assert "iqiyi" not in out and "baidu" not in out


def test_ordinary_hyphenation_is_left_alone():
    for text in ("a state-of-the-art solution", "the well-known follow-up plan"):
        assert pii.scrub(text) == text


def test_the_slug_rule_does_not_eat_the_isbn_rule_s_output():
    """Rules run in sequence over the same text, so a later one sees what an
    earlier one wrote. The replacement ISBN is digits and hyphens, which is
    slug-shaped; requiring a letter keeps them apart."""
    out = pii.scrub("Standard Book number: ISBN 978- 7- 301- 10091- 2")
    assert "ISBN" in out
    digits = [c for c in out.split("ISBN")[1] if c.isdigit()]
    assert len(digits) == 13


def test_a_url_path_does_not_survive_its_host():
    out = pii.scrub("https://techcrunch.com/2017/02/21/baidus-iqiyi-video/")
    assert "techcrunch" not in out and "iqiyi" not in out
