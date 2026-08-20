#!/usr/bin/env python
"""
Mint a workspace token.

    cd backend
    python scripts/mint_token.py --label P07            # workspace id derived from label
    python scripts/mint_token.py --label "Pilot 3" --workspace pilot3
    python scripts/mint_token.py --list

Prints the token once; it is stored (hashed? no -- plaintext, it IS the
credential) in data/workspaces.json. Hand the token to the participant, or
give them a link like https://host/?token=<token>.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import workspace  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", help="human label, e.g. participant code")
    ap.add_argument("--workspace", help="explicit workspace id (default: derived from label)")
    ap.add_argument("--list", action="store_true", help="list existing tokens")
    args = ap.parse_args()

    if args.list:
        table = workspace.load_token_table()
        if not table:
            print("(no tokens)")
        for tok, e in table.items():
            print(f"{e.get('workspace_id'):20s} {e.get('label', ''):20s} {e.get('created_at', '')}  {tok}")
        return 0

    if not args.label:
        ap.error("--label is required (or use --list)")
    entry = workspace.mint_token(args.label, args.workspace)
    print(f"workspace : {entry['workspace_id']}")
    print(f"label     : {entry['label']}")
    print(f"token     : {entry['token']}")
    print(f"table     : {workspace.token_table_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
