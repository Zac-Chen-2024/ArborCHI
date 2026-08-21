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


def test_regenerating_does_not_overwrite_the_baseline(auth_client, participant, monkeypatch):
    """红线 #1 is about the FIRST draft, and regenerating is normal use.

    `initial.json` used to be rewritten by every /generate. Nothing looked
    wrong -- the ordering inside each request was still snapshot-before-return,
    each generation still logged its own sha256, and the integrity check still
    reported "initial and final present, hashes match". But the file every
    edit measure is computed against had become the last draft the participant
    asked for, and entering the verification phase regenerates automatically,
    so the baseline was routinely gone before the phase that needs it began.
    """
    # Injected, so this test never reaches a provider: a real call would make
    # the assertion depend on the network and on a key being present, and on CI
    # (no key) the second generate would 503 and the test would pass having
    # checked nothing.
    async def fake_live(node_id, submitted, **_kwargs):
        return [{"sent_id": f"{node_id}_0",
                 "text": f"Rewritten text for {submitted['title']}. [Exhibit B1, p.4]",
                 "snippet_ids": list(submitted.get("snippet_ids") or []),
                 "exhibit_refs": [{"exhibit": "B1", "page": 4}],
                 "sentence_type": "unclassified"}]

    monkeypatch.setattr(study_generator, "generate_live_sentences", fake_live)

    hdr = _hdr(participant["join_token"])
    first = auth_client.post("/api/study/generate", headers=hdr,
                             json={"node_states": _unchanged_states()})
    assert first.status_code == 200, first.text

    changed = _unchanged_states()
    changed["s4"]["title"] = "Budget and hiring authority"
    second = auth_client.post("/api/study/generate", headers=hdr, json={
        "node_states": changed})
    assert second.status_code == 200, second.text
    assert second.json()["text"] != first.json()["text"]

    session = study.load_session(participant["session_id"])
    baseline = study_snapshots.read_snapshot(session, "initial")
    assert baseline["text"] == first.json()["text"]
    assert session["initial_snapshot_hash"] == baseline["sha256"]

    # The later draft is kept too -- under its own id, so nothing is lost.
    later = study_snapshots.read_snapshot(session, "draft_1")
    assert later is not None
    assert later["text"] == second.json()["text"]


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
    registry = materials.load_bundle()["planted"]["items"]
    assert len(planted) == len(registry)
    # At most one plant per node: two in the same paragraph would cue each
    # other (docs/植入错误设计 distribution rules).
    nodes = [s["subargument_id"] for s in planted]
    assert len(nodes) == len(set(nodes))
    # Several distinct kinds -- a probe made only of "wrong exhibit number"
    # would measure reference-checking rather than evidence evaluation.
    assert len({i["kind"] for i in registry}) >= 3


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


def test_generate_returns_503_when_live_generation_is_unavailable(
    auth_client, participant, monkeypatch
):
    """A provider that cannot answer must surface as 503, not as frozen text.

    The failure is injected rather than inferred from the environment. This
    test used to rely on the route's generator being a stub that returned
    None, which meant it passed for a reason that disappeared the moment live
    generation was wired up -- and would have passed on CI (no API key) while
    failing on any machine that had one. What it has to prove is the routing of
    a failure, so the failure is made to happen.
    """
    async def unavailable(*_args, **_kwargs):
        raise study_generator.GenerationError("provider unavailable")

    monkeypatch.setattr(study_generator, "generate_live_sentences", unavailable)

    r = auth_client.post("/api/study/generate", headers=_hdr(participant["join_token"]),
                         json={"node_states": {**_unchanged_states(),
                                               "s2": {"title": "Changed", "parent_id": "a1",
                                                      "snippet_ids": ["c3"], "state": "edited"}}})
    assert r.status_code == 503
    assert "not available" in r.json()["detail"]


def test_generate_refuses_an_empty_tree_rather_than_blanking_the_baseline(
    auth_client, participant
):
    """`node_states: {}` assembles an empty letter, and writing that over
    `initial.json` destroys the only baseline the analysis has -- with a 200 and
    nothing in the log to say anything went wrong."""
    r = auth_client.post("/api/study/generate", headers=_hdr(participant["join_token"]),
                         json={"node_states": {}})
    assert r.status_code == 400


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
    assert len(bundle["planted"]["items"]) > 0


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


# ---------------------------------------------------------------------------
# The working tree survives a reload
# ---------------------------------------------------------------------------

def test_the_working_tree_round_trips(auth_client, participant):
    """Without this the organisation phase was lost on any reload.

    The tree lived only in the browser: a refresh put every sub-argument back
    to `proposed` and undid every rename and move, and the next generation ran
    against the machine's original proposal. Nothing surfaced -- the letter
    still rendered, the phase still advanced, the log still held every
    `tree_op` -- so the session looked complete and would have been analysed as
    one, built on a structure the participant had not organised.
    """
    hdr = _hdr(participant["join_token"])
    assert auth_client.get("/api/study/tree", headers=hdr).json()["tree"] is None

    tree = [{"id": "a1", "title": "The organisation has a distinguished reputation",
             "subs": [{"id": "s4", "title": "Budget and hiring authority",
                       "state": "edited", "renamed": True, "snippet_ids": ["c5"]}]}]
    saved = auth_client.put("/api/study/tree", headers=hdr,
                            json={"tree": tree, "material_id": "case_v1"})
    assert saved.status_code == 200

    got = auth_client.get("/api/study/tree", headers=hdr).json()
    # Verbatim: a restored session has to be the interrupted one, not a
    # reconstruction that has to be trusted.
    assert got["tree"] == tree
    assert got["material_id"] == "case_v1"
    assert got["saved_at"]


def test_a_practice_tree_is_not_restored_over_the_real_material(auth_client, participant):
    """The practice phase serves a different bundle. A practice tree handed back
    for the real case would be a wrong tree that looks like a right one."""
    hdr = _hdr(participant["join_token"])
    auth_client.put("/api/study/tree", headers=hdr, json={
        "tree": [{"id": "pa1", "subs": []}], "material_id": "practice_v1"})

    got = auth_client.get("/api/study/tree", headers=hdr).json()
    assert got["tree"] is None


def test_the_tree_is_frozen_once_the_draft_is_handed_in(auth_client, participant):
    hdr = _hdr(participant["join_token"])
    auth_client.post("/api/study/generate", headers=hdr,
                     json={"node_states": _unchanged_states()})
    session = study.load_session(participant["session_id"])
    text = study_snapshots.read_snapshot(session, "initial")["text"]
    auth_client.post("/api/study/submit", headers=hdr, json={
        "text": text, "final_text_hash": study_snapshots.sha256(text)})

    r = auth_client.put("/api/study/tree", headers=hdr,
                        json={"tree": [], "material_id": "case_v1"})
    assert r.status_code == 409
