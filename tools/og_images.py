# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10", "cairosvg>=2.7"]
# ///
"""Write the link-preview images under static/img/og/: a board render framed with the brand's red corner marks
and a small red wordmark, with a large headline in Audiowide (the site's display face) above it, inside a
1200x627 canvas (1.91:1 — at or above the 1.91 LinkedIn needs to show its large card instead of dropping to a
160px thumbnail, AGENTS.md "Link previews"), in two formats:

- A truecolour RGBA PNG (no palette quantization: a quantized version once came out blurry and posterised on
  LinkedIn's Post Inspector, Roman, 6 Nov 2026), on a transparent background, for twitter:image: X reads
  twitter:image first and shows it on its own light or dark theme. The headline is white with a dark outline,
  so it reads on X's light theme and its two dark ones alike.
- A truecolour JPEG (quality ~90, 4:4:4 chroma, no subsampling, progressive off), the same frame flattened onto
  white, for og:image: LinkedIn and Facebook show a card on white and fill a transparent image with a dull grey
  instead, which read as a worse block than a plain white background (Roman, round 4 of link previews). The
  headline is near-black, the brand's light-theme text colour.

Usage: uv run tools/og_images.py PATH/TO/Audiowide-Regular.ttf [--check]   (`just og [--check]`, the font path
from vhrd_brand, same as `just wordmark`: the font itself is baked into these raster images, never shipped)

Each page's og:image and twitter:image are either the site defaults (config.toml extra.og_image,
extra.twitter_image) or its own (templates/base.html); /donguru, /pinsmith, /can, /software and /work each show
their own board. LinkedIn's organic posts (not the paid kind) show a small ~160px thumbnail, centre-cropped from
the square middle of the card (opengraphplus.com/consumers/linkedin/issues/small-thumbnail): the board is kept
big and centred, well inside that square crop, so it still reads there. The headline is for the platforms that
show the large card instead (X, Facebook, Slack, messengers): it sits above the board and may run outside the
square crop, cut off in LinkedIn's small thumbnail — that is fine, since the board carries that one on its own.
tools/check_pages.py checks every page's og:image is a 1200x627 truecolour JPEG and its twitter:image a
1200x627 truecolour PNG with alpha. `--check` also writes the default and donguru images composited onto the
backgrounds the platforms that don't honour transparency fill it with (X's dark themes, Facebook's grey) at the
full card and the square crop, and both at LinkedIn's small-thumbnail size, into target/shots. A change to
IMAGES's file names here must be followed by the same names in config.toml, each page's own
extra.og_image / extra.twitter_image and AGENTS.md, so a platform that caches a preview by its image URL
fetches the new file instead of the old.
"""

import io
import re
import sys
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BOARDS = ROOT / "static/img/boards"
OUT = ROOT / "static/img/og"

# 1.91:1, what LinkedIn, Facebook and X use for a large card, and the minimum ratio LinkedIn needs to show one
# at all: a 1200x630 canvas (1.905:1) falls just under it and loses the large card, so this stays 1200x627
# (1.914:1) and is never changed to round the height (Roman, 6 Nov 2026, opengraphplus.com/consumers/
# linkedin/issues/small-thumbnail).
W, H = 1200, 627
MIN_CARD_RATIO = 1.91
# The board's own bounding box (the render's margin is transparent) is scaled to fit this box, centred
# horizontally on the canvas: well inside the HxH square a square crop keeps, with margin either side.
SAFE_W, SAFE_H = 580, 391
# The board's box sits in the lower part of the canvas, below the headline band (HEAD_Y to about this line).
BOARD_TOP = 216
# Truecolour, a few hundred KB each at most (LinkedIn and Facebook accept up to 5-8 MB; this stays well under
# that while loading fast). Quantizing the PNG to a 256-colour palette once made it blurry and posterised on
# LinkedIn's Post Inspector (Roman, 6 Nov 2026), so there is no quantize step there.
BUDGET_KB = 1024
JPEG_QUALITY = 90  # no subsampling (4:4:4) and not progressive, so a scraper that reads only the first bytes of
# a progressive JPEG (or one that chokes on 4:2:0 chroma) still gets the whole, sharp image

