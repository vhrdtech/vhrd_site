# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10", "cairosvg>=2.7"]
# ///
"""Write the link-preview images (og:image, twitter:image) under static/img/og/: a board render on a transparent
background, framed with the brand's red corner marks and a small red wordmark, inside a 1200x627 canvas (1.91:1,
what LinkedIn, Facebook and X use for a large card).

Usage: uv run tools/og_images.py   (just og)

Each page's og:image is either the site default (config.toml extra.og_image) or its own extra.og_image
(templates/base.html); /donguru, /pinsmith, /can, /software and /work each show their own board. The board sits
inside SAFE_W x SAFE_H, centred, well inside the square crop (image height x image height) that LinkedIn,
messengers and some crawlers make from a wide card, so the whole board and the frame stay in view there too.
tools/check_pages.py checks every page's og:image exists at 1200x627; `--check` also writes the default image's
two crops, and composited onto the backgrounds the platforms that don't honour transparency fill it with
(white, X's dark themes, Facebook's grey), into target/shots.
"""

import io
import re
import sys
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
BOARDS = ROOT / "static/img/boards"
OUT = ROOT / "static/img/og"

W, H = 1200, 627
# The board's own bounding box (the render's margin is transparent) is scaled to fit this box, centred on the
# canvas: well inside the HxH square a square crop keeps, with margin either side (vertically, the full height).
SAFE_W, SAFE_H = 580, 480
BUDGET_KB = 400

RED = (242, 76, 68, 255)  # vhrd_brand dark.red (#f24c44): reads on a white card and on a dark one alike
GLOW = (255, 255, 255, 60)  # a soft halo behind the board, so a dark board's edge doesn't vanish on a dark card
MARK_LEN, MARK_W = 28, 3  # the corner marks' leg length and thickness, like .fig-frame's but sized for this canvas
FRAME_PAD = 20  # the corner-marked frame sits this far inside the square crop's left/right edges (and top/bottom)

# name (static/img/og/<name>.png), the board's render directory, its view, and the image's alt text.
IMAGES = [
    ("default", "b153-donguru", "hero", "Donguru (B153), a USB-C dongle PCB, on a dark background"),
    ("pinsmith", "b200-re-port", "hero", "Pinsmith (B200), a USB I/O PCB, on a dark background"),
    ("can", "b125-eth-2fdcan", "hero", "An Ethernet to dual isolated CAN FD bridge PCB (B125), on a dark background"),
    ("software", "b129-cannify-micro", "hero", "CANnify Micro (B129), a breadboard CAN FD node PCB, on a dark background"),
    ("work", "b135-usb-fdcan", "hero", "A USB to isolated CAN FD bridge PCB (B135), on a dark background"),
]

# Backgrounds the platforms fill transparency with instead of honouring it (LinkedIn and X show the image as it
# is): Facebook/Messenger's card grey, and X's own light and dark themes.
PLATFORM_BACKGROUNDS = [
    ("white", (255, 255, 255)),
    ("xblack", (0, 0, 0)),
    ("xnavy", (0x15, 0x20, 0x2b)),
    ("grey", (0xf0, 0xf2, 0xf5)),
]


def frame_box():
    square_left, square_right = (W - H) // 2, (W - H) // 2 + H
    return square_left + FRAME_PAD, FRAME_PAD, square_right - FRAME_PAD, H - FRAME_PAD


def board_render(board_dir, view):
    """The board's render, cropped to its own content (the source PNG's margin is transparent)."""
    png = BOARDS / board_dir / f"{board_dir.split('-')[0]}_{view}.png"
    im = Image.open(png).convert("RGBA")
    box = im.getbbox()
    if box is None:
        sys.exit(f"{png}: fully transparent, nothing to crop to")
    return im.crop(box)


