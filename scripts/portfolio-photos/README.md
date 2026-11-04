# portfolio-photos

Pulls own-work photos from Roman's portfolio PDF into `static/img/lab/`.

1. `uv run extract_pages.py SRC.pdf REVIEW_DIR` — renders every page and dumps
   each embedded image at native resolution into `REVIEW_DIR`, for picking.
2. `uv run build_lab_images.py REVIEW_DIR OUT_ROOT` — crops the images named in
   its `ITEMS` table and encodes them to AVIF + WebP at 640/1280/1920px wide
   (never upscaled) under `OUT_ROOT/<slug>/`.

`ITEMS` in `build_lab_images.py` is the record of which page, which embedded
image and which crop was picked for each cleared item (P2633#4nov-0920); it
only covers the items cleared 4 Nov 2026, not the whole portfolio.