RED = (242, 76, 68, 255)  # vhrd_brand dark.red (#f24c44): reads on a white card and on a dark one alike
INK = (26, 26, 26, 255)  # vhrd_brand light.text (#1a1a1a): the JPEG headline, on white
GLOW = (255, 255, 255, 16)  # a faint halo behind the board, just enough that a dark board's edge doesn't vanish
# on a dark card; weak and tight enough that it doesn't read as a grey cloud on a white one (Roman, 6 Nov 2026)
MARK_LEN, MARK_W = 28, 5  # the corner marks' leg length and thickness, like .fig-frame's but sized for this canvas
FRAME_PAD = 20  # the corner-marked frame sits this far inside the square crop's left/right edges (and top/bottom)

# The headline: Audiowide (the wordmark's face), left-aligned above the board, big enough to read in a small
# card (cap height >=40px at this 1200px width) and wrapped to at most two lines. A name before " · " (the
# product headlines below) is set in the brand red, like the one accented word in the real page's hero
# headline; the rest is the body colour (AGENTS.md "Conventions").
HEAD_X, HEAD_Y = 48, 40
HEAD_MAX_WIDTH = W - 2 * HEAD_X
HEAD_TARGET_CAP = 48
HEAD_MIN_CAP = 40
HEAD_MAX_LINES = 2
HEAD_LINE_PITCH_FACTOR = 1.25
HEAD_STROKE_W = 3  # the PNG headline's dark outline, so white text reads on X's light theme too

# the image's base name (static/img/og/<name>.png, transparent, for twitter:image, and <name>.jpg, flattened
# onto white, for og:image), the board's render directory, its view, the image's alt text, and the headline.
# Each name carries a version so LinkedIn, Facebook and Telegram, which cache a preview by its image URL, fetch
# the new file instead of one they already have: "-4" for this round's headline and the /donguru image split
# off the site default (Roman, round 5 of link previews, 6 Nov 2026).
IMAGES = [
    ("default-4", "b153-donguru", "hero",
     "Donguru (B153), a USB-C dongle PCB, framed by red corner marks and the VHRD.TECH wordmark",
     "Instruments for embedded development"),
    ("donguru-4", "b153-donguru", "hero",
     "Donguru (B153), a USB-C dongle PCB, framed by red corner marks and the VHRD.TECH wordmark",
     "Donguru · one cable from your PC to your board"),
    ("pinsmith-4", "b200-re-port", "hero",
     "Pinsmith (B200), a USB I/O PCB, framed by red corner marks and the VHRD.TECH wordmark",
     "Pinsmith · digital and analog I/O over USB"),
    ("can-4", "b125-eth-2fdcan", "hero",
     "An Ethernet to dual isolated CAN FD bridge PCB (B125), framed by red corner marks and the VHRD.TECH wordmark",
     "The CAN line · USB and Ethernet to isolated CAN FD"),
    ("software-4", "b129-cannify-micro", "hero",
     "CANnify Micro (B129), a breadboard CAN FD node PCB, framed by red corner marks and the VHRD.TECH wordmark",
     "The software for our instruments"),
    ("work-4", "b135-usb-fdcan", "hero",
     "A USB to isolated CAN FD bridge PCB (B135), framed by red corner marks and the VHRD.TECH wordmark",
     "Boards and projects from the VHRD lab"),
]

