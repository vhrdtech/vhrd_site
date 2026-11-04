#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Rebuild board product renders in static/img/boards/ from the KiCad projects in ~/git/hw.

Reads ~/git/hw (or VHRD_HW_ROOT), never writes there. For each board, finds the
newest source/<bnnn><rev> revision, renders a hero (3/4), top and bottom view
with kicad-cli, crops the transparent canvas tight to the board, and writes a
2400px-wide PNG plus AVIF/WebP web variants at 640/1280/1920px into
static/img/boards/<bnnn>-<slug>/, with a manifest.toml next to them.

3D model libraries (not committed, machine-local): set KICAD6_3DMODEL_DIR..
KICAD10_3DMODEL_DIR and VHRD_3DMODEL_DIR yourself, or rely on the defaults
below, which match gpd-omarchy's Syncthing layout.
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
HW_ROOT = Path(os.environ.get("VHRD_HW_ROOT", Path.home() / "git" / "hw"))
OUT_ROOT = REPO_ROOT / "static" / "img" / "boards"

# Machine-local 3D model libraries, not in git. Defaults match gpd-omarchy
# (Syncthing folder hw_tracking); override with the env vars if run elsewhere.
DEFAULT_KICAD_3DMODEL_DIR = Path.home() / "sync" / "hw_tracking" / "kicad-packages3D"
DEFAULT_VHRD_3DMODEL_DIR = Path.home() / "git" / "kicad-library" / "3dmodels"
for _var in ("KICAD6_3DMODEL_DIR", "KICAD7_3DMODEL_DIR", "KICAD8_3DMODEL_DIR",
             "KICAD9_3DMODEL_DIR", "KICAD10_3DMODEL_DIR"):
    os.environ.setdefault(_var, str(DEFAULT_KICAD_3DMODEL_DIR))
os.environ.setdefault("VHRD_3DMODEL_DIR", str(DEFAULT_VHRD_3DMODEL_DIR))

SRC_WIDTH = 2400
WEB_WIDTHS = (640, 1280, 1920)
RENDER_CANVAS = 3600
CROP_PAD_FRAC = 0.04
AVIF_QUALITY = 62
WEBP_QUALITY = 70


@dataclass
class Board:
    number: str    # "b153"
    hw_dir: str    # hw/<hw_dir>
    product: str
    slug: str


BOARDS = [
    Board("b153", "b153_typec_serial", "Donguru (Type-C Serial)", "donguru"),
    Board("b200", "b200_re_port", "rePort (RePort Lite)", "re-port"),
    Board("b125", "b125_2fdcan_iso_eth",
          "Ethernet to 2x ISO FDCAN bridge (DB-9, SD logging, optional PoE/BP)", "eth-2fdcan"),
    Board("b135", "b135_fdcan_iso_usb",
          "USB HS to ISO FDCAN bridge (DB-9, SD logging, optional BP)", "usb-fdcan"),
    Board("b146", "b146_db9_nanofit", "DB-9 to Nano-Fit adapter", "db9-nanofit"),
    Board("b129", "b129_cannify_micro", "CANnify Micro HV Pico-Lock", "cannify-micro"),
]

VIEWS = {
    # name: (kicad-cli --side, extra args)
    "hero": ("top", ["--perspective", "--rotate", "-45,0,45", "--floor"]),
    "top": ("top", []),
    "bottom": ("bottom", []),
}
ALT_SUFFIX = {
    "hero": "three-quarter view",
    "top": "top view",
    "bottom": "bottom view",
}


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        sys.exit(f"error: {name} not found on PATH")


def latest_revision_pcb(board: Board) -> tuple[str, Path]:
    source_dir = HW_ROOT / board.hw_dir / "source"
    candidates = sorted(p for p in source_dir.glob(f"{board.number}*") if p.is_dir())
    if not candidates:
        sys.exit(f"error: no {source_dir}/{board.number}* revision directory")
    latest = candidates[-1]
    rev = latest.name[len(board.number):].upper()
    pcb_files = sorted(latest.glob("*.kicad_pcb"))
    if len(pcb_files) != 1:
        sys.exit(f"error: expected exactly one .kicad_pcb in {latest}, found {pcb_files}")
    return rev, pcb_files[0]


