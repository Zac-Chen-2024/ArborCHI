"""OT-02: pre-generate the frozen paragraph for every node in a bundle.

Uses the same generator the live path uses (`study_generator`), so a frozen
sentence and a live one are produced by the same prompt, the same model and the
same sentence splitter. 红线 #3 asks that a participant cannot tell them apart;
that starts with them actually being alike, not with hiding a difference in the
CSS.

Writes `pregen/<node_id>.json` with `source: "frozen"` and `planted_id: null`.
Planting happens afterwards, as a separate hand-authored step -- an error has to
be written against the sentence that will carry it, and against the excerpt a
participant will check it with.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import materials  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services import study_generator  # noqa: E402
from app.services.llm_providers import close_clients  # noqa: E402


async def run(material_id: str, only: set[str] | None) -> int:
    bundle = materials.load_bundle(material_id)
    out_dir = materials.bundle_dir(material_id) / "pregen"
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    try:
        for arg in bundle["tree"]["arguments"]:
            for sub in arg["subs"]:
                node_id = sub["id"]
                if only and node_id not in only:
                    continue
                target = out_dir / f"{node_id}.json"
                if target.exists() and not only:
                    print(f"  {node_id}: exists, skipped")
                    continue

                submitted = {
                    "title": sub["title"],
                    "parent_id": arg["id"],
                    "snippet_ids": list(sub["snippet_ids"]),
                    "state": "proposed",
                }
                sentences = await study_generator.generate_live_sentences(
                    node_id, submitted, material_id=material_id,
                )
                for s in sentences:
                    s["source"] = "frozen"
                    s["planted_id"] = None
                    # The generator's own words, kept so plant_errors.py can
                    # derive the planted text from them every time instead of
                    # editing in place. Server-only: it is the correct version
                    # of a sentence a participant is being asked to check.
                    s["text_clean"] = s["text"]
                target.write_text(
                    json.dumps({"schema_version": 1, "node_id": node_id,
                                "sentences": sentences},
                               ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
                written += 1
                print(f"  {node_id}: {len(sentences)} sentences -- {sub['title']}")
                for s in sentences:
                    print(f"      {s['sent_id']}  {s['text']}")
    finally:
        await close_clients()
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--material", default="judging_v1")
    ap.add_argument("--nodes", default="", help="comma-separated; default all missing")
    args = ap.parse_args()

    settings.llm_provider = "openai_responses"
    only = {n.strip() for n in args.nodes.split(",") if n.strip()} or None

    # One event loop for the whole run: the provider caches an httpx client
    # bound to the loop that made it, so a loop per node works once and then
    # fails with "Event loop is closed".
    written = asyncio.run(run(args.material, only))
    print(f"\n{written} node(s) written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
