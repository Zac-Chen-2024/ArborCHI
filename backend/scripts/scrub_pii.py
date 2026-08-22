"""Replace the things that identify a person and cannot be listed.

A substitution table is a list of what someone noticed. That is enough for names
-- there are a few hundred and they recur, so reading the corpus finds them --
and it is not enough for numbers. The whole point of a national identity number
is that it is unique, so it is never in a table you already have; the same goes
for a contract number, a direct telephone line, a personal mailbox. The filing
holds one identity number, thirteen e-mail addresses, twenty telephone numbers
and a dozen reference numbers, and every one of them is a number nobody would
think to write down in advance.

So these are matched by shape and replaced by shape. Nothing has to be known
about a number for it to be caught; it only has to look like what it is.

Two properties the replacements need, and one they must not have.

**Consistent.** `liudehuan@vip.sina.com` appears in six exhibits. If each got
its own stand-in the replica would read as six different people, and an exhibit
that says "write to the address above" would stop making sense. The stand-in is
derived from the original, so the same input always gives the same output
without any state being carried between runs or between exhibits.

**Well-formed.** An identity number whose checksum is wrong, a telephone number
in a range that does not exist, an ISBN that fails its own check digit: these
read as fake to anyone who looks, and looking at exhibits is what the study
asks people to do. The replacements are built to pass the checks their formats
define.

**Not reversible.** The mapping is recorded so a person can audit the replica
against the original, but the derivation is a hash: knowing a replacement and
this file does not give back the original.
"""
from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Tuple

# Ordered. An e-mail address contains digits that would otherwise be read as a
# telephone number, and a URL contains a host that would be read as an address,
# so the specific shapes are matched before the general ones.
RULES: List[Tuple[str, re.Pattern]] = [
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("url", re.compile(r"\bhttps?://[^\s)>\"']+|\bwww\.[\w-]+(?:\.[\w-]+)+\b", re.I)),
    ("id18", re.compile(r"\b\d{17}[\dXx]\b")),
    ("id15", re.compile(r"\b\d{15}\b")),
    ("isbn", re.compile(r"\bISBN[\s:]*[\d\s-]{10,20}[\dXx]\b", re.I)),
    # A mainland mobile number: eleven digits opening 13-19. Matched before the
    # landline rule, which would otherwise take eight of its digits and leave
    # three of the original's standing -- a partial replacement being the one
    # outcome worse than none, because it looks handled.
    ("mobile", re.compile(r"\b(?:\+?86[-\s]?)?1[3-9]\d{9}\b")),
    ("phone", re.compile(r"\b(?:\+?86[-\s]?)?(?:0\d{2,3}[-\s]?)?\d{7,8}\b")),
]

# Deliberately not in the rules above: a bare four-digit year, a page number, a
# folio, a percentage. Replacing those would change what the documents say
# without protecting anybody.

_DIGITS = "0123456789"


def _stream(seed: str) -> str:
    """A long run of digits derived from the original. Deterministic across
    processes -- `hash()` is not, and a stand-in that changed between runs would
    make two builds of the same corpus disagree."""
    out = ""
    n = 0
    while len(out) < 64:
        h = hashlib.sha256(f"{seed}:{n}".encode()).hexdigest()
        out += "".join(str(int(c, 16) % 10) for c in h)
        n += 1
    return out


def _id18(seed: str) -> str:
    """An 18-digit identity number that passes its own checksum.

    The last digit of a mainland identity number is a check digit over the
    other seventeen. A stand-in that fails it is recognisably not a number, and
    the exhibits in this filing are things people are asked to read closely.

    The region and the date of birth are drawn from the hash too, so nothing of
    the original's is kept -- not the province, not the year.
    """
    d = _stream(seed)
    region = f"{int(d[0:2]) % 60 + 11:02d}{int(d[2:4]) % 90 + 10:02d}{int(d[4:6]) % 90 + 10:02d}"
    year = 1960 + int(d[6:8]) % 40
    month = 1 + int(d[8:10]) % 12
    day = 1 + int(d[10:12]) % 28
    body = f"{region}{year}{month:02d}{day:02d}{int(d[12:15]) % 1000:03d}"
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check = "10X98765432"[sum(int(c) * w for c, w in zip(body, weights)) % 11]
    return body + check


def _isbn13(seed: str) -> str:
    d = _stream(seed)
    body = "978" + d[:9]
    check = (10 - sum(int(c) * (1 if i % 2 == 0 else 3)
                      for i, c in enumerate(body)) % 10) % 10
    return f"{body[:3]}-{body[3]}-{body[4:7]}-{body[7:12]}-{check}"


