"""
Probe sampling (BE-13) against the pre-registered algorithm (PR-2).

These tests are the executable form of the pre-registration. If one of them has
to change, the rule changed, and docs/预注册_pre-registration.md needs an entry
saying so and why -- that is the point of writing the rule down before seeing
data.
"""
import hashlib
import json

import pytest

from app.core import alignment, probe, study, study_snapshots, workspace

CFG = {"target_items": 14, "min_items": 12, "max_items": 15, "max_planted_ratio": 0.6}


def _baseline(n_planted=3, n_total=20, subs=("s1", "s2", "s3", "s4")):
    """A synthetic initial snapshot: `n_total` cited sentences spread over
    `subs`, the first `n_planted` of them planted."""
    out = []
    for i in range(n_total):
        out.append({
            "sent_id": f"b{i}",
            "text": f"Sentence number {i} makes a claim about the record. "
                    f"[Exhibit B1, p.{i % 6 + 1}]",
            "planted_id": f"p{i}" if i < n_planted else None,
            "subargument_id": subs[i % len(subs)],
            "source": "frozen",
        })
    return out


def _final_text(baseline):
    return " ".join(s["text"] for s in baseline)


def _draw(baseline, final=None, token="tok", cfg=None):
    return probe.select_items(
        final if final is not None else _final_text(baseline),
        baseline, token=token, session_id="sess", config=cfg or CFG,
    )


# ---------------------------------------------------------------------------
# Candidate pool
# ---------------------------------------------------------------------------

def test_pool_is_only_sentences_that_cite_something():
    """PR-2. A heading has nothing to ask about, and "does the cited evidence
    support this?" has no answer when nothing is cited."""
    baseline = _baseline(n_planted=0, n_total=3)
    text = ("① A heading with no citation\n\n" + _final_text(baseline)
            + " A trailing claim with no support at all.")
    pool = probe.build_candidate_pool(text, baseline)
    assert len(pool) == 3
    assert all("[Exhibit" in item["text"] for item in pool)


def test_pool_carries_provenance_through_an_edit():
    """The participant reworded a planted sentence; it must still be found."""
    baseline = _baseline(n_planted=1, n_total=4)
    edited = list(baseline)
    text = _final_text(edited).replace(
        "Sentence number 0 makes a claim about the record.",
        "Sentence number 0 makes a claim regarding the record.",
    )
    pool = probe.build_candidate_pool(text, baseline)
    planted = [i for i in pool if i["planted_id"]]
    assert len(planted) == 1
    assert planted[0]["planted_id"] == "p0"
    assert planted[0]["match"] in ("edited", "rewritten")


def test_a_deleted_planted_sentence_does_not_survive():
    """PR-2 says SURVIVING planted sentences are mandatory. One the
    participant cut is not surviving."""
    baseline = _baseline(n_planted=2, n_total=6)
    kept = [s for s in baseline if s["sent_id"] != "b0"]
    pool = probe.build_candidate_pool(_final_text(kept), baseline)
    assert {i["planted_id"] for i in pool if i["planted_id"]} == {"p1"}


# ---------------------------------------------------------------------------
# The draw
# ---------------------------------------------------------------------------

def test_target_size_and_all_surviving_planted_are_included():
    baseline = _baseline(n_planted=3, n_total=20)
    out = _draw(baseline)
    assert out["stats"]["items"] == 14
    assert {i["planted_id"] for i in out["items"] if i["planted_id"]} == {"p0", "p1", "p2"}


def test_underflow_takes_the_whole_pool():
    baseline = _baseline(n_planted=1, n_total=5)
    out = _draw(baseline)
    assert out["stats"]["rule"] == "underflow"
    assert out["stats"]["items"] == 5


def test_planted_overflow_draws_only_from_planted():
    baseline = _baseline(n_planted=18, n_total=30)
    out = _draw(baseline)
    assert out["stats"]["rule"] == "planted_overflow"
    assert out["stats"]["items"] == 15
    assert all(i["planted_id"] for i in out["items"])


def test_planted_ratio_is_capped_by_dropping_planted_not_adding_filler():
    """PR-2's ceiling. A participant who notices that nearly every item has a
    problem starts answering "is this a trick one" instead of the question we
    asked, and their hit rate rises for a reason unrelated to the interface."""
    baseline = _baseline(n_planted=12, n_total=30)
    out = _draw(baseline)
    assert out["stats"]["rule"] == "planted_ratio_capped"
    assert out["stats"]["items"] == 14
    assert out["stats"]["planted_ratio"] <= 0.6
    assert out["stats"]["dropped_planted_for_ratio"] > 0


