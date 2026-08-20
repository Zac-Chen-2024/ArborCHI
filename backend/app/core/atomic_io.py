"""
Crash-safe, lock-guarded JSON I/O -- the ONLY way the backend writes JSON.

Guarantees
----------
* Crash safety: write to a temp file in the same directory, fsync, then
  os.replace() over the target. At any instant the target is either the
  complete old version or the complete new version, never a torn file.
* Concurrency safety: two layers --
    - a per-path threading.Lock for threads inside this process
      (FastAPI runs sync endpoints in a threadpool);
    - a portalocker exclusive lock on a sidecar "<file>.lock" for other
      processes (dev reload workers, scripts). The sidecar -- not the target
      -- is locked because os.replace() swaps the target's inode.
* Backup: before writing, the previous version is hard-linked to
  "<file>.bak" (link first, THEN write -- a failed link never touches the
  original). read_json() falls back to .bak when the main file is corrupt.
* Read-modify-write: update_json(path, mutator) holds the same locks across
  read -> mutate -> write, so concurrent updaters cannot lose each other's
  changes (a plain write_json only makes each single write atomic).

Reference: this is the classic POSIX "write temp + fsync + rename" recipe
(see os.replace docs, atomicwrites, Django FileSystemStorage).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import weakref
from pathlib import Path
from typing import Any, Callable, Union

import portalocker

logger = logging.getLogger(__name__)

PathLike = Union[str, os.PathLike]

_JSON_KW = dict(ensure_ascii=False, indent=2)

# One in-process lock per absolute path. WeakValueDictionary so idle paths do
# not accumulate forever; a lock is kept alive for as long as someone holds it.
_locks: "weakref.WeakValueDictionary[str, threading.Lock]" = weakref.WeakValueDictionary()
_locks_guard = threading.Lock()


def _thread_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


class _PathLock:
    """Context manager: in-process lock + cross-process sidecar lock."""

    def __init__(self, path: Path):
        self.path = path
        self.sidecar = path.with_name(path.name + ".lock")
        self._tlock = _thread_lock(path)
        self._fh = None

    def __enter__(self):
        self._tlock.acquire()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.sidecar, "a+")
            portalocker.lock(self._fh, portalocker.LOCK_EX)
        except Exception:
            self._tlock.release()
            raise
        return self

    def __exit__(self, *exc):
        try:
            if self._fh is not None:
                try:
                    portalocker.unlock(self._fh)
                finally:
                    self._fh.close()
        finally:
            self._tlock.release()


def _fsync_dir(directory: Path) -> None:
    """Best-effort directory fsync so the rename itself is durable."""
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_locked(path: Path, data: Any) -> None:
    """Assumes the caller holds _PathLock(path)."""
    bak = path.with_name(path.name + ".bak")
    tmp = path.with_name(path.name + ".tmp")

    # 1. Backup: hard-link the CURRENT file to .bak. Order matters -- link
    #    before writing; a link failure must never disturb the original.
    if path.exists():
        try:
            if bak.exists():
                bak.unlink()
            os.link(path, bak)
        except OSError as e:  # cross-device, FS without hardlinks, ...
            logger.warning("atomic_io: could not create backup for %s: %s", path, e)

    # 2. Write temp + fsync
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, **_JSON_KW)
        f.flush()
        os.fsync(f.fileno())

    # 3. Atomic swap
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def _read_locked(path: Path, default: Any = None) -> Any:
    """Assumes the caller holds _PathLock(path) (or does not care)."""
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        bak = path.with_name(path.name + ".bak")
        logger.error("atomic_io: %s is corrupt (%s); trying backup", path, e)
        if bak.exists():
            try:
                with open(bak, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError) as e2:
                logger.error("atomic_io: backup %s is also corrupt (%s)", bak, e2)
        return default


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_json(path: PathLike, default: Any = None) -> Any:
    """Read a JSON file. Missing -> default. Corrupt -> .bak, else default."""
    return _read_locked(Path(path), default)


def write_json(path: PathLike, data: Any) -> None:
    """Atomically replace `path` with the JSON serialisation of `data`."""
    p = Path(path)
    with _PathLock(p):
        _write_locked(p, data)


def update_json(path: PathLike, mutator: Callable[[Any], Any], default: Any = None) -> Any:
    """Locked read -> mutator(data) -> write. Returns the written data.

    `mutator` may modify in place and return None, or return a new object.
    """
    p = Path(path)
    with _PathLock(p):
        data = _read_locked(p, default)
        result = mutator(data)
        if result is None:
            result = data
        _write_locked(p, result)
        return result


def append_jsonl(path: PathLike, record: Any) -> None:
    """Append one JSON record as a line. O_APPEND is atomic per write for
    reasonably sized lines; fsync makes it durable."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _thread_lock(p):
        with open(p, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())


__all__ = ["read_json", "write_json", "update_json", "append_jsonl"]
