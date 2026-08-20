"""
Study parameters, loaded from study_config.json and hashed into every event.

Why a file and not constants. Pilot exists to change these numbers, and a
number that lives in Python is a number that changes without leaving a trace:
two sessions run a week apart would be indistinguishable in the log even though
one had a 15-minute organisation phase and the other 20. So the whole file is
hashed, and `config_hash` rides in every event envelope alongside the build
hash. Given a log, the exact parameters that session ran under are recoverable
from the log itself -- no cross-referencing a deploy history, no trusting a
lab notebook.

That is also why the loader caches by mtime rather than at import: the
moderator can edit the file between sessions without restarting the server, and
the next session picks up both the new values and the new hash.

The defaults here mirror the file and exist only so a missing config is a
degraded run rather than a crashed one; a missing file is logged loudly and
`config_hash` becomes "default" so those sessions are identifiable.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "study_config.json"

# Mirrors study_config.json. Used only when the file is missing or unreadable.
DEFAULTS: Dict[str, Any] = {
    "config_version": "default",
    "phases": {
        "organization": {
            "duration_seconds": 900, "softlock": True,
            "softlock_grace_seconds": 10, "visible_clock": True,
        },
        "generation": {"duration_seconds": None, "softlock": False, "visible_clock": False},
        "verification": {
            "duration_seconds": 1500, "hard_cap_seconds": 1920,
            "softlock": False, "visible_clock": False,
        },
    },
    "probe": {"target_items": 14, "min_items": 12, "max_items": 15, "max_planted_ratio": 0.6},
    "session": {"announced_minutes_min": 90, "announced_minutes_max": 95,
                "fixed_overhead_minutes": 46},
    "integrity": {"event_count_sigma": 3, "invalidate_if_log_loss_above": 0.20,
                  "heartbeat_coverage_min": 0.95},
    "sample": {"condition_c_target": 24, "condition_b_target": 0, "pilot_sessions": 4},
}

_cache: Optional[Dict[str, Any]] = None
_cache_mtime: Optional[float] = None
_cache_hash: str = "default"


def config_path() -> Path:
    """backend/study_config.json, regardless of the working directory."""
    return Path(__file__).resolve().parent.parent.parent / CONFIG_FILENAME


def _hash(data: Dict[str, Any]) -> str:
    """Hash of the semantic content, not the file bytes.

    Keys are sorted and `_comment` fields dropped, so reformatting the file or
    editing a comment does NOT change the hash -- only a change to an actual
    parameter does. Otherwise every prettier-run would look, in the data, like
    a protocol change.
    """
    def strip(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if not k.startswith("_")}
        if isinstance(o, list):
            return [strip(x) for x in o]
        return o

    canonical = json.dumps(strip(data), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def load(force: bool = False) -> Dict[str, Any]:
    """Current config, re-read when the file changes on disk."""
    global _cache, _cache_mtime, _cache_hash

    path = config_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        if _cache is None:
            logger.error("study_config.json not found at %s; running on defaults", path)
            _cache, _cache_mtime, _cache_hash = DEFAULTS, None, "default"
        return _cache

    if force or _cache is None or _cache_mtime != mtime:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.error("study_config.json is unreadable (%s); running on defaults", e)
            data = DEFAULTS
        _cache, _cache_mtime, _cache_hash = data, mtime, _hash(data)
        logger.info("study config loaded: version=%s hash=%s",
                    data.get("config_version"), _cache_hash)
    return _cache


def config_hash() -> str:
    load()
    return _cache_hash


def phase_config(phase: str) -> Dict[str, Any]:
    """Timing rules for one phase. An unlisted phase is untimed and unlocked."""
    return load().get("phases", {}).get(phase, {})


def probe_config() -> Dict[str, Any]:
    return load().get("probe", DEFAULTS["probe"])


def integrity_config() -> Dict[str, Any]:
    return load().get("integrity", DEFAULTS["integrity"])


__all__ = ["load", "config_hash", "config_path", "phase_config", "probe_config",
           "integrity_config", "DEFAULTS"]
