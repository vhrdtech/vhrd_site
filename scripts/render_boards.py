#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Rebuild board product renders in static/img/boards/ from the KiCad projects in ~/git/hw.

Reads ~/git/hw (or VHRD_HW_ROOT), never writes there. For each board, finds the
newest source/<bnnn><rev> revision, renders a hero (whole board, 3/4 angle),
a detail (tight 3/4 close-up), a top and a bottom view with kicad-cli (black
solder mask / white silkscreen, forced on a temp copy of the board so
~/git/hw is never touched), crops the transparent canvas tight to the board,
and writes a 2400px-wide PNG plus AVIF/WebP web variants at 480/640/1280/1920px
into static/img/boards/<bnnn>-<slug>/, with a manifest.toml next to them. The PNG
sources stay in the repo but never ship with the site (config.toml ignored_static).

With --variants it renders nothing: it makes the web variants that are missing
from the PNG sources already in static/img/boards/ and updates the manifests, so
a new width needs neither KiCad nor the 3D libraries.

3D model libraries (not committed, machine-local): set KICAD6_3DMODEL_DIR..
KICAD10_3DMODEL_DIR and VHRD_3DMODEL_DIR yourself, or rely on the defaults
below, which match gpd-omarchy's Syncthing layout: hw_tracking/kicad-packages3D
for the stock KiCad libraries and hw_tracking/vhrd-packages3D (own/ and
vendor/ subfolders) for VHRD's own and vendor models.

Silkscreen fonts are machine-local too, not fetched by this script: see
README.md ("Fonts used in renders") for where they come from and their
licences. Before rendering, every font a board's silkscreen names is checked
with fc-list; a missing one fails loudly instead of silently falling back to
the wrong font.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
HW_ROOT = Path(os.environ.get("VHRD_HW_ROOT", Path.home() / "git" / "hw"))
OUT_ROOT = REPO_ROOT / "static" / "img" / "boards"

# Machine-local 3D model libraries, not in git. Defaults match gpd-omarchy's
# Syncthing folder hw_tracking: kicad-packages3D for the stock KiCad libraries,
# vhrd-packages3D (own/ and vendor/ subfolders) for VHRD's own and vendor
# models; override with the env vars if run elsewhere.
DEFAULT_KICAD_3DMODEL_DIR = Path.home() / "sync" / "hw_tracking" / "kicad-packages3D"
DEFAULT_VHRD_3DMODEL_DIR = Path.home() / "sync" / "hw_tracking" / "vhrd-packages3D"
for _var in ("KICAD6_3DMODEL_DIR", "KICAD7_3DMODEL_DIR", "KICAD8_3DMODEL_DIR",
             "KICAD9_3DMODEL_DIR", "KICAD10_3DMODEL_DIR"):
    os.environ.setdefault(_var, str(DEFAULT_KICAD_3DMODEL_DIR))
os.environ.setdefault("VHRD_3DMODEL_DIR", str(DEFAULT_VHRD_3DMODEL_DIR))

SRC_WIDTH = 2400
WEB_WIDTHS = (480, 640, 1280, 1920)
RENDER_CANVAS = 3600
CROP_PAD_FRAC = 0.04
AVIF_QUALITY = 50
WEBP_QUALITY = 38


@dataclass
class Board:
    number: str    # "b153"
    hw_dir: str    # hw/<hw_dir>
    product: str
    slug: str


# Front-page boards only (Roman, 4 Nov 2026); the rest of ~/git/hw's boards
# are a separate later task.
BOARDS = [
    Board("b153", "b153_typec_serial", "Donguru (Type-C Serial)", "donguru"),
    Board("b200", "b200_re_port", "rePort (RePort Lite)", "re-port"),
    Board("b125", "b125_2fdcan_iso_eth",
          "Ethernet to 2x ISO FDCAN bridge (DB-9, SD logging, optional PoE/BP)", "eth-2fdcan"),
    Board("b135", "b135_fdcan_iso_usb",
          "USB HS to ISO FDCAN bridge (DB-9, SD logging, optional BP)", "usb-fdcan"),
]

VIEWS = {
    # name: (kicad-cli --side, extra args)
    # zoom 1 (kicad-cli's default fit) clips the board under --perspective
    # --rotate at this angle, so hero explicitly zooms out for full-board
    # margin; detail keeps the tighter framing at the same angle.
    "hero": ("top", ["--perspective", "--rotate", "-45,0,45", "--floor", "--zoom", "0.75"]),
    "detail": ("top", ["--perspective", "--rotate", "-45,0,45", "--floor"]),
    "top": ("top", []),
    "bottom": ("bottom", []),
}
ALT_SUFFIX = {
    "hero": "three-quarter view",
    "detail": "angled detail view",
    "top": "top view",
    "bottom": "bottom view",
}


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        sys.exit(f"error: {name} not found on PATH")


def fonts_used(pcb: Path) -> set[str]:
    return set(re.findall(r'\(face "([^"]+)"\)', pcb.read_text()))


def installed_font_families() -> set[str]:
    out = subprocess.run(["fc-list", "--format", "%{family}\n"], capture_output=True, text=True, check=True)
    families: set[str] = set()
    for line in out.stdout.splitlines():
        families.update(name.strip() for name in line.split(","))
    return families


def check_fonts(boards_pcbs: list[tuple["Board", Path]]) -> None:
    """Fail loudly if a board's silkscreen names a font that isn't installed,
    rather than let kicad-cli silently substitute the wrong one."""
    available = installed_font_families()
    missing: dict[str, set[str]] = {}
    for board, pcb in boards_pcbs:
        absent = fonts_used(pcb) - available
        if absent:
            missing[board.number] = absent
    if missing:
        lines = [f"  {b}: {', '.join(sorted(fonts))}" for b, fonts in sorted(missing.items())]
        sys.exit(
            "error: fonts missing from fc-list (see README.md \"Fonts used in renders\"):\n"
            + "\n".join(lines)
        )


