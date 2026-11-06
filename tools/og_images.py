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
  twitter:image first and shows it on its own light or dark theme. The headline is solid white with a soft dark
  shadow (not an outline), so it reads on X's light theme and its two dark ones alike.
- A truecolour JPEG (quality ~90, 4:4:4 chroma, no subsampling, progressive off), the same frame flattened onto
  white, for og:image: LinkedIn and Facebook show a card on white and fill a transparent image with a dull grey
  instead, which read as a worse block than a plain white background (Roman, round 4 of link previews). The
  headline is solid near-black, the brand's light-theme text colour.

Usage: uv run tools/og_images.py PATH/TO/Audiowide-Regular.ttf [--check]   (`just og [--check]`, the font path
from vhrd_brand, same as `just wordmark`: the font itself is baked into these raster images, never shipped)

Each page's og:image and twitter:image are either the site defaults (config.toml extra.og_image,
extra.twitter_image) or its own (templates/base.html); /donguru, /pinsmith, /can, /software and /work each show
their own board. LinkedIn's organic posts (not the paid kind) show a small ~160px thumbnail, centre-cropped from
the square middle of the card (opengraphplus.com/consumers/linkedin/issues/small-thumbnail): the board is kept
big and centred, well inside that square crop, so it still reads there. The corner marks sit near the card's own
edges, enclosing the headline, the board and the wordmark alike, with a margin; the corners and the headline are
cut off by LinkedIn's narrower 1:1 centre crop — that is fine, since only the board needs to survive it, and it
does. tools/check_pages.py checks every page's og:image is a 1200x627 truecolour JPEG and its twitter:image a
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
# Truecolour, a few hundred KB each at most (LinkedIn and Facebook accept up to 5-8 MB; this stays well under
# that while loading fast). Quantizing the PNG to a 256-colour palette once made it blurry and posterised on
# LinkedIn's Post Inspector (Roman, 6 Nov 2026), so there is no quantize step there.
BUDGET_KB = 1024
JPEG_QUALITY = 90  # no subsampling (4:4:4) and not progressive, so a scraper that reads only the first bytes of
# a progressive JPEG (or one that chokes on 4:2:0 chroma) still gets the whole, sharp image

# One red per image, not two side by side: on the JPEG (white) everything red — corners, wordmark, the
# headline's product name — is vhrd_brand's light-theme --vhrd-red/--accent; on the PNG (dark backgrounds)
# everything red is the dark-theme --accent, already lightened for contrast there (Roman, round 5, "two reds"
# pass, 6 Nov 2026).
LIGHT_RED = (0xc8, 0x14, 0x1c, 255)  # --vhrd-red / light.accent (#c8141c)
DARK_RED = (242, 76, 68, 255)  # dark.accent (#f24c44)
INK = (26, 26, 26, 255)  # vhrd_brand light.text (#1a1a1a): the JPEG headline's body colour, solid, on white
WHITE = (255, 255, 255, 255)  # the PNG headline's body colour, solid, with a soft dark shadow (SHADOW_* below)
GLOW = (255, 255, 255, 16)  # a faint halo behind the board, just enough that a dark board's edge doesn't vanish
# on a dark card; weak and tight enough that it doesn't read as a grey cloud on a white one (Roman, 6 Nov 2026)
MARK_LEN, MARK_W = 28, 5  # the corner marks' leg length and thickness, like .fig-frame's but sized for this canvas
# The four corners sit near the card's own edges, not the square crop's: an even inset from all four sides of
# the full 1200x627 canvas, so headline, board and wordmark all sit inside them with a margin. They are cut by
# LinkedIn's 1:1 centre crop — fine, the board alone is kept centred and big enough for that crop (Roman,
# round 5, 6 Nov 2026).
FRAME_MARGIN = 32
# The headline's top, clear of the top corner marks' own legs (MARK_LEN tall) with a small margin: "the
# headline's cap top" sits this far below the frame's own top edge. The wordmark's bottom (its baseline)
# mirrors this same gap up from the frame's bottom edge (BOARD_CORNER_GAP and the wordmark placement in
# compose(), below) — the same distance on both ends, by design, not two independent numbers (Roman, round 5,
# "mirror" pass, 6 Nov 2026).
CONTENT_PAD_X = 16
CONTENT_PAD_Y_TOP = MARK_LEN + 2

