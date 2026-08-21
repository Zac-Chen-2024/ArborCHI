#!/usr/bin/env python
"""
Pre-push audit -- the failure classes that pass on a developer's Windows box
and only surface on a clean Linux checkout, plus the study's restraint red
lines. Runs in CI; run it locally before pushing.

    python scripts/audit.py

Why this file exists. The first two pushes went out green on my machine and
red in CI, twice, for reasons a test suite structurally cannot catch:

  * `.gitignore` had a bare `data/`, which matches a directory named `data` at
    ANY depth -- it silently swallowed study-app/src/data/fixtures.ts. Every
    local build worked because the file was on disk; CI could not find it.
  * Windows resolves imports case-insensitively, Linux does not.
  * `python -m pytest` puts the CWD on sys.path, bare `pytest` does not.

Each of those is invisible to `npm run build` and `pytest` when run from a
working tree. The check that matters is "does the REPOSITORY build", and this
script is the cheap approximation of it; `git clone` to a temp dir is the
expensive one (see README).

The red-line checks are here rather than in the test suite because they are
statements about source code, not about behaviour: "no component may branch on
whether a node is a distractor" cannot be asserted by calling a function.
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'study-app', 'src')

problems: list[str] = []


def note(kind: str, msg: str) -> None:
    problems.append(f'[{kind}] {msg}')


def read(rel: str) -> str:
    return io.open(os.path.join(ROOT, rel), encoding='utf-8').read()


def strip_comments(src: str) -> str:
    """Source with comments removed. A comment that states a rule ("there must
    be no distractor flag here") is the opposite of a violation, and flagging
    it would train people to ignore this audit."""
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    return re.sub(r'//[^\n]*', '', src)


def walk(root: str, exts: tuple[str, ...]):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ('node_modules', 'dist')]
        for fn in filenames:
            if fn.endswith(exts):
                yield os.path.join(dirpath, fn)


# ---------------------------------------------------------------------------
# 1. Case-exact relative imports
# ---------------------------------------------------------------------------

IMPORT_RE = re.compile(r"""(?:from|import)\s+['"](\.[^'"]*)['"]""")
EXTS = ['', '.ts', '.tsx', '.json', '.css',
        os.sep + 'index.ts', os.sep + 'index.tsx']


def path_is_case_exact(path: str) -> bool:
    """os.path.exists() is case-insensitive on Windows; walk each segment
    against the real directory listing to find out what Linux would see."""
    cur = ROOT
    for part in os.path.relpath(path, ROOT).split(os.sep):
        try:
            if part not in os.listdir(cur):
                return False
        except OSError:
            return False
        cur = os.path.join(cur, part)
    return True


for path in walk(APP, ('.ts', '.tsx')):
    rel = os.path.relpath(path, ROOT)
    for spec in IMPORT_RE.findall(io.open(path, encoding='utf-8').read()):
        base = os.path.normpath(os.path.join(os.path.dirname(path), spec))
        for ext in EXTS:
            cand = base + ext
            if os.path.exists(cand):
                if not path_is_case_exact(cand):
                    note('CASE', f'{rel}: import {spec!r} differs in case from '
                                 f'the file on disk -- fails on Linux')
                break
        else:
            note('MISSING-IMPORT', f'{rel}: import {spec!r} resolves to nothing')


# ---------------------------------------------------------------------------
# 2. Everything the build needs is actually in the repository
# ---------------------------------------------------------------------------

tracked = set(subprocess.run(
    ['git', 'ls-files'], capture_output=True, text=True, cwd=ROOT
).stdout.splitlines())

for path in walk(APP, ('.ts', '.tsx', '.css', '.json')):
    rel = os.path.relpath(path, ROOT).replace(os.sep, '/')
    if rel not in tracked:
        note('UNTRACKED', f'{rel} exists locally but git does not track it '
                          f'-- a clean checkout cannot build')

REQUIRED = [
    'study-app/package.json', 'study-app/package-lock.json',
    'study-app/tsconfig.json', 'study-app/vite.config.ts',
    'study-app/index.html', 'study-app/eslint.config.js',
    'study-app/tailwind.config.js', 'study-app/postcss.config.js',
    'backend/pyproject.toml', 'backend/requirements.txt',
    'backend/requirements-dev.txt', '.github/workflows/ci.yml',
    'backend/study_config.json',
    # The material bundle is data the tests and every session read. It went in
    # a directory called `study_materials`, deliberately not `data`, after
    # .gitignore's bare `data/` swallowed study-app/src/data/fixtures.ts.
    'backend/study_materials/case_v1/manifest.json',
    'backend/study_materials/case_v1/tree.frozen.json',
    'backend/study_materials/case_v1/snippets.json',
    'backend/study_materials/case_v1/planted.json',
]
for rel in REQUIRED:
    if rel not in tracked:
        note('UNTRACKED', f'{rel} is required by CI but not tracked')


# ---------------------------------------------------------------------------
# 2b. No credential may be tracked
# ---------------------------------------------------------------------------
#
# The key lives in backend/.env, which .gitignore excludes -- but "excluded"
# is a property of one line in one file, and a key pasted into a script, a
# test fixture, or a README example is tracked like anything else. A committed
# key is not undone by deleting it: it is in the history, and on a public repo
# it is compromised the moment it is pushed.
#
# Patterns are assembled from parts so this file does not trip its own scan.
SECRET_PATTERNS = [
    ("OpenAI key", re.compile("sk" + r"-[A-Za-z0-9_\-]{24,}")),
    ("Google key", re.compile("AIza" + r"[0-9A-Za-z_\-]{30,}")),
    ("GitHub token", re.compile("gh[pousr]" + r"_[A-Za-z0-9]{30,}")),
    ("Anthropic key", re.compile("sk-ant" + r"-[A-Za-z0-9_\-]{20,}")),
    ("AWS key id", re.compile("AKIA" + r"[0-9A-Z]{16}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

SECRET_SCAN_SKIP = ('.png', '.jpg', '.jpeg', '.pdf', '.ico', '.woff', '.woff2')

for rel in sorted(tracked):
    if rel.endswith(SECRET_SCAN_SKIP):
        continue
    path = os.path.join(ROOT, rel)
    try:
        with io.open(path, encoding='utf-8', errors='ignore') as fh:
            body = fh.read()
    except OSError:
        continue
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(body):
            note('SECRET', f'{rel} contains something shaped like a {label}. '
                           f'Credentials belong in backend/.env, which is not '
                           f'tracked. If this was pushed, rotate it -- deleting '
                           f'the line does not remove it from history.')


# ---------------------------------------------------------------------------
# 3. Red lines, checked against the source
# ---------------------------------------------------------------------------

# 红线 #4 -- the participant may see a clock ONLY from the server's
# remaining_ms, which the server sends only during the organisation phase.
if 'remaining_ms' not in read('study-app/src/lib/session.ts'):
    note('RED-4', 'session.ts no longer reads remaining_ms')
if 'remainingMs !== null' not in read('study-app/src/components/shared/TopBar.tsx'):
    note('RED-4', 'TopBar no longer guards the countdown on a non-null value; '
                  'an `else` branch here would put a clock in the verify phase')
if 'remainingMs={null}' not in read('study-app/src/conditions/b/ConditionB.tsx'):
    note('RED-4', 'condition B no longer passes a null clock')

study_py = read('backend/app/core/study.py')
m = re.search(r'def public_state.*?(?=\n\n\ndef |\Z)', study_py, re.S)
if not m:
    note('RED-4', 'public_state not found in core/study.py')
else:
    # Reading the deadline to compute a remaining time is fine. Writing any
    # other time-shaped key INTO the response is the leak.
    written = re.findall(r"""state\[(['"])([a-z_]+)\1\]\s*=""", m.group(0))
    leaky = [k for _, k in written
             if k != 'remaining_ms' and ('deadline' in k or k.endswith('_ms'))]
    if leaky:
        note('RED-4', f'public_state writes time-shaped keys: {leaky}')

# 红线 #5 / C-14 -- no answer-key-shaped concept anywhere the frontend touches.
# Answer-key-shaped concepts. `planted_id` joins the list: planted error
# sentences are the probe's ground truth, so the field lives in the server-side
# snapshot only. A frontend that knew which sentences were planted would be
# marking its own homework.
BANNED = ['distractor', 'ground_truth', 'groundtruth', 'isdistractor',
          'probe_answer', 'answer_key', 'answerkey', 'planted_id', 'plantedid']
for path in walk(APP, ('.ts', '.tsx')):
    src = strip_comments(io.open(path, encoding='utf-8').read()).lower()
    for word in BANNED:
        if word in src:
            note('RED-5', f'{os.path.relpath(path, ROOT)} references {word!r} '
                          f'in code -- the backend must never send this and the '
                          f'frontend must have nowhere to put it')

# C-11 -- the magnifier shows the located passage and nothing else. A
# candidate-box prop would make the interface do the judging.
lb = strip_comments(read('study-app/src/components/shared/Lightbox.tsx')).lower()
if 'candidate' in lb:
    note('C-11', 'Lightbox gained a candidate-box concept; neighbouring-match '
                 'hints are a deliberate omission, not an oversight')


# ---------------------------------------------------------------------------
# 4. i18n coverage (FS-03)
# ---------------------------------------------------------------------------

def flatten(obj, prefix=''):
    out = []
    for k, v in obj.items():
        out += flatten(v, prefix + k + '.') if isinstance(v, dict) else [prefix + k]
    return out


en = set(flatten(json.loads(read('study-app/src/i18n/en.json'))))
zh = set(flatten(json.loads(read('study-app/src/i18n/zh.json'))))
if en != zh:
    note('I18N', f'en/zh key mismatch -- only-en={sorted(en - zh)} '
                 f'only-zh={sorted(zh - en)}')

used: set[str] = set()
# (?<![A-Za-z0-9_]) so that get('token') is not mistaken for t('token').
T_CALL = re.compile(r"""(?<![A-Za-z0-9_])t\(\s*['"]([a-zA-Z0-9_.]+)['"]""")
for path in walk(APP, ('.ts', '.tsx')):
    used |= set(T_CALL.findall(io.open(path, encoding='utf-8').read()))
missing = sorted(k for k in used if k not in en)
if missing:
    note('I18N', f'keys used in components but absent from en.json: {missing}')


# ---------------------------------------------------------------------------

def main() -> int:
    print(f'i18n     : {len(en)} keys, {len(used)} referenced in components')
    print(f'tracked  : {len(tracked)} files')
    print()
    if problems:
        print(f'{len(problems)} problem(s):')
        for p in problems:
            print('  ' + p)
        return 1
    print('audit clean')
    return 0


if __name__ == '__main__':
    sys.exit(main())
