"""
Study log ingestion (BE-06) and snapshots (红线 #1).

The tests that matter here are about not losing things: a gap must be recorded
rather than swallowed, one bad event must not cost the batch, and the phase on
a record must come from the server even when the client disagrees.
"""
import json

import pytest

from app.core import study, study_log, study_snapshots, workspace


@pytest.fixture
def auth_client(tmp_data_dir, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "auth_disabled", False)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def moderator(tmp_data_dir):
    return workspace.mint_token("mod", role="moderator")["token"]


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ptc(auth_client, moderator):
    """A started condition-C participant."""
    r = auth_client.post("/api/study/sessions", headers=_hdr(moderator), json={
        "condition": "c", "participant_code": "P01", "lang": "en"})
    out = r.json()
    auth_client.post("/api/study/start", headers=_hdr(out["join_token"]))
    return out


def _events(session_id):
    session = study.load_session(session_id)
    path = study.session_dir(
        session["workspace_id"], session_id, session["track"]) / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _ev(seq, event="chip_click", **payload):
    return {"seq": seq, "ts_mono": seq * 100, "ts_wall": "2026-08-20T00:00:00Z",
            "event": event, "payload": payload}


def _post(client, token, events):
    return client.post("/api/study/log/batch", headers=_hdr(token),
                       json={"events": events})


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def test_batch_is_appended_with_the_server_envelope(auth_client, ptc):
    r = _post(auth_client, ptc["join_token"], [
        _ev(0, "chip_click", snippet_id="c4", exhibit="B1", page=2, label="Reports to the CTO"),
        _ev(1, "heartbeat"),
    ])
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 2
    assert r.json()["acked_seq"] == 1

    recs = [e for e in _events(ptc["session_id"]) if e["source"] == "client"]
    assert [e["event"] for e in recs] == ["chip_click", "heartbeat"]
    first = recs[0]
    assert first["cond"] == "c"
    assert first["track"] == "formal"
    assert first["schema_version"] == study_log.SCHEMA_VERSION
    assert first["ts_wall"]           # server-stamped
    assert first["ts_mono"] == 0      # client-authored
    # The payload keeps the human-readable label, not just the id -- this is
    # what makes the log interpretable later.
    assert first["payload"]["label"] == "Reports to the CTO"


def test_one_bad_event_does_not_cost_the_batch(auth_client, ptc):
    r = _post(auth_client, ptc["join_token"], [
        _ev(0, "chip_click"),
        {"seq": 1, "event": "chip_click"},              # no ts_mono
        _ev(2, "not_a_real_event"),                     # not in the dictionary
        _ev(3, "heartbeat"),
    ])
    body = r.json()
    assert body["accepted"] == 2
    assert body["rejected"] == 2
    assert {x["reason"] for x in body["rejections"]} == {
        "missing ts_mono", "unknown event 'not_a_real_event'"}
    assert [e["event"] for e in _events(ptc["session_id"]) if e["source"] == "client"] \
        == ["chip_click", "heartbeat"]


def test_a_client_may_not_forge_a_server_event(auth_client, ptc):
    """A client-authored phase_enter would corrupt the phase reconstruction."""
    r = _post(auth_client, ptc["join_token"], [_ev(0, "phase_enter", phase="probe")])
    assert r.json()["rejected"] == 1


def test_condition_scoped_events_are_refused_from_the_wrong_condition(auth_client, moderator):
    out = auth_client.post("/api/study/sessions", headers=_hdr(moderator), json={
        "condition": "b", "participant_code": "P02", "lang": "en"}).json()
    auth_client.post("/api/study/start", headers=_hdr(out["join_token"]))

    r = _post(auth_client, out["join_token"], [
        _ev(0, "msg_send", text="hi"),      # B event: fine
        _ev(1, "tree_op", op="move"),       # C event: not in condition B
    ])
    assert r.json()["accepted"] == 1
    assert r.json()["rejected"] == 1


def test_seq_gap_is_registered_not_refused(auth_client, ptc):
    """The participant pulled the network cable. The session continues, and the
    analysis is told which stretch is missing (BE-06)."""
    _post(auth_client, ptc["join_token"], [_ev(0), _ev(1)])
    r = _post(auth_client, ptc["join_token"], [_ev(7), _ev(8)])

    assert r.status_code == 200
    assert r.json()["accepted"] == 2
    assert r.json()["gaps"] == [[2, 6]]
    assert study.load_session(ptc["session_id"])["seq_gaps"] == [[2, 6]]


def test_gaps_do_not_appear_for_contiguous_batches(auth_client, ptc):
    _post(auth_client, ptc["join_token"], [_ev(0), _ev(1)])
    r = _post(auth_client, ptc["join_token"], [_ev(2), _ev(3)])
    assert r.json()["gaps"] == []
    assert "seq_gaps" not in study.load_session(ptc["session_id"])


