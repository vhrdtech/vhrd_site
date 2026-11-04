# /// script
# requires-python = ">=3.11"
# dependencies = ["fonttools[woff]>=4.50"]
# ///
"""Cut a small Core subset out of each IBM Plex Latin1 face, for a faster first load.

Usage: uv run tools/fonts.py   (just fonts)

A page in English uses ASCII and a few marks (· © – × µ and the smart quotes), but the Latin1 files carry all of
Western European, about 20-25 KB per face. For every Latin1 face in static/fonts/fonts.css this writes
`<face>-Core.woff2` (the CORE characters only, about 30 % smaller) and a @font-face for it, and narrows the Latin1
face's unicode-range to the rest, so the browser loads Latin1 only for a page that uses one of those characters.
Run it again after a change to CORE or to the Latin1 files; it rewrites the Core files and their @font-face blocks.
fonttools is Python's font library and has no Rust equal for woff2 subsetting, hence a Python tool.
"""

import re
from pathlib import Path

from fontTools import subset

FONTS = Path(__file__).resolve().parent.parent / "static/fonts"
CORE = [(0x20, 0x7E), (0xA0, 0xA0), (0xA9, 0xA9), (0xB0, 0xB0), (0xB5, 0xB5), (0xB7, 0xB7), (0xD7, 0xD7),
        (0x2013, 0x2014), (0x2018, 0x2019), (0x201C, 0x201D), (0x2026, 0x2026), (0x2212, 0x2212)]
BLOCK = re.compile(r"@font-face \{.*?\}\n", re.S)


def parse(ranges):
    """'U+0020-007E, U+00A0' -> a set of code points."""
    out = set()
    for part in ranges.split(","):
        lo, _, hi = part.strip()[2:].partition("-")
        out.update(range(int(lo, 16), int(hi or lo, 16) + 1))
    return out


def fmt(points):
    """A set of code points -> 'U+0020-007E, U+00A0', merged into runs."""
    runs, pts = [], sorted(points)
    for p in pts:
        if runs and p == runs[-1][1] + 1:
            runs[-1][1] = p
        else:
            runs.append([p, p])
    return ", ".join(f"U+{a:04X}" + (f"-{b:04X}" if b != a else "") for a, b in runs)


def main():
    css = FONTS / "fonts.css"
    text = css.read_text()
    head = text[:text.index("@font-face")]
    core = set().union(*(range(a, b + 1) for a, b in CORE))
    blocks = []
    for block in BLOCK.findall(text):
        src = re.search(r'url\("([^"]+)"\)', block).group(1)
        if src.endswith("-Core.woff2"):
            continue  # made again below, from its Latin1 face
        if not src.endswith("-Latin1.woff2"):
            blocks.append(block)
            continue
        old = re.search(r"unicode-range: ([^;\n]+)", block).group(1)
        latin1 = parse(old) | core  # the face's full range, also when an earlier run narrowed it
        core_file = src.replace("-Latin1.woff2", "-Core.woff2")
        opts = subset.Options()
        opts.flavor = "woff2"
        opts.layout_features = ["*"]
        font = subset.load_font(str(FONTS / src), opts)
        sub = subset.Subsetter(opts)
        sub.populate(unicodes=sorted(core))
        sub.subset(font)
        subset.save_font(font, str(FONTS / core_file), opts)
        print(f"{core_file}: {(FONTS / core_file).stat().st_size / 1024:.1f} KB "
              f"(Latin1 {(FONTS / src).stat().st_size / 1024:.1f} KB)")
        blocks.append(block.replace(src, core_file).replace(old, fmt(core & latin1)))
        blocks.append(block.replace(old, fmt(latin1 - core)))
    css.write_text(head + "".join(blocks))


if __name__ == "__main__":
    main()
