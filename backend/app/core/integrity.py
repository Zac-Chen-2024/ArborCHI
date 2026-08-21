"""
End-of-session integrity report (BE-15, 日志手册 §8, PR-4).

Answers one question: **may this session enter the analysis?** It is run at
close-out, written to the session directory, and shown to the moderator as a
red/green list while the participant is still in the room -- which is the only
moment when a fixable problem can still be fixed.

Three verdicts, and the distinction between the last two is the whole point:

    pass    the check is satisfied
    flag    something is unusual and a human should look; the session stays
            valid
    fail    the session cannot be analysed

PR-4 assigns them deliberately. An event count more than 3σ from the baseline
is a **flag**, never an automatic rejection: a participant who worked unusually
fast is data, not damage, and discarding them on a threshold would quietly
select for people who behave like the mean. What does invalidate a session is
losing more than 20% of its log -- there the data is simply not there.

Nothing here modifies the session. A report is a reading, and re-running it
must give the same answer.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple

from .atomic_io import write_json
from .study import now_iso, session_dir
from .study_config import integrity_config
from .study_snapshots import read_snapshot, sha256

PASS, FLAG, FAIL = "pass", "flag", "fail"

# One heartbeat every 30s (see the log SDK).
HEARTBEAT_INTERVAL_MS = 30_000


def _check(name: str, status: str, detail: str, **extra: Any) -> Dict[str, Any]:
    return {"check": name, "status": status, "detail": detail, **extra}


def read_events(session: Dict[str, Any]) -> List[Dict[str, Any]]:
    path = session_dir(
        session["workspace_id"], session["session_id"], session["track"]
    ) / "events.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # A torn final line is itself a finding, not a crash.
            out.append({"event": "__unparseable__"})
    return out


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_seq_continuity(session: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """How much of the client's log actually arrived (PR-4).

    The client numbers its events; the server records gaps rather than
    rejecting them, so the arithmetic here is simply what never showed up.
    """
    gaps: List[Tuple[int, int]] = [tuple(g) for g in session.get("seq_gaps", [])]
    highest = int(session.get("seq_acked", -1))
    expected = highest + 1
    missing = sum(end - start + 1 for start, end in gaps)
    ratio = (missing / expected) if expected > 0 else 0.0
    limit = float(integrity_config()["invalidate_if_log_loss_above"])

    if not gaps:
        return _check("seq_continuity", PASS, f"no gaps in {expected} client events",
                      expected=expected, missing=0, loss_ratio=0.0)
    status = FAIL if ratio > limit else FLAG
    return _check(
        "seq_continuity", status,
        f"{missing} of {expected} client events never arrived "
        f"({ratio:.1%}; limit {limit:.0%})",
        expected=expected, missing=missing, loss_ratio=round(ratio, 4), gaps=gaps,
    )


def check_heartbeat(session: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Was the client alive throughout? (BE-15: coverage >= 95%.)

    Compared against the span the client was actually working, not the whole
    session: the setup phase happens while the moderator talks and the tab may
    not even be open yet.
    """
    beats = [e for e in events if e.get("event") == "heartbeat"]
    started = session.get("started_at")
    if not started or not beats:
        return _check("heartbeat", FLAG, "no heartbeats recorded", observed=len(beats))

    mono = [e["ts_mono"] for e in beats if isinstance(e.get("ts_mono"), (int, float))]
    if len(mono) < 2:
        return _check("heartbeat", FLAG, "too few heartbeats to judge coverage",
                      observed=len(beats))

    span_ms = max(mono) - min(mono)
    expected = max(1, round(span_ms / HEARTBEAT_INTERVAL_MS) + 1)
    coverage = min(1.0, len(beats) / expected)
    floor = float(integrity_config()["heartbeat_coverage_min"])
    status = PASS if coverage >= floor else FLAG
    return _check(
        "heartbeat", status,
        f"{len(beats)} of ~{expected} expected beats ({coverage:.0%}; floor {floor:.0%})",
        observed=len(beats), expected=expected, coverage=round(coverage, 4),
    )