def test_every_sub_argument_gets_at_least_one_item():
    """Stratification: a draw that landed entirely in one paragraph would tell
    us about the paragraph, not the participant."""
    baseline = _baseline(n_planted=0, n_total=24, subs=("s1", "s2", "s3", "s4", "s5", "s6"))
    out = _draw(baseline)
    represented = {i["subargument_id"] for i in out["items"]}
    assert represented == {"s1", "s2", "s3", "s4", "s5", "s6"}


def test_larger_strata_get_proportionally_more_items():
    baseline = []
    for i in range(18):
        baseline.append({
            "sent_id": f"b{i}",
            "text": f"Claim {i} about the record. [Exhibit B1, p.1]",
            "planted_id": None,
            # s1 holds 12 of 18, s2 holds 6.
            "subargument_id": "s1" if i < 12 else "s2",
            "source": "frozen",
        })
    out = _draw(baseline)
    counts = {}
    for item in out["items"]:
        counts[item["subargument_id"]] = counts.get(item["subargument_id"], 0) + 1
    assert counts["s1"] > counts["s2"]
    assert counts["s2"] >= 1


# ---------------------------------------------------------------------------
# Reproducibility (PR-2)
# ---------------------------------------------------------------------------

def test_the_same_token_always_draws_the_same_items():
    baseline = _baseline(n_planted=2, n_total=25)
    a = _draw(baseline, token="participant-07")
    b = _draw(baseline, token="participant-07")
    assert [i["sent_id"] for i in a["items"]] == [i["sent_id"] for i in b["items"]]


def test_different_tokens_draw_differently():
    baseline = _baseline(n_planted=0, n_total=25)
    a = _draw(baseline, token="participant-07")
    b = _draw(baseline, token="participant-08")
    assert [i["sent_id"] for i in a["items"]] != [i["sent_id"] for i in b["items"]]


def test_the_seed_is_derived_not_the_token_itself():
    """So it can be published in a pre-registration without publishing a
    credential."""
    seed = probe.seed_for("secret-token", "sess")
    assert isinstance(seed, int)
    assert str(seed) != "secret-token"
    assert "secret-token" not in hashlib.sha256(str(seed).encode()).hexdigest()


def test_presentation_order_interleaves_planted_and_filler():
    """PR-2: order is random and the two kinds are mixed, so the shape of the
    sample cannot be read off its ordering."""
    baseline = _baseline(n_planted=5, n_total=30)
    out = _draw(baseline)
    kinds = [bool(i["planted_id"]) for i in out["items"]]
    # Not all planted first, and not all last.
    assert kinds != sorted(kinds, reverse=True)
    assert kinds != sorted(kinds)


# ---------------------------------------------------------------------------
# The answer key never leaves the server
# ---------------------------------------------------------------------------

def test_public_item_drops_the_answer_and_the_hints():
    item = {
        "probe_index": 0, "sent_id": "b1", "text": "A claim. [Exhibit B1, p.2]",
        "planted_id": "p1", "similarity": 0.99, "source": "frozen",
        "subargument_id": "s1",
    }
    out = probe.public_item(item)
    assert out["text"] == item["text"]
    assert out["citations"] == ["[Exhibit B1, p.2]"]
    for leak in ("planted_id", "similarity", "source", "subargument_id"):
        assert leak not in out, leak


# ---------------------------------------------------------------------------
# Alignment thresholds (PR-3)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("a,b,expected", [
    ("The same sentence.", "The same sentence.", "same"),
    ("Dr. Li reported to the CTO.", "Dr. Li reported to the CTO!", "edited"),
    ("Dr. Li reported to the CTO and oversaw four teams.",
     "Dr. Li reported to the Chief Technology Officer.", "rewritten"),
    ("Revenue reached $320M.", "Entirely unrelated prose about penguins.", "new"),
])
def test_alignment_classes(a, b, expected):
    assert alignment.classify(alignment.similarity(a, b)) == expected


# ---------------------------------------------------------------------------
# Endpoint order guards (红线 #6)
# ---------------------------------------------------------------------------

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