def _phone(seed: str, original: str) -> str:
    """Keeps the original's shape -- its length, and its separators -- because
    a document's layout is built around it, and puts the digits in a range set
    aside for fiction."""
    d = _stream(seed)
    digits = [c for c in original if c in _DIGITS]
    new = list(d[:len(digits)])
    # A trunk prefix is structure, not identity: "010-" says Beijing landline,
    # and a stand-in that turns it into "845-" is not a telephone number any
    # more. Keep a leading zero where the original had one.
    if digits and digits[0] == "0":
        new[0] = "0"
        if len(digits) > 2:
            new[1] = "1"
    elif len(digits) >= 8:
        new[0:2] = list("84")          # no exchange is allocated here
    out, i = [], 0
    for c in original:
        if c in _DIGITS:
            out.append(new[i])
            i += 1
        else:
            out.append(c)
    return "".join(out)


HOSTS = ["nanhu.edu.cn", "cdca.org.cn", "qingzhoudigital.com", "newswireasia.com",
         "nhup.cn", "riverbend.example", "yunhe-group.com", "lumenoptics.cn",
         "smartretail.org.cn", "jinling.edu.cn", "meridian.example"]
USERS = ["r.fang", "y.qiu", "office", "press", "contact", "editor", "admin",
         "secretariat", "info", "review"]


def _email(seed: str) -> str:
    d = _stream(seed)
    return f"{USERS[int(d[:3]) % len(USERS)]}@{HOSTS[int(d[3:6]) % len(HOSTS)]}"


def _url(seed: str, original: str) -> str:
    d = _stream(seed)
    host = HOSTS[int(d[:3]) % len(HOSTS)]
    if original.lower().startswith("www."):
        return f"www.{host}"
    scheme = original.split("://", 1)[0]
    tail = original.split("://", 1)[1] if "://" in original else ""
    path = tail.split("/", 1)[1] if "/" in tail else ""
    return f"{scheme}://{host}" + (f"/{path}" if path else "")


def replacement(kind: str, original: str) -> str:
    seed = f"{kind}:{original.lower()}"
    if kind == "email":
        return _email(seed)
    if kind == "url":
        return _url(seed, original)
    if kind == "id18":
        return _id18(seed)
    if kind == "id15":
        return _id18(seed)[:15]
    if kind == "mobile":
        # Rebuilt into the original's own shape, so a "+86 " that was there
        # stays there. Replacing the country code with digits gave numbers like
        # "+19682047711", which is not a telephone number anywhere.
        d = _stream(seed)
        body = "1" + "3579"[int(d[0]) % 4] + d[1:10]
        digits, out = iter(body), []
        head = original[:original.rfind("1", 0, len(original) - 10)]
        for ch in original[len(head):]:
            out.append(next(digits) if ch in _DIGITS else ch)
        return head + "".join(out)
    if kind == "isbn":
        prefix = original[:original.lower().index("isbn") + 4]
        return f"{prefix} {_isbn13(seed)}"
    return _phone(seed, original)


def scrub(text: str, seen: Dict[str, str] | None = None) -> str:
    """Replace every identifying number, address and link in one passage.

    `seen` collects what was replaced with what, so the run can record its own
    mapping and the audit can check it.
    """
    for kind, pattern in RULES:
        def swap(match, kind=kind):
            original = match.group(0)
            new = replacement(kind, original)
            if seen is not None:
                seen.setdefault(original, new)
            return new
        text = pattern.sub(swap, text)
    return text


# What must not survive, checked by shape rather than by list -- the same way
# it was replaced. An audit built from a list can only find what the list knew
# about, which for numbers is nothing.
RESIDUAL = [
    ("identity number", re.compile(r"\b\d{17}[\dXx]\b|\b\d{15}\b")),
    ("e-mail address", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    # Eleven digits opening 13-19. The landline rule below cannot see one --
    # it bounds a run at seven or eight digits -- so without this the audit was
    # blind to exactly the class the corpus has twelve of.
    ("mobile number", re.compile(r"\b1[3-9]\d{9}\b")),
    ("telephone number", re.compile(r"\b(?:\+?86[-\s]?)?(?:0\d{2,3}[-\s]?)?\d{7,8}\b")),
]


def residuals(text: str, allowed: set) -> List[Tuple[str, str]]:
    """Anything still shaped like a personal identifier and not one of ours.

    Membership is by containment, not equality. The telephone rule matches a
    subscriber number on its own as well as a whole "010-84258203", so a
    stand-in this module generated comes back as a fragment of itself; compared
    for equality it reads as a leak, and an audit that cries wolf is one people
    learn to wave through.
    """
    joined = " ".join(allowed)
    out = []
    for label, pattern in RESIDUAL:
        for hit in pattern.findall(text):
            if hit not in allowed and hit not in joined:
                out.append((label, hit))
    return out