def check_snapshots(session: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Both snapshots exist and their stored text still hashes to what was
    recorded (红线 #1, BE-11).

    The initial one is the load-bearing case: it is the only baseline for what
    the participant changed, and it cannot be reconstructed afterwards.
    """
    problems: List[str] = []
    detail: Dict[str, Any] = {}

    initial = read_snapshot(session, "initial")
    if initial is None:
        problems.append("initial snapshot missing")
    else:
        detail["initial_sentences"] = len(initial.get("sentences", []))
        if sha256(initial["text"]) != initial["sha256"]:
            problems.append("initial snapshot hash does not match its text")
        recorded = session.get("initial_snapshot_hash")
        if recorded and recorded != initial["sha256"]:
            problems.append("initial snapshot hash differs from the session record")

    final = read_snapshot(session, "final")
    if session.get("submitted"):
        if final is None:
            problems.append("submitted but no final snapshot")
        else:
            if sha256(final["text"]) != final["sha256"]:
                problems.append("final snapshot hash does not match its text")
            if session.get("final_text_hash") != final["sha256"]:
                problems.append("final snapshot hash differs from the session record")
            detail["final_chars"] = final["char_count"]
    elif final is not None:
        problems.append("final snapshot exists but the session was never submitted")

    # The snapshot must predate any editing (红线 #1). The event order is the
    # evidence: draft_snapshot has to come before the first text_edit.
    snap_at = next((i for i, e in enumerate(events)
                    if e.get("event") == "draft_snapshot"), None)
    first_edit = next((i for i, e in enumerate(events)
                       if e.get("event") == "text_edit"), None)
    if snap_at is None:
        problems.append("no draft_snapshot event")
    elif first_edit is not None and first_edit < snap_at:
        problems.append("a text_edit was logged before the initial snapshot")

    if problems:
        return _check("snapshots", FAIL, "; ".join(problems), **detail)
    return _check("snapshots", PASS, "initial and final present, hashes match", **detail)


def check_phase_pairs(session: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Every phase entered was left, except the one the session ended in."""
    entered = [e["payload"].get("phase") for e in events if e.get("event") == "phase_enter"]
    exited = [e["payload"].get("phase") for e in events if e.get("event") == "phase_exit"]
    unmatched = [p for p in entered if entered.count(p) > exited.count(p)]
    # The final phase is legitimately unexited.
    current = session.get("phase")
    unmatched = [p for p in unmatched if p != current]
    if unmatched:
        return _check("phase_pairs", FAIL,
                      f"phases entered but never exited: {sorted(set(unmatched))}",
                      entered=len(entered), exited=len(exited))
    return _check("phase_pairs", PASS, f"{len(entered)} enter / {len(exited)} exit",
                  entered=len(entered), exited=len(exited))


def check_practice_checkpoint(session: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The practice gate was cleared (FS-06).

    A flag rather than a failure: a session that skipped practice is still
    analysable, but whoever reads it should know the participant went in
    without having demonstrated the interaction once.
    """
    passed = [e for e in events if e.get("event") == "checkpoint_passed"]
    if passed:
        gates = sorted({e["payload"].get("gate") for e in passed})
        return _check("practice_checkpoint", PASS, f"cleared: {gates}", count=len(passed))
    return _check("practice_checkpoint", FLAG, "no checkpoint_passed recorded", count=0)


def check_order(session: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """submit -> confidence -> probe (红线 #6).

    The server refuses out-of-order calls, so a violation here means something
    bypassed the API -- which is worth knowing loudly.
    """
    def first(name: str) -> Optional[int]:
        return next((i for i, e in enumerate(events) if e.get("event") == name), None)

    submit = first("submit")
    confidence = first("confidence_submit")
    probe = first("probe_start")

    problems = []
    if confidence is not None and submit is not None and confidence < submit:
        problems.append("confidence was recorded before submission")
    if probe is not None and confidence is None:
        problems.append("probe started without a confidence answer")
    if probe is not None and confidence is not None and probe < confidence:
        problems.append("probe started before confidence")

    if problems:
        return _check("order", FAIL, "; ".join(problems))
    reached = [n for n, i in (("submit", submit), ("confidence", confidence),
                              ("probe", probe)) if i is not None]
    return _check("order", PASS, f"reached: {reached or ['none yet']}")


def check_provenance(session: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Every event agrees on which material, tree and config it belongs to.

    A session whose events disagree cannot be pooled with anything: half of it
    ran on different material. This is what the schema-v3 envelope is for.
    """
    fields = ("config_hash", "material_manifest_hash", "tree_variant_id")
    seen: Dict[str, set] = {f: set() for f in fields}
    for e in events:
        for f in fields:
            if f in e:
                seen[f].add(e[f])

    mixed = {f: sorted(v) for f, v in seen.items() if len(v) > 1}
    if mixed:
        return _check("provenance", FAIL, f"events disagree on {list(mixed)}", mixed=mixed)

    values = {f: (next(iter(v)) if v else "") for f, v in seen.items()}
    if not values["material_manifest_hash"]:
        return _check("provenance", FAIL, "no material bound to this session", **values)
    return _check("provenance", PASS, "consistent across all events", **values)


def check_event_volume(
    session: Dict[str, Any],
    events: List[Dict[str, Any]],
    baseline: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Event count against the cohort baseline (PR-4).

    **Flag only.** A participant who worked unusually fast or unusually
    thoroughly is a finding, not a fault; rejecting them on a threshold would
    quietly select the sample toward people who behave like the mean.
    """
    count = sum(1 for e in events if e.get("source") == "client")
    # A z-score needs a cohort, not two sessions. With n=2 the SD is whatever
    # those two happened to differ by, and the first real session scored
    # z=+51 against a mean of 3 -- a flag that says nothing about the session
    # and, repeated, teaches the moderator to ignore this row. The floor is the
    # pre-registered pilot size (PR-4/PR-5), not a number chosen here.
    min_n = int(integrity_config().get("event_count_min_baseline_n", 4))
    if not baseline or baseline.get("n", 0) < min_n or not baseline.get("sd"):
        have = baseline.get("n", 0) if baseline else 0
        return _check("event_volume", PASS,
                      f"{count} client events; baseline needs {min_n} sessions, has {have}",
                      count=count, baseline=baseline or None)

    sigma = float(integrity_config()["event_count_sigma"])
    z = (count - baseline["mean"]) / baseline["sd"] if baseline["sd"] else 0.0
    status = FLAG if abs(z) > sigma else PASS
    return _check(
        "event_volume", status,
        f"{count} client events, z={z:+.2f} against mean {baseline['mean']:.0f} "
        f"(n={baseline['n']}); flag beyond {sigma}σ",
        count=count, z=round(z, 3), baseline=baseline,
    )


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

def cohort_baseline(counts: List[int]) -> Dict[str, float]:
    """Mean and SD of client-event counts across the formal cohort.

    PR-4: provisional from the pilot, recomputed after the first eight formal
    sessions, then frozen. Frozen matters -- a baseline that keeps absorbing
    new sessions moves toward whatever the sample does, and eventually nothing
    looks unusual.
    """
    n = len(counts)
    if n == 0:
        return {"n": 0, "mean": 0.0, "sd": 0.0}
    mean = sum(counts) / n
    if n < 2:
        return {"n": n, "mean": mean, "sd": 0.0}
    var = sum((c - mean) ** 2 for c in counts) / (n - 1)
    return {"n": n, "mean": round(mean, 2), "sd": round(math.sqrt(var), 2)}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

CHECKS = (
    check_seq_continuity,
    check_heartbeat,
    check_snapshots,
    check_phase_pairs,
    check_practice_checkpoint,
    check_order,
    check_provenance,
)


def build_report(
    session: Dict[str, Any],
    *,
    baseline: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Run every check. Returns the report; does not write it."""
    events = read_events(session)
    results = [fn(session, events) for fn in CHECKS]
    results.append(check_event_volume(session, events, baseline))

    failed = [r["check"] for r in results if r["status"] == FAIL]
    flagged = [r["check"] for r in results if r["status"] == FLAG]

    return {
        "schema_version": 1,
        "session_id": session["session_id"],
        "participant_code": session.get("participant_code"),
        "condition": session.get("condition"),
        "track": session.get("track"),
        "generated_at": now_iso(),
        # The verdict a human acts on. `valid` means analysable; flags are
        # things to look at, not reasons to discard.
        "verdict": "invalid" if failed else ("review" if flagged else "valid"),
        "failed": failed,
        "flagged": flagged,
        "event_count": len(events),
        "checks": results,
    }


def write_report(session: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    path = session_dir(
        session["workspace_id"], session["session_id"], session["track"]
    ) / "integrity.json"
    write_json(path, report)
    return report


__all__ = [
    "PASS", "FLAG", "FAIL", "read_events", "cohort_baseline", "build_report",
    "write_report", "CHECKS", "check_seq_continuity", "check_heartbeat",
    "check_snapshots", "check_phase_pairs", "check_practice_checkpoint",
    "check_order", "check_provenance", "check_event_volume",
]
