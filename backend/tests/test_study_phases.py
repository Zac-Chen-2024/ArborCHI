"""
Study session lifecycle: roles, the phase machine, and the timing red line.

The tests that matter most here are the negative ones -- BE-04 / 红线 #4 says
the verification phase must not leak a clock, and BE-02 says a participant
token must not reach a moderator route. Both are the kind of thing that breaks
silently, so they are asserted structurally (key absence, status code) rather
than by eyeballing a response.
"""
import json

import pytest

from app.core import study, workspace


@pytest.fixture
def auth_client(tmp_data_dir, monkeypatch):
    """Client with real token auth on -- the study routes gate on role, which
    only exists on a token entry."""
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


def _make_session(client, moderator, condition="c", lang="en", track="formal"):
    r = client.post("/api/study/sessions", headers=_hdr(moderator), json={
        "condition": condition, "participant_code": "P07", "lang": lang, "track": track,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _events(session_id):
    session = study.load_session(session_id)
    path = study.session_dir(
        session["workspace_id"], session_id, session["track"]) / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------
# BE-01 / BE-02: sessions and roles
# ---------------------------------------------------------------------------

def test_moderator_creates_session_and_participant_token(auth_client, moderator):
    out = _make_session(auth_client, moderator)
    assert out["condition"] == "c"
    assert out["join_url"].endswith(out["join_token"])

    entry = workspace.load_token_table()[out["join_token"]]
    assert entry["role"] == "participant"
    assert entry["track"] == "formal"
    assert entry["session_id"] == out["session_id"]


def test_participant_cannot_reach_moderator_routes(auth_client, moderator):
    out = _make_session(auth_client, moderator)
    ptc = _hdr(out["join_token"])

    assert auth_client.post("/api/study/sessions", headers=ptc, json={
        "condition": "b", "participant_code": "X", "lang": "en"}).status_code == 404
    assert auth_client.post("/api/study/advance", headers=ptc, json={
        "session_id": out["session_id"]}).status_code == 404
    assert auth_client.get(
        f"/api/study/monitor/{out['session_id']}", headers=ptc).status_code == 404


def test_no_token_is_unauthorized(auth_client):
    assert auth_client.get("/api/study/state").status_code == 401


def test_participant_state_is_its_own_session_only(auth_client, moderator):
    """There is no session_id parameter on /state -- a participant reads the
    session its own token is bound to, so cross-session access has no surface."""
    a = _make_session(auth_client, moderator, condition="c")
    b = _make_session(auth_client, moderator, condition="b")

    sa = auth_client.get("/api/study/state", headers=_hdr(a["join_token"])).json()
    sb = auth_client.get("/api/study/state", headers=_hdr(b["join_token"])).json()
    assert sa["session_id"] == a["session_id"] and sa["condition"] == "c"
    assert sb["session_id"] == b["session_id"] and sb["condition"] == "b"


def test_moderator_token_is_not_bound_to_a_session(auth_client, moderator):
    assert auth_client.get("/api/study/state", headers=_hdr(moderator)).status_code == 403


# ---------------------------------------------------------------------------
# BE-03: the phase machine
# ---------------------------------------------------------------------------

def test_phase_machine_walks_the_condition_c_order(auth_client, moderator):
    out = _make_session(auth_client, moderator, condition="c")
    sid = out["session_id"]
    seen = ["setup"]
    for _ in range(len(study.PHASES["c"]) - 1):
        r = auth_client.post("/api/study/advance", headers=_hdr(moderator),
                             json={"session_id": sid})
        assert r.status_code == 200, r.text
        seen.append(r.json()["phase"])
    assert seen == study.PHASES["c"]

    # Past the end is a conflict, not a silent no-op.
    r = auth_client.post("/api/study/advance", headers=_hdr(moderator),
                         json={"session_id": sid})
    assert r.status_code == 409


def test_condition_b_has_no_organization_or_generation(auth_client, moderator):
    assert "organization" not in study.PHASES["b"]
    assert "generation" not in study.PHASES["b"]
    assert "work" in study.PHASES["b"]


def test_advance_refuses_to_skip_a_phase(auth_client, moderator):
    """`to` is a confirmation of the next phase, never a jump instruction."""
    sid = _make_session(auth_client, moderator)["session_id"]
    r = auth_client.post("/api/study/advance", headers=_hdr(moderator),
                         json={"session_id": sid, "to": "verification"})
    assert r.status_code == 409
    assert study.load_session(sid)["phase"] == "setup"


def test_phase_transitions_are_logged_in_pairs(auth_client, moderator):
    sid = _make_session(auth_client, moderator)["session_id"]
    for _ in range(3):
        auth_client.post("/api/study/advance", headers=_hdr(moderator),
                         json={"session_id": sid})

    evs = [e for e in _events(sid) if e["event"] in ("phase_enter", "phase_exit")]
    assert [e["event"] for e in evs] == ["phase_exit", "phase_enter"] * 3
    assert [e["payload"]["phase"] for e in evs] == [
        "setup", "tutorial", "tutorial", "practice", "practice", "organization",
    ]


# ---------------------------------------------------------------------------
# BE-04 / 红线 #4: the clock
# ---------------------------------------------------------------------------

def _advance_to(client, moderator, sid, phase):
    for _ in range(len(study.PHASES["c"])):
        if study.load_session(sid)["phase"] == phase:
            return
        client.post("/api/study/advance", headers=_hdr(moderator),
                    json={"session_id": sid})
    raise AssertionError(f"never reached {phase}")


def test_organization_exposes_a_countdown(auth_client, moderator):
    out = _make_session(auth_client, moderator)
    _advance_to(auth_client, moderator, out["session_id"], "organization")

    state = auth_client.get("/api/study/state", headers=_hdr(out["join_token"])).json()
    assert state["phase"] == "organization"
    assert state["remaining_ms"] > 0


def test_verification_state_has_no_time_field_at_all(auth_client, moderator):
    """红线 #4. Not null, not zero -- absent. A participant reading the network
    tab must have nothing to render a clock from."""
    out = _make_session(auth_client, moderator)
    _advance_to(auth_client, moderator, out["session_id"], "verification")

    r = auth_client.get("/api/study/state", headers=_hdr(out["join_token"]))
    body = r.json()
    assert body["phase"] == "verification"
    assert not any("remaining" in k or "deadline" in k or "ms" in k for k in body), body
    # Belt and braces: no timestamp-shaped number anywhere in the payload.
    assert not any(isinstance(v, (int, float)) and v > 10_000 for v in body.values()), body


def test_softlock_drops_when_the_budget_runs_out(auth_client, moderator, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "study_org_seconds", 0)
    out = _make_session(auth_client, moderator)
    _advance_to(auth_client, moderator, out["session_id"], "organization")

    state = auth_client.get("/api/study/state", headers=_hdr(out["join_token"])).json()
    assert state["softlock"] is True
    assert any(e["event"] == "phase_softlock" for e in _events(out["session_id"]))


def test_silent_phases_get_the_grace_period(monkeypatch):
    """Organisation locks on the dot; a silently-timed phase gets the grace
    window so nobody is cut off mid-keystroke."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "study_softlock_grace_seconds", 10)
    base = 1_000_000

    org = {"phase": "organization", "phase_deadline_ms": base, "softlock": False}
    assert study.softlock_due(org, base) is True

    ver = {"phase": "verification", "phase_deadline_ms": base, "softlock": False}
    assert study.softlock_due(ver, base) is False
    assert study.softlock_due(ver, base + 9_999) is False
    assert study.softlock_due(ver, base + 10_000) is True


def test_moderator_monitor_does_see_the_clock(auth_client, moderator):
    """The clock exists; only the participant is kept from it (MOD-03)."""
    out = _make_session(auth_client, moderator)
    _advance_to(auth_client, moderator, out["session_id"], "verification")

    mon = auth_client.get(f"/api/study/monitor/{out['session_id']}",
                          headers=_hdr(moderator)).json()
    assert mon["phase"] == "verification"
    assert mon["phase_remaining_ms"] > 0


# ---------------------------------------------------------------------------
# FS-12 / BE-19: start button and track isolation
# ---------------------------------------------------------------------------

def test_start_is_idempotent(auth_client, moderator):
    out = _make_session(auth_client, moderator)
    ptc = _hdr(out["join_token"])

    assert auth_client.post("/api/study/start", headers=ptc).json()["started"] is True
    started_at = study.load_session(out["session_id"])["started_at"]

    auth_client.post("/api/study/start", headers=ptc)
    assert study.load_session(out["session_id"])["started_at"] == started_at
    assert sum(1 for e in _events(out["session_id"]) if e["event"] == "session_start") == 1


def test_test_track_lands_in_a_separate_tree(auth_client, moderator, tmp_data_dir):
    formal = _make_session(auth_client, moderator, track="formal")
    test = _make_session(auth_client, moderator, track="test")

    f = study.load_session(formal["session_id"])
    t = study.load_session(test["session_id"])
    assert study.session_dir(f["workspace_id"], f["session_id"], "formal").is_relative_to(
        tmp_data_dir / "workspaces")
    assert study.session_dir(t["workspace_id"], t["session_id"], "test").is_relative_to(
        tmp_data_dir / "study_test")


def test_test_track_records_are_field_for_field_identical(auth_client, moderator):
    """BE-19: a test run is a full dress rehearsal -- same envelope, same
    machine, only the path and the `track` value differ."""
    formal = _make_session(auth_client, moderator, track="formal")
    test = _make_session(auth_client, moderator, track="test")
    for out in (formal, test):
        auth_client.post("/api/study/start", headers=_hdr(out["join_token"]))
        auth_client.post("/api/study/advance", headers=_hdr(moderator),
                         json={"session_id": out["session_id"]})

    fe, te = _events(formal["session_id"]), _events(test["session_id"])
    assert [e["event"] for e in fe] == [e["event"] for e in te]
    assert [sorted(e) for e in fe] == [sorted(e) for e in te]
    assert {e["track"] for e in fe} == {"formal"}
    assert {e["track"] for e in te} == {"test"}
