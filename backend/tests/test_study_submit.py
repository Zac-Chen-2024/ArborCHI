"""
Submission, the declaration timestamp, and the lock (BE-11, PR-6, 红线 #1).

The verification phase has no buzzer and no lock, so `submit_declared` is the
only record of when the participant decided they had checked enough -- and that
decision is the dependent measure. These tests guard the three ways it could go
wrong quietly: submitting from the wrong phase, storing text that differs from
what was on screen, and continuing to accept writes after the fact.
"""
import hashlib
import json

import pytest

from app.core import study, study_snapshots, workspace


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


def _events(session_id):
    session = study.load_session(session_id)
    path = study.session_dir(
        session["workspace_id"], session_id, session["track"]) / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]




FINAL = ("Dr. Li reported directly to the CTO [Exhibit B1, p.2]. "
         "He oversaw four teams [Exhibit B1, p.3].")


@pytest.fixture
def verifying(auth_client, moderator, walk_to):
    """A condition-C participant sitting in the verification phase."""
    out = auth_client.post("/api/study/sessions", headers=_hdr(moderator), json={
        "condition": "c", "participant_code": "P11", "lang": "en"}).json()
    auth_client.post("/api/study/start", headers=_hdr(out["join_token"]))
    walk_to(auth_client, moderator, out, "verification")
    return out


def _submit(client, token, text=FINAL, digest=None):
    return client.post("/api/study/submit", headers=_hdr(token), json={
        "text": text,
        "final_text_hash": digest or hashlib.sha256(text.encode()).hexdigest(),
    })


# ---------------------------------------------------------------------------

def test_submit_writes_the_final_snapshot_and_locks(auth_client, verifying):
    r = _submit(auth_client, verifying["join_token"])
    assert r.status_code == 200, r.text
    assert r.json()["submitted"] is True

    session = study.load_session(verifying["session_id"])
    assert session["submitted"] is True
    assert session["final_text_hash"] == hashlib.sha256(FINAL.encode()).hexdigest()

    snap = study_snapshots.read_snapshot(session, "final")
    assert snap["text"] == FINAL
    assert snap["sentence_count"] == 2      # "Dr." is not a sentence end
    assert snap["citation_count"] == 2


def test_submit_declared_records_the_moment_and_the_elapsed_time(auth_client, verifying):
    _submit(auth_client, verifying["join_token"])

    declared = [e for e in _events(verifying["session_id"])
                if e["event"] == "submit_declared"]
    assert len(declared) == 1
    payload = declared[0]["payload"]
    assert payload["phase"] == "verification"
    # Server-side measurement of a duration the participant never saw.
    assert isinstance(payload["phase_elapsed_ms"], int)
    assert payload["char_count"] == len(FINAL)


def test_hash_mismatch_is_refused_before_anything_is_written(auth_client, verifying):
    """The probe quizzes the participant on the stored text; it must be the
    text they were looking at."""
    r = _submit(auth_client, verifying["join_token"],
                digest="0" * 64)
    assert r.status_code == 400

    session = study.load_session(verifying["session_id"])
    assert session["submitted"] is False
    assert study_snapshots.read_snapshot(session, "final") is None
    assert not any(e["event"] == "submit_declared" for e in _events(verifying["session_id"]))


def test_cannot_submit_from_a_phase_the_protocol_does_not_allow(auth_client, moderator, walk_to):
    out = auth_client.post("/api/study/sessions", headers=_hdr(moderator), json={
        "condition": "c", "participant_code": "P12", "lang": "en"}).json()
    auth_client.post("/api/study/start", headers=_hdr(out["join_token"]))
    walk_to(auth_client, moderator, out, "organization")

    r = _submit(auth_client, out["join_token"])
    assert r.status_code == 409
    assert study.load_session(out["session_id"])["submitted"] is False


def test_double_submit_is_refused(auth_client, verifying):
    assert _submit(auth_client, verifying["join_token"]).status_code == 200
    assert _submit(auth_client, verifying["join_token"]).status_code == 409
    assert len([e for e in _events(verifying["session_id"])
                if e["event"] == "submit"]) == 1


def test_everything_is_read_only_after_submit(auth_client, verifying):
    """BE-11: the final snapshot must not be able to drift from what the probe
    is built on."""
    _submit(auth_client, verifying["join_token"])

    r = auth_client.post("/api/study/log/batch", headers=_hdr(verifying["join_token"]),
                         json={"events": [{"seq": 0, "ts_mono": 1, "event": "text_edit",
                                           "payload": {}}]})
    assert r.status_code == 409


def test_can_submit_flag_flips_off_once_submitted(auth_client, verifying):
    _submit(auth_client, verifying["join_token"])
    state = auth_client.get("/api/study/state",
                            headers=_hdr(verifying["join_token"])).json()
    assert state["can_submit"] is False
    assert state["submitted"] is True
    # Still no clock, even at the end (红线 #4).
    assert not any("remaining" in k or "deadline" in k for k in state)


def test_every_event_carries_the_provenance_triple(auth_client, verifying):
    """schema v3: which parameters, which material, which tree. Without these
    a log says what happened but not what it happened to."""
    _submit(auth_client, verifying["join_token"])
    for record in _events(verifying["session_id"]):
        assert "config_hash" in record
        assert "material_manifest_hash" in record
        assert "tree_variant_id" in record
        assert record["schema_version"] == 3
    # The config hash is a real value, pinned at session creation.
    assert study.load_session(verifying["session_id"])["config_hash"]
