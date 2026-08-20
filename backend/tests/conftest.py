"""
Shared pytest fixtures.

`tmp_data_dir` redirects the storage layer to a throw-away directory so that
tests never touch backend/data/. Since M4 (path consolidation) every module
resolves paths through storage.data_dir()/projects_dir()/project_path(), which
read settings.data_dir -- so patching that one setting is enough.
"""
import json

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Fresh data root; auth disabled so unauthenticated requests hit the
    'default' workspace. Tests that exercise auth flip settings.auth_disabled."""
    from app.core.config import settings

    data = tmp_path / "data"
    (data / "workspaces" / "default" / "projects").mkdir(parents=True)
    monkeypatch.setattr(settings, "data_dir", str(data))
    monkeypatch.setattr(settings, "auth_disabled", True)
    return data


@pytest.fixture
def projects_root(tmp_data_dir):
    """projects/ directory of the default workspace."""
    return tmp_data_dir / "workspaces" / "default" / "projects"


@pytest.fixture
def client(tmp_data_dir):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def victim_project(projects_root):
    """A minimal project on disk; returns its id."""
    pdir = projects_root / "victim"
    pdir.mkdir()
    (pdir / "meta.json").write_text(
        json.dumps({"id": "victim", "name": "v", "createdAt": "2026-01-01T00:00:00"}),
        encoding="utf-8",
    )
    return "victim"


@pytest.fixture(autouse=True)
def _skip_llm_config_check(monkeypatch):
    """Tests never call an LLM; do not fail startup on missing keys."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "skip_llm_config_check", True)