# Backgrounds the transparent PNG (twitter:image) might be filled with instead of its own alpha: X's three
# themes (light, dim and lights-out) and Facebook/Messenger's card grey. LinkedIn no longer gets this file at
# all: og:image is the JPEG on white, since LinkedIn's Post Inspector showed the PNG blurry even once it was
# truecolour, and filled a transparent image's alpha with a dull grey rather than its own white card (Roman,
# round 4 of link previews, 6 Nov 2026).
PLATFORM_BACKGROUNDS = [
    ("white", (255, 255, 255)),
    ("xblack", (0, 0, 0)),
    ("xnavy", (0x15, 0x20, 0x2b)),
    ("grey", (0xf0, 0xf2, 0xf5)),
]
# The two names rendered into target/shots for a by-eye look (`--check`): the site default and /donguru's own,
# since both show the same board (B153) with different headlines.
SHOT_NAMES = ("default-4", "donguru-4")


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
    """Each corner as one flush L: a horizontal and a vertical bar sharing a MARK_W x MARK_W square at the
    pivot, like .fig-frame's CSS corners (two overlapping bars, not two separately-capped lines, which left a
    notch at the outer corner instead of a clean square point; Roman, 6 Nov 2026)."""
    x0, y0, x1, y1 = frame_box()
    d = ImageDraw.Draw(canvas)
    for cx, cy, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        hx0, hx1 = sorted((cx, cx + sx * MARK_LEN))
        hy0, hy1 = sorted((cy, cy + sy * MARK_W))
        d.rectangle([hx0, hy0, hx1, hy1], fill=RED)
        vx0, vx1 = sorted((cx, cx + sx * MARK_W))
        vy0, vy1 = sorted((cy, cy + sy * MARK_LEN))
        d.rectangle([vx0, vy0, vx1, vy1], fill=RED)


def font_for_cap_height(font_path, target_cap):
    """The Audiowide size whose capital letters are target_cap pixels tall, measured directly (fontTools'
    sCapHeight needs the font's own units-per-em table; this just renders "H" and measures its ink)."""
    size = round(target_cap / 0.7)
    probe = Image.new("RGBA", (4, 4))
    for _ in range(3):
        font = ImageFont.truetype(str(font_path), size)
        bbox = ImageDraw.Draw(probe).textbbox((0, 0), "H", font=font)
        cap = bbox[3] - bbox[1]
        if cap <= 0:
            break
        size = round(size * target_cap / cap)
    return ImageFont.truetype(str(font_path), size)


def wrap_headline(headline, font, max_width, max_lines):
    """headline's words, each with its original index (so the caller can colour the words before " · "
    differently), greedily wrapped to lines no wider than max_width. Shrinks nothing itself: the caller picks a
    smaller font and retries when the result is over max_lines."""
    words = list(enumerate(headline.split(" ")))
    space = font.getlength(" ")
    lines, line, line_w = [], [], 0.0
    for i, w in words:
        ww = font.getlength(w)
        add = ww if not line else ww + space
        if line and line_w + add > max_width:
            lines.append(line)
            line, line_w = [(i, w)], ww
        else:
            line.append((i, w))
            line_w += add
    if line:
        lines.append(line)
    return lines[:max_lines] if len(lines) > max_lines else lines, len(lines) <= max_lines


def draw_headline(canvas, font_path, headline, fill, stroke_fill=None):
    """The headline in Audiowide, left-aligned above the board: up to two lines, shrinking from
    HEAD_TARGET_CAP towards HEAD_MIN_CAP if it does not fit, the words up to " · " in the brand red."""
    cap = HEAD_TARGET_CAP
    while True:
        font = font_for_cap_height(font_path, cap)
        lines, fits = wrap_headline(headline, font, HEAD_MAX_WIDTH, HEAD_MAX_LINES)
        if fits or cap <= HEAD_MIN_CAP:
            break
        cap -= 2

    dot_at = next((i for i, w in enumerate(headline.split(" ")) if w == "·"), None)
    draw = ImageDraw.Draw(canvas)
    space = font.getlength(" ")
    line_pitch = round(font.size * HEAD_LINE_PITCH_FACTOR)
    y = HEAD_Y
    for line in lines:
        x = HEAD_X
        for i, word in line:
            colour = RED if dot_at is not None and i < dot_at else fill
            kwargs = {"stroke_width": HEAD_STROKE_W, "stroke_fill": stroke_fill} if stroke_fill else {}
            draw.text((x, y), word, font=font, fill=colour, **kwargs)
            x += font.getlength(word) + space
        y += line_pitch