# The headline: Audiowide (the wordmark's face), its capital letters' ink flush with the left corners' own
# outer edge (not an extra inset — "the D of Donguru" sits on the imaginary line the corner marks' vertical
# strokes draw), wrapped to at most two lines at HEAD_TARGET_CAP, the floor from "no small print" (every
# headline below fits two lines there). The words up to " · " (the product headlines below) are set in that
# image's one red (LIGHT_RED or DARK_RED above); the rest is the body colour (AGENTS.md "Conventions", Roman,
# round 5, 6 Nov 2026).
HEAD_TARGET_CAP = 40
HEAD_MIN_CAP = 40
HEAD_MAX_LINES = 2
HEAD_LINE_PITCH_FACTOR = 1.25
HEAD_BLOCK_BUFFER = 4  # added to each headline's own measured ink height (fit_headline) rather than
# reserving one worst-case height on every page: a one-line headline (/software) leaves the board that much
# more room below it, instead of a dead gap (Roman, round 5, "board bigger" pass, 6 Nov 2026).
HEAD_BOARD_GAP = 22  # a clearly visible gap (the headline sat right on top of the board two passes ago, at
# 16): less than the 32 the previous pass used, traded for a bigger board, but still twice that original gap.

# The board's own bounding box (the render's margin is transparent) is scaled to fit this box, centred
# horizontally on the canvas and vertically in the band below the headline and its gap. Its bottom edge may
# now come within BOARD_CORNER_GAP of the bottom corner marks' own legs — closer than the margin the headline
# and the wordmark keep, since the board's width never reaches the legs' x-range (they sit only in the outer
# ~60px either side, the board nowhere near that once centred within SAFE_W) — never touching them, but no
# longer held back by the wordmark either: the wordmark now sits over the board's own area near the corner,
# not in a separate row below it (Roman, round 5, "board bigger, again" pass, 6 Nov 2026).
SAFE_W = 580
BOARD_CORNER_GAP = 14  # within Roman's given 12-16px
WORDMARK_H = 33  # 1.25x the previous round's 26px (Roman, round 5, "mirror" pass, 6 Nov 2026)
# A soft dark shadow behind the white PNG headline (not an outline, which read as hollow), so it still reads on
# a light background once a platform composites the transparency away.
SHADOW_COLOR = (8, 8, 10, 170)
SHADOW_OFFSET = (0, 3)
SHADOW_BLUR = 4

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
    ("xlight", (255, 255, 255)),
    ("xblack", (0, 0, 0)),
    ("xnavy", (0x15, 0x20, 0x2b)),
    ("grey", (0xf0, 0xf2, 0xf5)),
]
# The two names rendered into target/shots for a by-eye look (`--check`): the site default and /donguru's own,
# since both show the same board (B153) with different headlines.
SHOT_NAMES = ("default-4", "donguru-4")


def frame_box():
    return FRAME_MARGIN, FRAME_MARGIN, W - FRAME_MARGIN, H - FRAME_MARGIN


def head_top():
    """The headline's cap top: this far below the frame's own top edge, clear of the top corner marks' own
    legs. The wordmark's bottom mirrors this same distance up from the frame's bottom edge (compose())."""
    return frame_box()[1] + CONTENT_PAD_Y_TOP


def board_render(board_dir, view):
    """The board's render, cropped to its own content (the source PNG's margin is transparent)."""
    png = BOARDS / board_dir / f"{board_dir.split('-')[0]}_{view}.png"
    im = Image.open(png).convert("RGBA")
    box = im.getbbox()
    if box is None:
        sys.exit(f"{png}: fully transparent, nothing to crop to")
    return im.crop(box)


def wordmark_png(width, height, red):
    """The VHRD.TECH wordmark (static/img/wordmark.svg), recoloured to this image's one red, rasterised to the
    given pixel size with a transparent background, then cropped to its own ink (not the raster canvas, which
    may carry a little padding) so the caller can align its right edge exactly."""
    svg = (ROOT / "static/img/wordmark.svg").read_text()
    svg = re.sub(r'fill="#[0-9a-fA-F]{6}"', f'fill="rgb{red[:3]}"', svg)
    png_bytes = cairosvg.svg2png(bytestring=svg.encode(), output_width=width, output_height=height)
    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return im.crop(im.getbbox())


