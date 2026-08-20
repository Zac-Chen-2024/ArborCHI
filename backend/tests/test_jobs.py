"""
Background jobs (M10): submit/poll/cancel, idempotency, failure, restart
recovery, workspace scoping, and the write-v3 endpoint returning a job.
"""
import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.core import jobs as jobs_mod
from app.core.jobs import JobCancelled, JobHandle, JobManager, NullJob


def _wait(client, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        rec = client.get(f"/api/jobs/{job_id}").json()
        if rec["status"] in ("succeeded", "failed", "cancelled"):
            return rec
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish: {rec}")


@pytest.fixture
def live_client(tmp_data_dir):
    """TestClient as a context manager keeps one event loop alive across
    requests, which background tasks need."""
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def fresh_manager(monkeypatch):
    m = JobManager()
    monkeypatch.setattr(jobs_mod, "manager", m)
    import app.routers.jobs as jr
    monkeypatch.setattr(jr, "manager", m)
    return m


# ---- manager unit behaviour (run inside the app loop via endpoints) -----------

def test_submit_poll_result_and_progress(live_client, fresh_manager, tmp_data_dir):
    from app.main import app

    async def work(job: JobHandle):
        for i in range(3):
            job.checkpoint(step=f"s{i}", detail=f"step {i}", progress=i / 3)
            await asyncio.sleep(0.01)
        return {"answer": 42}

    async def _submit():
        return fresh_manager.submit("demo", "proj-1", {"x": 1}, work)
    app.add_api_route("/api/_test/submit", _submit, methods=["POST"])

    rec = live_client.post("/api/_test/submit").json()
    assert rec["status"] in ("queued", "running") and rec["id"].startswith("job-")
    done = _wait(live_client, rec["id"])
    assert done["status"] == "succeeded" and done["result"] == {"answer": 42}
    assert done["progress"] == 1.0 and done["step"] == "s2"
    # persisted on disk in the workspace
    path = tmp_data_dir / "workspaces" / "default" / "jobs" / f"{rec['id']}.json"
    assert json.loads(path.read_text())["status"] == "succeeded"
    # listed
    listed = live_client.get("/api/jobs?project_id=proj-1").json()["jobs"]
    assert [j["id"] for j in listed] == [rec["id"]]


def test_idempotent_submit_returns_running_job(live_client, fresh_manager):
    from app.main import app
    gate = asyncio.Event()

    async def work(job):
        await gate.wait()
        return "ok"

    async def _submit():
        return fresh_manager.submit("demo", "p", {"same": True}, work)

    async def _release():
        gate.set()
        return {}
    app.add_api_route("/api/_test/submit2", _submit, methods=["POST"])
    app.add_api_route("/api/_test/release", _release, methods=["POST"])

    a = live_client.post("/api/_test/submit2").json()
    b = live_client.post("/api/_test/submit2").json()
    assert a["id"] == b["id"]
    live_client.post("/api/_test/release")
    assert _wait(live_client, a["id"])["status"] == "succeeded"
    # after completion, a new submit starts a new job
    gate.clear()
    c = live_client.post("/api/_test/submit2").json()
    assert c["id"] != a["id"]
    live_client.post("/api/_test/release")
    _wait(live_client, c["id"])


def test_cooperative_cancel(live_client, fresh_manager):
    from app.main import app
    ticks = {"n": 0}

    async def work(job):
        while True:
            ticks["n"] += 1
            job.checkpoint(detail=f"tick {ticks['n']}")
            await asyncio.sleep(0.01)

    async def _submit():
        return fresh_manager.submit("loop", "p", {"k": 1}, work)
    app.add_api_route("/api/_test/submit3", _submit, methods=["POST"])

    rec = live_client.post("/api/_test/submit3").json()
    time.sleep(0.05)
    r = live_client.post(f"/api/jobs/{rec['id']}/cancel")
    assert r.status_code == 200
    done = _wait(live_client, rec["id"])
    assert done["status"] == "cancelled"
    n = ticks["n"]
    time.sleep(0.05)
    assert ticks["n"] == n  # loop really stopped


def test_failure_is_recorded_not_raised(live_client, fresh_manager):
    from app.main import app

    async def work(job):
        raise ValueError("bad input /secret/path")

    async def _submit():
        return fresh_manager.submit("boom", "p", {"k": 2}, work)
    app.add_api_route("/api/_test/submit4", _submit, methods=["POST"])

    rec = live_client.post("/api/_test/submit4").json()
    done = _wait(live_client, rec["id"])
    assert done["status"] == "failed" and done["error"].startswith("ValueError")


def test_unknown_job_404_and_bad_id(live_client):
    assert live_client.get("/api/jobs/job-nope").status_code == 404
    assert live_client.get("/api/jobs/..").status_code == 404
    assert live_client.post("/api/jobs/job-nope/cancel").status_code == 404


def test_recover_on_startup_marks_running_as_failed(tmp_data_dir):
    m = JobManager()
    d = tmp_data_dir / "workspaces" / "default" / "jobs"
    d.mkdir(parents=True)
    (d / "job-a.json").write_text(json.dumps({"id": "job-a", "status": "running"}))
    (d / "job-b.json").write_text(json.dumps({"id": "job-b", "status": "succeeded"}))
    (tmp_data_dir / "workspaces" / "P07" / "jobs").mkdir(parents=True)
    (tmp_data_dir / "workspaces" / "P07" / "jobs" / "job-c.json").write_text(json.dumps({"id": "job-c", "status": "queued"}))
    assert m.recover_on_startup() == 2
    assert json.loads((d / "job-a.json").read_text())["status"] == "failed"
    assert json.loads((d / "job-b.json").read_text())["status"] == "succeeded"
    assert json.loads((tmp_data_dir / "workspaces" / "P07" / "jobs" / "job-c.json").read_text())["error"] == "server restarted"


def test_jobs_are_workspace_scoped(live_client, fresh_manager, tmp_data_dir, monkeypatch):
    from app.core import workspace as ws
    from app.core.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "auth_disabled", False)
    ta = ws.mint_token("A")["token"]
    tb = ws.mint_token("B")["token"]

    async def work(job):
        return "x"

    async def _submit():
        return fresh_manager.submit("scoped", "p", {"k": 3}, work)
    app.add_api_route("/api/_test/submit5", _submit, methods=["POST"])

    rec = live_client.post("/api/_test/submit5", headers={"Authorization": f"Bearer {ta}"}).json()
    assert (tmp_data_dir / "workspaces" / "A" / "jobs" / f"{rec['id']}.json").exists()
    assert live_client.get(f"/api/jobs/{rec['id']}", headers={"Authorization": f"Bearer {tb}"}).status_code == 404
    assert live_client.get(f"/api/jobs/{rec['id']}", headers={"Authorization": f"Bearer {ta}"}).status_code == 200


