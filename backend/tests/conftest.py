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


# ---------------------------------------------------------------------------
# Study helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def walk_to():
    """Advance a session to `phase`, doing what a real participant would.

    In particular it clears the practice gates before leaving the practice
    phase, because the server now refuses to advance past them (FS-06). Every
    test that needs a session further along goes through here, so the day
    another gate is added there is one place to teach.
    """
    from app.core import study

    def _walk(client, moderator_token, session, phase):
        sid = session["session_id"]
        headers = {"Authorization": f"Bearer {moderator_token}"}
        participant = {"Authorization": f"Bearer {session['join_token']}"}

        for _ in range(len(study.PHASES[session["condition"]]) + 2):
            current = study.load_session(sid)["phase"]
            if current == phase:
                return
            if current == "practice":
                from app.routers.study import PRACTICE_GATES
                for gate in PRACTICE_GATES.get(session["condition"], ()):
                    client.post("/api/study/checkpoint", headers=participant,
                                json={"gate": gate})
            r = client.post("/api/study/advance", headers=headers,
                            json={"session_id": sid})
            assert r.status_code == 200, r.text
        raise AssertionError(f"never reached {phase}")

    return _walk


@pytest.fixture(autouse=True)
def _no_real_llm_calls(monkeypatch):
    """The study's live generator never reaches a provider by default.

    Once backend/.env carries a real key, a study test that forgets to inject a
    fake generator quietly starts making paid, non-deterministic calls -- and
    the same test on CI, where there is no key, takes a different branch and
    passes without checking anything. Both failures are silent, which is why
    this is a fixture rather than a rule. It cost one test exactly this way:
    it ran green in 8 seconds locally and would have asserted nothing on CI.

    A test that wants live generation to succeed replaces this in its own body,
    which applies after the fixture. The provider layer itself is tested in
    test_llm_client.py through respx, below this seam and unaffected.
    """
    from app.services import study_generator

    async def refuse(node_id, *_args, **_kwargs):
        raise study_generator.GenerationError(
            f"test tried to generate {node_id} for real -- inject a fake "
            f"generator (see test_study_generate.py)"
        )

    monkeypatch.setattr(study_generator, "generate_live_sentences", refuse)
