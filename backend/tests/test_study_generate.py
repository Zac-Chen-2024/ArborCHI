"""
Generation, the initial snapshot, and the answer-key boundary
(BE-07, BE-08, 红线 #1/#3/#5).

Two things here are worth more than the rest of the file:

* `test_snapshot_exists_before_the_participant_can_edit` -- 红线 #1. The initial
  snapshot is the only baseline for "what did the human change", and it is the
  one artefact in the system that cannot be reconstructed after the fact.

* `test_nothing_in_any_participant_response_carries_the_answer_key` -- 红线 #5.
  Written as a sweep over every participant-reachable endpoint rather than as
  three separate assertions, so a NEW endpoint that leaks is caught by a test
  nobody remembered to update.
"""
import json

import pytest

from app.core import materials, study, study_snapshots, workspace
from app.services import study_generator


@pytest.fixture(autouse=True)
def _fresh_bundle_cache():
    materials.load_bundle.cache_clear()
    yield
    materials.load_bundle.cache_clear()


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




@pytest.fixture
def participant(auth_client, moderator, walk_to):
    out = auth_client.post("/api/study/sessions", headers=_hdr(moderator), json={
        "condition": "c", "participant_code": "P21", "lang": "en"}).json()
    auth_client.post("/api/study/start", headers=_hdr(out["join_token"]))
    walk_to(auth_client, moderator, out, "verification")
    return out


def _unchanged_states():
    """Every node exactly as the frozen tree has it, all accepted."""
    return {
        nid: {"title": n["title"], "parent_id": n["parent_id"],
              "snippet_ids": list(n["snippet_ids"]), "state": "accepted"}
        for nid, n in materials.frozen_nodes().items()
    }


# ---------------------------------------------------------------------------
# 红线 #1 -- the baseline exists before it can be spoiled
# ---------------------------------------------------------------------------

def test_snapshot_exists_before_the_participant_can_edit(auth_client, participant):
    """The response cannot arrive before the snapshot is on disk, so by the
    time the participant has anything to type into, the baseline is written."""
    r = auth_client.post("/api/study/generate", headers=_hdr(participant["join_token"]),
                         json={"node_states": _unchanged_states()})
    assert r.status_code == 200, r.text

    session = study.load_session(participant["session_id"])
    snap = study_snapshots.read_snapshot(session, "initial")
    assert snap is not None
    assert snap["text"] == r.json()["text"]
    assert snap["sha256"] == study_snapshots.sha256(r.json()["text"])
    assert session["initial_snapshot_hash"] == snap["sha256"]

    # And it is logged, so integrity can check for its presence.
    snaps = [e for e in _events(participant["session_id"])
             if e["event"] == "draft_snapshot"]
    assert len(snaps) == 1
    assert snaps[0]["payload"]["snapshot_id"] == "initial"
    assert snaps[0]["payload"]["trigger"] == "generation"


def test_snapshot_carries_per_sentence_provenance(auth_client, participant):
    """Every question about verification behaviour is asked per sentence, so the
    baseline has to be per sentence too."""
    auth_client.post("/api/study/generate", headers=_hdr(participant["join_token"]),
                     json={"node_states": _unchanged_states()})

    session = study.load_session(participant["session_id"])
    snap = study_snapshots.read_snapshot(session, "initial")
    for s in snap["sentences"]:
        assert s["sent_id"]
        assert s["subargument_id"]
        assert s["argument_id"]
        assert isinstance(s["position"], int)
        assert s["source"] in ("frozen", "live")
        assert "snippet_ids" in s and "exhibit_refs" in s
        # Present in the STORED snapshot -- this is where the probe reads it.
        assert "planted_id" in s

    planted = [s for s in snap["sentences"] if s["planted_id"]]
    assert len(planted) == 3      # the placeholder bundle plants three


# ---------------------------------------------------------------------------
# frozen vs live -- decided by the server (BE-08)
# ---------------------------------------------------------------------------

def test_untouched_nodes_read_frozen_text():
    built = study_generator.assemble(_unchanged_states())
    assert built["stats"]["nodes_changed"] == 0
    assert built["stats"]["live"] == 0
    assert all(s["source"] == "frozen" for s in built["sentences"])


