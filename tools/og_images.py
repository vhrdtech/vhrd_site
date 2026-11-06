# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10"]
# ///
"""Write the link-preview images under static/img/og/ by rendering the SVGs in assets/og/ with resvg, in two
looks from the same file (AGENTS.md "Link previews"):

- `<name>.jpg`: resvg with assets/og/light.css (a white card, near-black headline), flattened onto white and
  saved as a truecolour JPEG (quality 90, 4:4:4 chroma, not progressive) — extra.og_image.
- `<name>.png`: resvg with assets/og/dark.css (a transparent card, white headline with a soft shadow), resvg's
  own truecolour RGBA PNG output, unchanged — extra.twitter_image.

Both are asserted 1200x627 (1.91:1, the ratio LinkedIn needs for its large card, AGENTS.md "Link previews").
The layout (corners, headline, board image, wordmark) lives in the SVG files, not here: open one in Inkscape
or a text editor, save, then run `just og` to re-render every image.

Usage: uv run tools/og_images.py PATH/TO/Audiowide-Regular.ttf [--check]   (`just og [--check]`, the font path
from vhrd_brand, same as `just wordmark`: the font itself is baked into these raster images, never shipped)

`--check` also writes the default and donguru images composited onto the backgrounds a platform that doesn't
honour transparency might fill it with (X's dark themes, Facebook's grey), at the full 1.91:1 card and the
1:1 square crop, plus both at LinkedIn's small ~160px organic-post thumbnail size, into target/shots.
"""

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets/og"
OUT = ROOT / "static/img/og"

W, H = 1200, 627
BUDGET_KB = 1024
JPEG_QUALITY = 90

# The six share images: assets/og/<name>.svg -> static/img/og/<name>.jpg and .png. "-5" since the rendering
# engine changed (SVG + resvg, not Python + Pillow layout): LinkedIn, Facebook and Telegram cache a preview by
# its image URL, so a changed image needs a new name too, or they go on showing the old file.
NAMES = ["default-5", "donguru-5", "pinsmith-5", "can-5", "software-5", "work-5"]

# Backgrounds the transparent PNG (twitter:image) might be filled with instead of its own alpha: X's three
# themes and Facebook/Messenger's card grey.
PLATFORM_BACKGROUNDS = [
    ("xlight", (255, 255, 255)),
    ("xblack", (0, 0, 0)),
    ("xnavy", (0x15, 0x20, 0x2b)),
    ("grey", (0xf0, 0xf2, 0xf5)),
]
SHOT_NAMES = ("default-5", "donguru-5")


def render(svg, stylesheet, font_path, out_png):
    resvg = shutil.which("resvg") or str(Path.home() / ".local/bin/resvg")
    subprocess.run(
        [resvg, "--use-font-file", str(font_path), "--stylesheet", str(stylesheet), str(svg), str(out_png)],
        check=True,
    )
    img = Image.open(out_png)
    if img.size != (W, H):
        sys.exit(f"{out_png}: resvg rendered {img.size}, expected {(W, H)} (check the SVG's width/height)")
    return img


def square_crop(img):
    left = (W - H) // 2
    return img.crop((left, 0, left + H, H))


def write_shots(name, jpeg_img, png_img):
    """A by-eye look at the og:image JPEG (on white) and the twitter:image PNG composited onto the backgrounds
    a platform that doesn't honour its transparency might fill it with, at the full card, the 1:1 crop and
    LinkedIn's small organic-post thumbnail (AGENTS.md "Link previews")."""
    shots = ROOT / "target/shots"
    shots.mkdir(parents=True, exist_ok=True)
    jpeg_img.save(shots / f"og5-{name}-white-191x1.png")
    square_crop(jpeg_img).save(shots / f"og5-{name}-white-1x1.png")
    jpeg_img.resize((160, round(160 * H / W)), Image.LANCZOS).save(shots / f"og5-{name}-thumb-191x1.png")
    square_crop(jpeg_img).resize((160, 160), Image.LANCZOS).save(shots / f"og5-{name}-thumb-1x1.png")
    for bg_name, rgb in PLATFORM_BACKGROUNDS:
        flat = Image.new("RGB", (W, H), rgb)
        flat.paste(png_img, (0, 0), png_img)
        flat.save(shots / f"og5-{name}-{bg_name}-191x1.png")
        square_crop(flat).save(shots / f"og5-{name}-{bg_name}-1x1.png")


def write_image(path, img, fmt, **kwargs):
    img.save(path, fmt, **kwargs)
    kb = path.stat().st_size / 1024
    print(f"{path.relative_to(ROOT)}: {img.width}x{img.height}, {kb:.0f} KB")
    if kb > BUDGET_KB:
        sys.exit(f"{path}: {kb:.0f} KB, over the {BUDGET_KB} KB budget")


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith("--"):
        sys.exit(f"usage: {sys.argv[0]} PATH/TO/Audiowide-Regular.ttf [--check]")
    font_path = Path(sys.argv[1])
    check = "--check" in sys.argv[2:]
    OUT.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        base = name.rsplit("-", 1)[0]
        svg = ASSETS / f"{base}.svg"

        light_png = render(svg, ASSETS / "light.css", font_path, OUT / f"{name}-light-tmp.png")
        flat = Image.new("RGB", (W, H), (255, 255, 255))
        flat.paste(light_png, (0, 0), light_png)
        write_image(OUT / f"{name}.jpg", flat, "JPEG", quality=JPEG_QUALITY, subsampling=0, progressive=False, optimize=True)
        (OUT / f"{name}-light-tmp.png").unlink()

        png_img = render(svg, ASSETS / "dark.css", font_path, OUT / f"{name}.png")
        write_image(OUT / f"{name}.png", png_img, "PNG", optimize=True)

        if check and name in SHOT_NAMES:
            write_shots(name, flat, png_img)
    if check:
        print(f"target/shots/og5-*.png written ({len(SHOT_NAMES)} images x ({len(PLATFORM_BACKGROUNDS)} backgrounds x 2 crops + 2 thumbnails))")


if __name__ == "__main__":
    main()
