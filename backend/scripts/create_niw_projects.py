"""
Create NIW projects from source data in /data/niw/

For each person folder:
1. Create project dir in backend/data/projects/
2. Convert OCR page JSONs into documents/{exhibit_id}.json
3. Create metadata.json (legacy format, needed by documents router)
4. Create meta.json (new format, needed by projects router)
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Paths
ROOT = Path(__file__).parent.parent
DATA_NIW = ROOT / "data" / "niw"
PROJECTS_DIR = Path(__file__).parent / "data" / "projects"


def slugify(name: str) -> str:
    """Convert person name to project_id: 'Chen Zhen' -> 'chen_zhen'"""
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


def build_document(exhibit_id: str, ocr_dir: Path) -> dict:
    """
    Build a document JSON from OCR page files.

    OCR dir structure: /OCR/{exhibit_id}/page_1.json, page_2.json, ...
    Each page JSON: {page_number, markdown_text, text_blocks, raw_output}

    Output: {exhibit_id, pages: [{page_number, text_blocks, markdown_text}], total_blocks}
    """
    pages = []
    total_blocks = 0

    page_files = sorted(
        ocr_dir.glob("page_*.json"),
        key=lambda f: int(f.stem.split('_')[1])
    )

    for pf in page_files:
        with open(pf, 'r', encoding='utf-8') as f:
            page_data = json.load(f)

        blocks = page_data.get("text_blocks", [])
        total_blocks += len(blocks)

        pages.append({
            "page_number": page_data.get("page_number", 0),
            "text_blocks": blocks,
            "markdown_text": page_data.get("markdown_text", "")
        })

    return {
        "exhibit_id": exhibit_id,
        "pages": pages,
        "total_blocks": total_blocks
    }


def create_project(person_name: str, source_dir: Path):
    """Create a single NIW project."""
    project_id = slugify(person_name)
    project_dir = PROJECTS_DIR / project_id

    if project_dir.exists():
        print(f"  Project {project_id} already exists, overwriting documents...")

    # Create directories
    project_dir.mkdir(parents=True, exist_ok=True)
    docs_dir = project_dir / "documents"
    docs_dir.mkdir(exist_ok=True)
    for subdir in ["analysis", "relationship", "writing", "writing_v3",
                    "arguments", "extraction", "snippets", "entities"]:
        (project_dir / subdir).mkdir(exist_ok=True)

    # Process OCR data
    ocr_dir = source_dir / "OCR"
    exhibits = []

    exhibit_dirs = sorted(
        [d for d in ocr_dir.iterdir() if d.is_dir()],
        key=lambda d: (d.name[0], int(re.sub(r'[^0-9]', '', d.name) or '0'))
    )

    for exhibit_dir in exhibit_dirs:
        exhibit_id = exhibit_dir.name  # e.g. "A1", "B10"
        print(f"    Processing exhibit {exhibit_id}...", end="")

        doc = build_document(exhibit_id, exhibit_dir)

        # Save document JSON
        doc_file = docs_dir / f"{exhibit_id}.json"
        with open(doc_file, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)

        exhibits.append({
            "exhibit_id": exhibit_id,
            "page_count": len(doc["pages"]),
            "block_count": doc["total_blocks"]
        })
        print(f" {len(doc['pages'])} pages, {doc['total_blocks']} blocks")

    # Create metadata.json (legacy format — needed by documents router)
    metadata = {
        "project_id": project_id,
        "person_name": person_name,
        "visa_type": "NIW",
        "pipeline_stage": "ocr_complete",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(source_dir).replace("\\", "/"),
        "exhibits": exhibits,
        "stats": {
            "total_exhibits": len(exhibits),
            "total_pages": sum(e["page_count"] for e in exhibits),
            "total_blocks": sum(e["block_count"] for e in exhibits)
        }
    }

    with open(project_dir / "metadata.json", 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    # Create meta.json (new format — needed by projects router)
    # Count existing NIW projects for numbering
    year = datetime.now(timezone.utc).strftime("%Y")
    existing_niw = 0
    for item in PROJECTS_DIR.iterdir():
        if item.is_dir():
            mf = item / "meta.json"
            if mf.exists():
                try:
                    with open(mf, 'r', encoding='utf-8') as f:
                        m = json.load(f)
                    if m.get("projectNumber", "").startswith(f"NIW-{year}-"):
                        existing_niw += 1
                except Exception:
                    pass

    meta = {
        "id": project_id,
        "name": person_name,
        "projectType": "NIW",
        "projectNumber": f"NIW-{year}-{existing_niw + 1:03d}",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat()
    }

    with open(project_dir / "meta.json", 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"\n  Created: {project_id}")
    print(f"  Type: NIW ({meta['projectNumber']})")
    print(f"  Exhibits: {len(exhibits)}")
    print(f"  Total pages: {metadata['stats']['total_pages']}")
    print(f"  Total blocks: {metadata['stats']['total_blocks']}")

    return project_id


def main():
    if not DATA_NIW.exists():
        print(f"ERROR: NIW data directory not found: {DATA_NIW}")
        sys.exit(1)

    person_dirs = [d for d in DATA_NIW.iterdir() if d.is_dir() and (d / "OCR").exists()]

    if not person_dirs:
        print("No NIW person folders found with OCR data")
        sys.exit(1)

    print(f"Found {len(person_dirs)} NIW projects to create\n")

    created = []
    for person_dir in sorted(person_dirs):
        person_name = person_dir.name
        print(f"{'='*60}")
        print(f"  Creating project: {person_name}")
        print(f"{'='*60}")
        project_id = create_project(person_name, person_dir)
        created.append(project_id)
        print()

    print(f"\nDone! Created {len(created)} NIW projects: {created}")


if __name__ == "__main__":
    main()
