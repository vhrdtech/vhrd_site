# Features

Status: ✅ done · 🚧 in progress · 📋 planned · 💡 idea · 🐛 bug

## SITE: the site and its pages

- ✅ SITE-1 zola-skeleton: Zola site (version pinned in AGENTS.md), `config.toml`, base template, 404, robots.txt, sitemap, blog feed
- ✅ SITE-2 header-footer: header with the wordmark, Products, Software, Open source, Lab, Blog, theme toggle and the red "Get notified" button (a menu under 52rem); footer with Vhrd.tech AS, link columns and the build stamp (git hash and commit date)
- 🚧 SITE-3 page-stubs: stubs for /donguru, /report, /can, /software, /lab, /services, /about, /blog, /shop, each marked draft; filled by later steps
- ✅ SITE-4 browser-checks: `tools/check_pages.py` drives every page in headless Chromium at 390, 820 and 1440 px, dark and light (console clean, no sideways scroll, theme toggle, keyboard tabs, skip link); the front page's first view on a phone stays under 200 KB on the wire, and every image has alt, width and height
- 🚧 SITE-5 landing-page: the front page with every section of the plan: hero, products, Donguru spotlight with block diagram, software panel, "Work we are proud of" (B125, B135, the laser scanner, RockFace), the open-source stack (five crates: wire_weaver, shrink_wrap, exact_units, embedded_bedrock and cnt; crates.io version and downloads at build time, `data/stack.toml`), notify and contact. Copy is draft until Marketing and PM have read it; board renders and the IOWeaver screenshot show as placeholders until their files land; RockFace shows its own window (portfolio page 9) in the Debugger tab and its timeline view on the lab card
- ✅ SITE-8 fast-first-load: all CSS inline (`load_data` in `base.html`), the hero render preloaded with `fetchpriority="high"`, every other image lazy, Core font subsets (`just fonts`) with the three first-screen faces preloaded, the PNG render sources left out of the build, 480 px card variants; `just perf` measures the first screen on a slow phone (requests, KB, FCP, LCP, CLS)
- ✅ SITE-7 open-source-page: /open-source lists the stack's crates from `data/stack.toml` in order, then every other repository by area from `data/repos.toml` (38: name, language, pitch from its README; a private one says "coming in the future" and has no link; dot, mx3, the old shrink_wrap copy, io_weaver, rockface, usb_io_fw, can_bus and power_meter left off until confirmed), wired like the front page, canzone marked work in progress; wire_weaver and shrink_wrap show their icon SVGs (dark variant on the dark theme), and the track runs through every via's centre (checked by `just test`); every code sample is written to 44 columns and fits a phone without a sideways scroll from 320 px up (`fits = true`, checked by `just test`)

## LOOK: brand and motif

- ✅ LOOK-1 brand-sync: `tokens.css` and `vhrd.css` pulled from vhrd_brand by `just brand` and compared by `just test`; IBM Plex Sans, Mono and Serif self-hosted as woff2 subsets (OFL); the VHRD.TECH wordmark and favicon as Audiowide outlines (`just wordmark`)
- ✅ LOOK-2 theme-toggle: follows `prefers-color-scheme`, the toggle's choice is remembered (localStorage) and applied before first paint; code highlighting follows it
- ✅ LOOK-3 grid-and-traces: faint drawing grid, framed column with crosshairs where section rules meet it, mono caps labels, PCB traces in the signal colours between sections, routed like real tracks (vertical and horizontal runs, 45° corners, vias at the ends, the net name on the run), drawn in on scroll (CSS scroll-driven animation, no script; drawn at once under reduced motion)
- ✅ LOOK-4 scope-intro: the front page opens like an old CRT scope powering up: a dot in the centre opens into a rectangle that overshoots and settles on the four crosses of the view frame (`.view-frame`, every page), then fades to the page; on a slow link a sine with "LOADING", "SLOW LINK · CLICK TO SKIP" after 5 s, "TRIG'D" once the hero render and fonts are in, at most 20 s; on every load (not with a #fragment), skippable by click, key, wheel, touch or scroll, replayed by the footer's "Replay intro"; off under reduced motion and without JavaScript; the page is painted underneath, so the largest paint is not delayed and nothing shifts
- ✅ LOOK-5 scope-placeholders: a picture still on its way shows as a small scope screen in its own box (dark glass, graticule, the step sweeping; CSS pseudo-elements and a mask, no request), then fades in over it; `site.js` marks the frames, without it nothing changes; static under reduced motion

## BLOCK: components for templates and content

- ✅ BLOCK-1 section-label: `vh.section` and `vh.label` (numbered mono caps label, hairline, crosshairs)
- ✅ BLOCK-2 card-specs: `vh.card` (render, badge, pitch, specs, link; wired in a signal colour), `vh.cards` grid, `vh.specs` list
- ✅ BLOCK-3 fig-caption: `vh.fig` with the datasheet's red corner marks and a "FIG. n" caption; a hatched placeholder until the image exists
- ✅ BLOCK-5 responsive-images: `vh.fig` (and `vh.card`) take an image by path, one file or AVIF + WebP in several widths (`stem`, `widths`, `sizes`), width and height read from the file, lazy unless `eager`
- ✅ BLOCK-4 code-tabs: `vh.code_tabs`, Markdown panels as ARIA tabs (arrow keys); stacked without script

## ASSET: generated site assets

- ✅ ASSET-1 board-renders: `just renders` (`scripts/render_boards.py`, uv) rebuilds `static/img/boards/<bnnn>-<slug>/` from the newest revision of each board's KiCad project in `~/git/hw`: hero (whole board, 3/4 angle, with margin), detail (tighter 3/4 close-up), top and bottom views via `kicad-cli pcb render` (transparent, raytraced, black solder mask / white silkscreen forced on a temp copy so `~/git/hw` is never touched), cropped tight, 2400px PNG source (not shipped) plus AVIF/WebP at 480/640/1280/1920px (`--variants` makes missing widths from the PNGs without KiCad), with a `manifest.toml` per board (product, revision, source file, hw git hash, per-view alt text). Silkscreen fonts are checked against `fc-list` before rendering, failing loudly on a missing one. 3D model library paths are machine-local env vars (`KICAD6..10_3DMODEL_DIR`, `VHRD_3DMODEL_DIR`), not committed. Covers the front-page boards (Donguru, rePort, B125, B135); the rest of `~/git/hw`'s boards are a later task.

## PREVIEW: publishing

- ✅ PREVIEW-1 share-preview: `just preview TOKEN` builds with noindex (meta robots, robots.txt Disallow all) for https://shadow.vhrd.tech/TOKEN/, a fresh token per preview, uploaded as a folder with `tpm share`; `just check-preview URL` checks it in the browser
- ❌ PREVIEW-2 static-replace: dropped; `tpm share` replaces the static.vhrd.tech mover and its draft root helper
