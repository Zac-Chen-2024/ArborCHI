"""Walk one session end to end on a given material bundle, over the HTTP API.

Not a replacement for the browser walk -- it cannot see hover, linkage or the
soft lock. What it does check is everything that changes when the *material*
changes: what the participant is served, what the letter says, which sentences
the probe draws, and whether the answer key stays on the server.

Run against a live server:  python scripts/walk_material.py --material judging_v1
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = "http://127.0.0.1:8000/api/study"
BODIES: list[str] = []


def call(method, path, token=None, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data, timeout=180) as r:
            out = json.loads(r.read().decode())
            code = r.status
    except urllib.error.HTTPError as e:
        try:
            out = json.loads(e.read().decode())
        except Exception:
            out = {}
        code = e.code
    BODIES.append(json.dumps(out, ensure_ascii=False))
    return code, out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--material", default="judging_v1")
    args = ap.parse_args()

    from app.core import study, study_snapshots, workspace

    mod = workspace.mint_token("walk", role="moderator")["token"]
    code, s = call("POST", "/sessions", mod, {
        "condition": "c", "participant_code": "REAL-WALK", "lang": "en",
        "track": "test", "material_id": args.material})
    if code != 200:
        raise SystemExit(f"could not create session: {code} {s}")
    tok, sid = s["join_token"], s["session_id"]
    print(f"session {sid} on {args.material}")

    call("POST", "/start", tok)

    # setup -> tutorial -> practice
    for _ in range(2):
        call("POST", "/advance", mod, {"session_id": sid})
    code, practice = call("GET", "/material", tok)
    print(f"\npractice phase serves: {practice['material_id']} / "
          f"{practice['criterion']} / {practice['case_label']}")

    for gate in ("linkage", "lightbox"):
        call("POST", "/checkpoint", tok, {"gate": gate})
    call("POST", "/advance", mod, {"session_id": sid})      # -> organization

    code, mat = call("GET", "/material", tok)
    print(f"\nmeasured phase serves: {mat['material_id']} / {mat['criterion']} "
          f"/ {mat['cfr']} / {mat['case_label']}")
    print(f"  {len(mat['exhibits'])} exhibits, {len(mat['snippets'])} evidence cards")
    print(f"  tree: {len(mat['tree']['arguments'])} arguments, "
          f"{sum(len(a['subs']) for a in mat['tree']['arguments'])} sub-arguments")
    leaked = [k for k in ("planted_id", "distractor", "source_says")
              if k in json.dumps(mat, ensure_ascii=False)]
    print(f"  answer key in /material: {leaked or 'none'}")

    # The participant accepts the tree as proposed and generates.
    states = {
        sub["id"]: {"title": sub["title"], "parent_id": arg["id"],
                    "snippet_ids": list(sub["snippet_ids"]), "state": "accepted"}
        for arg in mat["tree"]["arguments"] for sub in arg["subs"]
    }
    call("POST", "/advance", mod, {"session_id": sid})       # -> generation
    code, letter = call("POST", "/generate", tok, {"node_states": states})
    if code != 200:
        raise SystemExit(f"generate failed: {code} {letter}")
    sents = letter["sentences"]
    cited = [s for s in sents if s.get("exhibit_refs")]
    print(f"\nletter: {len(sents)} sentences, {len(cited)} cited, "
          f"{len(letter['text'])} chars")
    print(f"  sources: {sorted({s['source'] for s in sents})}")
    print(f"  planted_id in response: "
          f"{'planted_id' in json.dumps(letter, ensure_ascii=False)}")

    call("POST", "/advance", mod, {"session_id": sid})       # -> verification
    text = letter["text"]
    code, _ = call("POST", "/submit", tok, {
        "text": text, "final_text_hash": study_snapshots.sha256(text)})
    print(f"\nsubmit: {code}")

    call("POST", "/advance", mod, {"session_id": sid})       # -> confidence
    call("POST", "/confidence", tok, {"likert_1_7": 4, "est_problem_count": 3})
    call("POST", "/advance", mod, {"session_id": sid})       # -> probe

    code, probe = call("POST", "/probe/start", tok)
    items = probe["items"]
    ids = [i["sent_id"] for i in items]
    session = study.load_session(sid)
    stats = (session.get("probe") or {}).get("stats") or {}
    print(f"\nprobe: {len(items)} items, {len(set(ids))} distinct")
    print(f"  rule={stats.get('rule')} pool={stats.get('pool')} "
          f"planted_surviving={stats.get('planted_surviving')} "
          f"planted_in_items={stats.get('planted_in_items')} "
          f"ratio={stats.get('planted_ratio')}")
    print(f"  answer key in /probe/start: "
          f"{'planted_id' in json.dumps(probe, ensure_ascii=False)}")

    for i in range(len(items)):
        call("POST", "/probe/answer", tok, {
            "probe_index": i, "judgment": "supported" if i % 2 else "not_supported",
            "rt_ms": 1500 + i * 300, "source_opened": i % 3 == 0})

    call("POST", "/advance", mod, {"session_id": sid})       # -> done
    code, report = call("POST", f"/close/{sid}", mod, {})
    print()
    for c in report["checks"]:
        print(f"  {c['status'].upper():<5} {c['check']:<22} {c.get('detail', '')[:66]}")
    print(f"\nverdict: {report['verdict']}  failed={report['failed']}  "
          f"flagged={report['flagged']}")

    blob = "\n".join(BODIES)
    # text_clean is the pre-planting sentence -- not a hint about the answer,
    # the answer. It reached this list only after nearly shipping.
    hits = [k for k in ("planted_id", "text_clean", "source_says",
                        "cross_criterion", "distractor")
            if k in blob]
    print(f"\nscanned {len(BODIES)} response bodies for the answer key: "
          f"{hits or 'zero hits'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