@pytest.fixture
def submitted(auth_client, moderator, walk_to):
    """A participant who has generated, submitted, and is ready for the probe."""
    out = auth_client.post("/api/study/sessions", headers=_hdr(moderator), json={
        "condition": "c", "participant_code": "P31", "lang": "en"}).json()
    token = _hdr(out["join_token"])
    auth_client.post("/api/study/start", headers=token)
    walk_to(auth_client, moderator, out, "verification")

    from app.core import materials
    states = {
        nid: {"title": n["title"], "parent_id": n["parent_id"],
              "snippet_ids": list(n["snippet_ids"]), "state": "accepted"}
        for nid, n in materials.frozen_nodes().items()
    }
    gen = auth_client.post("/api/study/generate", headers=token,
                           json={"node_states": states}).json()
    auth_client.post("/api/study/submit", headers=token, json={
        "text": gen["text"],
        "final_text_hash": study_snapshots.sha256(gen["text"]),
    })
    return out


def test_probe_refuses_before_confidence(auth_client, submitted):
    r = auth_client.post("/api/study/probe/start", headers=_hdr(submitted["join_token"]))
    assert r.status_code == 409


def test_probe_refuses_before_submission(auth_client, moderator, walk_to):
    out = auth_client.post("/api/study/sessions", headers=_hdr(moderator), json={
        "condition": "c", "participant_code": "P32", "lang": "en"}).json()
    auth_client.post("/api/study/start", headers=_hdr(out["join_token"]))
    walk_to(auth_client, moderator, out, "verification")
    auth_client.post("/api/study/confidence", headers=_hdr(out["join_token"]),
                     json={"likert_1_7": 5, "est_problem_count": 2})
    r = auth_client.post("/api/study/probe/start", headers=_hdr(out["join_token"]))
    assert r.status_code == 409


def test_full_order_works_and_the_draw_is_idempotent(auth_client, submitted):
    token = _hdr(submitted["join_token"])
    assert auth_client.post("/api/study/confidence", headers=token, json={
        "likert_1_7": 6, "est_problem_count": 1}).status_code == 200

    first = auth_client.post("/api/study/probe/start", headers=token)
    assert first.status_code == 200
    items = first.json()["items"]
    assert len(items) >= 1

    # A reload must show the SAME items -- a fresh draw would change what the
    # participant is being asked halfway through.
    second = auth_client.post("/api/study/probe/start", headers=token).json()
    assert [i["sent_id"] for i in second["items"]] == [i["sent_id"] for i in items]


def test_probe_response_never_carries_the_answer_key(auth_client, submitted):
    token = _hdr(submitted["join_token"])
    auth_client.post("/api/study/confidence", headers=token,
                     json={"likert_1_7": 4, "est_problem_count": 3})
    r = auth_client.post("/api/study/probe/start", headers=token)
    assert "planted" not in r.text.lower()

    # ...but the server kept it, and the log records it per answer.
    session = study.load_session(submitted["session_id"])
    assert any(i.get("planted_id") for i in session["probe"]["items"])


def test_answers_are_recorded_with_ground_truth_in_the_log(auth_client, submitted):
    token = _hdr(submitted["join_token"])
    auth_client.post("/api/study/confidence", headers=token,
                     json={"likert_1_7": 4, "est_problem_count": 3})
    auth_client.post("/api/study/probe/start", headers=token)

    r = auth_client.post("/api/study/probe/answer", headers=token, json={
        "probe_index": 0, "judgment": "not_supported", "rt_ms": 4200,
        "source_opened": True})
    assert r.status_code == 200

    session = study.load_session(submitted["session_id"])
    answer = session["probe"]["answers"]["0"]
    assert answer["judgment"] == "not_supported"
    assert answer["rt_ms"] == 4200
    assert answer["source_opened"] is True

    path = study.session_dir(
        session["workspace_id"], session["session_id"], session["track"]) / "events.jsonl"
    events = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    probe_events = [e for e in events if e["event"] == "probe_item"]
    assert len(probe_events) == 1
    assert "planted_id" in probe_events[0]["payload"]


def test_confidence_cannot_be_submitted_twice(auth_client, submitted):
    token = _hdr(submitted["join_token"])
    assert auth_client.post("/api/study/confidence", headers=token, json={
        "likert_1_7": 5, "est_problem_count": 0}).status_code == 200
    assert auth_client.post("/api/study/confidence", headers=token, json={
        "likert_1_7": 1, "est_problem_count": 9}).status_code == 409