def compose(board_dir, view, headline, font_path, headline_fill, headline_stroke=None):
    board = board_render(board_dir, view)
    scale = min(SAFE_W / board.width, SAFE_H / board.height)
    board = board.resize((round(board.width * scale), round(board.height * scale)), Image.LANCZOS)
    x = (W - board.width) // 2
    y = BOARD_TOP + (H - FRAME_PAD - BOARD_TOP - board.height) // 2

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # A faint halo behind the board: on a white or light card it stays close to invisible, on a dark one it
    # keeps a dark board's edge from vanishing into the background. Tight (a small pad, a short blur) so it
    # hugs the board's edge rather than reading as a grey cloud around it.
    pad = 18
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        [x - pad, y - pad, x + board.width + pad, y + board.height + pad], fill=GLOW
    )
    glow = glow.filter(ImageFilter.GaussianBlur(16))
    canvas.alpha_composite(glow)

    canvas.alpha_composite(board, (x, y))
    draw_corner_marks(canvas)

    fx0, fy0, fx1, fy1 = frame_box()
    wm_h = 20
    wm = wordmark_png(round(wm_h * 13424 / 1434), wm_h)
    wm_x, wm_y = fx1 - MARK_LEN - 10 - wm.width, fy1 - MARK_LEN - 10 - wm.height
    canvas.alpha_composite(wm, (wm_x, wm_y))

    draw_headline(canvas, font_path, headline, headline_fill, headline_stroke)

    return canvas, (x, y, x + board.width, y + board.height)


def square_crop(img):
    square_left, square_right = (W - H) // 2, (W - H) // 2 + H
    return img.crop((square_left, 0, square_right, H))


def write_shots(name, img):
    """One image, composited onto every platform background that doesn't honour transparency, at the full
    1.91:1 card and the 1:1 square crop, plus LinkedIn's small ~160px organic-post thumbnail at both ratios (on
    white, since og:image itself is already flattened there) — a by-eye look (AGENTS.md "Link previews")."""
    shots = ROOT / "target/shots"
    shots.mkdir(parents=True, exist_ok=True)
    for bg_name, rgb in PLATFORM_BACKGROUNDS:
        flat = Image.new("RGB", (W, H), rgb)
        flat.paste(img, (0, 0), img)
        flat.save(shots / f"og5-{name}-{bg_name}-191x1.png")
        square_crop(flat).save(shots / f"og5-{name}-{bg_name}-1x1.png")
    white = Image.new("RGB", (W, H), (255, 255, 255))
    white.paste(img, (0, 0), img)
    white.resize((160, round(160 * H / W)), Image.LANCZOS).save(shots / f"og5-{name}-thumb-191x1.png")
    square_crop(white).resize((160, 160), Image.LANCZOS).save(shots / f"og5-{name}-thumb-1x1.png")


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
    if W / H < MIN_CARD_RATIO:
        sys.exit(f"{W}x{H} is {W / H:.3f}:1, under the {MIN_CARD_RATIO}:1 LinkedIn needs for its large card")
    OUT.mkdir(parents=True, exist_ok=True)
    for name, board_dir, view, _, headline in IMAGES:
        img, bbox = compose(board_dir, view, headline, font_path, INK)
        # the square crop LinkedIn and messengers make from a 1.91:1 card: the middle H x H of the canvas
        square_left, square_right = (W - H) // 2, (W - H) // 2 + H
        if bbox[0] < square_left or bbox[2] > square_right:
            sys.exit(f"{name}: the board reaches x {bbox[0]}-{bbox[2]}, outside the {H}px square crop ({square_left}-{square_right})")
        # The transparent PNG, headline in white with a dark outline so it reads on X's light theme too. Kept
        # for twitter:image.
        png_img, _ = compose(board_dir, view, headline, font_path, (255, 255, 255, 255), INK)
        write_image(OUT / f"{name}.png", png_img, "PNG", optimize=True)
        # The same frame flattened onto white, headline in near-black, for og:image: quality ~90, 4:4:4 chroma
        # (subsampling=0) and not progressive, so LinkedIn and Facebook show it sharp on the white card they
        # composite it onto.
        flat = Image.new("RGB", (W, H), (255, 255, 255))
        flat.paste(img, (0, 0), img)
        write_image(OUT / f"{name}.jpg", flat, "JPEG", quality=JPEG_QUALITY, subsampling=0, progressive=False, optimize=True)
        if check and name in SHOT_NAMES:
            write_shots(name, png_img)
    if check:
        print(f"target/shots/og5-*.png written ({len(SHOT_NAMES)} images x ({len(PLATFORM_BACKGROUNDS)} backgrounds x 2 crops + 2 thumbnails))")


if __name__ == "__main__":
    main()