def make_mask_black_copy(pcb: Path) -> Path:
    """Copy the board's whole source revision dir to a temp dir and force its
    stackup to black solder mask / white silkscreen there, so the real board
    files under ~/git/hw are never touched. Returns the copied .kicad_pcb.
    Every board's stackup already has a (color ...) on these 4 layers, so a
    straight replace is enough (verified against all 4 front-page boards)."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="vhrd-render-"))
    shutil.copytree(pcb.parent, tmp_dir / pcb.parent.name)
    tmp_pcb = tmp_dir / pcb.parent.name / pcb.name
    text = tmp_pcb.read_text()

    def fix_layer(m: re.Match) -> str:
        target = "Black" if "Mask" in m.group(1) else "White"
        return re.sub(r'\(color "[^"]+"\)', f'(color "{target}")', m.group(0))

    # Anchored on the stackup's own (type "Top/Bottom Solder Mask"|"Silk Screen")
    # child, not just the layer name: a bare (layer "F.SilkS") also appears on
    # every individual silkscreen item (a different shape, no (type ...) child),
    # and a loose match swallows hundreds of those instead of the 4 stackup ones.
    text, n = re.subn(
        r'\(layer "([FB]\.(?:Mask|SilkS))"\s*\(type "[^"]*"\)\s*'
        r'(?:\(color "[^"]+"\)\s*)?(?:\(thickness [^)]+\)\s*)?\)',
        fix_layer, text,
    )
    if n != 4:
        sys.exit(f"error: expected 4 F/B Mask+SilkS stackup layers in {pcb}, patched {n}")
    tmp_pcb.write_text(text)
    return tmp_pcb


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
        "--use-board-stackup-colors",
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


def write_web_variants(master: Image.Image, stem: Path, missing_only: bool = False) -> dict[int, dict[str, int]]:
    sizes: dict[int, dict[str, int]] = {}
    for width in WEB_WIDTHS:
        if missing_only and stem.with_name(f"{stem.name}-{width}.avif").exists() \
                and stem.with_name(f"{stem.name}-{width}.webp").exists():
            continue
        height = round(master.height * width / master.width)
        resized = master if width == master.width else master.resize((width, height), Image.LANCZOS)
        webp_path = stem.with_name(f"{stem.name}-{width}.webp")
        resized.save(webp_path, format="WEBP", quality=WEBP_QUALITY, method=6)

        tmp_png = stem.with_name(f"{stem.name}-{width}.tmp.png")
        resized.save(tmp_png)
        avif_path = stem.with_name(f"{stem.name}-{width}.avif")
        subprocess.run(
            ["avifenc", "-q", str(AVIF_QUALITY), "--qalpha", "85", "-s", "4",
             str(tmp_png), str(avif_path)],
            check=True, capture_output=True, text=True,
        )
        tmp_png.unlink()

        sizes[width] = {"webp": webp_path.stat().st_size, "avif": avif_path.stat().st_size}
    return sizes


def write_manifest(board: Board, rev: str, source_file: str, git_hash: str,
                    out_dir: Path, view_sizes: dict[str, dict]) -> None:
    lines = [
        f'board = "{board.number.upper()}"',
        f'product = "{board.product}"',
        f'slug = "{board.slug}"',
        f'revision = "{rev}"',
        f'source_file = "{source_file}"',
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
    require_tool("fc-list")
    if not HW_ROOT.is_dir():
        sys.exit(f"error: hw repo not found at {HW_ROOT}")
    git_hash = hw_git_hash()

    resolved = [(board, *latest_revision_pcb(board)) for board in BOARDS]
    check_fonts([(board, pcb) for board, _rev, pcb in resolved])

    report: list[str] = []
    for board, rev, pcb in resolved:
        out_dir = OUT_ROOT / f"{board.number}-{board.slug}"
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"== {board.number.upper()} {board.product} (rev {rev}) ==")

        render_pcb = make_mask_black_copy(pcb)
        view_sizes: dict[str, dict] = {}
        for view in VIEWS:
            raw_png = out_dir / f"_raw_{view}.png"
            out_png = out_dir / f"{board.number}_{view}.png"
            print(f"  rendering {view}...")
            render_view(render_pcb, view, raw_png)
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
        shutil.rmtree(render_pcb.parent.parent)

        write_manifest(board, rev, str(pcb.relative_to(HW_ROOT)), git_hash, out_dir, view_sizes)

    print("\n".join(report))


def variants_only() -> None:
    """The web variants missing next to the committed PNG sources, and the manifests updated to list them."""
    require_tool("avifenc")
    for board in BOARDS:
        out_dir = OUT_ROOT / f"{board.number}-{board.slug}"
        old = tomllib.loads((out_dir / "manifest.toml").read_text())
        view_sizes: dict[str, dict] = {}
        for view in VIEWS:
            png = out_dir / f"{board.number}_{view}.png"
            sizes = write_web_variants(Image.open(png).convert("RGBA"), out_dir / png.stem, missing_only=True)
            view_sizes[view] = {"source": png, "sizes": sizes}
            for w, s in sizes.items():
                print(f"{board.number} {view}: {w}w webp {s['webp'] // 1024} KB / avif {s['avif'] // 1024} KB")
        write_manifest(board, old["revision"], old["source_file"], old["hw_git_hash"], out_dir, view_sizes)


if __name__ == "__main__":
    variants_only() if sys.argv[1:] == ["--variants"] else main()
