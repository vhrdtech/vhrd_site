# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Crop, resize and encode the chosen portfolio photos into static/img/lab/<slug>/
as AVIF + WebP at 640/1280/1920px wide (never upscaled past the source).

Source images come from extract_pages.py's output. Run via:
    uv run build_lab_images.py REVIEW_DIR OUT_ROOT

The ITEMS table below records exactly which embedded image (by the filename
extract_pages.py gives it, WxH included) was picked for each cleared lab
item, and the crop box used to clean up the frame. Re-run after re-extracting
to reproduce the same output from the same source PDF.
"""
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

WIDTHS = [640, 1280, 1920]
AVIF_Q = "68"
WEBP_Q = 82

# slug -> [(source filename in REVIEW_DIR, crop_box_or_None, output_basename[, corner_radius]), ...]
# A corner radius (px of the cropped source) cuts the corners round and keeps them transparent: for app windows.
ITEMS = {
    "thermocouple-afe": [
        ("p03_img06_532x982.png", None, "thermocouple-afe"),
    ],
    "can-servo-controller": [
        ("p03_img05_466x566.png", None, "can-servo-controller"),
    ],
    "raspberry-pi-carrier": [
        ("p03_img07_606x458.png", None, "raspberry-pi-carrier"),
    ],
    "bms-50a-100a": [
        ("p06_img02_646x1007.png", None, "bms-50a-100a"),
    ],
    "torque-sensor-afe": [
        ("p08_img04_753x703.png", None, "torque-sensor-afe"),
    ],
    "motor-controller-6step-foc": [
        ("p08_img02_588x294.png", None, "motor-controller-6step-foc"),
    ],
    "propeller-test-stand": [
        ("p08_img05_1280x960.jpeg", None, "propeller-test-stand"),
    ],
    "lab": [
        ("p13_img01_1867x1400.jpeg", None, "lab-1"),
        ("p13_img02_1951x1463.jpeg", None, "lab-2"),
    ],
    "laser-scanner-aoi": [
        ("p14_img04_1117x1004.png", None, "laser-scanner-aoi-1"),
        # crop out the monitor/code on the left of the full-rig photo
        ("p14_img01_1673x1255.jpeg", (600, 0, 1673, 1255), "laser-scanner-aoi-2"),
        ("p14_img00_946x1261.jpeg", None, "laser-scanner-aoi-3"),
        # the board on the linear rails, cut to 4:3 around the carriages
        ("p14_img02_952x1269.jpeg", (0, 230, 952, 944), "laser-scanner-aoi-rails"),
    ],
    # RockFace under its old name, "MCU tracer - debugger" (page 9): the whole window for the software panel, and
    # the left part of the timeline view alone for the lab card (4:3, its labels readable at card size; Roman,
    # 4 Nov 2026). The log view crop is kept for later use.
    "rockface": [
        ("p09_img00_1830x1456.png", (112, 76, 1718, 1308), "rockface-window", 20),
        ("p09_img00_1830x1456.png", (126, 676, 686, 1096), "rockface-log"),
        ("p09_img00_1830x1456.png", (126, 188, 610, 551), "rockface-timeline"),
    ],
    "granite-cnc": [
        ("p18_img02_2021x1617.jpeg", None, "granite-cnc-1"),
        ("p18_img01_2021x1617.jpeg", None, "granite-cnc-2"),
        ("p18_img00_803x642.jpeg", None, "granite-cnc-3"),
    ],
    "eskate-elongboard": [
        ("p17_img01_1946x836.png", None, "eskate-elongboard-1"),
        ("p17_img00_978x1303.png", None, "eskate-elongboard-2"),
    ],
}


def process_image(src_path: Path, crop_box, out_dir: Path, out_basename: str, radius: int = 0):
    im = Image.open(src_path).convert("RGB")
    if crop_box:
        im = im.crop(crop_box)
    if radius:
        mask = Image.new("L", im.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.size[0] - 1, im.size[1] - 1), radius, fill=255)
        im.putalpha(mask)
    native_w, native_h = im.size
    widths = [w for w in WIDTHS if w <= native_w] or [native_w]
    produced = []
    for w in widths:
        h = round(native_h * w / native_w)
        resized = im.resize((w, h), Image.LANCZOS) if w != native_w else im

        webp_path = out_dir / f"{out_basename}-{w}.webp"
        resized.save(webp_path, "WEBP", quality=WEBP_Q, method=6)

        png_tmp = out_dir / f"_tmp_{out_basename}_{w}.png"
        resized.save(png_tmp, "PNG")
        avif_path = out_dir / f"{out_basename}-{w}.avif"
        subprocess.run(
            ["avifenc", "-q", AVIF_Q, "-s", "6", str(png_tmp), str(avif_path)],
            check=True,
            capture_output=True,
        )
        png_tmp.unlink()
        produced.append((w, h))
    return produced


def main():
    review_dir = Path(sys.argv[1])
    out_root = Path(sys.argv[2])
    only = set(sys.argv[3:])  # optional: build just these slugs or output names
    for slug, images in ITEMS.items():
        out_dir = out_root / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        for src_name, crop_box, out_basename, *radius in images:
            if only and slug not in only and out_basename not in only:
                continue
            produced = process_image(review_dir / src_name, crop_box, out_dir, out_basename, *radius)
            print(f"{slug}/{out_basename}: widths {produced}")


if __name__ == "__main__":
    main()