def test_accepting_a_node_is_not_a_change():
    """The participant endorsed what was there; the frozen text still describes
    it. Only renaming, re-parenting or changing the evidence is a change."""
    states = _unchanged_states()
    for s in states.values():
        s["state"] = "accepted"
    assert study_generator.assemble(states)["stats"]["nodes_changed"] == 0


@pytest.mark.parametrize("mutate,reason", [
    (lambda s: s.update(title="Something else entirely"), "renamed"),
    (lambda s: s.update(parent_id="a1"), "reparented"),
    (lambda s: s.update(snippet_ids=["c1"]), "evidence_changed"),
])
def test_the_server_detects_each_kind_of_change(mutate, reason):
    frozen = materials.frozen_nodes()
    states = _unchanged_states()
    mutate(states["s4"])
    changed, got = study_generator.node_is_changed("s4", states["s4"], frozen)
    assert changed is True
    assert got == reason


def test_a_new_node_is_always_live():
    frozen = materials.frozen_nodes()
    changed, reason = study_generator.node_is_changed(
        "s99", {"title": "Invented", "snippet_ids": []}, frozen)
    assert (changed, reason) == (True, "new_node")


def test_changed_nodes_are_generated_live_and_stamped():
    states = _unchanged_states()
    states["s4"]["title"] = "Budget and headcount authority"

    def fake_live(node_id, submitted):
        return [{"sent_id": f"{node_id}_live_0",
                 "text": f"Rewritten text for {submitted['title']}.",
                 "snippet_ids": submitted["snippet_ids"],
                 "exhibit_refs": [], "sentence_type": "claim"}]

    built = study_generator.assemble(states, generate_live=fake_live)
    by_node = {}
    for s in built["sentences"]:
        by_node.setdefault(s["subargument_id"], []).append(s)

    assert all(s["source"] == "live" for s in by_node["s4"])
    assert all(s["change_reason"] == "renamed" for s in by_node["s4"])
    # Every OTHER node stays frozen -- BE-08's acceptance criterion exactly.
    for node_id, sentences in by_node.items():
        if node_id != "s4":
            assert all(s["source"] == "frozen" for s in sentences)
    # The bundle has 10 pre-generated sentences across 6 nodes; s4 holds one,
    # so regenerating it leaves 9 frozen.
    assert built["stats"] == {"frozen": 9, "live": 1, "nodes_changed": 1, "nodes_total": 6}


def test_live_sentences_never_claim_a_planted_id():
    """A planted error lives in a specific pre-written sentence. Regenerated
    prose is new text; claiming it still carries the plant would corrupt the
    probe's ground truth."""
    states = _unchanged_states()
    states["s1"]["title"] = "Renamed"

    def fake_live(node_id, submitted):
        return [{"sent_id": "x", "text": "New.", "snippet_ids": [],
                 "exhibit_refs": [], "sentence_type": "claim",
                 "planted_id": "p1"}]      # a generator trying to claim one

    built = study_generator.assemble(states, generate_live=fake_live)
    assert all(s["planted_id"] is None
               for s in built["sentences"] if s["source"] == "live")


def test_a_changed_node_without_a_generator_fails_loudly():
    """Silently falling back to frozen text would look like success while
    falsifying `source` -- the independent variable."""
    states = _unchanged_states()
    states["s2"]["title"] = "Changed"
    with pytest.raises(study_generator.GenerationError):
        study_generator.assemble(states, generate_live=None)


def test_generate_returns_503_when_live_generation_is_unavailable(auth_client, participant):
    r = auth_client.post("/api/study/generate", headers=_hdr(participant["join_token"]),
                         json={"node_states": {**_unchanged_states(),
                                               "s2": {"title": "Changed", "parent_id": "a1",
                                                      "snippet_ids": ["c3"], "state": "edited"}}})
    assert r.status_code == 503


def test_generating_twice_does_not_poison_the_cached_bundle():
    """Regeneration is a real flow (the participant edits the tree and asks
    again), and the sentence dicts are stamped in place -- so they must be
    copies of the bundle, not the bundle."""
    first = study_generator.assemble(_unchanged_states())
    second = study_generator.assemble(_unchanged_states())
    assert [s["position"] for s in first["sentences"]] ==            [s["position"] for s in second["sentences"]]

    # And the bundle on the way out still looks like the file on disk.
    raw = materials.load_bundle()["pregen"]["s1"]["sentences"][0]
    assert "position" not in raw
    assert "subargument_id" not in raw


