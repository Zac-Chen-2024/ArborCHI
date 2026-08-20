"""
Integrity report (BE-15, PR-4).

BE-15's acceptance is "假实验后逐条绿;人为制造一项缺陷 -> 对应条目红" --
so every check here is exercised twice: once on a clean session, and once on a
session with that specific defect injected. A check that cannot go red is not a
check.
"""
import json

import pytest

from app.core import integrity, study, study_snapshots, workspace


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


def _append_event(session, event, payload=None, **envelope):
    from app.core.atomic_io import append_jsonl
    from app.core.study_events import events_path

    record = {
        "schema_version": 3, "seq": None, "srv_seq": None,
        "ts_wall": study.now_iso(), "ts_mono": envelope.pop("ts_mono", 0),
        "phase": session.get("phase"), "practice": False,
        "cond": session["condition"], "track": session["track"], "build": "",
        "config_hash": session.get("config_hash", ""),
        "material_manifest_hash": session.get("material_manifest_hash", ""),
        "tree_variant_id": session.get("tree_variant_id", ""),
        "source": envelope.pop("source", "client"),
        "session_id": session["session_id"],
        "event": event, "payload": payload or {},
    }
    record.update(envelope)
    append_jsonl(events_path(session), record)


@pytest.fixture
def finished(auth_client, moderator, walk_to):
    """A complete, clean condition-C session: started, practised, generated,
    submitted, confidence answered, probe drawn and answered."""
    from app.core import materials

    out = auth_client.post("/api/study/sessions", headers=_hdr(moderator), json={
        "condition": "c", "participant_code": "P41", "lang": "en"}).json()
    token = _hdr(out["join_token"])
    auth_client.post("/api/study/start", headers=token)

    auth_client.post("/api/study/log/batch", headers=token, json={"events": [
        {"seq": 0, "ts_mono": 0, "event": "heartbeat", "payload": {}},
        {"seq": 1, "ts_mono": 30_000, "event": "heartbeat", "payload": {}},
        {"seq": 2, "ts_mono": 60_000, "event": "heartbeat", "payload": {}},
        {"seq": 3, "ts_mono": 90_000, "event": "heartbeat", "payload": {}},
    ]})
    # walk_to clears the practice gates on the way through, which is what
    # produces the checkpoint_passed events the report looks for.
    walk_to(auth_client, moderator, out, "verification")

    states = {
        nid: {"title": n["title"], "parent_id": n["parent_id"],
              "snippet_ids": list(n["snippet_ids"]), "state": "accepted"}
        for nid, n in materials.frozen_nodes().items()
    }
    gen = auth_client.post("/api/study/generate", headers=token,
                           json={"node_states": states}).json()
    auth_client.post("/api/study/submit", headers=token, json={
        "text": gen["text"], "final_text_hash": study_snapshots.sha256(gen["text"])})
    auth_client.post("/api/study/confidence", headers=token,
                     json={"likert_1_7": 5, "est_problem_count": 2})
    auth_client.post("/api/study/probe/start", headers=token)
    return out


# ---------------------------------------------------------------------------
# Clean session
# ---------------------------------------------------------------------------

def test_a_clean_session_comes_back_valid(auth_client, moderator, finished):
    r = auth_client.post(f"/api/study/close/{finished['session_id']}",
                         headers=_hdr(moderator))
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["verdict"] == "valid", report["checks"]
    assert report["failed"] == []
    assert {c["check"] for c in report["checks"]} == {
        "seq_continuity", "heartbeat", "snapshots", "phase_pairs",
        "practice_checkpoint", "order", "provenance", "event_volume",
    }


def test_the_report_is_written_to_the_session_directory(auth_client, moderator, finished):
    auth_client.post(f"/api/study/close/{finished['session_id']}", headers=_hdr(moderator))
    session = study.load_session(finished["session_id"])
    path = study.session_dir(
        session["workspace_id"], session["session_id"], session["track"]) / "integrity.json"
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["verdict"] == "valid"


