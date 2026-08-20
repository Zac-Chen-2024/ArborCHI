#!/usr/bin/env python
"""
Dry run -- the automatable half of docs/假实验脚本_v1_draft.md.

    cd backend
    ./.venv/Scripts/python.exe scripts/dry_run.py [--base http://127.0.0.1:8000]

Walks one condition-C session end to end against a RUNNING server and checks
each step against its acceptance id. Prints a green/red list and exits non-zero
if anything fails.

Why this exists as well as the test suite. The tests exercise the code; this
exercises the deployment -- the actual process, the actual config file, the
actual material bundle on disk, over HTTP. Those are the things that differ
between "it works" and "it works on the machine the study runs on", and they
are exactly what a dry run before a pilot is for.

It runs on the **test track**, so everything it writes lands in
data/study_test/ and can never be mistaken for a session (BE-19/BE-20).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import study, study_snapshots  # noqa: E402
from app.core.workspace import mint_token  # noqa: E402

RESULTS: list[tuple[str, str, bool, str]] = []


def check(step: str, acceptance: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((step, acceptance, bool(ok), detail))
    return bool(ok)


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/") + "/api/study"

    def __call__(self, method: str, path: str, token: Optional[str] = None,
                 body: Any = None) -> Tuple[int, Any]:
        req = urllib.request.Request(self.base + path, method=method)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, data, timeout=30) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode())
            except Exception:
                return e.code, {}
        except urllib.error.URLError as e:
            raise SystemExit(f"cannot reach {self.base}: {e}") from e


def events_of(session_id: str) -> list[Dict[str, Any]]:
    session = study.load_session(session_id)
    path = study.session_dir(
        session["workspace_id"], session_id, session["track"]) / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


LEAK_WORDS = ("planted", "distractor", "ground_truth", "answer_key")


def run(base: str) -> int:
    api = Api(base)
    seen_bodies: list[str] = []

    def call(method, path, token=None, body=None):
        code, out = api(method, path, token, body)
        seen_bodies.append(json.dumps(out, ensure_ascii=False))
        return code, out

    mod = mint_token("dry-run", role="moderator")["token"]

    # --- A1 -----------------------------------------------------------------
    code, s = call("POST", "/sessions", mod, {
        "condition": "c", "participant_code": "DRY-RUN", "lang": "en", "track": "test"})
    check("A1", "BE-01/BE-19", code == 200 and s.get("track") == "test",
          f"status {code}")
    tok, sid = s["join_token"], s["session_id"]

    # --- A2, A3 -------------------------------------------------------------
    code, _ = call("POST", "/sessions", tok, {
        "condition": "c", "participant_code": "X", "lang": "en"})
    check("A2", "BE-02", code == 404, f"participant -> moderator route: {code}")
    code, _ = call("GET", "/state")
    check("A3", "BE-02", code == 401, f"no token: {code}")

    # --- A4 -----------------------------------------------------------------
    call("POST", "/start", tok)
    call("POST", "/start", tok)
    starts = [e for e in events_of(sid) if e["event"] == "session_start"]
    check("A4", "FS-12", len(starts) == 1, f"{len(starts)} session_start events")

    # --- A5 -----------------------------------------------------------------
    for _ in range(2):
        call("POST", "/advance", mod, {"session_id": sid})
    code, st = call("GET", "/state", tok)
    code, practice_mat = call("GET", "/material", tok)
    check("A5", "BE-18",
          st["phase"] == "practice" and practice_mat["practice"] is True
          and practice_mat["tree"]["criterion"] != "Leading or Critical Role",
          f"{practice_mat.get('material_id')} / {practice_mat['tree']['criterion']}")

    # --- A6, A7, A8 ---------------------------------------------------------
    code, blocked = call("POST", "/advance", mod, {"session_id": sid})
    check("A6", "FS-06", code == 409, f"{code} {blocked.get('detail', '')}")

    call("POST", "/checkpoint", tok, {"gate": "lightbox"})
    code, _ = call("POST", "/advance", mod, {"session_id": sid})
    check("A7", "FS-06", code == 409, f"half-cleared advance: {code}")

    call("POST", "/checkpoint", tok, {"gate": "linkage"})
    # --- A9: practice events carry practice:true ---------------------------
    call("POST", "/log/batch", tok, {"events": [
        {"seq": 0, "ts_mono": 100, "event": "heartbeat", "payload": {}}]})
    practice_events = [e for e in events_of(sid)
                       if e["source"] == "client" and e["event"] == "heartbeat"]
    check("A9", "BE-18", all(e["practice"] for e in practice_events),
          f"{len(practice_events)} practice-phase client events")

    code, adv = call("POST", "/advance", mod, {"session_id": sid})
    code2, real_mat = call("GET", "/material", tok)
    check("A8", "FS-06",
          code == 200 and real_mat["practice"] is False
          and real_mat["tree"]["criterion"] == "Leading or Critical Role",
          f"advance {code}; material now {real_mat.get('material_id')}")

    # --- A10 ----------------------------------------------------------------
    code, st = call("GET", "/state", tok)
    check("A10", "BE-04/FS-07",
          st["phase"] == "organization" and "remaining_ms" in st
          and st["can_submit"] is False,
          f"remaining_ms={st.get('remaining_ms')}")

    # --- A11 ----------------------------------------------------------------
    code, ack = call("POST", "/log/batch", tok, {"events": [
        {"seq": 1, "ts_mono": 1000, "event": "tree_op", "payload": {
            "op": "move", "node_id": "s4", "node_title": "Decision and resource authority",
            "before": {"node_id": "s4", "parent_id": "a2", "title": "Decision and resource authority",
                       "parent_title": "The petitioner performs a leading role within it",
                       "snippet_ids": ["c5"], "state": "proposed", "index_in_parent": 1},
            "after": {"node_id": "s4", "parent_id": "a1", "title": "Decision and resource authority",
                      "parent_title": "The organisation has a distinguished reputation",
                      "snippet_ids": ["c5"], "state": "edited", "index_in_parent": 2}}},
    ]})
    op = next((e for e in events_of(sid) if e["event"] == "tree_op"), None)
    check("A11", "BE-06",
          ack.get("accepted") == 1 and op is not None
          and "before" in op["payload"] and "after" in op["payload"],
          f"acked_seq={ack.get('acked_seq')}")

    # --- A12, A13, A14 ------------------------------------------------------
    # On a SIDE session, not the one being walked. A12 deliberately loses two
    # thirds of a log, which is exactly what PR-4 says invalidates a session --
    # injecting that into the session A30 then closes out as clean would be
    # testing two contradictory things at once. A real dry run does not damage
    # the session it is about to certify either.
    _, side = call("POST", "/sessions", mod, {
        "condition": "c", "participant_code": "DRY-LOGS", "lang": "en", "track": "test"})
    side_tok = side["join_token"]
    call("POST", "/start", side_tok)

    call("POST", "/log/batch", side_tok, {"events": [
        {"seq": 0, "ts_mono": 100, "event": "heartbeat", "payload": {}},
        {"seq": 1, "ts_mono": 200, "event": "heartbeat", "payload": {}}]})
    code, gapped = call("POST", "/log/batch", side_tok, {"events": [
        {"seq": 8, "ts_mono": 2000, "event": "heartbeat", "payload": {}}]})
    check("A12", "BE-06", code == 200 and gapped.get("gaps") == [[2, 7]],
          f"gap registered, not refused: {gapped.get('gaps')}")

    code, mixed = call("POST", "/log/batch", side_tok, {"events": [
        {"seq": 9, "ts_mono": 2100, "event": "heartbeat", "payload": {}},
        {"seq": 10, "ts_mono": 2200, "event": "not_a_real_event", "payload": {}},
    ]})
    check("A13", "BE-06", mixed.get("accepted") == 1 and mixed.get("rejected") == 1,
          f"{mixed.get('accepted')} accepted / {mixed.get('rejected')} rejected")
    code, forged = call("POST", "/log/batch", side_tok, {"events": [
        {"seq": 11, "ts_mono": 2300, "event": "phase_enter", "payload": {"phase": "done"}}]})
    check("A14", "BE-06", forged.get("rejected") == 1, "client forging a server event")

    # And the damaged side session must be judged invalid -- the other half of
    # PR-4, checked here rather than left to inference.
    _, side_report = call("POST", f"/close/{side['session_id']}", mod)
    seq_row = next((c for c in side_report.get("checks", [])
                    if c["check"] == "seq_continuity"), {})
    check("A12b", "PR-4",
          seq_row.get("status") == "fail" and side_report.get("verdict") == "invalid",
          f"67% log loss -> {side_report.get('verdict')}")

    # --- A15 ----------------------------------------------------------------
    call("POST", "/advance", mod, {"session_id": sid})      # -> generation
    states = {
        sub["id"]: {"title": sub["title"], "parent_id": arg["id"],
                    "snippet_ids": sub["snippet_ids"], "state": "accepted"}
        for arg in real_mat["tree"]["arguments"] for sub in arg["subs"]
    }
    code, gen = call("POST", "/generate", tok, {"node_states": states})
    session = study.load_session(sid)
    snap = study_snapshots.read_snapshot(session, "initial")
    check("A15", "BE-08/红线#1",
          code == 200 and snap is not None
          and snap["text"] == gen["text"]
          and snap["sha256"] == study_snapshots.sha256(gen["text"])
          and all("source" in x for x in gen["sentences"]),
          f"{len(gen.get('sentences', []))} sentences, snapshot hash matches")

    # --- A16 ----------------------------------------------------------------
    changed = dict(states)
    first_node = next(iter(changed))
    changed[first_node] = {**changed[first_node], "title": "A different heading entirely"}
    code, _ = call("POST", "/generate", tok, {"node_states": changed})
    check("A16", "BE-08", code == 503,
          f"changed node without a generator -> {code} (must not silently reuse frozen text)")

    # --- A17, A18 -----------------------------------------------------------
    call("POST", "/advance", mod, {"session_id": sid})      # -> verification
    code, st = call("GET", "/state", tok)
    leaky = [k for k in st if "remain" in k or "deadline" in k or k.endswith("_ms")]
    check("A17", "BE-04/红线#4",
          st["phase"] == "verification" and leaky == [] and st["can_submit"] is True,
          f"keys={list(st)}")

    far_future = study.now_ms() + 10 * 60 * 60 * 1000
    check("A18", "PR-6", study.softlock_due(study.load_session(sid), far_future) is False,
          "verification never soft-locks, even hours over budget")

    # --- A19 ----------------------------------------------------------------
    code, _ = call("POST", "/probe/start", tok)
    check("A19", "红线#6", code == 409, f"probe before submit: {code}")

    # --- A20, A21 -----------------------------------------------------------
    text = gen["text"]
    code, _ = call("POST", "/submit", tok, {"text": text, "final_text_hash": "0" * 64})
    after_bad = study.load_session(sid)
    check("A20", "BE-11",
          code == 400 and after_bad["submitted"] is False
          and study_snapshots.read_snapshot(after_bad, "final") is None,
          f"bad hash -> {code}, nothing written")

    code, _ = call("POST", "/submit", tok, {
        "text": text, "final_text_hash": hashlib.sha256(text.encode()).hexdigest()})
    declared = [e for e in events_of(sid) if e["event"] == "submit_declared"]
    final = study_snapshots.read_snapshot(study.load_session(sid), "final")
    check("A21", "BE-11",
          code == 200 and len(declared) == 1
          and "phase_elapsed_ms" in declared[0]["payload"] and final is not None,
          f"submit {code}; elapsed recorded")

    # --- A22 ----------------------------------------------------------------
    code, _ = call("POST", "/log/batch", tok, {"events": [
        {"seq": 2, "ts_mono": 3000, "event": "text_edit", "payload": {}}]})
    check("A22", "BE-11", code == 409, f"write after submit: {code}")

    # --- A23, A24 -----------------------------------------------------------
    code, _ = call("POST", "/probe/start", tok)
    check("A23", "红线#6", code == 409, f"probe before confidence: {code}")
    code, _ = call("POST", "/confidence", tok, {"likert_1_7": 5, "est_problem_count": 2})
    check("A24", "BE-12", code == 200, f"confidence {code}")

    # --- A25, A26, A27 ------------------------------------------------------
    code, pr = call("POST", "/probe/start", tok)
    items = pr.get("items", [])
    # The placeholder bundle only yields ten cited sentences, so PR-2's
    # underflow rule fires and the whole pool is taken. With the real material
    # this should land in the 12-15 band; if it still says "underflow" then,
    # the letter is shorter than the protocol assumes and that is a finding.
    check("A25", "BE-13/PR-2",
          code == 200 and items and all(i["citations"] for i in items)
          and "planted" not in json.dumps(pr).lower(),
          f"{len(items)} items, all cited, no answer key"
          + ("  [placeholder pool < 12: underflow rule]" if len(items) < 12 else ""))

    code, again = call("POST", "/probe/start", tok)
    check("A26", "BE-13",
          [i["sent_id"] for i in again.get("items", [])] == [i["sent_id"] for i in items],
          "re-opening draws the same items")

    for i, item in enumerate(items[:3]):
        call("POST", "/probe/answer", tok, {
            "probe_index": item["probe_index"],
            "judgment": ["supported", "not_supported", "unsure"][i % 3],
            "rt_ms": 3000 + i * 400, "source_opened": i % 2 == 0})
    answered = [e for e in events_of(sid) if e["event"] == "probe_item"]
    check("A27", "FS-09",
          len(answered) == min(3, len(items))
          and all("planted_id" in e["payload"] for e in answered)
          and all("rt_ms" in e["payload"] for e in answered),
          f"{len(answered)} answers, ground truth in the log only")

    # --- A28 ----------------------------------------------------------------
    blob = " ".join(seen_bodies).lower()
    hits = [w for w in LEAK_WORDS if w in blob]
    check("A28", "BE-07/红线#5", hits == [],
          f"scanned {len(seen_bodies)} response bodies; leaks={hits}")

    # --- A29 ----------------------------------------------------------------
    evs = events_of(sid)
    triples = {(e.get("config_hash"), e.get("material_manifest_hash"),
                e.get("tree_variant_id")) for e in evs}
    check("A29", "schema v3",
          len(triples) == 1 and all(triples.pop()),
          f"{len(evs)} events share one provenance triple")

    # --- A30 ----------------------------------------------------------------
    code, report = call("POST", f"/close/{sid}", mod)
    reds = [c for c in report.get("checks", []) if c["status"] == "fail"]
    ambers = [c["check"] for c in report.get("checks", []) if c["status"] == "flag"]
    check("A30", "BE-15/MOD-06",
          code == 200 and not reds,
          f"verdict={report.get('verdict')}; flagged={ambers}"
          + (f"; FAILED={[c['check'] + ': ' + c['detail'] for c in reds]}" if reds else ""))

    # --- A31 ----------------------------------------------------------------
    # Injure one thing and confirm the matching row goes red (BE-15's own
    # acceptance: a check that cannot fail is not a check).
    session = study.load_session(sid)
    snap_path = study_snapshots.snapshots_dir(session) / "initial.json"
    backup = snap_path.read_text(encoding="utf-8")
    snap_path.unlink()
    code, injured = call("POST", f"/close/{sid}", mod)
    row = next((c for c in injured.get("checks", []) if c["check"] == "snapshots"), {})
    check("A31", "BE-15",
          row.get("status") == "fail" and injured.get("verdict") == "invalid",
          f"removed the initial snapshot -> {row.get('status')} / {injured.get('verdict')}")
    snap_path.write_text(backup, encoding="utf-8")
    call("POST", f"/close/{sid}", mod)          # restore a truthful report

    # --- A32 ----------------------------------------------------------------
    code, formal = call("POST", "/sessions", mod, {
        "condition": "c", "participant_code": "DRY-FORMAL", "lang": "en", "track": "formal"})
    call("POST", "/start", formal["join_token"])
    f_events = events_of(formal["session_id"])
    t_events = [e for e in evs if e["event"] in {x["event"] for x in f_events}]
    same_shape = (
        [sorted(e) for e in f_events]
        == [sorted(e) for e in t_events[:len(f_events)]]
    )
    check("A32", "BE-19",
          same_shape and {e["track"] for e in f_events} == {"formal"},
          "formal and test event records are field-for-field identical")

    return report_results()


def report_results() -> int:
    width = max(len(a) for _, a, _, _ in RESULTS) + 2
    failed = 0
    print()
    for step, acceptance, ok, detail in RESULTS:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"  [{mark}] {step:<4} {acceptance:<{width}} {detail}")
    print()
    print(f"{len(RESULTS) - failed}/{len(RESULTS)} steps passed")
    if failed:
        print("\nDry run FAILED. Do not proceed to a pilot.")
    else:
        print("\nAutomated half of the dry run is green. "
              "Now walk part B (browser) in docs/假实验脚本_v1_draft.md.")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8000",
                    help="server root (default: %(default)s)")
    args = ap.parse_args()
    return run(args.base)


if __name__ == "__main__":
    raise SystemExit(main())
