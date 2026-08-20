"""
Workspace isolation (M5). One bearer token == one workspace.
"""
import json

import pytest

from app.core import workspace as ws
from app.core.config import settings


@pytest.fixture
def two_workspaces(tmp_data_dir, monkeypatch):
    """Auth ON, tokens for workspaces A and B, one project in each."""
    monkeypatch.setattr(settings, "auth_disabled", False)
    a = ws.mint_token("Participant A", "wsA")
    b = ws.mint_token("Participant B", "wsB")
    for w in ("wsA", "wsB"):
        pdir = tmp_data_dir / "workspaces" / w / "projects" / f"proj-{w}"
        pdir.mkdir(parents=True)
        (pdir / "meta.json").write_text(
            json.dumps({"id": f"proj-{w}", "name": w, "createdAt": "2026-01-01T00:00:00"}), encoding="utf-8"
        )
    return {"A": a["token"], "B": b["token"]}


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_no_token_is_401_when_auth_enabled(client, two_workspaces):
    r = client.get("/api/projects")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"
    assert r.json()["error"] == "Unauthorized"


def test_invalid_token_is_401(client, two_workspaces):
    assert client.get("/api/projects", headers=_auth("nope")).status_code == 401
    assert client.get("/api/projects?token=nope").status_code == 401


def test_public_paths_do_not_need_token(client, two_workspaces):
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200


def test_each_token_sees_only_its_own_projects(client, two_workspaces):
    a = client.get("/api/projects", headers=_auth(two_workspaces["A"])).json()
    b = client.get("/api/projects", headers=_auth(two_workspaces["B"])).json()
    assert [p["id"] for p in a] == ["proj-wsA"]
    assert [p["id"] for p in b] == ["proj-wsB"]


def test_cross_workspace_access_is_404_not_403(client, two_workspaces):
    """A's token asking for B's project id must look exactly like 'does not exist'."""
    r = client.get("/api/projects/proj-wsB", headers=_auth(two_workspaces["A"]))
    assert r.status_code == 404
    r = client.delete("/api/projects/proj-wsB", headers=_auth(two_workspaces["A"]))
    assert r.status_code == 404
    # ...and B's project is still there
    r = client.get("/api/projects/proj-wsB", headers=_auth(two_workspaces["B"]))
    assert r.status_code == 200


def test_query_param_token_works_for_direct_urls(client, two_workspaces):
    r = client.get(f"/api/projects/proj-wsA?token={two_workspaces['A']}")
    assert r.status_code == 200


def test_created_project_lands_in_the_token_workspace(client, tmp_data_dir, two_workspaces):
    r = client.post("/api/projects", json={"name": "new", "projectType": "EB-1A"}, headers=_auth(two_workspaces["B"]))
    assert r.status_code == 200
    pid = r.json()["id"]
    assert (tmp_data_dir / "workspaces" / "wsB" / "projects" / pid / "meta.json").exists()
    assert not (tmp_data_dir / "workspaces" / "wsA" / "projects" / pid).exists()


def test_auth_disabled_falls_back_to_default_but_honours_valid_token(client, two_workspaces, monkeypatch, tmp_data_dir):
    monkeypatch.setattr(settings, "auth_disabled", True)
    # unauthenticated -> default workspace (empty)
    assert client.get("/api/projects").json() == []
    # valid token still selects its workspace
    a = client.get("/api/projects", headers=_auth(two_workspaces["A"])).json()
    assert [p["id"] for p in a] == ["proj-wsA"]
    # invalid token is still rejected (do not silently downgrade)
    assert client.get("/api/projects", headers=_auth("bad")).status_code == 401


def test_mint_token_writes_table_and_creates_dir(tmp_data_dir):
    entry = ws.mint_token("P07")
    table = ws.load_token_table()
    assert table[entry["token"]]["workspace_id"] == "P07"
    assert (tmp_data_dir / "workspaces" / "P07" / "projects").is_dir()
    assert ws.lookup_token(entry["token"]) == "P07"
    assert ws.lookup_token("") is None


def test_context_is_reset_between_requests(client, two_workspaces):
    """After a request for A, an unauthenticated request must not leak A's context."""
    client.get("/api/projects", headers=_auth(two_workspaces["A"]))
    assert client.get("/api/projects").status_code == 401
    assert ws.current_workspace() == "default"
