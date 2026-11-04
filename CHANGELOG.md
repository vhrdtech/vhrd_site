# Changelog

## [Unreleased]

### Added

- Fast first load (SITE-8 fast-first-load). On a phone the front page's first view went from 187 KB to 143 KB and from 14 to 10 requests; on a slow 4G phone the first paint came at 484 ms instead of 724 ms and the largest paint at 1400 ms instead of 1592 ms. All CSS is inline, the hero render is preloaded with high priority, three Core font subsets are preloaded, and the PNG render sources no longer ship with the site (54 MB to 17 MB built).
- `just perf` (`tools/perf.py`): the front page's first screen on a slow phone, as Lighthouse's mobile run measures it.
- `just fonts` (`tools/fonts.py`): Core subsets of the IBM Plex Latin1 faces, about 30 % smaller.
- Board renders at 480 px for the cards, and `just renders --variants` to make missing widths from the PNG sources without KiCad.
- Zola site skeleton (Zola 0.23.6, Tera 2 components): base template, header, footer with the build stamp, 404, robots.txt, sitemap and blog feed.
- Brand from vhrd_brand: `tokens.css` and `vhrd.css` pulled by `just brand` (v0.9.9), IBM Plex Sans, Mono and Serif self-hosted (OFL, woff2 subsets), the VHRD.TECH wordmark and favicon as Audiowide outlines (`just wordmark`).
- Dark and light theme: follows the system, a toggle in the header remembers the choice.
- The look: drawing grid, framed column with crosshairs, mono caps labels, FIG. captions with corner marks, PCB traces in the signal colours between sections, drawn in on scroll (off under reduced motion).
- Components for templates and Markdown: `vh.section`, `vh.label`, `vh.trace`, `vh.card`, `vh.cards`, `vh.specs`, `vh.fig`, `vh.code_tabs`.
- Page stubs for the site map: /, /donguru, /report, /can, /software, /open-source, /lab, /services, /about, /blog, /shop.
- `tools/check_pages.py`: every page in headless Chromium at phone, tablet and desktop widths in both themes, part of `just test`.
- `scripts/portfolio-photos/`: `extract_pages.py` (dump a PDF's pages and embedded
  images for review) and `build_lab_images.py` (crop/encode the picked images into
  `static/img/lab/`), so the selection can be reproduced or extended later.
- Own-work lab photos from Roman's portfolio, cropped and compressed to AVIF + WebP
  (640/1280/1920px wide, never upscaled) under `static/img/lab/<slug>/`, one
  `manifest.toml` per item (title, portfolio page, facts, alt text, tools). Covers
  the 11 items cleared 4 Nov 2026: thermocouple AFE, CAN servo controller,
  Raspberry Pi carrier board, BMS (6-10S, 50A/100A), torque sensor AFE, 6-step and
  FOC motor controller, propeller test stand, the lab, 3D laser scanner (AOI),
  granite CNC, eSkate. No employer work included. (P2633#4nov-0920)
- `just renders` (`scripts/render_boards.py`, uv): rebuilds `static/img/boards/<bnnn>-<slug>/`
  from the newest revision of each board's KiCad project in `~/git/hw` — hero (whole board,
  3/4 angle, with margin), detail (tighter 3/4 close-up), top and bottom views via
  `kicad-cli pcb render` (transparent, raytraced), cropped tight, 2400px PNG source plus
  AVIF/WebP at 640/1280/1920px, with a `manifest.toml` per board (product, revision, source
  file, hw git hash, per-view alt text). Every render forces a black solder mask / white
  silkscreen on a temp copy of the board source, never touching `~/git/hw`; the silkscreen
  fonts each board names are checked against `fc-list` first, failing loudly on a missing one
  instead of silently falling back. Covers the front-page boards: Donguru (B153), rePort
  (B200), B125, B135; the rest of `~/git/hw`'s boards are a later task. (P2633#4nov-0919d)
- `vh.fig` takes images by path: `stem` and `widths` give AVIF and WebP in several widths with `sizes`; width and height come from the file; the placeholder shows until the file exists, so board renders appear when they land in `static/img/boards/`.
- The browser check holds the first view on a phone to 200 KB on the wire and fails on an image without alt, width or height.
- just recipes: `test`, `lint`, `install` (Zola into ~/.local/bin), `brand`, `wordmark`, `serve`, `build`, `check-browser`, `check-preview URL`, `preview TOKEN` (noindex build for a share link, https://shadow.vhrd.tech/TOKEN/, uploaded with `tpm share`).
- /open-source lists every public crate from `data/stack.toml` in order: wire_weaver, shrink_wrap, exact_units, embedded_bedrock, canzone (marked work in progress), choreograph, egui_tabular, vhrd_egui.
- Lab photo of the 3D laser scanner's linear rails (portfolio page 14), and `build_lab_images.py` can build single images by name.
- The front page, every section filled (draft copy, facts from the project and crate READMEs): hero, the three products (Donguru, rePort, the CAN line), the Donguru spotlight with its block diagram, the software panel (GUI, debugger, code tabs) with IOWeaver, RockFace and WireWeaver, "Work we are proud of" from four areas (B125 Ethernet to CAN FD, B135 USB to CAN FD, the 3D laser scanner on its linear rails, RockFace with its log view and icon), the open-source stack "from register to GUI" (wire_weaver, shrink_wrap, exact_units and embedded_bedrock, with their logos in the theme's variant, a code sample each and, where published, the crates.io version and downloads fetched at build time), notify and contact.
- RockFace screenshots from the portfolio (page 9, its old name "MCU tracer - debugger"): the whole window, with transparent rounded corners, in the software panel's Debugger tab, and the log view on the lab card, where the text stays readable at card size. `build_lab_images.py` takes an optional corner radius for app windows; `vh.card` takes an `icon` shown before the title.

### Changed

- The Donguru product card shows the same render as the hero, so a phone loads it once; with the board renders in place the first view on a phone is 187 KB of the 200 KB budget.
- Traces between sections are routed like PCB tracks: vertical and horizontal runs, 45° corners, a via at each end and the net name on the run (they used to be stretched diagonals).
- Headlines are in the text colour; the brand red marks one word of the hero and stays for accents.
- Arrows after links are CSS masks instead of arrow characters, so no page loads the Pi font subsets for them; the skip link uses the medium weight, so the semibold face is not loaded either.

