# /// script
# requires-python = ">=3.11"
# dependencies = ["fonttools>=4.50"]
# ///
"""Write the VHRD.TECH wordmark as SVG outlines of Audiowide (OFL), so the font itself never ships.

Usage: uv run tools/wordmark.py PATH/TO/Audiowide-Regular.ttf  (`just wordmark` passes vhrd_brand's copy)

Writes templates/partials/wordmark.html (inline in the header and footer, coloured by CSS through the classes
`wm-word` and `wm-dot`), static/img/wordmark.svg (stand-alone, the dark-theme brand colours baked in) and
static/favicon.svg (the V on the dark background).
"""

import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
PARTS = [("VHRD", "wm-word"), (".", "wm-dot"), ("TECH", "wm-word")]
DARK = {"wm-word": "#f24c44", "wm-dot": "#9a9a9a"}  # vhrd_brand dark.red and dark.muted


def outline(font):
    glyphs, cmap = font.getGlyphSet(), font.getBestCmap()
    cap = font["OS/2"].sCapHeight
    x, paths = 0, []
    for text, cls in PARTS:
        pen = SVGPathPen(glyphs)
        for ch in text:
            name = cmap[ord(ch)]
            # font units are y-up with the baseline at 0; SVG is y-down: flip, baseline at y = cap height
            glyphs[name].draw(TransformPen(pen, (1, 0, 0, -1, x, cap)))
            x += glyphs[name].width
        paths.append((cls, pen.getCommands()))
    return paths, x, cap


def write_favicon(font, cap):
    """static/favicon.svg: the wordmark's V in red on the dark background, centred in a rounded square."""
    glyphs = font.getGlyphSet()
    v = glyphs[font.getBestCmap()[ord("V")]]
    size = cap * 1.6
    pen = SVGPathPen(glyphs)
    v.draw(TransformPen(pen, (1, 0, 0, -1, (size - v.width) / 2, (size + cap) / 2)))
    (ROOT / "static/favicon.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size:g} {size:g}">'
        f'<rect width="{size:g}" height="{size:g}" rx="{size / 8:g}" fill="#0f0f10"/>'
        f'<path fill="#f24c44" d="{pen.getCommands()}"/></svg>\n'
    )


def main():
    font = TTFont(sys.argv[1])
    paths, width, cap = outline(font)
    write_favicon(font, cap)
    view = f"0 0 {width} {cap}"
    inline = "".join(f'<path class="{c}" d="{d}"/>' for c, d in paths)
    (ROOT / "templates/partials").mkdir(parents=True, exist_ok=True)
    (ROOT / "templates/partials/wordmark.html").write_text(
        f'<svg class="wordmark" viewBox="{view}" aria-hidden="true" focusable="false">{inline}</svg>\n'
    )
    alone = "".join(f'<path fill="{DARK[c]}" d="{d}"/>' for c, d in paths)
    (ROOT / "static/img").mkdir(parents=True, exist_ok=True)
    (ROOT / "static/img/wordmark.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}" role="img"><title>VHRD.TECH</title>{alone}</svg>\n'
    )


if __name__ == "__main__":
    main()
