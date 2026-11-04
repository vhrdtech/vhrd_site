# /// script
# requires-python = ">=3.11"
# dependencies = ["pymupdf"]
# ///
"""Render each page and extract embedded images (native resolution) from a PDF,
for reviewing which photos to pick. Run via `uv run extract_pages.py SRC.pdf OUT_DIR`.
"""
import sys

import pymupdf


def main():
    src, outdir = sys.argv[1], sys.argv[2]
    doc = pymupdf.open(src)
    for pno in range(len(doc)):
        page = doc[pno]
        pix = page.get_pixmap(dpi=120)
        pix.save(f"{outdir}/page{pno + 1:02d}.png")

        with open(f"{outdir}/page{pno + 1:02d}.txt", "w") as f:
            f.write(page.get_text().strip())

        for imgidx, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            base = doc.extract_image(xref)
            w, h = base.get("width"), base.get("height")
            fname = f"{outdir}/p{pno + 1:02d}_img{imgidx:02d}_{w}x{h}.{base['ext']}"
            with open(fname, "wb") as f:
                f.write(base["image"])

    print(f"done, {len(doc)} pages")


if __name__ == "__main__":
    main()