def test_close_is_idempotent(auth_client, moderator, finished):
    a = auth_client.post(f"/api/study/close/{finished['session_id']}",
                         headers=_hdr(moderator)).json()
    b = auth_client.post(f"/api/study/close/{finished['session_id']}",
                         headers=_hdr(moderator)).json()
    assert a["verdict"] == b["verdict"]
    assert [c["status"] for c in a["checks"]] == [c["status"] for c in b["checks"]]


def test_only_a_moderator_can_close(auth_client, finished):
    r = auth_client.post(f"/api/study/close/{finished['session_id']}",
                         headers=_hdr(finished["join_token"]))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Injected defects -- each check must be able to go red
# ---------------------------------------------------------------------------

def test_a_large_seq_gap_invalidates_the_session(finished):
    """PR-4: losing more than 20% of the log is the one thing that invalidates."""
    def _damage(rec):
        rec["seq_acked"] = 100
        rec["seq_gaps"] = [[10, 90]]      # 81 of 101 missing
        return rec

    session = study.update_session(finished["session_id"], _damage)
    report = integrity.build_report(session)
    seq = next(c for c in report["checks"] if c["check"] == "seq_continuity")
    assert seq["status"] == integrity.FAIL
    assert seq["loss_ratio"] > 0.2
    assert report["verdict"] == "invalid"


def test_a_small_seq_gap_only_flags(finished):
    def _damage(rec):
        rec["seq_acked"] = 100
        rec["seq_gaps"] = [[10, 14]]      # 5 of 101
        return rec

    session = study.update_session(finished["session_id"], _damage)
    report = integrity.build_report(session)
    seq = next(c for c in report["checks"] if c["check"] == "seq_continuity")
    assert seq["status"] == integrity.FLAG
    assert report["verdict"] == "review"      # still analysable


def test_a_missing_initial_snapshot_invalidates(finished):
    session = study.load_session(finished["session_id"])
    path = study_snapshots.snapshots_dir(session) / "initial.json"
    path.unlink()

    report = integrity.build_report(session)
    snaps = next(c for c in report["checks"] if c["check"] == "snapshots")
    assert snaps["status"] == integrity.FAIL
    assert "initial snapshot missing" in snaps["detail"]
    assert report["verdict"] == "invalid"


def test_a_tampered_snapshot_is_caught_by_its_hash(finished):
    session = study.load_session(finished["session_id"])
    path = study_snapshots.snapshots_dir(session) / "final.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    body["text"] += " An extra sentence nobody wrote."
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")

    report = integrity.build_report(session)
    snaps = next(c for c in report["checks"] if c["check"] == "snapshots")
    assert snaps["status"] == integrity.FAIL
    assert "hash does not match" in snaps["detail"]


def test_an_edit_before_the_snapshot_invalidates(finished):
    """红线 #1 stated as a check: if a text_edit precedes the baseline, the
    baseline is not a baseline."""
    session = study.load_session(finished["session_id"])
    events = integrity.read_events(session)
    # Rewrite the log with a text_edit moved in front of the snapshot.
    path = study.session_dir(
        session["workspace_id"], session["session_id"], session["track"]) / "events.jsonl"
    snap_at = next(i for i, e in enumerate(events) if e["event"] == "draft_snapshot")
    edit = dict(events[0], event="text_edit", payload={}, source="client")
    events.insert(snap_at, edit)
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
                    encoding="utf-8")

    report = integrity.build_report(session)
    snaps = next(c for c in report["checks"] if c["check"] == "snapshots")
    assert snaps["status"] == integrity.FAIL
    assert "before the initial snapshot" in snaps["detail"]


