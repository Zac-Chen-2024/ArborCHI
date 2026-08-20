"""
Prompt registry (M8). Prompts are versioned files under backend/prompts/.

The hash snapshot enforces the workflow rule "prompt wording changes are a
deliberate, separate `prompt:` commit": editing a prompt body without bumping
its version and refreshing tests/fixtures/prompt_hashes.json fails here.
"""
import hashlib
import json
from pathlib import Path

import pytest

from app.core import prompt_loader as pl

FIXTURE = Path(__file__).parent / "fixtures" / "prompt_hashes.json"


def test_all_prompts_validate():
    prompts = pl.validate_all()
    assert len(prompts) >= 100
    ids = {p.id for p in prompts}
    # a few load-bearing ones
    for must in ["extractor/unified_extraction_system_prompt", "organizer/organize_user_prompt",
                 "writer/step1_generate_subargument_body_user_prompt", "writer/eb1a_base_system_prompt",
                 "subdivider/subdivide_user_prompt", "recommender/infer_argument_title_user_prompt"]:
        assert must in ids, must


def test_prompt_bodies_match_snapshot():
    """Refresh with: python -c 'from tests.test_prompts import refresh; refresh()' in a prompt: commit."""
    snap = json.loads(FIXTURE.read_text())
    current = _current_hashes()
    changed = sorted(k for k in current if k in snap and snap[k] != current[k])
    added = sorted(set(current) - set(snap))
    removed = sorted(set(snap) - set(current))
    assert not changed, f"prompt bodies changed without a version bump: {changed}"
    assert not removed, f"prompts removed: {removed}"
    assert not added, f"new prompts not in snapshot (refresh the fixture): {added}"


def _current_hashes():
    current = {f"{p.id}@v{p.version}": hashlib.sha256(p.body.encode()).hexdigest() for p in pl.list_prompts()}
    # JSON data assets (structured prompt content) are snapshotted the same way
    current.update({f"{i}@v{v}": hashlib.sha256(t.encode()).hexdigest() for i, v, t in pl.list_data_assets()})
    return current


def refresh():  # pragma: no cover - maintenance helper
    FIXTURE.write_text(json.dumps(_current_hashes(), indent=2, sort_keys=True))


def test_render_returns_str_subclass_with_metadata():
    r = pl.render("recommender/infer_argument_title_user_prompt",
                  standard_key="awards", current_title_or_none="(none)", child_info="- a")
    assert isinstance(r, str)
    assert "awards" in r
    assert r.prompt_id == "recommender/infer_argument_title_user_prompt"
    assert r.version == 1 and len(r.hash) == 16
    # json-serialisable like a plain str
    assert json.dumps({"content": r}).startswith('{"content": ')


def test_render_missing_variable_is_clear():
    with pytest.raises(pl.PromptError, match="missing variable"):
        pl.render("recommender/infer_argument_title_user_prompt", standard_key="awards")


def test_raw_prompt_cannot_be_rendered_and_body_works():
    body = pl.body("writer/eb1a_base_system_prompt")
    assert body.startswith("You are a Senior Immigration Attorney")
    with pytest.raises(pl.PromptError, match="format: raw"):
        pl.render("writer/eb1a_base_system_prompt")


def test_unknown_prompt():
    with pytest.raises(pl.PromptError, match="not found"):
        pl.load("nope/nothing")


def test_version_selection(tmp_path, monkeypatch):
    d = tmp_path / "mod"
    d.mkdir()
    (d / "x@v1.md").write_text("---\nid: mod/x\nversion: 1\nvariables: [a]\n---\nv1 {a}", encoding="utf-8")
    (d / "x@v2.md").write_text("---\nid: mod/x\nversion: 2\nvariables: [a]\n---\nv2 {a}", encoding="utf-8")
    monkeypatch.setattr(pl, "PROMPTS_DIR", tmp_path)
    pl.load.cache_clear()
    try:
        assert pl.render("mod/x", a=1) == "v2 1"
        assert pl.render("mod/x", version=1, a=1) == "v1 1"
        assert pl.load("mod/x").version == 2
    finally:
        pl.load.cache_clear()
