#!/usr/bin/env python
"""
One-off migration: data/projects/ -> data/workspaces/default/projects/

    cd backend
    python scripts/migrate_to_workspaces.py --dry-run
    python scripts/migrate_to_workspaces.py

Steps
  1. tar.gz the whole data/ directory to data/backup/pre-workspace-<ts>.tar.gz
  2. move data/projects -> data/workspaces/default/projects (os.rename; same fs)
Idempotent: if data/projects does not exist, nothing happens. Refuses to run
if the target already exists (merge by hand in that case).
"""
import argparse
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.storage import data_dir  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-backup", action="store_true", help="skip the tar.gz backup (not recommended)")
    args = ap.parse_args()

    root = data_dir()
    src = root / "projects"
    dst = root / "workspaces" / "default" / "projects"
    print(f"data root : {root}")
    print(f"source    : {src}  ({'exists' if src.exists() else 'missing'})")
    print(f"target    : {dst}  ({'exists' if dst.exists() else 'missing'})")

    if not src.exists():
        print("nothing to migrate")
        return 0
    if dst.exists() and any(dst.iterdir()):
        print("ERROR: target already exists and is not empty; merge manually", file=sys.stderr)
        return 2

    n = sum(1 for p in src.iterdir() if p.is_dir())
    print(f"projects  : {n}")
    if args.dry_run:
        print("dry-run: no changes made")
        return 0

    if not args.no_backup:
        bdir = root / "backup"
        bdir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        tar_path = bdir / f"pre-workspace-{ts}.tar.gz"
        print(f"backup    : {tar_path} ...", end="", flush=True)
        with tarfile.open(tar_path, "w:gz") as tar:
            for child in root.iterdir():
                if child.name == "backup":
                    continue
                tar.add(child, arcname=child.name)
        print(" done")

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.rmdir()
    src.rename(dst)
    print(f"moved     : {src} -> {dst}")
    print("done. Set AUTH_DISABLED=true for local use, or mint tokens with scripts/mint_token.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