def test_a_lost_checkpoint_event_only_flags(finished):
    """The gate makes it impossible to reach the task without clearing
    practice, so a session missing the event did not skip practice -- it lost
    the record of it. Still analysable; still worth telling the reader."""
    session = study.load_session(finished["session_id"])
    path = study.session_dir(
        session["workspace_id"], session["session_id"], session["track"]) / "events.jsonl"
    events = [e for e in integrity.read_events(session)
              if e["event"] != "checkpoint_passed"]
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
                    encoding="utf-8")

    report = integrity.build_report(study.load_session(finished["session_id"]))
    cp = next(c for c in report["checks"] if c["check"] == "practice_checkpoint")
    assert cp["status"] == integrity.FLAG
    assert report["verdict"] == "review"
    assert "practice_checkpoint" in report["flagged"]


def test_mixed_material_hashes_invalidate(finished):
    """A session whose events disagree about the material cannot be pooled with
    anything -- half of it ran on something else."""
    session = study.load_session(finished["session_id"])
    _append_event(session, "heartbeat", material_manifest_hash="a-different-bundle")

    report = integrity.build_report(session)
    prov = next(c for c in report["checks"] if c["check"] == "provenance")
    assert prov["status"] == integrity.FAIL
    assert "material_manifest_hash" in prov["mixed"]


def test_confidence_after_probe_is_an_order_failure(finished):
    session = study.load_session(finished["session_id"])
    # A probe_start with no confidence before it.
    path = study.session_dir(
        session["workspace_id"], session["session_id"], session["track"]) / "events.jsonl"
    events = [e for e in integrity.read_events(session)
              if e["event"] != "confidence_submit"]
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
                    encoding="utf-8")

    report = integrity.build_report(study.load_session(finished["session_id"]))
    order = next(c for c in report["checks"] if c["check"] == "order")
    assert order["status"] == integrity.FAIL
    assert "without a confidence answer" in order["detail"]


def test_an_unexited_phase_is_a_failure(finished):
    session = study.load_session(finished["session_id"])
    _append_event(session, "phase_enter", {"phase": "probe"}, source="server")

    report = integrity.build_report(study.load_session(finished["session_id"]))
    pairs = next(c for c in report["checks"] if c["check"] == "phase_pairs")
    assert pairs["status"] == integrity.FAIL


# ---------------------------------------------------------------------------
# Event volume -- flag only (PR-4)
# ---------------------------------------------------------------------------

def test_event_volume_flags_but_never_fails(finished):
    """An unusually fast or thorough participant is a finding, not damage.
    Rejecting them on a threshold would select the sample toward the mean."""
    session = study.load_session(finished["session_id"])
    baseline = {"n": 10, "mean": 500.0, "sd": 10.0}      # this session is far off

    report = integrity.build_report(session, baseline=baseline)
    vol = next(c for c in report["checks"] if c["check"] == "event_volume")
    assert vol["status"] == integrity.FLAG
    assert abs(vol["z"]) > 3
    assert report["verdict"] == "review"          # flagged, NOT invalid
    assert "event_volume" not in report["failed"]


def test_event_volume_passes_without_a_baseline(finished):
    session = study.load_session(finished["session_id"])
    report = integrity.build_report(session, baseline={"n": 1, "mean": 5.0, "sd": 0.0})
    vol = next(c for c in report["checks"] if c["check"] == "event_volume")
    assert vol["status"] == integrity.PASS


@pytest.mark.parametrize("counts,expected_n", [([], 0), ([10], 1), ([10, 20, 30], 3)])
def test_cohort_baseline_shapes(counts, expected_n):
    out = integrity.cohort_baseline(counts)
    assert out["n"] == expected_n
    if expected_n >= 2:
        assert out["sd"] > 0


def test_cohort_baseline_is_the_sample_sd():
    out = integrity.cohort_baseline([2, 4, 4, 4, 5, 5, 7, 9])
    assert out["mean"] == 5.0
    assert out["sd"] == pytest.approx(2.14, abs=0.01)