def test_null_job_is_inert():
    NullJob().checkpoint(step="x", detail="y", progress=0.5)
    with pytest.raises(JobCancelled):
        m = JobManager()
        m._cancel_flags.add("job-x")
        # a handle whose job is flagged raises even without persistence
        h = JobHandle(m, "job-x")
        m._update = lambda *a, **k: None
        h.checkpoint(detail="d")


# ---- write v3 endpoint returns a job -----------------------------------------

def test_write_v3_endpoint_returns_job_with_result(live_client, fresh_manager, victim_project, monkeypatch):
    import app.routers.writing as wr

    async def fake_pipeline(**kw):
        job = kw.get("job")
        if job:
            job.checkpoint(step="step1", detail="Step 1/3: Argument 1/1", progress=0.3)
        return {"success": True, "section": kw["standard_key"], "paragraph_text": "Hello.",
                "sentences": [{"text": "Hello.", "snippet_ids": [], "sentence_type": "opening"}],
                "provenance_index": {}, "validation": {"total_sentences": 1, "traced_sentences": 0}}
    monkeypatch.setattr(wr, "write_petition_section_v3", fake_pipeline)
    monkeypatch.setattr(wr, "save_writing_v3", lambda *a, **k: "v1")

    r = live_client.post(f"/api/write/v3/{victim_project}/awards", json={"provider": "deepseek"})
    assert r.status_code == 202, r.text
    rec = r.json()
    assert rec["type"] == "write_v3" and rec["project_id"] == victim_project
    done = _wait(live_client, rec["id"])
    assert done["status"] == "succeeded"
    assert done["result"]["success"] is True and done["result"]["paragraph_text"] == "Hello."
    assert done["result"]["sentences"][0]["sentence_type"] == "opening"


# ---- step-1 checkpoints ---------------------------------------------------------

def test_step1_checkpoint_roundtrip_and_fingerprint(tmp_data_dir, victim_project):
    from app.services import petition_writer_v3 as pw

    arg = {"id": "arg-1", "title": "T", "sub_arguments": [{"id": "sa-1", "title": "s", "purpose": "p", "relationship": "r",
                                                          "snippets": [{"id": "snp_A1_x"}, {"id": "snp_A1_y"}]}]}
    fp1 = pw._step1_fingerprint(arg, "deepseek", "EB-1A", None, None)
    fp_same = pw._step1_fingerprint(json.loads(json.dumps(arg)), "deepseek", "EB-1A", None, None)
    assert fp1 == fp_same
    # snippet order does not matter; content does
    arg2 = json.loads(json.dumps(arg))
    arg2["sub_arguments"][0]["snippets"].reverse()
    assert pw._step1_fingerprint(arg2, "deepseek", "EB-1A", None, None) == fp1
    arg3 = json.loads(json.dumps(arg))
    arg3["sub_arguments"][0]["title"] = "changed"
    assert pw._step1_fingerprint(arg3, "deepseek", "EB-1A", None, None) != fp1
    assert pw._step1_fingerprint(arg, "openai", "EB-1A", None, None) != fp1

    assert pw._load_step1_checkpoint(victim_project, "awards", fp1) is None
    bodies = [{"subargument_id": "sa-1", "sentences": [{"text": "x", "snippet_ids": ["snp_A1_x"]}]}]
    pw._save_step1_checkpoint(victim_project, "awards", fp1, bodies)
    assert pw._load_step1_checkpoint(victim_project, "awards", fp1) == bodies