def draw_corner_marks(canvas, red):
    """Each corner as one flush L: a horizontal and a vertical bar sharing a MARK_W x MARK_W square at the
    pivot, like .fig-frame's CSS corners (two overlapping bars, not two separately-capped lines, which left a
    notch at the outer corner instead of a clean square point; Roman, 6 Nov 2026)."""
    x0, y0, x1, y1 = frame_box()
    d = ImageDraw.Draw(canvas)
    for cx, cy, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        hx0, hx1 = sorted((cx, cx + sx * MARK_LEN))
        hy0, hy1 = sorted((cy, cy + sy * MARK_W))
        d.rectangle([hx0, hy0, hx1, hy1], fill=red)
        vx0, vx1 = sorted((cx, cx + sx * MARK_W))
        vy0, vy1 = sorted((cy, cy + sy * MARK_LEN))
        d.rectangle([vx0, vy0, vx1, vy1], fill=red)


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


def fit_headline(font_path, headline):
    """The Audiowide font, wrapped lines and left x (the first glyph's own ink, not its left side bearing,
    flush with the frame's left edge — "the D of Donguru" on the left corners' outer vertical stroke, every
    image) for this headline at HEAD_TARGET_CAP, shrinking towards HEAD_MIN_CAP if it somehow does not fit two
    lines. Also the line pitch and the actual ink height of the wrapped block: a one-line headline (/software)
    measures far less than a two-line one, so the caller can give the board that difference back rather than
    reserving a worst-case height on every page (Roman, round 5, "board bigger" pass, 6 Nov 2026)."""
    fx0, _, fx1, _ = frame_box()
    scratch = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    cap = HEAD_TARGET_CAP
    while True:
        font = font_for_cap_height(font_path, cap)
        # the wrap width as if text started exactly at fx0: close enough for wrapping (the bearing correction
        # below shifts the whole block by at most a few px) and never widens a line past the frame's own edge.
        max_width = (fx1 - CONTENT_PAD_X) - fx0
        lines, fits = wrap_headline(headline, font, max_width, HEAD_MAX_LINES)
        if fits or cap <= HEAD_MIN_CAP:
            break
        cap -= 2

    # The first glyph's own left bearing (the gap PIL's draw origin leaves before the ink starts): subtract it
    # so the glyph's ink, not the nominal draw position, lands exactly on fx0.
    first_word = lines[0][0][1]
    bearing = scratch.textbbox((0, 0), first_word, font=font)[0]
    x_start = fx0 - bearing
    line_pitch = round(font.size * HEAD_LINE_PITCH_FACTOR)

    tops, bottoms = [], []
    for i, line in enumerate(lines):
        text = " ".join(w for _, w in line)
        bbox = scratch.textbbox((x_start, i * line_pitch), text, font=font)
        tops.append(bbox[1])
        bottoms.append(bbox[3])
    block_height = max(bottoms) - min(tops)

    return font, lines, x_start, line_pitch, block_height


def draw_headline(canvas, font, lines, x_start, line_pitch, headline, fill, accent, shadow=False):
    """The headline already fit by fit_headline, painted at the top of the frame's interior: the words up to
    " · " in accent (this image's one red), the rest in fill. shadow draws a soft dark halo behind the text
    first (the PNG variant, for a light background), rather than an outline."""
    cy0 = head_top()
    dot_at = next((i for i, w in enumerate(headline.split(" ")) if w == "·"), None)
    space = font.getlength(" ")

    def paint(draw_fn):
        y = cy0
        for line in lines:
            x = x_start
            for i, word in line:
                colour = accent if dot_at is not None and i < dot_at else fill
                draw_fn(x, y, word, colour)
                x += font.getlength(word) + space
            y += line_pitch

    if shadow:
        slayer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(slayer)
        dx, dy = SHADOW_OFFSET
        paint(lambda x, y, word, colour: sdraw.text((x + dx, y + dy), word, font=font, fill=SHADOW_COLOR))
        slayer = slayer.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
        canvas.alpha_composite(slayer)

    draw = ImageDraw.Draw(canvas)
    paint(lambda x, y, word, colour: draw.text((x, y), word, font=font, fill=colour))


