"""Render the bundle's exhibit pages to images.

The evidence viewer and the magnifier were drawing the document as grey bars.
That came straight from the interface mockup, where a wireframe placeholder is
the right thing; it is not the right thing once a participant is being asked to
check a sentence against the page it cites.

Three of the five planted-error kinds -- wrong_exhibit, overstated,
stale_qualifier -- are defined as findable only by opening the exhibit and
reading it. `source_opened` and the magnifier dwell time are dependent
variables. And the whole reason the bundle stores a normalised bbox is to put a
highlight on the page. None of that means anything against grey bars.

Output: `pages/<EXHIBIT>/<n>.jpg`, one per page, plus a `pages/index.json`
recording each page's rendered pixel size and its aspect ratio. The bbox stays
in its 0-1000 space (红线 #8); the client scales it to whatever size the image
is displayed at, so the highlight lands correctly at any zoom.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PDF_ROOT = Path(r"F:/Python-Project/Arbor_CHI_2027/data/Dehuan Liu/PDF")
BUNDLE_ROOT = Path(__file__).resolve().parents[1] / "study_materials"

# Wide enough for the magnifier (its card is min(1080px, 86vw)) with room to
# zoom, small enough that a session does not spend its first minute loading.
TARGET_WIDTH = 1400


def source_pdf(exhibit_dir: str) -> Path:
    """c1 -> PDF/C/c1.pdf"""
    group = exhibit_dir[0].upper()
    return PDF_ROOT / group / f"{exhibit_dir}.pdf"


def dir_for(display_id: str) -> str:
    """C-1 -> c1, matching the source tree."""
    return display_id.replace("-", "").lower()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--material", default="judging_v1")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise SystemExit("PyMuPDF is required: pip install pymupdf") from None

    bundle = BUNDLE_ROOT / args.material
    snippets = json.loads((bundle / "snippets.json").read_text(encoding="utf-8"))
    out_root = bundle / "pages"
    out_root.mkdir(parents=True, exist_ok=True)

    index: dict = {}
    total = 0
    for ex in snippets["exhibits"]:
        display_id = ex["id"]
        pdf_path = source_pdf(dir_for(display_id))
        if not pdf_path.exists():
            raise SystemExit(f"no PDF for {display_id} at {pdf_path}")

        doc = fitz.open(pdf_path)
        if doc.page_count != ex["pages"]:
            # The OCR page count and the PDF's must agree, or a citation to
            # "p.5" points at a different page than the one that was read.
            raise SystemExit(
                f"{display_id}: OCR says {ex['pages']} pages, PDF has {doc.page_count}")

        target = out_root / display_id
        target.mkdir(exist_ok=True)
        pages = []
        for n in range(doc.page_count):
            page = doc[n]
            out = target / f"{n + 1}.jpg"
            if out.exists() and not args.force:
                pages.append(index.get(display_id, {}).get("pages", [{}])[0])
                continue
            zoom = TARGET_WIDTH / page.rect.width
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            pix.save(out, jpg_quality=82)
            pages.append({"page": n + 1, "w": pix.width, "h": pix.height})
            total += 1
        doc.close()
        index[display_id] = {"pages": pages}
        print(f"  {display_id}: {len(pages)} pages")

    (out_root / "index.json").write_text(
        json.dumps({"schema_version": 1, "target_width": TARGET_WIDTH,
                    "exhibits": index}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    size = sum(p.stat().st_size for p in out_root.rglob("*.jpg"))
    print(f"\n{total} pages rendered, {size / 1e6:.1f} MB -> {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
