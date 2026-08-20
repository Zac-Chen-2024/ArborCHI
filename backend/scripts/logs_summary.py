#!/usr/bin/env python
"""
Summarise interaction logs: per session, time spent per panel and event counts.

    cd backend
    python scripts/logs_summary.py                       # all workspaces
    python scripts/logs_summary.py --workspace P07
    python scripts/logs_summary.py --session session_1700000000000_abc

Time-per-panel is computed from the panel_focus stream: each panel_focus opens
an interval that closes at the next panel_focus (or the last event of the
session). This is the raw material for the "same time budget, different
allocation" analysis (Doc/01 M6).
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.storage import data_dir  # noqa: E402


def load_sessions(workspace: str | None, session: str | None):
    root = data_dir() / "workspaces"
    for ws_dir in sorted(root.iterdir()) if root.is_dir() else []:
        if workspace and ws_dir.name != workspace:
            continue
        logs = ws_dir / "logs"
        if not logs.is_dir():
            continue
        for f in sorted(logs.glob("*.jsonl")):
            if session and f.stem != session:
                continue
            recs = []
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            recs.sort(key=lambda r: r.get("ts", 0))
            yield ws_dir.name, f.stem, recs


def summarise(recs):
    counts = Counter(r["event"] for r in recs)
    panel_time = defaultdict(float)
    focus = [r for r in recs if r["event"] == "panel_focus"]
    last_ts = recs[-1]["ts"] if recs else 0
    for i, r in enumerate(focus):
        end = focus[i + 1]["ts"] if i + 1 < len(focus) else last_ts
        panel_time[r["panel"]] += max(0, end - r["ts"]) / 1000.0
    return counts, panel_time


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace")
    ap.add_argument("--session")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    out = []
    for ws, sid, recs in load_sessions(args.workspace, args.session):
        if not recs:
            continue
        counts, panel_time = summarise(recs)
        duration = (recs[-1]["ts"] - recs[0]["ts"]) / 1000.0
        row = {"workspace": ws, "session": sid, "events": len(recs), "duration_s": round(duration, 1),
               "by_event": dict(counts), "panel_time_s": {k: round(v, 1) for k, v in panel_time.items()}}
        out.append(row)
        if not args.json:
            print(f"[{ws}] {sid}: {len(recs)} events over {duration:.0f}s")
            print("   events : " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
            print("   panels : " + ", ".join(f"{k}={v:.0f}s" for k, v in sorted(panel_time.items(), key=lambda kv: -kv[1])))
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif not out:
        print("(no sessions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