def compose(board_dir, view, headline, font_path, headline_fill, red, headline_shadow=False):
    fy1 = frame_box()[3]
    cy0 = head_top()
    font, lines, x_start, line_pitch, head_h = fit_headline(font_path, headline)
    board_top = cy0 + head_h + HEAD_BLOCK_BUFFER + HEAD_BOARD_GAP
    board_bottom_max = fy1 - BOARD_CORNER_GAP
    safe_h = board_bottom_max - board_top

    board = board_render(board_dir, view)
    scale = min(SAFE_W / board.width, safe_h / board.height)
    board = board.resize((round(board.width * scale), round(board.height * scale)), Image.LANCZOS)
    x = (W - board.width) // 2
    y = board_top + (safe_h - board.height) // 2

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
    draw_corner_marks(canvas, red)

    # The wordmark's baseline sits CONTENT_PAD_Y_TOP above the frame's bottom edge — the same distance up as
    # the headline's cap top sits down from the frame's top edge, a deliberate mirror, not two independent
    # numbers — its own ink flush with the right corners' outer vertical edge (the same treatment as the
    # headline's left edge, above). It now sits over the board's own area near that corner, not in a separate
    # row below it: the board's bottom edge is free to run past where the wordmark used to hold it back
    # (Roman, round 5, "mirror" pass, 6 Nov 2026).
    fx1 = frame_box()[2]
    wm = wordmark_png(round(WORDMARK_H * 13424 / 1434), WORDMARK_H, red)
    wm_bottom = fy1 - CONTENT_PAD_Y_TOP
    wm_x, wm_y = fx1 - wm.width, wm_bottom - wm.height
    canvas.alpha_composite(wm, (wm_x, wm_y))

    draw_headline(canvas, font, lines, x_start, line_pitch, headline, headline_fill, red, headline_shadow)

    return canvas, (x, y, x + board.width, y + board.height)


def square_crop(img):
    square_left, square_right = (W - H) // 2, (W - H) // 2 + H
    return img.crop((square_left, 0, square_right, H))


def write_shots(name, jpeg_img, png_img):
    """The real og:image JPEG (solid near-black headline) on white, since that is what LinkedIn and Facebook
    actually show and what LinkedIn's small organic-post thumbnail crops from; the twitter:image PNG (solid
    white headline with a soft shadow) composited onto the backgrounds a platform that doesn't honour its
    transparency might fill it with instead — X's two dark themes, X's own light theme, and Facebook's grey.
    Each at the full 1.91:1 card and the 1:1 square crop, plus the JPEG at LinkedIn's small ~160px
    organic-post thumbnail size — a by-eye look (AGENTS.md "Link previews")."""
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
    if W / H < MIN_CARD_RATIO:
        sys.exit(f"{W}x{H} is {W / H:.3f}:1, under the {MIN_CARD_RATIO}:1 LinkedIn needs for its large card")
    OUT.mkdir(parents=True, exist_ok=True)
    for name, board_dir, view, _, headline in IMAGES:
        img, bbox = compose(board_dir, view, headline, font_path, INK, LIGHT_RED)
        # the square crop LinkedIn and messengers make from a 1.91:1 card: the middle H x H of the canvas
        square_left, square_right = (W - H) // 2, (W - H) // 2 + H
        if bbox[0] < square_left or bbox[2] > square_right:
            sys.exit(f"{name}: the board reaches x {bbox[0]}-{bbox[2]}, outside the {H}px square crop ({square_left}-{square_right})")
        # The transparent PNG, headline solid white with a soft dark shadow so it reads on X's light theme too.
        # Kept for twitter:image.
        png_img, _ = compose(board_dir, view, headline, font_path, WHITE, DARK_RED, headline_shadow=True)
        write_image(OUT / f"{name}.png", png_img, "PNG", optimize=True)
        # The same frame flattened onto white, headline solid near-black, for og:image: quality ~90, 4:4:4
        # chroma (subsampling=0) and not progressive, so LinkedIn and Facebook show it sharp on the white card
        # they composite it onto.
        flat = Image.new("RGB", (W, H), (255, 255, 255))
        flat.paste(img, (0, 0), img)
        write_image(OUT / f"{name}.jpg", flat, "JPEG", quality=JPEG_QUALITY, subsampling=0, progressive=False, optimize=True)
        if check and name in SHOT_NAMES:
            write_shots(name, flat, png_img)
    if check:
        print(f"target/shots/og5-*.png written ({len(SHOT_NAMES)} images x ({len(PLATFORM_BACKGROUNDS)} backgrounds x 2 crops + 2 thumbnails))")


if __name__ == "__main__":
    main()
