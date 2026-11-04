# portfolio-photos

Pulls own-work photos from Roman's portfolio PDF into `static/img/lab/`.

1. `uv run extract_pages.py SRC.pdf REVIEW_DIR` — renders every page and dumps
   each embedded image at native resolution into `REVIEW_DIR`, for picking.
2. `uv run build_lab_images.py REVIEW_DIR OUT_ROOT [NAME ...]` — crops the images named in
   its `ITEMS` table and encodes them to AVIF + WebP at 640/1280/1920px wide
   (never upscaled) under `OUT_ROOT/<slug>/`. With NAMEs (slugs or output names) it builds only those.

`ITEMS` in `build_lab_images.py` is the record of which page, which embedded
image and which crop was picked for each cleared item (P2633#4nov-0920); it
only covers the items cleared 4 Nov 2026, not the whole portfolio.

The photos Roman sent on 4 Nov 2026 (lab equipment, the real B135 rev B, B156, VG095 and a third mx3 window) are in the same table, built from `~/Downloads/site` as REVIEW_DIR: `uv run build_lab_images.py ~/Downloads/site ../../static/img/lab lab-equipment b135-photo just-screw-it vg095-eth-can mx3-bom-cost`. Every output carries only the pixels: no EXIF, GPS or camera data.
