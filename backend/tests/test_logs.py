"""
Interaction log ingestion (M6).
"""
import json


def _read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_ingest_appends_canonical_records(client, tmp_data_dir):
    body = {
        "session_id": "session_1_abc",
        "project_id": "proj-1",
        "logs": [
            {"ts": 1700000000000, "event": "node_create", "panel": "tree", "payload": {"id": "subarg-1"}},
            {"ts": 1700000001000, "event": "panel_focus", "panel": "letter"},
            {"ts": 1700000002000, "event": "bogus_event", "panel": "tree"},          # rejected
            {"ts": "not-a-number", "event": "citation_click", "panel": "letter"},   # rejected
            {"ts": 1700000003000, "event": "pdf_scroll", "panel": "weird", "payload": "nope"},  # panel->other, payload->{}
        ],
    }
    r = client.post("/api/logs/interactions", json=body)
    assert r.status_code == 200
    assert r.json() == {"success": True, "accepted": 3, "rejected": 2}

    path = tmp_data_dir / "workspaces" / "default" / "logs" / "session_1_abc.jsonl"
    recs = _read(path)
    assert [x["event"] for x in recs] == ["node_create", "panel_focus", "pdf_scroll"]
    assert recs[0] == {
        "ts": 1700000000000, "session_id": "session_1_abc", "project_id": "proj-1",
        "event": "node_create", "panel": "tree", "payload": {"id": "subarg-1"},
        "received_at": recs[0]["received_at"],
    }
    assert recs[1]["payload"] == {}
    assert recs[2]["panel"] == "other" and recs[2]["payload"] == {}


def test_ingest_accepts_text_plain_beacon_body(client, tmp_data_dir):
    """navigator.sendBeacon sends a text/plain Blob; body must still be parsed."""
    body = json.dumps({"session_id": "s2", "project_id": None,
                       "logs": [{"ts": 1, "event": "letter_edit", "panel": "letter", "payload": {}}]})
    r = client.post("/api/logs/interactions", content=body, headers={"Content-Type": "text/plain"})
    assert r.status_code == 200 and r.json()["accepted"] == 1
    assert (tmp_data_dir / "workspaces" / "default" / "logs" / "s2.jsonl").exists()


def test_ingest_appends_across_batches(client, tmp_data_dir):
    for i in range(3):
        client.post("/api/logs/interactions", json={"session_id": "s3", "logs": [{"ts": i, "event": "pdf_scroll", "panel": "pdf"}]})
    assert [r["ts"] for r in _read(tmp_data_dir / "workspaces" / "default" / "logs" / "s3.jsonl")] == [0, 1, 2]


def test_ingest_validates_shape(client):
    assert client.post("/api/logs/interactions", content=b"not json").status_code == 400
    assert client.post("/api/logs/interactions", json={"session_id": "../x", "logs": []}).status_code == 400
    assert client.post("/api/logs/interactions", json={"session_id": "ok", "logs": "nope"}).status_code == 400
    assert client.post("/api/logs/interactions", json={"session_id": "ok"}).json()["accepted"] == 0


def test_logs_are_workspace_scoped(client, tmp_data_dir, monkeypatch):
    from app.core import workspace as ws
    from app.core.config import settings

    monkeypatch.setattr(settings, "auth_disabled", False)
    tok = ws.mint_token("P01")["token"]
    r = client.post("/api/logs/interactions", json={"session_id": "s4", "logs": [{"ts": 1, "event": "node_delete", "panel": "tree"}]},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert (tmp_data_dir / "workspaces" / "P01" / "logs" / "s4.jsonl").exists()
    assert client.post("/api/logs/interactions", json={"session_id": "s4", "logs": []}).status_code == 401