def hw_git_hash() -> str:
    out = subprocess.run(
        ["git", "-C", str(HW_ROOT), "describe", "--always", "--dirty"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def render_view(pcb: Path, view: str, out_png: Path) -> None:
    side, extra = VIEWS[view]
    cmd = [
        "kicad-cli", "pcb", "render",
        "--output", str(out_png),
        "--width", str(RENDER_CANVAS), "--height", str(RENDER_CANVAS),
        "--side", side,
        "--background", "transparent",
        "--quality", "high",
        *extra,
        str(pcb),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def crop_and_resize(raw_png: Path, out_png: Path) -> Image.Image:
    img = Image.open(raw_png).convert("RGBA")
    bbox = img.getbbox()
    if bbox is None:
        sys.exit(f"error: {raw_png} rendered fully transparent")
    left, upper, right, lower = bbox
    w, h = right - left, lower - upper
    pad = round(max(w, h) * CROP_PAD_FRAC)
    left = max(0, left - pad)
    upper = max(0, upper - pad)
    right = min(img.width, right + pad)
    lower = min(img.height, lower + pad)
    img = img.crop((left, upper, right, lower))
    target_h = round(img.height * SRC_WIDTH / img.width)
    img = img.resize((SRC_WIDTH, target_h), Image.LANCZOS)
    img.save(out_png)
    return img


def write_web_variants(master: Image.Image, stem: Path) -> dict[int, dict[str, int]]:
    sizes: dict[int, dict[str, int]] = {}
    for width in WEB_WIDTHS:
        height = round(master.height * width / master.width)
        resized = master if width == master.width else master.resize((width, height), Image.LANCZOS)
        webp_path = stem.with_name(f"{stem.name}-{width}.webp")
        resized.save(webp_path, format="WEBP", quality=WEBP_QUALITY, method=6)

        tmp_png = stem.with_name(f"{stem.name}-{width}.tmp.png")
        resized.save(tmp_png)
        avif_path = stem.with_name(f"{stem.name}-{width}.avif")
        subprocess.run(
            ["avifenc", "-q", str(AVIF_QUALITY), "--qalpha", "90", "-s", "4",
             str(tmp_png), str(avif_path)],
            check=True, capture_output=True, text=True,
        )
        tmp_png.unlink()

        sizes[width] = {"webp": webp_path.stat().st_size, "avif": avif_path.stat().st_size}
    return sizes


def write_manifest(board: Board, rev: str, pcb: Path, git_hash: str,
                    out_dir: Path, view_sizes: dict[str, dict]) -> None:
    lines = [
        f'board = "{board.number.upper()}"',
        f'product = "{board.product}"',
        f'slug = "{board.slug}"',
        f'revision = "{rev}"',
        f'source_file = "{pcb.relative_to(HW_ROOT)}"',
        f'hw_git_hash = "{git_hash}"',
        "",
    ]
    short_product = board.product.split(" (")[0]
    for view, data in view_sizes.items():
        alt = f"{board.number.upper()} {short_product} PCB, {ALT_SUFFIX[view]}"
        lines += [
            "[[views]]",
            f'name = "{view}"',
            f'alt = "{alt}"',
            f'source = "{data["source"].name}"',
            "web = [",
        ]
        for width in WEB_WIDTHS:
            lines.append(
                f'  {{ width = {width}, webp = "{data["source"].stem}-{width}.webp", '
                f'avif = "{data["source"].stem}-{width}.avif" }},'
            )
        lines += ["]", ""]
    (out_dir / "manifest.toml").write_text("\n".join(lines))


def main() -> None:
    require_tool("kicad-cli")
    require_tool("avifenc")
    if not HW_ROOT.is_dir():
        sys.exit(f"error: hw repo not found at {HW_ROOT}")
    git_hash = hw_git_hash()

    report: list[str] = []
    for board in BOARDS:
        rev, pcb = latest_revision_pcb(board)
        out_dir = OUT_ROOT / f"{board.number}-{board.slug}"
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"== {board.number.upper()} {board.product} (rev {rev}) ==")

        view_sizes: dict[str, dict] = {}
        for view in VIEWS:
            raw_png = out_dir / f"_raw_{view}.png"
            out_png = out_dir / f"{board.number}_{view}.png"
            print(f"  rendering {view}...")
            render_view(pcb, view, raw_png)
            master = crop_and_resize(raw_png, out_png)
            raw_png.unlink()
            sizes = write_web_variants(master, out_dir / f"{board.number}_{view}")
            view_sizes[view] = {"source": out_png, "sizes": sizes}
            report.append(
                f"{board.number} {view}: source {out_png.stat().st_size // 1024} KB, "
                + ", ".join(
                    f"{w}w webp {s['webp'] // 1024} KB / avif {s['avif'] // 1024} KB"
                    for w, s in sizes.items()
                )
            )

        write_manifest(board, rev, pcb, git_hash, out_dir, view_sizes)

    print("\n".join(report))


if __name__ == "__main__":
    main()
