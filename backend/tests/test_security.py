"""
M0 security regression tests (Doc/02).

1. Path-parameter traversal must be rejected with 404 and must never touch
   anything outside the project directory.
2. 500 responses must not leak exception text (paths, upstream bodies).
3. CORS must be an allow-list.
"""
import pytest


@pytest.mark.parametrize("bad_id", ["%2e%2e", "a.b", "x%20y", "..%2f..%2fetc", "*", "a%00b"])
def test_traversal_ids_rejected_on_delete(client, tmp_data_dir, projects_root, victim_project, bad_id):
    (tmp_data_dir / "canary").mkdir()
    r = client.delete(f"/api/projects/{bad_id}")
    assert r.status_code == 404
    # nothing outside projects/ was touched
    assert (tmp_data_dir / "canary").exists()
    assert (projects_root / "victim").exists()


def test_dotdot_project_id_does_not_wipe_data_dir(client, tmp_data_dir, projects_root, victim_project):
    """Regression for Doc/00 R1: DELETE /api/projects/%2e%2e used to rmtree(DATA_DIR)."""
    (tmp_data_dir / "style_templates").mkdir()
    r = client.delete("/api/projects/%2e%2e")
    assert r.status_code == 404
    assert sorted(p.name for p in tmp_data_dir.iterdir()) == ["style_templates", "workspaces"]
    assert (projects_root / "victim").exists()


def test_standard_key_glob_rejected(client, victim_project):
    r = client.delete(f"/api/arguments/{victim_project}/standards/*")
    assert r.status_code == 404


def test_storage_get_project_dir_rejects_unsafe_ids(tmp_data_dir):
    from app.services import storage

    for bad in ["..", "a/b", "a\\b", ".", "", "a b"]:
        with pytest.raises(ValueError):
            storage.get_project_dir(bad)
    ok = storage.get_project_dir("project-123")
    assert ok.parent == tmp_data_dir / "workspaces" / "default" / "projects"


def test_500_does_not_leak_exception_text(client, projects_root, victim_project):
    # corrupt meta.json -> json.JSONDecodeError inside the handler
    (projects_root / "victim" / "meta.json").write_text("{not json", encoding="utf-8")
    r = client.get(f"/api/projects/{victim_project}")
    assert r.status_code == 500
    body = r.json()
    assert body["error"] == "Internal server error"
    assert "error_id" in body
    assert "/" not in r.text and "\\" not in r.text
    assert "JSONDecodeError" not in r.text


def test_cors_allowlist(client):
    evil = client.options(
        "/api/projects",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert evil.headers.get("access-control-allow-origin") is None
    ok = client.options(
        "/api/projects",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"


async def test_missing_provider_key_is_a_400_not_500(client, monkeypatch):
    """A request that picks a provider without a configured key gets a clear 400."""
    import pytest

    from app.core.config import settings
    from app.core.errors import ConfigError
    from app.main import app
    from app.services.llm_client import call_llm_text

    monkeypatch.setattr(settings, "openai_api_key", "")

    # 1. the client raises ConfigError before any network call
    with pytest.raises(ConfigError):
        await call_llm_text("hi", provider="openai")

    # 2. the app maps ConfigError -> 400 with the message intact
    async def _boom():
        raise ConfigError("Openai API key not configured. Set OPENAI_API_KEY in .env")
    app.add_api_route("/api/_test/config-error", _boom, methods=["GET"])
    r = client.get("/api/_test/config-error")
    assert r.status_code == 400, r.text
    assert "OPENAI_API_KEY" in r.json()["error"]