def test_out_of_order_within_a_batch_is_accepted(auth_client, ptc):
    r = _post(auth_client, ptc["join_token"], [_ev(2), _ev(0), _ev(1)])
    assert r.json()["accepted"] == 3
    assert r.json()["gaps"] == []
    assert r.json()["acked_seq"] == 2


def test_phase_comes_from_the_server_not_the_client(auth_client, moderator, ptc, walk_to):
    """A client a poll behind must not file events under the previous phase."""
    walk_to(auth_client, moderator, ptc, "organization")
    assert study.load_session(ptc["session_id"])["phase"] == "organization"

    stale = _ev(0)
    stale["phase"] = "tutorial"          # what the client still believes
    _post(auth_client, ptc["join_token"], [stale])

    rec = [e for e in _events(ptc["session_id"]) if e["source"] == "client"][0]
    assert rec["phase"] == "organization"
    assert rec["phase_client"] == "tutorial"   # the disagreement stays visible


def test_practice_flag_is_derived_from_the_phase(auth_client, moderator, ptc):
    """BE-18: everything during practice carries practice:true."""
    for _ in range(2):
        auth_client.post("/api/study/advance", headers=_hdr(moderator),
                         json={"session_id": ptc["session_id"]})
    assert study.load_session(ptc["session_id"])["phase"] == "practice"

    _post(auth_client, ptc["join_token"], [_ev(0, "checkpoint_passed", gate="lightbox")])
    rec = [e for e in _events(ptc["session_id"]) if e["source"] == "client"][-1]
    assert rec["practice"] is True


def test_batch_needs_a_participant_token(auth_client, moderator):
    assert auth_client.post("/api/study/log/batch", json={"events": []}).status_code == 401
    assert _post(auth_client, moderator, [_ev(0)]).status_code == 403


def test_oversized_payload_is_truncated_not_dropped(auth_client, ptc):
    big = _ev(0, "text_edit", changed_text="x" * (study_log.MAX_PAYLOAD_BYTES + 100))
    r = _post(auth_client, ptc["join_token"], [big])
    assert r.json()["accepted"] == 1
    rec = [e for e in _events(ptc["session_id"]) if e["source"] == "client"][-1]
    assert rec["truncated"] is True
    assert rec["payload"]["_truncated"] is True


# ---------------------------------------------------------------------------
# find_gaps
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("previous,seqs,expected", [
    (-1, [0, 1, 2], []),
    (-1, [0, 2], [(1, 1)]),
    (2, [3, 4], []),
    (2, [10], [(3, 9)]),
    (-1, [5, 0, 1], [(2, 4)]),      # out of order, gap after sorting
    (5, [3, 4], []),                # a late re-send is not a gap
])
def test_find_gaps(previous, seqs, expected):
    assert study_log.find_gaps(previous, seqs) == expected


# ---------------------------------------------------------------------------
# Human-readable summaries -- the point of carrying titles in payloads
# ---------------------------------------------------------------------------

def test_summaries_read_as_sentences():
    move = {"event": "tree_op", "payload": {
        "op": "move", "node_id": "s4", "node_title": "Decision and resource authority",
        "to_parent_title": "The petitioner performs a leading role"}}
    assert study_log.summarise(move) == (
        'moved “Decision and resource authority” under '
        '“The petitioner performs a leading role”')

    hover = {"event": "hover_end", "payload": {
        "exhibit": "B1", "page": 4, "dwell_ms": 1800}}
    assert study_log.summarise(hover) == (
        "hovered evidence B1 p.4 for 1800ms without selecting it")

    assert study_log.summarise({"event": "heartbeat", "payload": {}}) is None


def test_text_edit_summary_counts_what_changed_not_the_whole_draft():
    """A one-word fix in a long letter must not read as "edited 11 sentences" --
    the post-task interview quotes these lines back at the participant."""
    edit = {"event": "text_edit", "payload": {
        "affected_sent_ids": ["s_a", "s_b"],
        "sentence_count": 11,
        "splits": 1,
    }}
    line = study_log.summarise(edit)
    assert "2 sentence(s)" in line
    assert "11" not in line
    assert "split 1" in line


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

def test_snapshot_stores_text_whole_and_meta_without_it(auth_client, ptc):
    session = study.load_session(ptc["session_id"])
    text = ("Dr. Li reported to the CTO [Exhibit B1, p.2]. "
            "He led four teams [Exhibit B1, p.3].")

    meta = study_snapshots.write_snapshot(session, "initial", "draft", text)

    assert "text" not in meta
    assert meta["sha256"] == study_snapshots.sha256(text)
    assert meta["citation_count"] == 2
    assert meta["sentence_count"] == 2

    body = study_snapshots.read_snapshot(session, "initial")
    assert body["text"] == text


def test_citation_regex_matches_the_frontend(auth_client, ptc):
    """The count shown on screen and the count stored must never disagree."""
    text = "A [Exhibit B1, p.2] and B [Exhibit C1, p.1; Exhibit C2, p.3] end."
    assert study_snapshots.count_citations(text) == 2
