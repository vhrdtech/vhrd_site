"""The share images' version (AGENTS.md "Link previews"): one short hash over every file under static/img/og/,
which templates/base.html puts after og:image and twitter:image as `?v=`. LinkedIn, Facebook and Telegram cache a
preview by its image URL, so a changed image needs a new URL, or they go on showing the old file; the file names
stay fixed, so the nginx maps and locations never change with an image.

One hash for the whole set, not one per file: nginx answers one URL with different files by User-Agent (the
square card at default.jpg, the JPEG at default.png), so a change to any file has to change every URL.

Standard library only: tools/og_images.py writes it into data/og.toml, and tools/check_live.py (the runner's
python3, without uv) checks that file against the build.
"""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data/og.toml"
LENGTH = 10


def og_version(folder):
    """The version of the share images in folder: each file's name and bytes, in name order."""
    digest = hashlib.sha256()
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix in (".jpg", ".png"):
            digest.update(path.name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()[:LENGTH]


def write_data(folder):
    """data/og.toml with the version of folder, for templates/base.html (load_data)."""
    version = og_version(folder)
    DATA.write_text("# Written by `just og` (tools/og_images.py) or `python3 tools/og_version.py`, never by hand: the share\n"
                    "# images' version, the `?v=` after og:image and twitter:image. tools/check_live.py fails when it is not the build's.\n"
                    f'version = "{version}"\n')
    return version


if __name__ == "__main__":
    print(write_data(ROOT / "static/img/og"))