def test_removed_nodes_contribute_no_text():
    states = _unchanged_states()
    states["s6"]["state"] = "removed"
    built = study_generator.assemble(states)
    assert all(s["subargument_id"] != "s6" for s in built["sentences"])
    assert built["stats"]["nodes_total"] == 5


# ---------------------------------------------------------------------------
# 红线 #5 -- the answer key never leaves the server
# ---------------------------------------------------------------------------

LEAK_WORDS = ("planted", "distractor", "ground_truth", "answer_key")


def _leaks(blob: str):
    return [w for w in LEAK_WORDS if w in blob.lower()]


def test_nothing_in_any_participant_response_carries_the_answer_key(auth_client, participant):
    """A sweep, not three assertions: a new participant-facing endpoint that
    leaks should fail a test nobody remembered to update."""
    token = _hdr(participant["join_token"])
    responses = {
        "state": auth_client.get("/api/study/state", headers=token),
        "whoami": auth_client.get("/api/study/whoami", headers=token),
        "material": auth_client.get("/api/study/material", headers=token),
        "generate": auth_client.post("/api/study/generate", headers=token,
                                     json={"node_states": _unchanged_states()}),
    }
    for name, r in responses.items():
        assert r.status_code == 200, f"{name}: {r.status_code}"
        found = _leaks(r.text)
        assert found == [], f"{name} response leaks {found}"


def test_the_bundle_itself_does_contain_the_answer_key():
    """The negative test above would pass trivially if the data were simply
    absent. It is not: the server has it, and chooses not to send it."""
    bundle = materials.load_bundle()
    raw = json.dumps(bundle, ensure_ascii=False)
    assert "planted_id" in raw
    assert "distractor" in raw
    assert len(bundle["planted"]["items"]) == 3


def test_public_tree_strips_the_distractor_flag():
    public = materials.public_tree()
    frozen = materials.frozen_nodes()
    assert any(n["distractor"] for n in frozen.values())     # it is in the bundle
    for arg in public["arguments"]:
        for sub in arg["subs"]:
            assert "distractor" not in sub                   # and not in the response


def test_public_sentence_keeps_source_but_drops_planted_id():
    """`source` is data the analysis needs and the UI must ignore (红线 #3);
    `planted_id` is the probe's answer key."""
    s = {"sent_id": "x", "text": "t", "source": "frozen", "planted_id": "p1"}
    out = materials.public_sentence(s)
    assert out["source"] == "frozen"
    assert "planted_id" not in out


# ---------------------------------------------------------------------------
# Bundle integrity
# ---------------------------------------------------------------------------

def test_manifest_hash_covers_every_file_not_just_the_manifest(tmp_path, monkeypatch):
    """An edited pregen sentence changes the letter a participant reads, so it
    must change the hash their log carries."""
    import shutil

    src = materials.bundle_dir("case_v1")
    dst = tmp_path / "study_materials" / "case_v1"
    shutil.copytree(src, dst)
    monkeypatch.setattr(materials, "materials_root", lambda: tmp_path / "study_materials")

    materials.load_bundle.cache_clear()
    before = materials.manifest_hash("case_v1")

    pregen = dst / "pregen" / "s1.json"
    data = json.loads(pregen.read_text(encoding="utf-8"))
    data["sentences"][0]["text"] += " One more clause."
    pregen.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    materials.load_bundle.cache_clear()
    assert materials.manifest_hash("case_v1") != before


def test_session_records_which_material_it_ran_on(auth_client, participant):
    session = study.load_session(participant["session_id"])
    assert session["material_manifest_hash"] == materials.manifest_hash("case_v1")
    assert session["tree_variant_id"] == materials.tree_variant_id("case_v1")
    for record in _events(participant["session_id"]):
        assert record["material_manifest_hash"] == session["material_manifest_hash"]


def test_placeholder_bundle_is_marked_as_such():
    """Any run against invented material must be identifiable in the data."""
    assert materials.load_bundle()["manifest"]["placeholder"] is True


def test_bbox_is_normalised_not_pixels():
    """红线 #8. The OCR source gives pixels and no page dimensions, so the
    bundle must carry the normalised form -- there is nothing to convert with
    at render time."""
    snippets = materials.public_snippets()
    assert snippets["bbox_space"] == 1000
    for s in snippets["snippets"].values():
        assert len(s["bbox"]) == 4
        assert all(0 <= v <= 1000 for v in s["bbox"]), s