def wordmark_png(width, height):
    """The VHRD.TECH wordmark (static/img/wordmark.svg), recoloured to a single red that reads on white and on
    black alike, rasterised to the given pixel size with a transparent background."""
    svg = (ROOT / "static/img/wordmark.svg").read_text()
    svg = re.sub(r'fill="#[0-9a-fA-F]{6}"', f'fill="rgb{RED[:3]}"', svg)
    png_bytes = cairosvg.svg2png(bytestring=svg.encode(), output_width=width, output_height=height)
    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")


def draw_corner_marks(canvas):
    x0, y0, x1, y1 = frame_box()
    d = ImageDraw.Draw(canvas)
    for cx, cy, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        d.line([(cx, cy), (cx + sx * MARK_LEN, cy)], fill=RED, width=MARK_W)
        d.line([(cx, cy), (cx, cy + sy * MARK_LEN)], fill=RED, width=MARK_W)


def compose(board_dir, view):
    board = board_render(board_dir, view)
    scale = min(SAFE_W / board.width, SAFE_H / board.height)
    board = board.resize((round(board.width * scale), round(board.height * scale)), Image.LANCZOS)
    x, y = (W - board.width) // 2, (H - board.height) // 2

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # A soft halo behind the board: on a white or light card it blends away, on a dark one it keeps a dark
    # board's edge from vanishing into the background.
    pad = 60
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        [x - pad, y - pad, x + board.width + pad, y + board.height + pad], fill=GLOW
    )
    glow = glow.filter(ImageFilter.GaussianBlur(40))
    canvas.alpha_composite(glow)

    canvas.alpha_composite(board, (x, y))
    draw_corner_marks(canvas)

    fx0, fy0, fx1, fy1 = frame_box()
    wm_h = 15
    wm = wordmark_png(round(wm_h * 13424 / 1434), wm_h)
    wm_x, wm_y = fx1 - MARK_LEN - 10 - wm.width, fy1 - MARK_LEN - 10 - wm.height
    canvas.alpha_composite(wm, (wm_x, wm_y))

    return canvas, (x, y, x + board.width, y + board.height)


def write_shots(img):
    """The default image, composited onto every platform background that doesn't honour transparency, at the
    full 1.91:1 card and the 1:1 crop a square-crop platform keeps, for a by-eye look (AGENTS.md "Link previews")."""
    shots = ROOT / "target/shots"
    shots.mkdir(parents=True, exist_ok=True)
    square_left, square_right = (W - H) // 2, (W - H) // 2 + H
    for name, rgb in PLATFORM_BACKGROUNDS:
        flat = Image.new("RGB", (W, H), rgb)
        flat.paste(img, (0, 0), img)
        flat.save(shots / f"og2-{name}-191x1.png")
        flat.crop((square_left, 0, square_right, H)).save(shots / f"og2-{name}-1x1.png")
    print(f"{shots}/og2-*.png written ({len(PLATFORM_BACKGROUNDS)} backgrounds x 2 crops)")


def main():
    check = "--check" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    for name, board_dir, view, _ in IMAGES:
        img, bbox = compose(board_dir, view)
        # the square crop LinkedIn and messengers make from a 1.91:1 card: the middle H x H of the canvas
        square_left, square_right = (W - H) // 2, (W - H) // 2 + H
        if bbox[0] < square_left or bbox[2] > square_right:
            sys.exit(f"{name}: the board reaches x {bbox[0]}-{bbox[2]}, outside the {H}px square crop ({square_left}-{square_right})")
        path = OUT / f"{name}.png"
        # Flat CAD-render colours and a soft glow and few alpha levels: quantizing loses nothing visible and
        # turns a lossless RGBA PNG from (for a photo) over a megabyte into one well inside the budget.
        img.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).save(
            path, "PNG", optimize=True
        )
        kb = path.stat().st_size / 1024
        print(f"{path.relative_to(ROOT)}: {img.width}x{img.height}, {kb:.0f} KB")
        if kb > BUDGET_KB:
            sys.exit(f"{path}: {kb:.0f} KB, over the {BUDGET_KB} KB budget")
        if name == "default" and check:
            write_shots(img)


if __name__ == "__main__":
    main()
