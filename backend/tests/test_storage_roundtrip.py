"""
Save/load pairs of the storage layer. These are the safety net for M3
(atomic write replacement) and M4 (path consolidation): both are mechanical
refactors whose only real risk is a missed call site.
"""
import json

from app.services import storage
from app.services.petition_writer_v3 import load_latest_writing_v3, save_writing_v3
from app.services.snippet_recommender import load_legal_arguments, save_legal_arguments


def test_create_and_get_project(tmp_data_dir):
    meta = storage.create_project("Alice", "NIW")
    assert meta["projectType"] == "NIW"
    assert meta["projectNumber"].startswith("NIW-")
    got = storage.get_project(meta["id"])
    assert got["name"] == "Alice"
    assert [p["id"] for p in storage.list_projects()] == [meta["id"]]


def test_update_project_meta(tmp_data_dir):
    meta = storage.create_project("Bob")
    updated = storage.update_project_meta(meta["id"], {"beneficiaryName": "Bob B."})
    assert updated["beneficiaryName"] == "Bob B."
    assert storage.get_project(meta["id"])["beneficiaryName"] == "Bob B."


def test_documents_roundtrip(tmp_data_dir):
    meta = storage.create_project("Carol")
    assert storage.get_documents(meta["id"]) == []
    storage.add_document(meta["id"], {"id": "d1", "file_name": "a.pdf"})
    storage.update_document(meta["id"], "d1", {"page_count": 3})
    docs = storage.get_documents(meta["id"])
    assert docs == [{"id": "d1", "file_name": "a.pdf", "page_count": 3}]


def test_delete_project(tmp_data_dir):
    meta = storage.create_project("Dan")
    assert storage.delete_project(meta["id"]) is True
    assert storage.get_project(meta["id"]) is None
    assert storage.delete_project(meta["id"]) is False


def test_legal_arguments_roundtrip(tmp_data_dir):
    pid = "proj-1"
    assert load_legal_arguments(pid) == {"arguments": [], "sub_arguments": []}
    data = {"arguments": [{"id": "arg-1", "standard_key": "awards", "sub_argument_ids": ["subarg-1"]}],
            "sub_arguments": [{"id": "subarg-1", "argument_id": "arg-1", "snippet_ids": ["snp_A1_x"]}]}
    save_legal_arguments(pid, data)
    assert load_legal_arguments(pid) == data


def test_writing_v3_roundtrip_latest_wins(tmp_data_dir, monkeypatch):
    pid = "proj-2"
    assert load_latest_writing_v3(pid, "awards") is None
    v1 = save_writing_v3(pid, "awards", {"paragraph_text": "first", "sentences": []})
    # version ids are second-resolution timestamps; force a later one
    from datetime import datetime, timedelta, timezone

    import app.services.petition_writer_v3 as pw

    class _Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(timezone.utc) + timedelta(seconds=5)
    monkeypatch.setattr(pw, "datetime", _Later)
    v2 = save_writing_v3(pid, "awards", {"paragraph_text": "second", "sentences": []})
    assert v2 > v1
    assert load_latest_writing_v3(pid, "awards")["paragraph_text"] == "second"
    # other sections are isolated
    assert load_latest_writing_v3(pid, "membership") is None


def test_concurrent_subargument_creation_loses_nothing(tmp_data_dir):
    """Rapid UI actions fire overlapping requests; every created SubArgument must survive."""
    import threading

    from app.services.snippet_recommender import create_subargument

    pid = "proj-3"
    save_legal_arguments(pid, {"arguments": [{"id": "arg-1", "standard_key": "awards", "sub_argument_ids": []}],
                              "sub_arguments": []})

    def worker(i):
        create_subargument(pid, "arg-1", f"t{i}", "", "", [])

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    data = load_legal_arguments(pid)
    assert len(data["sub_arguments"]) == 30
    assert len(data["arguments"][0]["sub_argument_ids"]) == 30


def test_resolve_source_path_falls_back_to_source_data_dir(tmp_data_dir, projects_root, tmp_path, monkeypatch):
    """metadata.json holds a Windows path from another machine; resolve by folder name."""
    from app.core.config import settings

    src_root = tmp_path / "srcdata"
    (src_root / "eb1a" / "Dehuan Liu" / "PDF").mkdir(parents=True)
    monkeypatch.setattr(settings, "source_data_dir", str(src_root))

    pdir = projects_root / "dehuan_liu"
    pdir.mkdir()
    (pdir / "metadata.json").write_text(
        json.dumps({"source_path": "F:\\\\work\\\\data\\\\eb1a\\\\Dehuan Liu"}), encoding="utf-8"
    )
    assert storage.resolve_source_path("dehuan_liu") == src_root / "eb1a" / "Dehuan Liu"

    # an existing absolute path wins
    (pdir / "metadata.json").write_text(json.dumps({"source_path": str(src_root)}), encoding="utf-8")
    assert storage.resolve_source_path("dehuan_liu") == src_root

    # nothing resolvable -> None (router turns this into 404)
    (pdir / "metadata.json").write_text(json.dumps({"source_path": "/nowhere/Nobody"}), encoding="utf-8")
    assert storage.resolve_source_path("dehuan_liu") is None
    assert storage.resolve_source_path("no_such_project") is None


def test_partial_writing_versions_are_skipped_by_default(tmp_data_dir, monkeypatch):
    """A partial regeneration (subargument_ids) must never be served as the section (M13)."""
    from datetime import datetime, timedelta, timezone

    import app.services.petition_writer_v3 as pw

    pid = "proj-3"
    save_writing_v3(pid, "awards", {"paragraph_text": "full", "sentences": [{"text": "a"}]})

    class _Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(timezone.utc) + timedelta(seconds=5)
    monkeypatch.setattr(pw, "datetime", _Later)
    save_writing_v3(pid, "awards", {"paragraph_text": "part", "sentences": [{"text": "b"}], "partial": True})

    assert load_latest_writing_v3(pid, "awards")["paragraph_text"] == "full"
    assert load_latest_writing_v3(pid, "awards", full_only=False)["paragraph_text"] == "part"


def test_put_sentences_persists_full_version(client, victim_project):
    """PUT .../sentences stores what the user sees and GET /sections serves it back."""
    body = {"sentences": [
        {"text": "Opening.", "snippet_ids": [], "sentence_type": "opening"},
        {"text": "Body one [Exhibit A1, p.2].", "snippet_ids": ["s1"], "subargument_id": "sa-1", "argument_id": "arg-1"},
        {"text": "Closing.", "snippet_ids": [], "sentence_type": "closing"},
    ], "source": "user_commit"}
    r = client.put(f"/api/write/v3/{victim_project}/awards/sentences", json=body)
    assert r.status_code == 200 and r.json()["sentence_count"] == 3
    r = client.get(f"/api/write/v3/{victim_project}/sections")
    sections = r.json()["sections"]
    assert len(sections) == 1
    sec = sections[0]
    assert sec["paragraph_text"] == "Opening. Body one [Exhibit A1, p.2]. Closing."
    assert sec["provenance_index"]["by_subargument"] == {"sa-1": [1]}
    assert sec["provenance_index"]["by_snippet"] == {"s1": [1]}
    # path allow-list still applies
    assert client.put(f"/api/write/v3/{victim_project}/..%2Fx/sentences", json=body).status_code in (400, 404, 422)
