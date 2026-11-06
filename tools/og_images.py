# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10"]
# ///
"""Write the link-preview images (og:image, twitter:image) under static/img/og/: a board render centred on the
site's dark background, inside a 1200x627 canvas (1.91:1, what LinkedIn, Facebook and X use for a large card).

Usage: uv run tools/og_images.py   (just og)

Each page's og:image is either the site default (config.toml extra.og_image) or its own extra.og_image
(templates/base.html); /donguru, /pinsmith, /can, /software and /work each show their own board. The board sits
inside SAFE_W x SAFE_H, centred, well inside the square crop (image height x image height) that LinkedIn,
messengers and some crawlers make from a wide card, so the whole board stays in view there too: tools/check_pages.py
checks every page's og:image exists at 1200x627; `--check` also writes the two crops of the default image into
target/shots, for a by-eye look at both.
"""

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
BOARDS = ROOT / "static/img/boards"
OUT = ROOT / "static/img/og"

W, H = 1200, 627
BG = (15, 15, 16)  # --bg, dark (static/css/brand/tokens.css)
# The board's own bounding box (the render's margin is transparent) is scaled to fit this box, centred on the
# canvas: well inside the HxH square a square crop keeps, with margin either side (vertically, the full height).
SAFE_W, SAFE_H = 600, 500
BUDGET_KB = 300

# name (static/img/og/<name>.jpg), the board's render directory, its view, and the image's alt text.
IMAGES = [
    ("default", "b153-donguru", "hero", "Donguru (B153), a USB-C dongle PCB, on a dark background"),
    ("pinsmith", "b200-re-port", "hero", "Pinsmith (B200), a USB I/O PCB, on a dark background"),
    ("can", "b125-eth-2fdcan", "hero", "An Ethernet to dual isolated CAN FD bridge PCB (B125), on a dark background"),
    ("software", "b129-cannify-micro", "hero", "CANnify Micro (B129), a breadboard CAN FD node PCB, on a dark background"),
    ("work", "b135-usb-fdcan", "hero", "A USB to isolated CAN FD bridge PCB (B135), on a dark background"),
]


def board_render(board_dir, view):
    """The board's render, cropped to its own content (the source PNG's margin is transparent)."""
    png = BOARDS / board_dir / f"{board_dir.split('-')[0]}_{view}.png"
    im = Image.open(png).convert("RGBA")
    box = im.getbbox()
    if box is None:
        sys.exit(f"{png}: fully transparent, nothing to crop to")
    return im.crop(box)


def compose(board_dir, view):
    board = board_render(board_dir, view)
    scale = min(SAFE_W / board.width, SAFE_H / board.height)
    board = board.resize((round(board.width * scale), round(board.height * scale)), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H), BG)
    x, y = (W - board.width) // 2, (H - board.height) // 2
    canvas.paste(board, (x, y), board)
    return canvas, (x, y, x + board.width, y + board.height)


def main():
    check = "--check" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    for name, board_dir, view, _ in IMAGES:
        img, bbox = compose(board_dir, view)
        # the square crop LinkedIn and messengers make from a 1.91:1 card: the middle H x H of the canvas
        square_left, square_right = (W - H) // 2, (W - H) // 2 + H
        if bbox[0] < square_left or bbox[2] > square_right:
            sys.exit(f"{name}: the board reaches x {bbox[0]}-{bbox[2]}, outside the {H}px square crop ({square_left}-{square_right})")
        path = OUT / f"{name}.jpg"
        img.save(path, "JPEG", quality=85, optimize=True)
        kb = path.stat().st_size / 1024
        print(f"{path.relative_to(ROOT)}: {img.width}x{img.height}, {kb:.0f} KB")
        if kb > BUDGET_KB:
            sys.exit(f"{path}: {kb:.0f} KB, over the {BUDGET_KB} KB budget")
        if name == "default" and check:
            shots = ROOT / "target/shots"
            shots.mkdir(parents=True, exist_ok=True)
            img.crop((square_left, 0, square_right, H)).save(shots / "og-default-1x1.png")
            img.save(shots / "og-default-191x1.png")
            print(f"{shots / 'og-default-1x1.png'}, {shots / 'og-default-191x1.png'} written")


if __name__ == "__main__":
    main()
