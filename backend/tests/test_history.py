"""Structural undo / redo (M13)."""
from app.services import history
from app.services.snippet_recommender import load_legal_arguments, update_legal_arguments


def _doc(n_sub):
    return {
        "arguments": [{"id": "arg-1", "standard_key": "awards", "sub_argument_ids": [f"sa-{i}" for i in range(n_sub)]}],
        "sub_arguments": [{"id": f"sa-{i}", "argument_id": "arg-1", "title": f"t{i}", "snippet_ids": []} for i in range(n_sub)],
    }


def test_every_change_is_recorded_and_undoable(tmp_data_dir):
    pid = "hist-1"
    update_legal_arguments(pid, lambda d: _doc(1))
    update_legal_arguments(pid, lambda d: _doc(2))

    def rename(d):
        d["sub_arguments"][0]["title"] = "renamed"
    update_legal_arguments(pid, rename)

    peek = history.peek(pid)
    assert peek["undo_depth"] == 3 and peek["redo_depth"] == 0
    # newest first; label = the function that *owns* the mutator (here: this test)
    assert peek["undo"][0]["label"] == "test_every_change_is_recorded_and_undoable"
    assert load_legal_arguments(pid)["sub_arguments"][0]["title"] == "renamed"


def test_no_op_writes_are_not_recorded(tmp_data_dir):
    pid = "hist-2"
    update_legal_arguments(pid, lambda d: _doc(1))
    update_legal_arguments(pid, lambda d: None)  # touches nothing
    update_legal_arguments(pid, lambda d: d)
    assert history.peek(pid)["undo_depth"] == 1
    update_legal_arguments(pid, lambda d: _doc(3), record=False)
    assert history.peek(pid)["undo_depth"] == 1


def test_undo_redo_endpoints(client, victim_project):
    pid = victim_project
    update_legal_arguments(pid, lambda d: _doc(1), label="seed")
    update_legal_arguments(pid, lambda d: _doc(2), label="add sub-argument")

    r = client.get(f"/api/arguments/{pid}/history").json()
    assert r["undo"][0]["label"] == "add sub-argument" and r["redo"] == []

    r = client.post(f"/api/arguments/{pid}/undo").json()
    assert r["applied"] and r["label"] == "add sub-argument"
    assert r["affected_standard_keys"] == ["awards"]
    assert len(load_legal_arguments(pid)["sub_arguments"]) == 1
    assert r["undo_depth"] == 1 and r["redo_depth"] == 1

    r = client.post(f"/api/arguments/{pid}/redo").json()
    assert r["applied"] and len(load_legal_arguments(pid)["sub_arguments"]) == 2
    assert r["redo_depth"] == 0

    # undo twice -> empty document; a third undo is a no-op
    client.post(f"/api/arguments/{pid}/undo")
    client.post(f"/api/arguments/{pid}/undo")
    assert load_legal_arguments(pid) == {"arguments": [], "sub_arguments": []}
    r = client.post(f"/api/arguments/{pid}/undo").json()
    assert r["applied"] is False

    # a fresh change after undo clears the redo stack
    client.post(f"/api/arguments/{pid}/redo")
    update_legal_arguments(pid, lambda d: _doc(5), label="new branch")
    assert history.peek(pid)["redo_depth"] == 0


def test_undo_stack_is_bounded(tmp_data_dir):
    pid = "hist-3"
    for i in range(history.MAX_ENTRIES + 7):
        update_legal_arguments(pid, lambda d, i=i: _doc(i % 4 + 1) | {"n": i})
    assert history.peek(pid)["undo_depth"] == history.MAX_ENTRIES


def test_structural_endpoint_records_undo(client, victim_project):
    """A real router mutation (PUT subargument) leaves an undo entry with a readable label."""
    pid = victim_project
    update_legal_arguments(pid, lambda d: _doc(1), label="seed")
    r = client.put(f"/api/arguments/{pid}/subarguments/sa-0", json={"title": "new title"})
    assert r.status_code == 200
    peek = history.peek(pid)
    assert peek["undo"][0]["label"] == "update_subargument"
    client.post(f"/api/arguments/{pid}/undo")
    assert load_legal_arguments(pid)["sub_arguments"][0]["title"] == "t0"
