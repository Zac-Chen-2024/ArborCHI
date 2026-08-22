"""
app/core/atomic_io -- crash-safe, lock-guarded JSON I/O (M3).

Written before the implementation (M2) so that M3 turns them green.

M3 landed, so these import the module rather than skipping past it. An
importorskip here would have gone on quietly hiding all eight of them the day
this module stopped importing, which is the one day they matter.
"""
import json
import threading

from app.core import atomic_io


def test_roundtrip(tmp_path):
    p = tmp_path / "a" / "b.json"  # parent dirs are created on demand
    atomic_io.write_json(p, {"x": 1, "y": [1, 2, "三"]})
    assert atomic_io.read_json(p) == {"x": 1, "y": [1, 2, "三"]}
    # no temp files left behind
    assert sorted(f.name for f in p.parent.iterdir()) == ["b.json", "b.json.bak", "b.json.lock"] or \
           sorted(f.name for f in p.parent.iterdir()) == ["b.json", "b.json.lock"]


def test_read_missing_returns_default(tmp_path):
    assert atomic_io.read_json(tmp_path / "nope.json") is None
    assert atomic_io.read_json(tmp_path / "nope.json", default={}) == {}


def test_bak_is_previous_version_and_used_on_corruption(tmp_path):
    p = tmp_path / "c.json"
    atomic_io.write_json(p, {"v": 1})
    atomic_io.write_json(p, {"v": 2})
    assert json.loads(p.with_suffix(".json.bak").read_text()) == {"v": 1}
    # corrupt the main file -> read falls back to .bak
    p.write_text("{corrupt", encoding="utf-8")
    assert atomic_io.read_json(p) == {"v": 1}


def test_corrupt_without_bak_returns_default(tmp_path):
    p = tmp_path / "d.json"
    p.write_text("{corrupt", encoding="utf-8")
    assert atomic_io.read_json(p, default={"fallback": True}) == {"fallback": True}


def test_concurrent_writes_leave_a_complete_document(tmp_path):
    """50 threads write distinct payloads; the file must equal one of them, whole."""
    p = tmp_path / "e.json"
    payloads = [{"writer": i, "blob": "x" * 5000} for i in range(50)]

    def worker(i):
        atomic_io.write_json(p, payloads[i])

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    final = json.loads(p.read_text(encoding="utf-8"))
    assert final in payloads


def test_update_json_is_atomic_read_modify_write(tmp_path):
    """50 threads each increment a counter via update_json; result must be 50."""
    p = tmp_path / "f.json"
    atomic_io.write_json(p, {"n": 0})

    def bump(d):
        d["n"] += 1
        return d

    def worker():
        atomic_io.update_json(p, bump)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert atomic_io.read_json(p)["n"] == 50


def test_update_json_default_when_missing(tmp_path):
    p = tmp_path / "g.json"
    out = atomic_io.update_json(p, lambda d: {**d, "k": 1}, default={})
    assert out == {"k": 1}
    assert atomic_io.read_json(p) == {"k": 1}


def test_append_jsonl(tmp_path):
    p = tmp_path / "log" / "s.jsonl"
    atomic_io.append_jsonl(p, {"a": 1})
    atomic_io.append_jsonl(p, {"b": "二"})
    lines = p.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [{"a": 1}, {"b": "二"}]
